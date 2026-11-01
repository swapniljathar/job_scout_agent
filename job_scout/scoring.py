"""Fit scoring engine: ranks a job against target roles and keyword preferences."""


def score_job(job, resume_text, must_haves, excludes, target_roles):
    """Returns (score 10–99, human-readable reason)."""
    title = job.get("title", "").lower()
    description = job.get("jobDescription", "").lower()
    combined_text = f"{title} {description}"

    score = 65
    reasons = []

    title_matches = [role.strip().lower() for role in target_roles if role.strip().lower() in title]
    if title_matches:
        score += 15
        reasons.append(f"Title directly matches: '{title_matches[0].title()}'.")
    elif any(w in title for w in ["product", "ai", "apm", "manager"]):
        score += 8
        reasons.append("Title aligns with product/AI focus.")

    excluded_found = [kw.strip().lower() for kw in excludes if kw.strip() and kw.strip().lower() in combined_text]
    if excluded_found:
        score -= 25
        reasons.append(f"Contains excluded keywords: {', '.join(excluded_found)}.")

    matched_must_haves = [kw.strip().lower() for kw in must_haves if kw.strip() and kw.strip().lower() in combined_text]
    if matched_must_haves:
        boost = min(len(matched_must_haves) * 4, 15)
        score += boost
        reasons.append(f"Matches key competencies: {', '.join(matched_must_haves[:4])}.")

    if "agent" in combined_text or "llm" in combined_text or "generative ai" in combined_text:
        score += 5
        reasons.append("Synergy with generative AI and agentic workflow experience.")

    final_score = max(10, min(99, score))
    why_text = " ".join(reasons) if reasons else "General alignment with product profile."
    return final_score, why_text


def score_jobs(jobs, resume_text, must_haves, excludes, target_roles):
    """Scores jobs in place (adds 'score' and 'why') and returns them sorted best-first."""
    for job in jobs:
        job["score"], job["why"] = score_job(job, resume_text, must_haves, excludes, target_roles)
    return sorted(jobs, key=lambda j: j["score"], reverse=True)
