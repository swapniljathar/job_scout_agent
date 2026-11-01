import os
from datetime import datetime
import streamlit as st

from job_scout.agent import JobScoutAgent, ScoutCriteria
from job_scout.config import settings
from job_scout.digest import generate_email_digest_html
from job_scout.linkedin_scraper import build_linkedin_url
from job_scout.resume_parser import ResumeParseError, docling_available, parse_resume_bytes, parse_resume_link
from job_scout.storage import check_supabase_duplicates, store_job_in_supabase

agent = JobScoutAgent()

# ---------------------------------------------------------
# Page Configuration
# ---------------------------------------------------------
st.set_page_config(
    page_title="Job Scout & ATS Resume Agent",
    page_icon="🎯",
    layout="wide",
    initial_sidebar_state="expanded"
)

# ---------------------------------------------------------
# Session State Setup
# ---------------------------------------------------------
if "decisions" not in st.session_state:
    st.session_state["decisions"] = []

if "tailored_resumes" not in st.session_state:
    st.session_state["tailored_resumes"] = {}

# ---------------------------------------------------------
# Sidebar: Criteria & Pipeline Configuration
# ---------------------------------------------------------
st.sidebar.title("🎯 Job Scout Agent")
st.sidebar.caption("n8n Workflow + Streamlit Automation")

target_roles_input = st.sidebar.text_area(
    "Target Roles (comma-separated)",
    "Product Manager, Associate Product Manager, AI Product Manager",
    help="Primary job titles to search on LinkedIn"
)

location_input = st.sidebar.text_input(
    "Target Location",
    "Pune, Maharashtra, India",
    help="Geographic location for LinkedIn job listings"
)

col_f1, col_f2 = st.sidebar.columns(2)
with col_f1:
    time_filter = st.selectbox(
        "Date Posted",
        ["past24Hours", "pastWeek", "pastMonth"],
        index=1,
        help="Matching n8n f_TPR parameter"
    )
with col_f2:
    workplace_filter = st.selectbox(
        "Workplace",
        ["Any", "remote", "hybrid_or_remote", "onsite_or_remote"],
        index=0,
        help="Matching n8n f_WT parameter"
    )

must_have_keywords = st.sidebar.text_input(
    "Must-Have Keywords",
    "Python, AI, LLM, Agile, Product Strategy"
)

exclude_keywords = st.sidebar.text_input(
    "Exclude Keywords",
    "Manual QA, Unpaid, 10+ years"
)

max_jobs_to_fetch = st.sidebar.slider(
    "Target Job Recommendations",
    min_value=10,
    max_value=100,
    value=50,
    step=10,
    help="Select how many job recommendations to display on the dashboard (defaults to 50)"
)

data_source = st.sidebar.radio(
    "Data Source Mode",
    ["Apify Async Crawler", "Curated Demo Feed"],
    index=1,
    help="Toggle to Curated Demo Feed for instantaneous testing, or Apify Async Crawler to execute live LinkedIn extraction."
)

# Generated LinkedIn URL preview
primary_role = target_roles_input.split(",")[0].strip() if target_roles_input else "Product Manager"
remote_val = None if workplace_filter == "Any" else workplace_filter
generated_linkedin_url = build_linkedin_url(primary_role, location_input, time_filter, remote_val)

with st.sidebar.expander("🔗 Targeted LinkedIn Query URL", expanded=False):
    st.caption(generated_linkedin_url)

if st.sidebar.button("💾 Save Search Configuration"):
    st.sidebar.success("Criteria saved!")

# ---------------------------------------------------------
# Master Resume Helpers
# ---------------------------------------------------------
MASTER_RESUME_PATH = settings.master_resume_path.name

def load_master_resume():
    return agent.load_resume()

def save_master_resume(content):
    agent.save_resume(content)

# ---------------------------------------------------------
# UI Header
# ---------------------------------------------------------
st.title("🎯 Job Scout & ATS Resume Agent")
st.caption("Automated Agent Pipeline • LinkedIn Crawling • ATS Resume Tailoring • ModernCV LaTeX • Supabase Tracking")

# ---------------------------------------------------------
# Tabs
# ---------------------------------------------------------
tab1, tab2, tab3 = st.tabs(["📋 Scored Job Feed", "📄 Master Resume", "⚙️ Pipeline Diagnostics & Email Digest"])

