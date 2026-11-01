"""ATS resume tailoring (Gemini or heuristic) and ModernCV LaTeX rendering."""
import re
import logging

import requests

from job_scout.config import settings
from job_scout.resume_parser import extract_contact, extract_sections
from job_scout.unslop import UNSLOP_PROMPT, unslop

logger = logging.getLogger(__name__)

# ---------------------------------------------------------
# 5. ATS Resume Optimizer (from n8n 'ATS Optimizer Agent')
# ---------------------------------------------------------
ATS_SYSTEM_PROMPT = """You are an expert ATS resume optimizer.

Your task is to revise the resume so it is optimized for Applicant Tracking Systems (ATS) and tailored to the target job (JD).

Keyword Optimization: Extract the most important hard skills, technical terms, tools, certifications, and role-specific keywords from the JD. Integrate these throughout the resume, especially in experience bullet points, summary, and skills section.

Role Alignment: Identify responsibilities and achievements from the current resume that most closely match the target role. Rewrite bullet points to highlight quantifiable achievements, results, and leadership impact. Reorder or reframe content so the most role-aligned experiences are emphasized.

Professional Voice: Use strong action verbs (Led, Launched, Optimized, Delivered, Drove, Built, Reduced, Increased). Focus on measurable outcomes where they exist in the original. Do NOT invent metrics.

Bullet rules: Each bullet = action + what + outcome. Max 4-6 bullets per role. Max 2 pages total content.

Final Output (STRICT, follow exactly):
Return ONLY plain text. No Markdown. No asterisks. No ### headers. No horizontal rules. No bullet symbols like •.

Use ONLY these section headers (ALL CAPS, on their own line):
NAME
CONTACT
SUMMARY
PROFESSIONAL EXPERIENCE
EDUCATION
SKILLS

Separate sections with one blank line.
For bullets use: - (hyphen + space)
For job entries use exactly:
COMPANY | LOCATION
TITLE | DATES
- bullet
- bullet

Do not invent facts, companies, dates, or metrics.
""" + UNSLOP_PROMPT


GEMINI_ENDPOINT = "https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"


def _generate_with_gemini(system_prompt, prompt, gemini_api_key):
    """Calls the Gemini REST API (same model family as the n8n 'Google Gemini Chat Model' node).
    Returns generated text, or None if Gemini is unavailable or fails."""
    if not gemini_api_key:
        return None
    try:
        response = requests.post(
            GEMINI_ENDPOINT.format(model=settings.gemini_model),
            headers={"x-goog-api-key": gemini_api_key, "Content-Type": "application/json"},
            json={
                "system_instruction": {"parts": [{"text": system_prompt}]},
                "contents": [{"role": "user", "parts": [{"text": prompt}]}],
            },
            timeout=180,  # full Flash models can think for 2+ minutes
        )
        if response.status_code != 200:
            logger.warning("Gemini HTTP %s, falling back to heuristic engine: %s", response.status_code, response.text[:200])
            return None
        parts = response.json().get("candidates", [{}])[0].get("content", {}).get("parts", [])
        text = "".join(part.get("text", "") for part in parts).strip()
        return text or None
    except (requests.RequestException, ValueError, IndexError) as err:
        logger.warning("Gemini generation failed, falling back to heuristic engine: %s", err)
    return None

