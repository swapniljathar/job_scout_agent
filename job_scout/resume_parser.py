"""
Resume parser with Docling + document-link support.

Engines (first available wins):
  1. Docling (IBM) — layout-aware PDF/DOCX/PPTX/HTML/image → Markdown, keeps headings,
     reading order, bullet lists and tables intact. Install with `pip install docling`.
  2. pypdf / python-docx — plain text fallback.
  3. UTF-8 decode — for .md / .txt.

Sources:
  - local file paths
  - raw bytes (uploads from Streamlit or the web dashboard)
  - document links: Google Docs, Google Drive, Dropbox, OneDrive or any direct URL
"""
import io
import re
import socket
import ipaddress
import logging
import urllib.parse
from dataclasses import dataclass, field, asdict
from functools import lru_cache
from pathlib import Path

import requests

from job_scout.config import settings

logger = logging.getLogger(__name__)

SUPPORTED_EXTENSIONS = {".pdf", ".docx", ".pptx", ".html", ".htm", ".md", ".txt", ".png", ".jpg", ".jpeg"}
TEXT_EXTENSIONS = {".md", ".txt"}

CONTENT_TYPE_EXTENSIONS = {
    "application/pdf": ".pdf",
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document": ".docx",
    "application/vnd.openxmlformats-officedocument.presentationml.presentation": ".pptx",
    "text/html": ".html",
    "text/markdown": ".md",
    "text/plain": ".txt",
    "image/png": ".png",
    "image/jpeg": ".jpg",
}

# Canonical section name → heading aliases seen in real resumes
SECTION_ALIASES = {
    "summary": ["summary", "about me", "profile", "professional summary", "executive summary", "objective"],
    "experience": ["experience", "work experience", "professional experience", "employment history", "work history"],
    "skills": ["skills", "key skills", "technical skills", "core competencies", "core expertise"],
    "education": ["education", "academic background", "education & certifications"],
    "certifications": ["certifications", "certificates", "licenses & certifications"],
    "projects": ["projects", "key projects"],
    "languages": ["languages", "spoken languages"],
}


class ResumeParseError(Exception):
    pass


@dataclass
class ParsedResume:
    text: str
    source: str
    engine: str
    sections: dict = field(default_factory=dict)
    contact: dict = field(default_factory=dict)
    skills: list = field(default_factory=list)
    warnings: list = field(default_factory=list)

    @property
    def word_count(self):
        return len(self.text.split())

    def to_dict(self):
        data = asdict(self)
        data["word_count"] = self.word_count
        return data


# ---------------------------------------------------------
# Docling engine
# ---------------------------------------------------------
def docling_available():
    try:
        import docling  # noqa: F401
        return True
    except ImportError:
        return False


@lru_cache(maxsize=1)
def _docling_converter():
    # Building the converter loads layout models, so do it once per process.
    from docling.document_converter import DocumentConverter
    return DocumentConverter()


def _parse_with_docling(data, filename):
    from docling.datamodel.base_models import DocumentStream
    stream = DocumentStream(name=filename, stream=io.BytesIO(data))
    result = _docling_converter().convert(stream)
    return result.document.export_to_markdown()


# ---------------------------------------------------------
# Fallback engines
# ---------------------------------------------------------
def _parse_pdf_fallback(data):
    import pypdf
    reader = pypdf.PdfReader(io.BytesIO(data))
    return "\n\n".join(page.extract_text() or "" for page in reader.pages)


def _parse_docx_fallback(data):
    import docx
    document = docx.Document(io.BytesIO(data))
    return "\n".join(p.text for p in document.paragraphs if p.text.strip())


def _extract_text(data, filename, use_docling):
    """Returns (text, engine_name, warnings)."""
    ext = Path(filename).suffix.lower()
    warnings = []

    if ext in TEXT_EXTENSIONS:
        return data.decode("utf-8", errors="ignore"), "plain", warnings

    if use_docling and docling_available():
        try:
            return _parse_with_docling(data, filename), "docling", warnings
        except Exception as err:
            logger.warning("Docling failed on %s, falling back: %s", filename, err)
            warnings.append(f"Docling failed ({err}); used fallback parser.")
    elif use_docling:
        warnings.append("Docling not installed; used basic parser. Run `pip install docling` for layout-aware parsing.")

    try:
        if ext == ".pdf":
            return _parse_pdf_fallback(data), "pypdf", warnings
        if ext == ".docx":
            return _parse_docx_fallback(data), "python-docx", warnings
    except ImportError as err:
        raise ResumeParseError(f"Missing parser dependency: {err.name}. Run: pip install -r requirements.txt") from err

    if ext in (".html", ".htm"):
        from job_scout.linkedin_scraper import strip_html
        return strip_html(data.decode("utf-8", errors="ignore")), "html", warnings

    raise ResumeParseError(f"Unsupported file type '{ext}'. Install Docling for images/PPTX, or upload PDF, DOCX, MD or TXT.")