# =========================================================
# TAB 1: Scored Job Feed
# =========================================================
with tab1:
    col_hdr, col_btn = st.columns([4, 1])
    with col_hdr:
        st.subheader("Curated & Scored Job Opportunities")
    with col_btn:
        if st.button("🔄 Refresh Pipeline", use_container_width=True):
            st.cache_data.clear()
            st.rerun()

    status_placeholder = st.empty()
    criteria = ScoutCriteria(
        query=primary_role,
        location=location_input,
        time_filter=time_filter,
        remote_filter=remote_val,
        target_roles=[r.strip() for r in target_roles_input.split(",") if r.strip()],
        must_haves=[k.strip() for k in must_have_keywords.split(",") if k.strip()],
        excludes=[k.strip() for k in exclude_keywords.split(",") if k.strip()],
        max_jobs=max_jobs_to_fetch,
    )

    if data_source == "Apify Async Crawler":
        with st.spinner(f"Executing asynchronous Apify crawling for {max_jobs_to_fetch} jobs..."):
            raw_jobs, fetch_error = agent.discover(criteria, live=True, fill_with_samples=True, status_callback=status_placeholder.info)
        if fetch_error:
            st.warning(f"⚠️ Apify Notice: {fetch_error}")
            st.info(f"💡 Showing {max_jobs_to_fetch} curated recommendations below so you can test ATS optimization and LaTeX generation without waiting.")
    else:
        st.info(f"ℹ️ Showing **{max_jobs_to_fetch} curated recommendations** for Pune, Remote & Tech Hubs.")
        raw_jobs, _ = agent.discover(criteria, live=False)

    status_placeholder.empty()

    # Deduplication check against Supabase
    new_jobs = check_supabase_duplicates(raw_jobs)
    new_links = {nj.get("jobLink") for nj in new_jobs}

    # Process and score
    resume_content = load_master_resume()
    scored_jobs = agent.score(raw_jobs, criteria, resume_content)
    for item in scored_jobs:
        item["is_new"] = item.get("jobLink") in new_links

    # Quick Search & Filter Controls for browsing 50+ recommendations smoothly
    col_search, col_filter = st.columns([3, 2])
    with col_search:
        search_filter = st.text_input("🔍 Quick search by keyword or company", "", placeholder="e.g. AI, Pune, Google, Generative, Remote...")
    with col_filter:
        match_filter = st.selectbox("Filter by Match Tier", ["All Scores", "High Match Only (≥80%)", "Top 25 Only"], index=0)

    # Apply filters
    display_jobs = scored_jobs
    if search_filter:
        s_query = search_filter.strip().lower()
        display_jobs = [j for j in display_jobs if s_query in j.get("title", "").lower() or s_query in j.get("company", "").lower() or s_query in j.get("location", "").lower()]

    if match_filter == "High Match Only (≥80%)":
        display_jobs = [j for j in display_jobs if j.get("score", 0) >= 80]
    elif match_filter == "Top 25 Only":
        display_jobs = display_jobs[:25]

    if display_jobs:
        st.success(f"Displaying {len(display_jobs)} ranked opportunities evaluated against your Master Profile (from {len(scored_jobs)} total loaded).")

        for idx, job in enumerate(display_jobs, 1):
            score = job["score"]
            badge_color = "🟢" if score >= 85 else ("🟡" if score >= 70 else "⚪")
            new_tag = "🆕 " if job.get("is_new") else ""

            with st.expander(f"{badge_color} {new_tag}#{idx} — {job['title']} @ {job['company']} (Match: {score}/100)"):
                col_info1, col_info2 = st.columns([3, 1])
                with col_info1:
                    st.markdown(f"**📍 Location:** {job['location']} | **💼 Seniority:** {job['seniorityLevel']} | **📅 Posted:** {job['postedAt']}")
                    st.markdown(f"**💡 Why you fit:** {job['why']}")
                    st.markdown(f"[🔗 Open Original Listing on LinkedIn]({job['jobLink']})")
                with col_info2:
                    st.metric(label="Alignment Score", value=f"{score}%")

                with st.expander("📄 Full Job Description Snippet", expanded=False):
                    desc = job.get("jobDescription", "")
                    st.text(desc[:1200] + ("..." if len(desc) > 1200 else ""))

                # Action buttons matching n8n nodes
                c1, c2, c3, c4 = st.columns(4)

                with c1:
                    if st.button(f"✨ Tailor ATS Resume #{idx}", key=f"tailor_{idx}"):
                        with st.spinner("Tailoring resume, building ModernCV LaTeX and drafting cover letter..."):
                            tailored = agent.tailor(job, resume_content)

                            st.session_state["tailored_resumes"][job["company"]] = {
                                "ats_text": tailored.ats_text,
                                "latex_code": tailored.latex_code,
                                "tex_file": tailored.tex_file,
                                "txt_file": tailored.txt_file,
                                "cover_letter": tailored.cover_letter,
                                "cover_file": tailored.cover_file
                            }

                            st.session_state["decisions"].append({
                                "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                                "action": "Tailored Resume (ATS + LaTeX)",
                                "job": f"{job['title']} @ {job['company']}",
                                "score": score
                            })

                        st.success(f"ATS & LaTeX resumes generated for {job['company']}!")

                with c2:
                    if st.button(f"💾 Record to Supabase #{idx}", key=f"store_{idx}"):
                        saved, msg = store_job_in_supabase(job)
                        if saved:
                            st.success(f"Saved {job['company']} to Supabase 'jobs' table!")
                        else:
                            st.info(f"Supabase Notice: {msg}")

                with c3:
                    if st.button(f"⏭️ Skip #{idx}", key=f"skip_{idx}"):
                        st.session_state["decisions"].append({
                            "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                            "action": "Skipped",
                            "job": f"{job['title']} @ {job['company']}",
                            "score": score
                        })
                        st.info(f"Marked #{idx} as skipped.")

                with c4:
                    if st.button(f"🚫 Not a Fit #{idx}", key=f"nofit_{idx}"):
                        st.session_state["decisions"].append({
                            "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                            "action": "Not a Fit",
                            "job": f"{job['title']} @ {job['company']}",
                            "score": score
                        })
                        st.warning(f"Marked #{idx} as not a fit.")

                # If tailored resume exists for this job, show download buttons
                if job["company"] in st.session_state["tailored_resumes"]:
                    res_info = st.session_state["tailored_resumes"][job["company"]]
                    col_dl1, col_dl2, col_dl3 = st.columns(3)
                    with col_dl1:
                        st.download_button(
                            label=f"⬇️ Download ATS Resume (.txt)",
                            data=res_info["ats_text"],
                            file_name=os.path.basename(res_info["txt_file"]),
                            mime="text/plain",
                            key=f"dl_txt_{idx}"
                        )
                    with col_dl2:
                        st.download_button(
                            label=f"⬇️ Download ModernCV (.tex)",
                            data=res_info["latex_code"],
                            file_name=os.path.basename(res_info["tex_file"]),
                            mime="text/x-tex",
                            key=f"dl_tex_{idx}"
                        )
                    with col_dl3:
                        st.download_button(
                            label="⬇️ Download Cover Letter (.txt)",
                            data=res_info["cover_letter"],
                            file_name=os.path.basename(res_info["cover_file"]),
                            mime="text/plain",
                            key=f"dl_cover_{idx}"
                        )
                    with st.expander("✉️ Cover letter draft", expanded=False):
                        st.text(res_info["cover_letter"])
    else:
        st.warning("No listings found matching current criteria.")

