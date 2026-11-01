"""
Dashboard web server + JSON API.

Routes:
  GET  /                         → job-hunt-dashboard.html
  GET  /favicon.svg|ico          → favicon
  GET  /api/health               → {"ok": true, "docling": bool}
  POST /api/resume/parse?filename=resume.pdf   (raw file bytes as body)
  POST /api/resume/parse         {"url": "<document link>"}  (application/json)
"""
import json
import logging
import urllib.parse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from job_scout.config import PROJECT_ROOT, settings
from job_scout.resume_parser import ResumeParseError, docling_available, parse_resume_bytes, parse_resume_link

logger = logging.getLogger(__name__)

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

    def do_GET(self):
        if self.path.split('?', 1)[0] == '/api/health':
            self._send_json(200, {"ok": True, "docling": docling_available()})
            return
        self._route_static(include_body=True)

    def do_HEAD(self):
        self._route_static(include_body=False)

    def do_POST(self):
        parsed_url = urllib.parse.urlparse(self.path)
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


def run_server(port=None):
    port = port or settings.port
    ThreadingHTTPServer.allow_reuse_address = True
    with ThreadingHTTPServer(("", port), DashboardHandler) as httpd:
        print(f"Job Scout Agent is live at: http://localhost:{port}")
        print(f"Resume parser engine: {'Docling' if docling_available() else 'basic (pip install docling for layout-aware parsing)'}")
        httpd.serve_forever()