# ---------------------------------------------------------
# Structure extraction
# ---------------------------------------------------------
def _normalize_text(text):
    # Ligatures and odd glyphs that PDF extractors commonly emit
    replacements = {"ﬁ": "fi", "ﬂ": "fl", "ﬀ": "ff", "ﬃ": "ffi", "ﬄ": "ffl", " ": " "}
    for old, new in replacements.items():
        text = text.replace(old, new)
    text = re.sub(r"[ \t]+\n", "\n", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def _match_section(line):
    """Returns the canonical section key if `line` looks like a section heading."""
    candidate = re.sub(r"^#+\s*", "", line.strip()).strip("*_: ").lower()
    if not candidate or len(candidate) > 40:
        return None
    for key, aliases in SECTION_ALIASES.items():
        if candidate in aliases:
            return key
    return None


def extract_sections(text):
    """Splits resume text into canonical sections keyed by SECTION_ALIASES. Text before the first heading → 'header'."""
    sections = {"header": []}
    current = "header"
    for line in text.splitlines():
        key = _match_section(line)
        if key:
            current = key
            sections.setdefault(current, [])
            continue
        sections.setdefault(current, []).append(line)
    return {key: "\n".join(lines).strip() for key, lines in sections.items() if "\n".join(lines).strip()}


def extract_contact(text):
    email = re.search(r"[\w.+-]+@[\w-]+\.[\w.-]+", text)
    phone = re.search(r"\+?\d[\d\s().-]{8,}\d", text)
    linkedin = re.search(r"(?:https?://)?(?:www\.)?linkedin\.com/in/[\w-]+/?", text, re.IGNORECASE)
    first_line = next((line.strip("#* ").strip() for line in text.splitlines() if line.strip()), "")
    return {
        "name": first_line if len(first_line.split()) <= 5 else "",
        "email": email.group(0) if email else "",
        "phone": phone.group(0).strip() if phone else "",
        "linkedin": linkedin.group(0) if linkedin else "",
    }


def extract_skills(skills_section):
    """Flattens 'Category: a, b, c' bullet lines into a de-duplicated skill list."""
    skills = []
    for line in skills_section.splitlines():
        line = re.sub(r"^[\s\-*•]+", "", line).strip()
        if not line:
            continue
        if ":" in line:
            line = line.split(":", 1)[1]
        for item in re.split(r"[,;|]", line):
            item = item.strip(" .*")
            if item and len(item) <= 60 and item.lower() not in (s.lower() for s in skills):
                skills.append(item)
    return skills


# ---------------------------------------------------------
# Document links
# ---------------------------------------------------------
def normalize_doc_link(url):
    """Rewrites share links (Google Docs/Drive, Dropbox, OneDrive) into direct-download URLs."""
    parsed = urllib.parse.urlparse(url.strip())
    host = parsed.netloc.lower()

    gdoc = re.search(r"/document/d/([\w-]+)", parsed.path)
    if "docs.google.com" in host and gdoc:
        return f"https://docs.google.com/document/d/{gdoc.group(1)}/export?format=docx"

    gdrive = re.search(r"/file/d/([\w-]+)", parsed.path)
    if "drive.google.com" in host and gdrive:
        return f"https://drive.google.com/uc?export=download&id={gdrive.group(1)}"
    if "drive.google.com" in host and "id=" in parsed.query:
        file_id = urllib.parse.parse_qs(parsed.query)["id"][0]
        return f"https://drive.google.com/uc?export=download&id={file_id}"

    if "dropbox.com" in host:
        query = urllib.parse.parse_qs(parsed.query)
        query["dl"] = ["1"]
        return urllib.parse.urlunparse(parsed._replace(query=urllib.parse.urlencode(query, doseq=True)))

    if "1drv.ms" in host or "onedrive.live.com" in host:
        separator = "&" if parsed.query else "?"
        return f"{url}{separator}download=1"

    return url


def _assert_public_host(url):
    """Blocks links to localhost / private networks so a shared server can't be used to probe internal hosts."""
    parsed = urllib.parse.urlparse(url)
    if parsed.scheme not in ("http", "https") or not parsed.hostname:
        raise ResumeParseError("Document link must be an http(s) URL.")
    try:
        infos = socket.getaddrinfo(parsed.hostname, None)
    except socket.gaierror as err:
        raise ResumeParseError(f"Could not resolve host '{parsed.hostname}'.") from err
    for info in infos:
        ip = ipaddress.ip_address(info[4][0])
        if ip.is_private or ip.is_loopback or ip.is_link_local or ip.is_reserved:
            raise ResumeParseError("Document links to private or local network addresses are not allowed.")


def _filename_from_response(response, url):
    disposition = response.headers.get("Content-Disposition", "")
    match = re.search(r'filename\*?=(?:UTF-8\'\')?"?([^";]+)"?', disposition)
    if match:
        name = urllib.parse.unquote(match.group(1))
        if Path(name).suffix.lower() in SUPPORTED_EXTENSIONS:
            return name
    path_name = Path(urllib.parse.urlparse(url).path).name
    if Path(path_name).suffix.lower() in SUPPORTED_EXTENSIONS:
        return path_name
    content_type = response.headers.get("Content-Type", "").split(";")[0].strip().lower()
    return "resume" + CONTENT_TYPE_EXTENSIONS.get(content_type, ".pdf")


def fetch_doc_link(url, max_bytes=None):
    """Downloads a document link. Returns (bytes, filename)."""
    max_bytes = max_bytes or settings.max_resume_bytes
    download_url = normalize_doc_link(url)

    try:
        # Follow redirects by hand so every hop is checked against private addresses.
        for _ in range(6):
            _assert_public_host(download_url)
            response = requests.get(download_url, stream=True, timeout=30, allow_redirects=False)
            if response.is_redirect:
                download_url = urllib.parse.urljoin(download_url, response.headers["Location"])
                response.close()
                continue
            break
        else:
            raise ResumeParseError("Too many redirects while downloading document link.")

        with response:
            if response.status_code != 200:
                raise ResumeParseError(
                    f"Could not download document (HTTP {response.status_code}). "
                    "Make sure the link is shared as 'Anyone with the link can view'."
                )
            chunks, size = [], 0
            for chunk in response.iter_content(64 * 1024):
                size += len(chunk)
                if size > max_bytes:
                    raise ResumeParseError(f"Document exceeds {max_bytes // (1024 * 1024)} MB limit.")
                chunks.append(chunk)
            data = b"".join(chunks)
            filename = _filename_from_response(response, download_url)
    except requests.RequestException as err:
        raise ResumeParseError(f"Failed to download document link: {err}") from err

    if filename.endswith(".html") and b"accounts.google.com" in data[:20000]:
        raise ResumeParseError("Google returned a sign-in page. Share the document as 'Anyone with the link can view'.")
    return data, filename


# ---------------------------------------------------------
# Public API
# ---------------------------------------------------------
def parse_resume_bytes(data, filename, use_docling=None):
    if not data:
        raise ResumeParseError("The uploaded file is empty.")
    if len(data) > settings.max_resume_bytes:
        raise ResumeParseError(f"File exceeds {settings.max_resume_bytes // (1024 * 1024)} MB limit.")
    use_docling = settings.use_docling if use_docling is None else use_docling

    raw_text, engine, warnings = _extract_text(data, filename, use_docling)
    text = _normalize_text(raw_text)
    if not text:
        raise ResumeParseError("No text could be extracted. If this is a scanned PDF, install Docling for OCR support.")

    sections = extract_sections(text)
    return ParsedResume(
        text=text,
        source=filename,
        engine=engine,
        sections=sections,
        contact=extract_contact(text),
        skills=extract_skills(sections.get("skills", "")),
        warnings=warnings,
    )


def parse_resume_file(path, use_docling=None):
    path = Path(path)
    if not path.is_file():
        raise ResumeParseError(f"File not found: {path}")
    return parse_resume_bytes(path.read_bytes(), path.name, use_docling)


def parse_resume_link(url, use_docling=None):
    data, filename = fetch_doc_link(url)
    parsed = parse_resume_bytes(data, filename, use_docling)
    parsed.source = url
    return parsed


def parse_resume(source, use_docling=None):
    """Parses a resume from a local path or a document link."""
    source = str(source)
    if source.startswith(("http://", "https://")):
        return parse_resume_link(source, use_docling)
    return parse_resume_file(source, use_docling)
