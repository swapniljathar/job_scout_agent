"""Central configuration: loads `.env` (if present) and exposes typed settings."""
import os
from dataclasses import dataclass
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent


def load_dotenv(path=PROJECT_ROOT / ".env"):
    """Minimal .env loader (KEY=VALUE lines). Existing environment variables win."""
    if not path.exists():
        return
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))


load_dotenv()


@dataclass
class Settings:
    # Scraping
    apify_token: str = os.getenv("APIFY_API_TOKEN", "")
    apify_actor_id: str = os.getenv("APIFY_ACTOR_ID", "curious_coder~linkedin-jobs-scraper")

    # Storage. On the server SUPABASE_KEY should be the secret key (sb_secret_...): the jobs table is
    # locked to it. The publishable key is only used to verify dashboard logins.
    supabase_url: str = os.getenv("SUPABASE_URL", "https://advkivbiwhwpncyomcei.supabase.co/rest/v1/")
    supabase_key: str = os.getenv("SUPABASE_KEY", "sb_publishable_9hgSwmou0V8xdADTAG-mjw_3fFL3Z_t")
    supabase_publishable_key: str = os.getenv("SUPABASE_PUBLISHABLE_KEY", "sb_publishable_9hgSwmou0V8xdADTAG-mjw_3fFL3Z_t")
    ledger_file: Path = PROJECT_ROOT / "job_ledger.json"

    # Enrichment / LLM
    lusha_api_key: str = os.getenv("LUSHA_API_KEY", "")
    gemini_api_key: str = os.getenv("GEMINI_API_KEY", "")
    gemini_model: str = os.getenv("GEMINI_MODEL", "gemini-flash-lite-latest")

    # Resume
    master_resume_path: Path = PROJECT_ROOT / "master_resume.md"
    resumes_dir: Path = PROJECT_ROOT / "resumes"
    use_docling: bool = os.getenv("USE_DOCLING", "true").lower() not in ("0", "false", "no")
    max_resume_bytes: int = int(os.getenv("MAX_RESUME_BYTES", str(10 * 1024 * 1024)))

    # Web server. Any Supabase account can use the dashboard; set ALLOWED_EMAILS to limit it to a list.
    port: int = int(os.getenv("PORT", "8080"))
    allowed_emails: tuple = tuple(e.strip().lower() for e in os.getenv("ALLOWED_EMAILS", "").split(",") if e.strip())

    # Daily scout run (built into `main.py serve`): one run per user, queued one after another.
    # SCOUT_QUERY / SCOUT_LOCATION are the defaults for a new user's search and for `main.py scout`.
    scout_schedule_enabled: bool = os.getenv("SCOUT_SCHEDULE", "true").lower() not in ("0", "false", "no")
    scout_daily_time: str = os.getenv("SCOUT_DAILY_TIME", "06:30")
    scout_timezone: str = os.getenv("SCOUT_TIMEZONE", "Asia/Kolkata")
    scout_query: str = os.getenv("SCOUT_QUERY", "AI Product Manager")
    scout_location: str = os.getenv("SCOUT_LOCATION", "Pune, Maharashtra, India")
    scout_max_jobs: int = int(os.getenv("SCOUT_MAX_JOBS", "5"))
    # Each run spends the server's Apify and Gemini credits, so "Run scout now" is limited per user per day
    scout_manual_runs_per_day: int = int(os.getenv("SCOUT_MANUAL_RUNS_PER_DAY", "3"))


settings = Settings()
