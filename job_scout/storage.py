"""Persistence: local JSON ledger + Supabase deduplication and storage."""
import json
import logging
from datetime import datetime, timedelta, timezone

import requests

from job_scout.config import settings

logger = logging.getLogger(__name__)

# ---------------------------------------------------------
# Persistent Local Ledger (job_ledger.json)
# ---------------------------------------------------------
LEDGER_FILE = settings.ledger_file

def load_ledger():
    if LEDGER_FILE.exists():
        try:
            with open(LEDGER_FILE, "r", encoding="utf-8") as file:
                return json.load(file)
        except (json.JSONDecodeError, OSError) as err:
            logger.error("Failed to load ledger from %s: %s", LEDGER_FILE, err)
    return {"seen_urls": {}, "jobs": [], "decisions": []}

def save_ledger(ledger):
    try:
        with open(LEDGER_FILE, "w", encoding="utf-8") as file:
            json.dump(ledger, file, indent=2)
    except OSError as err:
        logger.error("Error saving ledger to %s: %s", LEDGER_FILE, err)

def is_job_in_ledger(job_url):
    ledger = load_ledger()
    return job_url in ledger.get("seen_urls", {})

def record_job_in_ledger(job_data):
    ledger = load_ledger()
    url = job_data.get("jobLink") or job_data.get("url") or ""
    if url:
        ledger.setdefault("seen_urls", {})[url] = {
            "company": job_data.get("company", ""),
            "title": job_data.get("title", ""),
            "scored_at": datetime.now().isoformat(),
            "score": job_data.get("score", 0)
        }
        # Keep job records
        existing_indices = [i for i, j in enumerate(ledger.get("jobs", [])) if (j.get("jobLink") or j.get("url")) == url]
        if existing_indices:
            ledger["jobs"][existing_indices[0]] = job_data
        else:
            ledger.setdefault("jobs", []).append(job_data)
        save_ledger(ledger)


# ---------------------------------------------------------
# 4. Supabase Storage & Deduplication
# ---------------------------------------------------------
def get_supabase_headers(key=None):
    """
    CRITICAL SUPABASE RULES:
    - Send publishable key on 'apikey' header ONLY.
    - Do NOT include 'Authorization: Bearer'.
    - Send Content-Type: application/json and Prefer: return=minimal.
    """
    return {
        "apikey": key or settings.supabase_key,
        "Content-Type": "application/json",
        "Prefer": "return=minimal"
    }

def store_job_in_supabase(job, tailored=None, url=None, key=None):
    """
    Inserts a job into Supabase 'jobs' table using insert-only POST.
    `tailored` (agent.TailoredResume) adds the drafts the dashboard shows for review.
    Treats HTTP 201 as success.
    """
    url = url or settings.supabase_url
    headers = get_supabase_headers(key)
    # job_url/job_title/company/processed_at match the n8n 'Store Job Record' node; the rest feed the dashboard
    payload = {
        "job_url": job.get("jobLink") or job.get("url") or "",
        "job_title": job.get("title", ""),
        "company": job.get("company", ""),
        "location": job.get("location", ""),
        "posted_at": job.get("postedAt", ""),
        "score": int(job.get("score") or 0),
        "reason": job.get("why", ""),
        "matched_keywords": job.get("matched", []),
        "job_description": job.get("jobDescription", ""),
        "status": "new",
        "processed_at": datetime.now(timezone.utc).isoformat(),
    }
    if tailored:
        payload["tailored_resume"] = tailored.ats_text
        payload["cover_letter"] = tailored.cover_letter
    try:
        endpoint = f"{url.rstrip('/')}/jobs"
        res = requests.post(endpoint, json=payload, headers=headers, timeout=8)
        # HTTP 201 is Created; 200/204 also treated as success
        success = res.status_code in [200, 201, 204]
        return success, f"HTTP {res.status_code}: {res.text[:100]}"
    except Exception as e:
        return False, str(e)

def check_supabase_duplicates(jobs, url=None, key=None):
    """
    Filters out jobs that have already been recorded in Supabase or the local ledger.
    Matches import contract for app.py and daily_job_scout.py.
    """
    url = url or settings.supabase_url
    key = key or settings.supabase_key
    seen_urls = set()

    # 1. Check local ledger
    ledger = load_ledger()
    seen_urls.update(ledger.get("seen_urls", {}).keys())

    # 2. Check Supabase 'jobs' table if reachable (only the candidate URLs, like n8n 'Filter Out Duplicates')
    links = [job.get("jobLink") or job.get("url") for job in jobs if job.get("jobLink") or job.get("url")]
    if url and key and links:
        try:
            quoted = ",".join('"{}"'.format(link.replace('"', '\\"')) for link in links)
            response = requests.get(
                f"{url.rstrip('/')}/jobs",
                params={"select": "job_url", "job_url": f"in.({quoted})"},
                headers=get_supabase_headers(key),
                timeout=10,
            )
            if response.status_code == 200:
                seen_urls.update(row["job_url"] for row in response.json() if row.get("job_url"))
            else:
                logger.warning("Supabase dedup query returned HTTP %s: %s", response.status_code, response.text[:200])
        except requests.RequestException as exc:
            logger.warning("Could not reach Supabase for remote deduplication: %s", exc)

    new_jobs = []
    for job in jobs:
        link = job.get("jobLink") or job.get("url") or ""
        if link and link not in seen_urls:
            new_jobs.append(job)
            seen_urls.add(link)
        elif not link:
            new_jobs.append(job)
    return new_jobs



JOB_STATUSES = ("new", "reviewed", "applied", "skipped")


def list_jobs(days=30, url=None, key=None):
    """Returns (rows, error): jobs processed in the last `days` days, newest first."""
    url = url or settings.supabase_url
    since = (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()
    try:
        response = requests.get(
            f"{url.rstrip('/')}/jobs",
            params={"select": "*", "processed_at": f"gte.{since}", "order": "processed_at.desc", "limit": "300"},
            headers=get_supabase_headers(key),
            timeout=10,
        )
        if response.status_code == 200:
            return response.json(), None
        return [], f"Supabase HTTP {response.status_code}: {response.text[:200]}"
    except requests.RequestException as err:
        return [], f"Could not reach Supabase: {err}"


def update_job(job_id, fields, url=None, key=None):
    """Updates one job row by id. Returns (success, error)."""
    url = url or settings.supabase_url
    fields = dict(fields, updated_at=datetime.now(timezone.utc).isoformat())
    if fields.get("status") == "applied":
        fields["applied_at"] = fields["updated_at"]
    try:
        response = requests.patch(
            f"{url.rstrip('/')}/jobs",
            params={"id": f"eq.{int(job_id)}"},
            json=fields,
            headers=get_supabase_headers(key),
            timeout=10,
        )
        if response.status_code in (200, 204):
            return True, None
        return False, f"Supabase HTTP {response.status_code}: {response.text[:200]}"
    except requests.RequestException as err:
        return False, f"Could not reach Supabase: {err}"