def generate_ats_optimized_resume(current_resume_text, job_description, target_role="Product Manager", gemini_api_key=None):
    """
    Generates an ATS-tailored plain text resume following the strict n8n format.
    Uses Google Gemini if API key is present; otherwise applies heuristic ATS tailoring.
    """
    prompt = f"My current resume:\n{current_resume_text}\n\nA target job description (JD) for the role I am applying to:\n{job_description}"
    generated = _generate_with_gemini(ATS_SYSTEM_PROMPT, prompt, gemini_api_key or settings.gemini_api_key)
    if generated:
        return unslop(generated), None

    # Local Heuristic ATS Optimizer
    # Extract keywords from JD
    jd_words = set(re.findall(r'\b[A-Za-z]{3,}\b', job_description.lower()))
    highlight_skills = []
    for skill in ["AI", "LLM", "Python", "Agile", "PRD", "Scrum", "SQL", "Product Strategy", "RAG", "Prompt Engineering", "Data Analytics", "Roadmapping"]:
        if skill.lower() in jd_words:
            highlight_skills.append(skill)

    skills_str = ", ".join(highlight_skills) if highlight_skills else "Product Management, Agile, Strategy, AI/ML, Python"

    # NAME / CONTACT headers follow the strict n8n output format so build_moderncv_latex can read them
    contact = extract_contact(current_resume_text or "")
    name = contact["name"] or "Swapnil Jathar"
    contact_line = " | ".join(filter(None, [
        "Pune, Maharashtra, India",
        contact["email"] or "swapnil@example.com",
        contact["phone"],
        re.sub(r"^https?://(www\.)?", "", contact["linkedin"]) or "linkedin.com/in/swapnil-jathar",
    ]))

    ats_plain = f"""NAME
{name}

CONTACT
{contact_line}

SUMMARY
Product Manager working on AI/ML products and agentic workflows. Writes PRDs, works with engineering on technical trade-offs, and ships enterprise automation products. Applying for {target_role} roles.

PROFESSIONAL EXPERIENCE
Mphasis (Client: JPMorganChase) | Pune, India
Associate Product Manager | 2022 - Present
- Led enterprise workflow optimization platforms powered by AI and automation, improving team efficiency by 30%.
- Wrote Product Requirement Documents (PRDs) and user stories for Agile sprints.
- Partnered with machine learning teams and enterprise stakeholders to integrate LLM and analytics pipelines.
- Tracked adoption, latency and accuracy metrics and used them to reprioritize the roadmap.

Birdvision Consulting | Pune, India
Product Associate | 2021 - 2022
- Managed end-to-end sprint backlogs, release coordination, and customer feedback loops for SaaS engagement products.
- Conducted user interviews and competitive benchmarking to inform feature prioritization and roadmap milestones.
- Designed wireframes and ran User Acceptance Testing (UAT) with engineering teams.

EDUCATION
Pune University | Pune, India
Bachelor of Engineering | 2017 - 2021

SKILLS
Core Competencies: Product Strategy, Roadmapping, PRDs, Agile/Scrum, User Research, Stakeholder Management
Technical & AI: {skills_str}, Streamlit, REST APIs, Supabase, Git, Jira
"""
    return unslop(ats_plain), None


# ---------------------------------------------------------
# Cover Letter Drafting
# ---------------------------------------------------------
COVER_LETTER_SYSTEM_PROMPT = """You write short cover letters for job applications.

Write 3 short paragraphs, under 220 words in total, addressed to the hiring team.
Paragraph 1: name the role and company, then give the single strongest fact from the resume that matches the job.
Paragraph 2: connect one or two more resume facts to specific requirements in the job description.
Paragraph 3: one or two sentences asking for a conversation. No generic praise of the company.
Sign off with "Sincerely," and the candidate's name.

Use only facts, numbers, companies and dates that appear in the resume. Do not invent anything.
Return plain text only.
""" + UNSLOP_PROMPT


def _resume_bullets(resume_text):
    experience = extract_sections(resume_text).get("experience", resume_text)
    bullets = []
    for line in experience.splitlines():
        line = line.strip()
        if re.match(r"^[-*\u2022]\s+", line):
            bullets.append(re.sub(r"^[-*\u2022]\s+", "", line).rstrip("."))
    return bullets


def _first_person(bullet):
    """'Led X' → 'I led X'. Leaves bullets that don't start with a past-tense verb untouched."""
    first, _, rest = bullet.partition(" ")
    if first.lower().endswith("ed") or first.lower() in ("led", "built", "ran", "wrote", "drove", "won", "grew", "set", "cut", "made"):
        return f"I {first.lower()} {rest}".strip()
    return bullet


