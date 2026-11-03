"""
Dashboard web server + JSON API.

Routes:
  GET  /                         → job-hunt-dashboard.html
  GET  /favicon.svg|ico          → favicon
  GET  /api/health               → {"ok": true, "docling": bool}

Signed-in routes (Authorization: Bearer <Supabase access token>; any account, or only ALLOWED_EMAILS if set).
Every user sees and changes only their own profile and jobs:
  POST /api/resume/parse?filename=resume.pdf   (raw file bytes as body)
  POST /api/resume/parse         {"url": "<document link>"}  (application/json)
  GET  /api/profile              → master resume, search settings, daily run on/off, manual runs left today
  POST /api/profile              {"master_resume"?, "search_roles"?: [...], "search_locations"?: [...], "work_types"?: [...],
                                  "posted_within"?: "24h|3d|7d|30d", "keywords"?, "daily_enabled"?}
  GET  /api/jobs                 → {"jobs": [...]} processed in the last 30 days
  POST /api/jobs/<id>            {"status": "reviewed|applied|skipped|new", "tailored_resume"?, "cover_letter"?}
  GET  /api/scout/status         → the user's running/queued run, last run, next scheduled run, recent log lines
  POST /api/scout/run            → queues a run now (400 without a resume, 409 if already queued, 429 over the daily limit)
"""
import json
import logging
import re
import threading
import time
import urllib.parse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import requests

from job_scout.config import PROJECT_ROOT, settings
from job_scout.resume_parser import ResumeParseError, docling_available, parse_resume_bytes, parse_resume_link
from job_scout.scheduler import POSTED_WITHIN, WORK_TYPES, runner, search_settings, today
from job_scout.storage import JOB_STATUSES, PROFILE_FIELDS, get_profile, list_jobs, save_profile, update_job

logger = logging.getLogger(__name__)

_token_cache = {}  # access token -> (user, expires_at)
_token_lock = threading.Lock()
MAX_RESUME_CHARS = 100_000
LIST_LIMITS = {"search_roles": 5, "search_locations": 3, "work_types": 3}  # max items per list


def verify_login(auth_header):
    """Returns ({"id", "email"}, error). Checks the Supabase access token and, if set, ALLOWED_EMAILS."""
    token = auth_header[7:].strip() if auth_header.lower().startswith("bearer ") else ""
    if not token:
        return None, "Sign in to see your jobs."

    with _token_lock:
        cached = _token_cache.get(token)
    if cached and cached[1] > time.time():
        user = cached[0]
    else:
        auth_url = settings.supabase_url.split("/rest/v1")[0].rstrip("/") + "/auth/v1/user"
        try:
            response = requests.get(auth_url, headers={"apikey": settings.supabase_publishable_key,
                                                       "Authorization": f"Bearer {token}"}, timeout=8)
        except requests.RequestException as err:
            return None, f"Could not reach Supabase to check your login: {err}"
        if response.status_code != 200:
            return None, "Your session has expired. Sign in again."
        data = response.json()
        user = {"id": data.get("id"), "email": (data.get("email") or "").lower()}
        if not user["id"]:
            return None, "Your session has expired. Sign in again."
        with _token_lock:
            if len(_token_cache) > 1000:
                _token_cache.clear()
            _token_cache[token] = (user, time.time() + 300)

    if settings.allowed_emails and user["email"] not in settings.allowed_emails:
        return None, f"{user['email'] or 'This account'} is not allowed on this server (ALLOWED_EMAILS)."
    return user, None


def validate_profile_fields(body):
    """Returns (fields to save, error) for a POST /api/profile body."""
    fields = {k: body[k] for k in PROFILE_FIELDS if k in body}
    for key, value in fields.items():
        if key == "daily_enabled":
            if not isinstance(value, bool):
                return None, "daily_enabled must be true or false."
        elif key in LIST_LIMITS:
            if not isinstance(value, list) or not all(isinstance(v, str) and 0 < len(v.strip()) <= 80 for v in value):
                return None, f"{key} must be a list of short text values."
            value = list(dict.fromkeys(v.strip() for v in value))
            if len(value) > LIST_LIMITS[key]:
                return None, f"Choose at most {LIST_LIMITS[key]} {key.replace('search_', '').replace('_', ' ')}."
            if key == "work_types" and any(v not in WORK_TYPES for v in value):
                return None, f"work_types must be from {', '.join(WORK_TYPES)}."
            if key != "work_types" and not value:
                return None, f"Add at least one {key.replace('search_', '')[:-1]}."
            fields[key] = value
        elif key == "posted_within":
            if value not in POSTED_WITHIN:
                return None, f"posted_within must be one of {', '.join(POSTED_WITHIN)}."
        elif not isinstance(value, str):
            return None, f"{key} must be text."
        elif len(value) > (500 if key == "keywords" else MAX_RESUME_CHARS):
            return None, f"{key} is too long."
    if not fields:
        return None, "Nothing to update."
    return fields, None


