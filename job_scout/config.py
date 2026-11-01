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

    # Storage
    supabase_url: str = os.getenv("SUPABASE_URL", "https://advkivbiwhwpncyomcei.supabase.co/rest/v1/")
    supabase_key: str = os.getenv("SUPABASE_KEY", "sb_publishable_9hgSwmou0V8xdADTAG-mjw_3fFL3Z_t")
    ledger_file: Path = PROJECT_ROOT / "job_ledger.json"

    # Enrichment / LLM
    lusha_api_key: str = os.getenv("LUSHA_API_KEY", "")
    gemini_api_key: str = os.getenv("GEMINI_API_KEY", "")
    gemini_model: str = os.getenv("GEMINI_MODEL", "gemini-2.5-flash")

    # Resume
    master_resume_path: Path = PROJECT_ROOT / "master_resume.md"
    resumes_dir: Path = PROJECT_ROOT / "resumes"
    use_docling: bool = os.getenv("USE_DOCLING", "true").lower() not in ("0", "false", "no")
    max_resume_bytes: int = int(os.getenv("MAX_RESUME_BYTES", str(10 * 1024 * 1024)))

    # Web server
    port: int = int(os.getenv("PORT", "8080"))


settings = Settings()