def generate_cover_letter(resume_text, job, gemini_api_key=None):
    """Drafts a cover letter from the master resume for `job` (dict with title/company/jobDescription), unslopped."""
    title = job.get("title", "this")
    company = job.get("company", "your company")
    description = job.get("jobDescription", "")

    prompt = f"Resume:\n{resume_text}\n\nRole: {title} at {company}\n\nJob description:\n{description}"
    generated = _generate_with_gemini(COVER_LETTER_SYSTEM_PROMPT, prompt, gemini_api_key or settings.gemini_api_key)
    if generated:
        return unslop(generated)

    # Heuristic: pick the resume bullets that share the most words with the job description
    jd_words = set(re.findall(r"[a-z]{4,}", description.lower()))
    ranked = sorted(_resume_bullets(resume_text), key=lambda b: len(jd_words & set(re.findall(r"[a-z]{4,}", b.lower()))), reverse=True)
    name = extract_contact(resume_text).get("name") or "Candidate"

    opening = f"I'm applying for the {title} role at {company}."
    if ranked:
        opening += f" {_first_person(ranked[0])}."
    middle = " ".join(f"{_first_person(b)}." for b in ranked[1:3]) if len(ranked) > 1 else ""
    if middle:
        middle = f"Two more things from my resume match this role. {middle}"

    paragraphs = [f"Dear {company} hiring team,", opening]
    if middle:
        paragraphs.append(middle)
    paragraphs.append("I'd like to talk about what I could take on in this role. My resume is attached.")
    paragraphs.append(f"Sincerely,\n{name}")
    return unslop("\n\n".join(paragraphs))

# ---------------------------------------------------------
# 6. ModernCV LaTeX Resume Builder (from n8n 'Build LaTeX Resume')
# ---------------------------------------------------------
def latex_escape(s):
    if not s:
        return ""
    replacements = [
        ('\\', r'\textbackslash{}'),
        ('&', r'\&'),
        ('%', r'\%'),
        ('$', r'\$'),
        ('#', r'\#'),
        ('_', r'\_'),
        ('{', r'\{'),
        ('}', r'\}'),
        ('~', r'\textasciitilde{}'),
        ('^', r'\textasciicircum{}'),
    ]
    for old, new in replacements:
        s = s.replace(old, new)
    return s

def extract_section(text, header):
    # Header lookup is case-insensitive; the next-header lookahead only stops at ALL CAPS lines
    pattern = rf'(?:^|\n)(?i:{re.escape(header)})\s*\n([\s\S]*?)(?=\n[A-Z][A-Z ]{{2,}}\s*\n|$)'
    match = re.search(pattern, text)
    return match.group(1).strip() if match else ""

def build_experience_latex(text):
    if not text:
        return r"\cvitem{}{}"
    lines = text.split("\n")
    blocks = []
    current = []
    for line in lines:
        trimmed = line.strip()
        if not trimmed:
            continue
        if "|" in trimmed and not trimmed.startswith("-") and len(current) > 0:
            blocks.append(current)
            current = []
        current.append(trimmed)
    if current:
        blocks.append(current)

    out = ""
    for block in blocks:
        company_name, location = (block[0].split("|") + [""])[:2]
        title, dates = (block[1].split("|") + [""])[:2] if len(block) > 1 else ("", "")
        bullets = [bullet for bullet in block[2:] if bullet.startswith("- ")]

        out += f"\n\\cventry{{{latex_escape(dates.strip())}}}{{{latex_escape(title.strip())}}}{{{latex_escape(company_name.strip())}}}{{{latex_escape(location.strip())}}}{{}}{{\n"
        if bullets:
            out += "  \\begin{itemize}\n"
            for bullet in bullets:
                clean_bullet = re.sub(r'^-\s+', '', bullet)
                out += f"    \\item {latex_escape(clean_bullet)}\n"
            out += "  \\end{itemize}\n"
        out += "}\n"
    return out or r"\cvitem{}{}"

