"""
Dashboard web server + JSON API.

Routes:
  GET  /                         → job-hunt-dashboard.html
  GET  /favicon.svg|ico          → favicon
  GET  /api/health               → {"ok": true, "docling": bool}
  POST /api/resume/parse?filename=resume.pdf   (raw file bytes as body)
  POST /api/resume/parse         {"url": "<document link>"}  (application/json)

Signed-in routes (Authorization: Bearer <Supabase access token>, email must be in ALLOWED_EMAILS):
  GET  /api/jobs                 → {"jobs": [...]} processed in the last 30 days
  POST /api/jobs/<id>            {"status": "reviewed|applied|skipped|new", "tailored_resume"?, "cover_letter"?}
  GET  /api/scout/status         → running run, last run, next scheduled run, recent log lines
  POST /api/scout/run            → starts a run now (409 if one is already running)
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
from job_scout.scheduler import runner
from job_scout.storage import JOB_STATUSES, list_jobs, update_job

logger = logging.getLogger(__name__)

_token_cache = {}  # access token -> (email, expires_at)
_token_lock = threading.Lock()


def verify_login(auth_header):
    """Returns (email, error). Checks the Supabase access token and the ALLOWED_EMAILS list."""
    if not settings.allowed_emails:
        return None, "Set ALLOWED_EMAILS in the server's .env to your dashboard login email."
    token = auth_header[7:].strip() if auth_header.lower().startswith("bearer ") else ""
    if not token:
        return None, "Sign in to see your jobs."

    with _token_lock:
        cached = _token_cache.get(token)
    if cached and cached[1] > time.time():
        email = cached[0]
    else:
        auth_url = settings.supabase_url.split("/rest/v1")[0].rstrip("/") + "/auth/v1/user"
        try:
            response = requests.get(auth_url, headers={"apikey": settings.supabase_publishable_key,
                                                       "Authorization": f"Bearer {token}"}, timeout=8)
        except requests.RequestException as err:
            return None, f"Could not reach Supabase to check your login: {err}"
        if response.status_code != 200:
            return None, "Your session has expired. Sign in again."
        email = (response.json().get("email") or "").lower()
        with _token_lock:
            _token_cache[token] = (email, time.time() + 300)

    if email not in settings.allowed_emails:
        return None, f"{email or 'This account'} is not allowed on this server (ALLOWED_EMAILS)."
    return email, None

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
        email, err = verify_login(self.headers.get('Authorization', ''))
        if err:
            self._send_json(403 if "not allowed" in err else 401, {"error": err})
        return email

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
            if self._require_login():
                rows, err = list_jobs()
                if err:
                    self._send_json(502, {"error": err})
                else:
                    self._send_json(200, {"jobs": rows})
        elif path == '/api/scout/status':
            if self._require_login():
                self._send_json(200, runner.status())
        elif path.startswith('/api/'):
            self._send_json(404, {"error": "Not found"})
        else:
            self._route_static(include_body=True)

    def do_HEAD(self):
        self._route_static(include_body=False)

    def do_POST(self):
        parsed_url = urllib.parse.urlparse(self.path)
        if parsed_url.path == '/api/scout/run':
            if self._require_login():
                if runner.start("manual"):
                    self._send_json(202, runner.status())
                else:
                    self._send_json(409, {"error": "A scout run is already in progress."})
            return
        job_match = re.fullmatch(r'/api/jobs/(\d+)', parsed_url.path)
        if job_match:
            if self._require_login():
                self._update_job(int(job_match.group(1)))
            return
        if parsed_url.path != '/api/resume/parse':
            self._send_json(404, {"error": "Not found"})
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

    def _update_job(self, job_id):
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
        ok, err = update_job(job_id, fields)
        if ok:
            self._send_json(200, {"ok": True})
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
        if not settings.allowed_emails:
            print("⚠️  ALLOWED_EMAILS is empty: nobody can load jobs or start a run from the dashboard.")
        httpd.serve_forever()