def profile_payload(user, profile):
    """The profile as the dashboard sees it, with defaults for a user who hasn't saved one yet."""
    profile = profile or {}
    used = (profile.get("manual_runs_count") or 0) if profile.get("manual_runs_date") == today().isoformat() else 0
    return {
        "email": user["email"],
        "master_resume": profile.get("master_resume") or "",
        **search_settings(profile),
        "daily_enabled": profile.get("daily_enabled", True) is not False,
        "manual_runs_left": max(settings.scout_manual_runs_per_day - used, 0),
        "manual_runs_per_day": settings.scout_manual_runs_per_day,
        "_used": used,
    }

HTML_FILE = PROJECT_ROOT / "job-hunt-dashboard.html"
FAVICON_FILE = PROJECT_ROOT / "favicon.svg"


class DashboardHandler(BaseHTTPRequestHandler):
    def _serve_file(self, file_path, content_type, is_cached=False, include_body=True):
        try:
            content = file_path.read_bytes()
            self.send_response(200)
            self.send_header('Content-Type', content_type)
            self.send_header('Content-Length', str(len(content)))
            if is_cached:
                self.send_header('Cache-Control', 'public, max-age=86400')
            else:
                self.send_header('Cache-Control', 'no-cache, no-store, must-revalidate')
            self.end_headers()
            if include_body:
                self.wfile.write(content)
        except FileNotFoundError:
            self.send_response(404)
            self.end_headers()
        except OSError as err:
            self.send_response(500)
            self.end_headers()
            if include_body:
                self.wfile.write(str(err).encode('utf-8'))

    def _send_json(self, status, payload):
        body = json.dumps(payload).encode('utf-8')
        self.send_response(status)
        self.send_header('Content-Type', 'application/json')
        self.send_header('Content-Length', str(len(body)))
        self.send_header('Cache-Control', 'no-store')
        self.end_headers()
        self.wfile.write(body)

    def _route_static(self, include_body):
        clean_path = self.path.split('?', 1)[0].split('#', 1)[0]
        if clean_path in ('/favicon.ico', '/favicon.svg'):
            self._serve_file(FAVICON_FILE, 'image/svg+xml', is_cached=True, include_body=include_body)
        else:
            self._serve_file(HTML_FILE, 'text/html; charset=utf-8', is_cached=False, include_body=include_body)

    def _require_login(self):
        user, err = verify_login(self.headers.get('Authorization', ''))
        if err:
            self._send_json(403 if "not allowed" in err else 401, {"error": err})
        return user

    def _load_profile(self, user):
        """Returns the user's profile payload, or None after sending a 502."""
        profile, err = get_profile(user["id"])
        if err:
            self._send_json(502, {"error": err})
            return None
        return profile_payload(user, profile)

    def _discard_body(self):
        """Reads an unwanted upload so the browser sees the error response instead of a reset connection."""
        length = min(int(self.headers.get('Content-Length') or 0), settings.max_resume_bytes)
        while length > 0:
            chunk = self.rfile.read(min(length, 65536))
            if not chunk:
                break
            length -= len(chunk)

    def _read_json(self, limit=1024 * 1024):
        length = int(self.headers.get('Content-Length') or 0)
        if length > limit:
            raise ValueError("Request body too large.")
        return json.loads(self.rfile.read(length) or b'{}') if length else {}

    def do_GET(self):
        path = self.path.split('?', 1)[0]
        if path == '/api/health':
            self._send_json(200, {"ok": True, "docling": docling_available()})
        elif path == '/api/jobs':
            user = self._require_login()
            if user:
                rows, err = list_jobs(user["id"])
                if err:
                    self._send_json(502, {"error": err})
                else:
                    self._send_json(200, {"jobs": rows})
        elif path == '/api/profile':
            user = self._require_login()
            profile = user and self._load_profile(user)
            if profile:
                profile.pop("_used")
                self._send_json(200, profile)
        elif path == '/api/scout/status':
            user = self._require_login()
            if user:
                self._send_json(200, runner.status(user["id"]))
        elif path.startswith('/api/'):
            self._send_json(404, {"error": "Not found"})
        else:
            self._route_static(include_body=True)

    def do_HEAD(self):
        self._route_static(include_body=False)

    def do_POST(self):
        parsed_url = urllib.parse.urlparse(self.path)
        if parsed_url.path == '/api/scout/run':
            user = self._require_login()
            if user:
                self._start_run(user)
            return
        if parsed_url.path == '/api/profile':
            user = self._require_login()
            if user:
                self._save_profile(user)
            return
        job_match = re.fullmatch(r'/api/jobs/(\d+)', parsed_url.path)
        if job_match:
            user = self._require_login()
            if user:
                self._update_job(int(job_match.group(1)), user)
            return
        if parsed_url.path != '/api/resume/parse':
            self._send_json(404, {"error": "Not found"})
            return
        if not self._require_login():
            self._discard_body()
            return

        length = int(self.headers.get('Content-Length') or 0)
        if length <= 0:
            self._send_json(400, {"error": "Empty request body."})
            return
        if length > settings.max_resume_bytes:
            self._send_json(413, {"error": f"File exceeds {settings.max_resume_bytes // (1024 * 1024)} MB limit."})
            return
        body = self.rfile.read(length)

        try:
            if self.headers.get('Content-Type', '').startswith('application/json'):
                url = (json.loads(body or b'{}').get('url') or '').strip()
                if not url:
                    self._send_json(400, {"error": "Missing 'url' field."})
                    return
                result = parse_resume_link(url)
            else:
                query = urllib.parse.parse_qs(parsed_url.query)
                filename = (query.get('filename') or ['resume.pdf'])[0]
                result = parse_resume_bytes(body, filename)
        except (ResumeParseError, ValueError) as err:
            self._send_json(422, {"error": str(err)})
            return
        except Exception as err:
            logger.exception("Resume parse failed")
            self._send_json(500, {"error": f"Unexpected parser error: {err}"})
            return

        self._send_json(200, result.to_dict())

    def _start_run(self, user):
        profile = self._load_profile(user)
        if not profile:
            return
        if not profile["master_resume"].strip():
            self._send_json(400, {"error": "Add your master resume on the My Resume tab first."})
            return
        if profile["manual_runs_left"] <= 0:
            self._send_json(429, {"error": f"You've used today's {settings.scout_manual_runs_per_day} manual runs. "
                                           "The daily run still adds new jobs every morning."})
            return
        if not runner.start(user["id"], "manual"):
            self._send_json(409, {"error": "Your scout run is already in progress."})
            return
        save_profile(user["id"], {"email": user["email"], "manual_runs_date": today().isoformat(),
                                  "manual_runs_count": profile["_used"] + 1})
        self._send_json(202, dict(runner.status(user["id"]), manual_runs_left=profile["manual_runs_left"] - 1))

    def _save_profile(self, user):
        try:
            body = self._read_json(limit=2 * 1024 * 1024)
        except ValueError as err:
            self._send_json(400, {"error": str(err) or "Invalid JSON."})
            return
        fields, err = validate_profile_fields(body if isinstance(body, dict) else {})
        if err:
            self._send_json(400, {"error": err})
            return
        ok, err = save_profile(user["id"], dict(fields, email=user["email"]))
        if ok:
            self._send_json(200, {"ok": True})
        else:
            self._send_json(502, {"error": err})

    def _update_job(self, job_id, user):
        try:
            body = self._read_json()
        except ValueError as err:
            self._send_json(400, {"error": str(err) or "Invalid JSON."})
            return
        fields = {k: body[k] for k in ("status", "tailored_resume", "cover_letter") if isinstance(body.get(k), str)}
        if "status" in fields and fields["status"] not in JOB_STATUSES:
            self._send_json(400, {"error": f"status must be one of {', '.join(JOB_STATUSES)}"})
            return
        if not fields:
            self._send_json(400, {"error": "Nothing to update."})
            return
        ok, err = update_job(job_id, user["id"], fields)
        if ok:
            self._send_json(200, {"ok": True})
        elif err == "not found":
            self._send_json(404, {"error": "Job not found."})
        else:
            self._send_json(502, {"error": err})


def run_server(port=None, schedule=True):
    port = port or settings.port
    ThreadingHTTPServer.allow_reuse_address = True
    with ThreadingHTTPServer(("", port), DashboardHandler) as httpd:
        print(f"Job Scout Agent is live at: http://localhost:{port}")
        print(f"Resume parser engine: {'Docling' if docling_available() else 'basic (pip install docling for layout-aware parsing)'}")
        if schedule and settings.scout_schedule_enabled:
            runner.start_schedule()
            print(f"Daily scout run: {settings.scout_daily_time} {settings.scout_timezone} (next: {runner.next_run_at():%Y-%m-%d %H:%M})")
        if settings.allowed_emails:
            print(f"Dashboard logins limited to ALLOWED_EMAILS ({len(settings.allowed_emails)} address(es)).")
        else:
            print("Dashboard open to any signed-up account (set ALLOWED_EMAILS to limit it).")
        httpd.serve_forever()