# =========================================================
# TAB 2: Master Resume
# =========================================================
with tab2:
    st.subheader("Master Resume Profile")
    st.markdown("Your foundational resume used by the agent to match qualifications and draft customized variations.")

    def show_parsed_resume(parsed, key):
        st.success(f"Extracted {parsed.word_count} words from `{parsed.source}` using **{parsed.engine}**.")
        for warning in parsed.warnings:
            st.warning(warning)
        col_meta1, col_meta2 = st.columns(2)
        with col_meta1:
            st.markdown("**Detected sections:** " + (", ".join(k for k in parsed.sections if k != "header") or "—"))
            st.markdown("**Contact:** " + " · ".join(v for v in parsed.contact.values() if v))
        with col_meta2:
            st.markdown("**Skills:** " + (", ".join(parsed.skills[:15]) or "—"))

        with st.expander("👁️ Preview Parsed Content", expanded=False):
            st.markdown(parsed.text[:3000] + ("..." if len(parsed.text) > 3000 else ""))

        if st.button("✅ Save & Set as Master Resume", type="primary", key=f"save_parsed_{key}"):
            save_master_resume(parsed.text)
            st.success("Master resume updated! Job match scores will now recalculate.")
            st.rerun()

    engine_label = "Docling (layout-aware)" if docling_available() else "basic text extraction — `pip install docling` for better results"
    st.caption(f"Parser engine: {engine_label}")

    # Upload Section
    st.markdown("#### 📤 Upload Your Resume")
    uploaded_file = st.file_uploader(
        "Upload a resume file to automatically parse and update your Master Profile",
        type=["pdf", "docx", "md", "txt"],
        help="Supported formats: PDF (.pdf), Microsoft Word (.docx), Markdown (.md), Plain Text (.txt)"
    )

    if uploaded_file is not None:
        with st.spinner(f"Parsing '{uploaded_file.name}'..."):
            try:
                show_parsed_resume(parse_resume_bytes(uploaded_file.getvalue(), uploaded_file.name), "upload")
            except ResumeParseError as err:
                st.error(f"⚠️ {err}")

    # Document Link Section
    st.markdown("#### 🔗 Import from Document Link")
    doc_link = st.text_input(
        "Google Docs, Google Drive, Dropbox, OneDrive or direct PDF/DOCX link",
        placeholder="https://docs.google.com/document/d/.../edit",
        help="The document must be shared as 'Anyone with the link can view'."
    )
    if doc_link:
        with st.spinner("Downloading and parsing document..."):
            try:
                show_parsed_resume(parse_resume_link(doc_link), "link")
            except ResumeParseError as err:
                st.error(f"⚠️ {err}")

    st.markdown("---")

    # Current Master Resume Display & Editor
    st.markdown("#### 📄 Current Active Master Resume")
    resume_text = load_master_resume()

    col_view1, col_view2 = st.columns([3, 1])
    with col_view2:
        edit_mode = st.toggle("✏️ Edit Resume Text", value=False)

    if edit_mode:
        updated_resume = st.text_area("Edit Markdown Content", resume_text, height=500)
        if st.button("💾 Save Edits to `master_resume.md`", type="primary"):
            save_master_resume(updated_resume)
            st.success("Master resume edits saved successfully!")
            st.rerun()
    else:
        if resume_text:
            st.code(resume_text, language="markdown")
        else:
            st.warning("No `master_resume.md` file found in workspace. Please upload a resume above or create one.")