def build_education_latex(text):
    if not text:
        return r"\cvitem{}{}"
    lines = [line.strip() for line in text.split("\n") if line.strip() and not line.strip().startswith("-")]
    out = ""
    for i in range(0, len(lines) - 1, 2):
        school, location = (lines[i].split("|") + [""])[:2]
        degree, dates = (lines[i+1].split("|") + [""])[:2]
        out += f"\\cventry{{{latex_escape(dates.strip())}}}{{{latex_escape(degree.strip())}}}{{{latex_escape(school.strip())}}}{{{latex_escape(location.strip())}}}{{}}{{}}\n"
    return out or r"\cvitem{}{}"

def build_skills_latex(text):
    if not text:
        return r"\cvitem{}{}"
    lines = [line.strip().lstrip("- ") for line in text.split("\n") if line.strip()]
    out = []
    for line in lines:
        if ":" in line:
            category, items = line.split(":", 1)
            out.append(f"\\cvitem{{{latex_escape(category.strip())}}}{{{latex_escape(items.strip())}}}")
        else:
            out.append(f"\\cvitem{{}}{{{latex_escape(line)}}}")
    return "\n".join(out)

def build_moderncv_latex(ats_plain_text):
    """
    Builds a professional ModernCV LaTeX document from the ATS plain text resume.
    """
    name_raw = extract_section(ats_plain_text, "NAME") or "Swapnil Jathar"
    contact_raw = extract_section(ats_plain_text, "CONTACT")
    summary_raw = extract_section(ats_plain_text, "SUMMARY")
    experience_raw = extract_section(ats_plain_text, "PROFESSIONAL EXPERIENCE")
    education_raw = extract_section(ats_plain_text, "EDUCATION")
    skills_raw = extract_section(ats_plain_text, "SKILLS")

    # Name
    full_name = name_raw.split("\n")[0].strip() or "Swapnil Jathar"
    name_parts = full_name.split()
    first_name = " ".join(name_parts[:-1]) if len(name_parts) > 1 else full_name
    last_name = name_parts[-1] if len(name_parts) > 1 else ""

    # Contact tokens
    contact_tokens = [s.strip() for s in contact_raw.replace("\n", " | ").split("|") if s.strip()]
    email = next((t for t in contact_tokens if "@" in t), "swapnil@example.com")
    phone = next((t for t in contact_tokens if re.search(r'\d{3}[-.\s]\d{3}', t)), "")
    linkedin = next((t for t in contact_tokens if "linkedin" in t.lower()), "")
    linkedin_clean = re.sub(r'^(https?://)?(www\.)?linkedin\.com/in/', '', linkedin, flags=re.IGNORECASE).strip('/')
    city = next((t for t in contact_tokens if "@" not in t and not re.search(r'\d{3}[-.\s]\d{3}', t) and "linkedin" not in t.lower()), "Pune, India")

    latex_code = f"""\\documentclass[11pt,a4paper,sans]{{moderncv}}
\\moderncvstyle{{banking}}
\\moderncvcolor{{blue}}
\\usepackage[scale=0.88]{{geometry}}
\\usepackage{{hyperref}}
\\nopagenumbers{{}}

\\name{{{latex_escape(first_name)}}}{{{latex_escape(last_name)}}}
"""
    if phone:
        latex_code += f"\\phone[mobile]{{{latex_escape(phone)}}}\n"
    latex_code += f"\\email{{{latex_escape(email)}}}\n"
    if linkedin_clean:
        latex_code += f"\\social[linkedin]{{{latex_escape(linkedin_clean)}}}\n"
    latex_code += f"\\address{{{latex_escape(city)}}}{{}}{{}}\n"

    latex_code += f"""
\\begin{{document}}
\\makecvtitle

\\section{{Summary}}
\\cvitem{{}}{{{latex_escape(summary_raw.replace(chr(10), ' '))}}}

\\section{{Professional Experience}}
{build_experience_latex(experience_raw)}

\\section{{Education}}
{build_education_latex(education_raw)}

\\section{{Skills}}
{build_skills_latex(skills_raw)}

\\end{{document}}
"""
    return latex_code

