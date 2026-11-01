"""
JobScoutAgent — orchestrates the full workflow used by the CLI, Streamlit app and web server:

    resume (Docling) → LinkedIn discovery (Apify) → dedupe → score → ATS tailoring → LaTeX → store → digest
"""
import logging
from dataclasses import dataclass, field
from datetime import datetime

from job_scout.config import settings
from job_scout.digest import generate_email_digest_html
from job_scout.linkedin_scraper import scrape_linkedin_jobs
from job_scout.resume_builder import build_moderncv_latex, generate_ats_optimized_resume, generate_cover_letter
from job_scout.resume_parser import ParsedResume, parse_resume
from job_scout.sample_jobs import get_sample_jobs
from job_scout.scoring import score_jobs
from job_scout.storage import check_supabase_duplicates, store_job_in_supabase
from job_scout.utils import sanitize_slug

logger = logging.getLogger(__name__)

FALLBACK_RESUME = "Swapnil Jathar - Associate Product Manager | AI Systems"


@dataclass
class ScoutCriteria:
    query: str = "AI Product Manager"
    location: str = "Pune, Maharashtra, India"
    time_filter: str = "pastWeek"
    remote_filter: str = None
    target_roles: list = field(default_factory=lambda: ["Product Manager", "Associate Product Manager", "AI Product Manager"])
    must_haves: list = field(default_factory=lambda: ["Python", "AI", "LLM", "Agile", "Product Strategy"])
    excludes: list = field(default_factory=lambda: ["Manual QA", "Unpaid", "10+ years"])
    max_jobs: int = 5


@dataclass
class TailoredResume:
    ats_text: str
    latex_code: str
    cover_letter: str = ""
    txt_file: str = ""
    tex_file: str = ""
    cover_file: str = ""


class JobScoutAgent:
    def __init__(self, resume_path=None, log=print):
        self.resume_path = resume_path or settings.master_resume_path
        self.log = log

    # ---------------- Resume ----------------
    def load_resume(self):
        if self.resume_path.exists():
            return self.resume_path.read_text(encoding="utf-8")
        return ""

    def save_resume(self, text):
        self.resume_path.write_text(text, encoding="utf-8")

    def import_resume(self, source) -> ParsedResume:
        """Parses a file path or document link (via Docling) and makes it the master resume."""
        parsed = parse_resume(source)
        self.save_resume(parsed.text)
        return parsed

    # ---------------- Discovery ----------------
    def discover(self, criteria, live=True, fill_with_samples=False, status_callback=None):
        """Returns (jobs, notice). Falls back to the curated feed if the crawler is unavailable."""
        if not live:
            return get_sample_jobs(criteria.max_jobs), None

        jobs, err = scrape_linkedin_jobs(
            criteria.query, criteria.location, criteria.time_filter, criteria.remote_filter,
            max_items=criteria.max_jobs, max_days=30, status_callback=status_callback,
        )
        if err:
            return get_sample_jobs(criteria.max_jobs), err
        if fill_with_samples and len(jobs) < criteria.max_jobs:
            jobs.extend(get_sample_jobs(criteria.max_jobs - len(jobs)))
        return jobs, None

    def score(self, jobs, criteria, resume_text=None):
        resume_text = self.load_resume() if resume_text is None else resume_text
        return score_jobs(jobs, resume_text, criteria.must_haves, criteria.excludes, criteria.target_roles)

    def scout(self, criteria, live=True, status_callback=None):
        """Discover + score. Returns (ranked_jobs, notice)."""
        jobs, notice = self.discover(criteria, live=live, status_callback=status_callback)
        return self.score(jobs, criteria), notice

    # ---------------- Tailoring ----------------
    def tailor(self, job, resume_text=None, save=True):
        resume_text = self.load_resume() if resume_text is None else resume_text
        ats_text, _ = generate_ats_optimized_resume(resume_text, job["jobDescription"], target_role=job["title"])
        tailored = TailoredResume(
            ats_text=ats_text,
            latex_code=build_moderncv_latex(ats_text),
            cover_letter=generate_cover_letter(resume_text, job),
        )
        if save:
            settings.resumes_dir.mkdir(exist_ok=True)
            stem = f"resume_{sanitize_slug(job['company'])}_{datetime.now():%Y%m%d}"
            txt_path = settings.resumes_dir / f"{stem}.txt"
            tex_path = settings.resumes_dir / f"{stem}.tex"
            txt_path.write_text(tailored.ats_text, encoding="utf-8")
            tex_path.write_text(tailored.latex_code, encoding="utf-8")
            cover_path = settings.resumes_dir / f"cover_letter_{sanitize_slug(job['company'])}_{datetime.now():%Y%m%d}.txt"
            cover_path.write_text(tailored.cover_letter, encoding="utf-8")
            tailored.txt_file, tailored.tex_file, tailored.cover_file = str(txt_path), str(tex_path), str(cover_path)
        return tailored

    # ---------------- Daily run ----------------
    def run_daily(self, criteria=None):
        """Headless daily pipeline (formerly daily_job_scout.py). Returns processed jobs."""
        criteria = criteria or ScoutCriteria()
        log = self.log
        log("=" * 60)
        log(f"🎯 Starting Daily Job Scout Pipeline — {datetime.now():%Y-%m-%d %H:%M:%S}")
        log("=" * 60)

        resume_text = self.load_resume()
        if resume_text:
            log(f"✓ Loaded Master Resume ({len(resume_text.split())} words)")
        else:
            resume_text = FALLBACK_RESUME
            log(f"⚠️ No {self.resume_path.name} found; using fallback profile.")

        log("🚀 Triggering Apify crawler...")
        fetch_criteria = ScoutCriteria(**{**criteria.__dict__, "max_jobs": criteria.max_jobs * 3})
        jobs, err = scrape_linkedin_jobs(
            fetch_criteria.query, fetch_criteria.location, fetch_criteria.time_filter, fetch_criteria.remote_filter,
            max_items=fetch_criteria.max_jobs, max_days=7, status_callback=log,
        )
        if err:
            log(f"⚠️ Apify notice: {err}")
            return []
        log(f"✓ Parsed & cleaned {len(jobs)} job listings.")

        new_jobs = check_supabase_duplicates(jobs)
        log(f"✓ After Supabase deduplication: {len(new_jobs)} new listings.")
        if not new_jobs:
            log("ℹ️ No new listings to process today.")
            return []

        ranked = self.score(new_jobs, criteria, resume_text)[:criteria.max_jobs]
        processed = []
        for i, job in enumerate(ranked, 1):
            log(f"\n[{i}/{len(ranked)}] Processing: {job['title']} @ {job['company']} (score {job['score']})")
            tailored = self.tailor(job, resume_text)
            log(f"  ✓ Saved LaTeX: {tailored.tex_file}")
            log(f"  ✓ Saved ATS Text: {tailored.txt_file}")
            log(f"  ✓ Saved Cover Letter: {tailored.cover_file}")

            stored, s_err = store_job_in_supabase(job)
            log("  ✓ Stored record in Supabase." if stored else f"  ⚠️ Supabase store note: {s_err}")
            processed.append(job)

        digest_file = settings.resumes_dir.parent / f"email_digest_{datetime.now():%Y%m%d}.html"
        digest_file.write_text(generate_email_digest_html(processed), encoding="utf-8")
        log(f"\n✓ Generated Email Digest: {digest_file.name}")
        log("\n" + "=" * 60)
        log(f"🎉 Pipeline Complete! Processed {len(processed)} target opportunities.")
        log("=" * 60)
        return processed
