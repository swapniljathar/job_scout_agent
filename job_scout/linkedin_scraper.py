"""LinkedIn job discovery: search URL builder, async Apify crawler, and result normalizer."""
import re
import time
import logging
import urllib.parse
from datetime import datetime, timedelta

import requests

from job_scout.config import settings

logger = logging.getLogger(__name__)

APIFY_BASE = "https://api.apify.com/v2"


# ---------------------------------------------------------
# 1. LinkedIn Search URL Builder (from n8n 'Build LinkedIn URL')
# ---------------------------------------------------------
TIME_FILTERS = {  # time_filter -> (LinkedIn f_TPR, days)
    "past24Hours": ("r86400", 1),
    "past3Days": ("r259200", 3),
    "pastWeek": ("r604800", 7),
    "pastMonth": ("r2592000", 30),
}
WORK_TYPE_CODES = {"onsite": "1", "remote": "2", "hybrid": "3"}  # LinkedIn f_WT codes


def time_filter_days(time_filter):
    return TIME_FILTERS.get(time_filter, TIME_FILTERS["pastWeek"])[1]


def role_keywords(query):
    """One role as-is, or several as a LinkedIn boolean search: "Product Manager" OR "Product Owner"."""
    if isinstance(query, str):
        return query
    roles = [r.strip().replace('"', '') for r in query if r and r.strip()]
    return roles[0] if len(roles) == 1 else " OR ".join(f'"{r}"' for r in roles)


def build_linkedin_url(query="AI Product Manager", location="Pune, Maharashtra, India", time_filter="pastWeek", remote_filter=None,
                       work_types=None):
    """
    Constructs a targeted LinkedIn Jobs public search URL matching n8n workflow.
    - query: one role, or a list of roles (searched together with OR)
    - time_filter options: 'past24Hours' (r86400), 'past3Days' (r259200), 'pastWeek' (r604800), 'pastMonth' (r2592000)
    - remote_filter options: 'remote' (2), 'hybrid_or_remote' (2,3), 'onsite_or_remote' (1,2, the n8n default), None for any
    - work_types: list of 'onsite', 'hybrid', 'remote' (overrides remote_filter); empty for any
    - LinkedIn f_WT codes: 1 = on-site, 2 = remote, 3 = hybrid
    """
    time_posted_range = TIME_FILTERS.get(time_filter, TIME_FILTERS["pastWeek"])[0]
    encoded_query = urllib.parse.quote(role_keywords(query))
    encoded_location = urllib.parse.quote(location)

    url = f"https://www.linkedin.com/jobs/search/?keywords={encoded_query}&location={encoded_location}&f_TPR={time_posted_range}&sortBy=DD"

    codes = sorted({WORK_TYPE_CODES[w] for w in (work_types or []) if w in WORK_TYPE_CODES})
    if codes:
        url += "&f_WT=" + "%2C".join(codes)
    elif remote_filter == "remote":
        url += "&f_WT=2"
    elif remote_filter == "hybrid_or_remote":
        url += "&f_WT=2%2C3"
    elif remote_filter == "onsite_or_remote":
        url += "&f_WT=1%2C2"

    return url


# ---------------------------------------------------------
# 2. Asynchronous Apify Runner & Poller
# ---------------------------------------------------------
def _trigger_apify_run(start_url, payload, headers):
    """Initiates an asynchronous Apify actor run and returns (run_id, dataset_id, error)."""
    try:
        response = requests.post(start_url, json=payload, headers=headers, timeout=30)
        if response.status_code not in [200, 201]:
            return None, None, f"Failed to start Apify actor (HTTP {response.status_code}): {response.text[:200]}"
        run_data = response.json().get("data", {})
        run_id = run_data.get("id")
        dataset_id = run_data.get("defaultDatasetId")
        if not run_id:
            return None, None, "Apify did not return a valid run ID."
        return run_id, dataset_id, None
    except requests.RequestException as err:
        return None, None, f"Apify start connection error: {err}"


def _poll_apify_run_status(check_url, max_attempts=30, status_callback=None):
    """Polls Apify run status until SUCCEEDED, failed, or timed out."""
    attempt = 0
    while attempt < max_attempts:
        time.sleep(10)
        attempt += 1
        try:
            status_res = requests.get(check_url, timeout=20)
            if status_res.status_code == 200:
                current_status = status_res.json().get("data", {}).get("status", "UNKNOWN")
                if status_callback:
                    status_callback(f"⏳ Apify crawler active... Status: {current_status} ({attempt * 10}s elapsed)")
                if current_status == "SUCCEEDED":
                    return True, None
                elif current_status in ["FAILED", "ABORTED", "TIMED-OUT"]:
                    return False, f"Apify crawler run finished with status: {current_status}"
            else:
                if status_callback:
                    status_callback(f"⚠️ Status check HTTP {status_res.status_code}. Retrying...")
        except requests.RequestException as err:
            logger.warning("Network blip while polling Apify run status: %s", err)
    return False, f"Apify scraping timed out after {max_attempts * 10} seconds."


