"""
Unslop: strip AI-writing tells from tailored resumes and cover letters.

Based on https://github.com/cursor/plugins/blob/main/pstack/skills/unslop/SKILL.md.
Two layers:
  - UNSLOP_PROMPT is appended to every LLM drafting prompt so the model avoids the patterns.
  - unslop() is a deterministic cleanup pass applied to every draft afterwards (LLM or heuristic),
    limited to substitutions that keep the sentence grammatical.
"""
import re

UNSLOP_PROMPT = """
Writing rules (unslop). Follow them strictly:
- Use plain words. Never use: leverage, utilize, spearhead, synergy, robust, seamless, cutting-edge, dynamic, passionate, results-driven, proven track record, delve, pivotal, crucial, showcase, foster, enhance, testament, landscape, tapestry, underscore, vibrant, additionally, journey, game-changer, north star, flywheel, paradigm.
- No em dashes or en dashes. Use a period or a comma. Date ranges use a plain hyphen (2022 - Present).
- No "not just X, but Y". No forced groups of three. No "from X to Y" lists.
- No superficial -ing tails such as "ensuring...", "highlighting...", "showcasing...", "fostering...".
- No filler: "in order to" is "to", "due to the fact that" is "because". No hedging.
- Active voice. Name who did what. Prefer a number or a concrete fact over an adjective or adverb.
- One idea per sentence. Whole sentences with articles and verbs, no arrows or symbol-speak.
- No emojis, no curly quotes, no bold labels followed by a colon, no title-case sentences.
- Cover letters: no "I am writing to express my enthusiasm", no "I hope this finds you well", no generic closing like "I look forward to contributing to your continued success". Open with the role and the strongest relevant fact.
"""

# (pattern, replacement). Case of the first letter is preserved. Order matters: phrases before single words.
_REPLACEMENTS = [
    (r"\bI am writing to (?:express|convey) my (?:strong |keen |eager |sincere |great )?(?:enthusiasm|interest|excitement) (?:for|in) (?:applying (?:for|to) )?", "I'm applying for "),
    (r"\bI hope (?:this|my) (?:letter |message |email )?finds you well\.?\s*", ""),
    (r"\bI hope this helps!?\s*", ""),
    (r",? ensuring (?!that\b)", " with "),  # superficial -ing tail: keep the fact, drop the flourish
    (r"\bin order to\b", "to"),
    (r"\bdue to the fact that\b", "because"),
    (r"\bit is (?:important|worth) (?:to note|noting) that\s*", ""),
    (r"\b(?:a )?proven track record (?:of|in)\b", "a record of"),
    (r"\b(?:a )?proven track record (?=\w+ing\b)", "experience "),
    (r"\b0\s*\u2192\s*1\b", "0-to-1"),
    (r"\s*\u2192\s*", " to "),
    (r"\bresults[- ]driven\s+", ""),
    (r"\bhighly motivated\s+", ""),
    (r"\bdetail[- ]oriented\s+", ""),
    (r"\b(?:deeply |truly )?passionate about\b", "interested in"),
    (r"\bcutting[- ]edge\b", "modern"),
    (r"\bstate[- ]of[- ]the[- ]art\b", "modern"),
    (r"\bgame[- ]chang(?:er|ing)\b", "major"),
    (r"\bseamless(?:ly)?\s+", ""),
    (r"\bspearhead(ed|ing|s)?\b", None),  # handled by _verb_map
    (r"\bleverag(e|ed|es|ing)\b", None),
    (r"\butiliz(e|ed|es|ing)\b", None),
    (r"\bshowcas(e|ed|es|ing)\b", None),
    (r"\bfoster(ed|ing|s)?\b", None),
    (r"\benhanc(e|ed|es|ing)\b", None),
    (r"\bfacilitat(e|ed|es|ing)\b", None),
    (r"\bsynerg(?:y|ies) with\b", "fit with"),
    (r"\bpivotal\b", "key"),
    (r"\bcrucial\b", "key"),
    (r"\bnumerous\b", "many"),
    (r"\bmyriad of\b", "many"),
    (r"\bAdditionally, ", ""),
    (r"\bMoreover, ", ""),
    (r"\bFurthermore, ", ""),
]

