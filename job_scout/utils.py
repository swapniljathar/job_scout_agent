"""Shared helpers."""
import re


def sanitize_slug(text: str) -> str:
    """
    Sanitizes a company name or role title into a clean alphanumeric slug suitable for filenames and URLs.
    """
    if not text:
        return "untitled"
    cleaned = "".join(c for c in text if c.isalnum() or c in (' ', '_', '-')).strip()
    slug = re.sub(r'[\s\-]+', '_', cleaned).lower()
    return slug or "untitled"