# =========================================================
# TAB 3: Pipeline Diagnostics & Email Digest
# =========================================================
with tab3:
    st.subheader("Pipeline Diagnostics & Daily Digest")

    col_stat1, col_stat2, col_stat3 = st.columns(3)
    with col_stat1:
        st.metric("Total Jobs Evaluated", len(scored_jobs))
    with col_stat2:
        high_matches = sum(1 for j in scored_jobs if j["score"] >= 80)
        st.metric("High Match Opportunities (≥80%)", high_matches)
    with col_stat3:
        st.metric("Decisions Recorded", len(st.session_state["decisions"]))

    st.markdown("---")
    st.subheader("📧 Daily Email Digest Preview (n8n Style)")
    st.markdown("This formatted summary table matches the n8n Gmail node output for daily job reports.")

    email_html = generate_email_digest_html(scored_jobs[:5])
    st.components.v1.html(email_html, height=350, scrolling=True)

    with st.expander("📋 Copy Raw Email HTML"):
        st.code(email_html, language="html")

    st.markdown("---")
    st.subheader("Decisions & Feedback Log")
    if st.session_state["decisions"]:
        st.dataframe(st.session_state["decisions"], use_container_width=True)
    else:
        st.info("No decisions recorded yet in this session.")

    st.markdown("---")
    st.subheader("Connected Integrations & Services")
    st.json({
        "apify_actor": "curious_coder~linkedin-jobs-scraper",
        "supabase_endpoint": settings.supabase_url,
        "resume_parser": "docling" if docling_available() else "basic",
        "active_mode": data_source,
        "n8n_parity": "Full (URL builder, async crawler, Supabase deduplication, ATS resume, ModernCV LaTeX, Email digest)",
        "master_resume_file": MASTER_RESUME_PATH
    })