def _fetch_apify_dataset_items(dataset_id, token):
    """Downloads scraped items from Apify dataset."""
    items_url = f"{APIFY_BASE}/datasets/{dataset_id}/items?token={token}"
    try:
        items_res = requests.get(items_url, timeout=30)
        if items_res.status_code == 200:
            return items_res.json(), None
        return [], f"Failed to fetch dataset items (HTTP {items_res.status_code}): {items_res.text[:200]}"
    except requests.RequestException as err:
        return [], f"Failed to download Apify dataset items: {err}"


def run_apify_async(search_url, token=None, actor_id=None, max_items=10, status_callback=None):
    """
    Runs the Apify actor asynchronously and polls until SUCCEEDED.
    `search_url` is one LinkedIn search URL or a list of them (one crawler run either way).
    Returns (raw_items, error).
    """
    token = token or settings.apify_token
    actor_id = actor_id or settings.apify_actor_id
    if not token:
        return [], "APIFY_API_TOKEN is not configured."

    headers = {"Content-Type": "application/json"}
    start_url = f"{APIFY_BASE}/acts/{actor_id}/runs?token={token}"
    payload = {
        "urls": search_url if isinstance(search_url, list) else [search_url],
        "scrapeCompany": False,
        "count": max_items
    }

    if status_callback:
        status_callback("🚀 Triggering asynchronous Apify run...")

    run_id, dataset_id, err = _trigger_apify_run(start_url, payload, headers)
    if err:
        return [], err

    check_url = f"{APIFY_BASE}/acts/{actor_id}/runs/{run_id}?token={token}"
    succeeded, poll_err = _poll_apify_run_status(check_url, max_attempts=30, status_callback=status_callback)
    if not succeeded:
        return [], poll_err

    if status_callback:
        status_callback("📥 Crawler succeeded! Downloading dataset items...")

    return _fetch_apify_dataset_items(dataset_id, token)


# ---------------------------------------------------------
# 3. HTML Stripper & Result Normalizer (from n8n 'Parse Apify Job Results1')
# ---------------------------------------------------------
def strip_html(html_text):
    if not html_text:
        return ""
    text = re.sub(r'<br\s*/?>', '\n', html_text, flags=re.IGNORECASE)
    text = re.sub(r'</?(li|p|div|h[1-6])[^>]*>', '\n', text, flags=re.IGNORECASE)
    text = re.sub(r'<[^>]+>', '', text)
    text = text.replace('&amp;', '&').replace('&lt;', '<').replace('&gt;', '>').replace('&nbsp;', ' ')
    text = re.sub(r'\n{3,}', '\n\n', text)
    return text.strip()


def parse_apify_jobs(raw_items, max_days=3, max_limit=100):
    """
    Normalizes raw Apify items matching the exact logic in n8n's 'Parse & Filter 3-Day Fresh Jobs'.
    Filters duplicates, confirms recency within `max_days`, and drops descriptions under 50 characters.
    """
    jobs = []
    seen = set()
    cutoff_date = (datetime.now() - timedelta(days=max_days)).strftime("%Y-%m-%d")

    for item in raw_items:
        job_link = item.get("link") or item.get("jobUrl") or item.get("url") or ""
        if not job_link or job_link in seen:
            continue

        posted_at = item.get("postedAt") or ""
        if posted_at and posted_at[:10] < cutoff_date:
            continue

        desc = item.get("descriptionHtml")
        if desc:
            job_description = strip_html(desc)
        else:
            job_description = item.get("descriptionText") or ""

        if not job_description or len(job_description) < 50:
            continue

        jobs.append({
            "title": item.get("title") or "No Title",
            "company": item.get("companyName") or item.get("company") or "Unknown Company",
            "location": item.get("location") or "Unknown Location",
            "postedAt": posted_at[:10] if posted_at else datetime.now().strftime("%Y-%m-%d"),
            "employmentType": item.get("employmentType") or "Full-time",
            "seniorityLevel": item.get("seniorityLevel") or "Mid-Senior level",
            "jobLink": job_link,
            "applyUrl": item.get("applyUrl") or "",
            "jobDescription": job_description
        })

        seen.add(job_link)
        if len(jobs) >= max_limit:
            break

    return jobs


def scrape_linkedin_jobs(query, location, time_filter="pastWeek", remote_filter=None, max_items=10, max_days=7, status_callback=None,
                         work_types=None):
    """
    End-to-end: build URL(s) → run crawler → normalize. Returns (jobs, error).
    `query` and `location` may be lists: all roles go into one search per location.
    """
    locations = [location] if isinstance(location, str) else [loc for loc in location if loc]
    search_urls = [build_linkedin_url(query, loc, time_filter, remote_filter, work_types) for loc in locations]
    raw_items, err = run_apify_async(search_urls, max_items=max_items, status_callback=status_callback)
    if err:
        return [], err
    return parse_apify_jobs(raw_items, max_days=max_days, max_limit=max_items), None