_VERB_MAP = {
    "spearhead": {"": "lead", "ed": "led", "ing": "leading", "s": "leads"},
    "leverag": {"e": "use", "ed": "used", "es": "uses", "ing": "using"},
    "utiliz": {"e": "use", "ed": "used", "es": "uses", "ing": "using"},
    "showcas": {"e": "show", "ed": "showed", "es": "shows", "ing": "showing"},
    "foster": {"": "build", "ed": "built", "ing": "building", "s": "builds"},
    "enhanc": {"e": "improve", "ed": "improved", "es": "improves", "ing": "improving"},
    "facilitat": {"e": "run", "ed": "ran", "es": "runs", "ing": "running"},
}

# Words to report even when they can't be rewritten mechanically
SLOP_WORDS = [
    "delve", "tapestry", "testament", "landscape", "underscore", "vibrant", "intricate", "interplay",
    "garner", "robust", "dynamic", "passionate", "synergy", "journey", "north star", "flywheel", "paradigm",
    "not just", "ensuring", "showcasing", "fostering", "highlighting",
]

_EMOJI = re.compile("[\U0001F300-\U0001FAFF\U00002700-\U000027BF\U0001F000-\U0001F2FF\u2600-\u26FF\uFE0F]")
_DATE_TOKEN = r"(?:\d{4}|Present|Current|Now|(?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Sept|Oct|Nov|Dec)[a-z]*\.?(?: \d{4})?)"


def _match_case(original, replacement):
    if original[:1].isupper() and replacement:
        return replacement[:1].upper() + replacement[1:]
    return replacement


def _replace_dashes(text):
    # Date ranges keep a plain hyphen: "May 2025 — Present" → "May 2025 - Present"
    text = re.sub(rf"({_DATE_TOKEN})\s*[\u2014\u2013]\s*({_DATE_TOKEN})", r"\1 - \2", text)
    # Spaced dash between clauses → comma
    text = re.sub(r"\s+[\u2014\u2013]\s+", ", ", text)
    # Unspaced em dash inside a sentence → comma
    text = re.sub(r"(?<=\w)\u2014(?=\w)", ", ", text)
    # Remaining en dashes are numeric ranges: "15–20%" → "15-20%"
    return text.replace("\u2013", "-").replace("\u2014", ", ")


def unslop(text):
    """Deterministic cleanup of AI tells. Safe to run on any resume or cover letter draft."""
    if not text:
        return text

    text = text.replace("\u201c", '"').replace("\u201d", '"').replace("\u2018", "'").replace("\u2019", "'")
    text = _replace_dashes(text)
    text = _EMOJI.sub("", text)

    for pattern, replacement in _REPLACEMENTS:
        if replacement is None:
            stem = re.sub(r"\\b|\(.*", "", pattern)
            forms = _VERB_MAP[stem]
            text = re.sub(pattern, lambda m, s=stem, f=forms: _match_case(m.group(0), f[m.group(1) or ""]), text, flags=re.IGNORECASE)
        elif replacement == "":
            # Deletion: if the removed phrase opened a sentence, capitalize the word that now opens it
            text = re.sub(f"(?:{pattern})(\\w?)", lambda m: m.group(1).upper() if m.group(0)[:1].isupper() else m.group(1),
                          text, flags=re.IGNORECASE)
        else:
            text = re.sub(pattern, lambda m, r=replacement: _match_case(m.group(0), r), text, flags=re.IGNORECASE)

    text = re.sub(r"[ \t]{2,}", " ", text)
    text = re.sub(r" +([,.;:])", r"\1", text)
    text = re.sub(r",\s*,", ",", text)
    return text.strip()


def find_slop(text):
    """Returns the AI-tell words/phrases still present in `text` (for review warnings)."""
    lowered = (text or "").lower()
    found = [word for word in SLOP_WORDS if re.search(rf"\b{re.escape(word)}\b", lowered)]
    if "\u2014" in (text or ""):
        found.append("em dash")
    return found
