## 🎯 Job Scout Agent · Intelligent Career Navigator & ATS Suite

[![Python](https://img.shields.io/badge/Python-3.10+-3776AB?logo=python&logoColor=white)](https://python.org)
[![TailwindCSS](https://img.shields.io/badge/TailwindCSS-v3.4-38B2AC?logo=tailwindcss&logoColor=white)](https://tailwindcss.com)
[![Streamlit](https://img.shields.io/badge/Streamlit-1.32+-FF4B4B?logo=streamlit&logoColor=white)](https://streamlit.io)
[![Apify](https://img.shields.io/badge/Apify-LinkedIn_Crawler-00C5FF?logo=apify&logoColor=white)](https://apify.com)
[![Supabase](https://img.shields.io/badge/Supabase-Auth_&_DB-3ECF8E?logo=supabase&logoColor=white)](https://supabase.com)
[![Privacy](https://img.shields.io/badge/Privacy-100%25_Local_Resume-brightgreen)](https://github.com/swapniljathar/job_scout_agent)

> **Job Scout Agent** is a privacy-first, human-in-the-loop autonomous job discovery and application tailoring platform. It automates high-match role scouting from LinkedIn, calculates multi-dimensional ATS fit scores against your master profile, and generates bespoke, editable resumes, cover letters, and recruiter outreach messages.

---

## 💡 About

**Job Scout Agent** bridges the gap between generic spray-and-pray applications and exhausting manual tailoring. It acts as an autonomous personal career co-pilot—discovering relevant opportunities, calculating ATS alignment, and drafting tailored application assets while keeping **you firmly in control**.

### Core Pillars
- **🎯 Precision Fit over Volume**: Evaluates roles using multi-dimensional scoring (Title Alignment, Skills Match, Seniority) so you only spend time on high-yield opportunities ($\ge 80\%$).
- **✍️ Human-in-the-Loop Tailoring**: Generates job-specific resume bullets and cover letters with an interactive editor to inspect, refine, and approve before applying.
- **⚡ Recruiter Intelligence**: Surfaces hiring managers and generates personalized, high-converting LinkedIn connection notes and outreach drafts.
- **🔒 Privacy by Design**: Master resumes, personal contact details, and application records remain 100% on your local machine.

---

## 🗺️ Complete Website & Application Map

The Job Scout Agent interface is designed with a soothing, distraction-free neutral aesthetic (soft whites, light greys, pastel accent cards) and an intuitive, tabbed architecture with an interactive slide-over review drawer.

### 1. Visual Site Architecture

```mermaid
flowchart TD
    subgraph Global_Header["Top Navigation Bar"]
        Brand["Logo & Title (Job Scout)"]
        NavLinks["Navigation Tabs"]
        ScoutStatus["Live Agent Status Badge"]
        ScoutBtn["Run Scout Cycle"]
        AuthBtn["User Profile / Sign In"]
    end

    subgraph Main_Views["Main Application Views"]
        TabDash["📊 1. Dashboard\n• Hero & Session Metrics\n• Top Pastel Matches Grid\n• Staged Applications Queue\n• Quick Scout Triggers"]
        TabBrowse["🔍 2. Browse Roles\n• Full Job Search & Feed\n• Location, Exp & Score Filters\n• Keyword Search & Sort\n• Instant Tailor / Skip Actions"]
        TabApps["📑 3. Applications\n• Ledger Table & History\n• Filter by Pipeline Status\n• Review Generated Material\n• Export CSV / Print"]
        TabTracker["📌 4. Pipeline Tracker\n• Interactive Kanban Board\n• Drag/Drop Status Stages\n• Discovery ➔ Offer Journey\n• Follow-up Reminders"]
        TabInbox["✉️ 5. Outreach Inbox\n• Recruiter Contacts Directory\n• AI Cold Outreach Generator\n• Connection Notes\n• Follow-Up Message Drafter"]
        TabResume["📄 6. Master Resume Hub\n• Active Resume Viewer & Editor\n• Drag-and-Drop Uploader\n• Skill & Competency Matrix\n• Instant Re-Score Trigger"]
    end

    subgraph SlideOver_Drawer["📂 Role Review & Tailoring Slide-Over Drawer"]
        DTabResume["📝 ATS Tailored Resume\n• Side-by-side Role Alignment\n• Live AI Bullet Rephraser\n• Editable Markdown View\n• Download .md / .txt / .tex"]
        DTabCover["✉️ Custom Cover Letter\n• Company Culture Alignment\n• Dynamic Candidate Pitch\n• Editable Letter Area\n• One-Click Copy / Export"]
        DTabLusha["👥 Recruiter Intelligence\n• Verified Hiring Manager Info\n• Direct Email & LinkedIn Link\n• Personalized Connection Note\n• Recruiter Outreach Pitch"]
        DTabDetails["📋 Full Job Details\n• Full Job Description\n• Key Responsibilities Checklist\n• Requirements vs Skills Match\n• Compensation & Location"]
    end

    subgraph Auth_System["🔐 Authentication & Profile Modal"]
        OAuth["Social OAuth:\n• Google\n• GitHub\n• LinkedIn"]
        EmailAuth["Custom Email / Password:\n• Sign In Form\n• Sign Up Form\n• Forgot Password"]
        GuestMode["⚡ Demo / Guest Mode One-Click Bypass"]
    end

    Global_Header --> Main_Views
    NavLinks --> TabDash
    NavLinks --> TabBrowse
    NavLinks --> TabApps
    NavLinks --> TabTracker
    NavLinks --> TabInbox
    NavLinks --> TabResume

    TabDash -->|"Click Card / Review"| SlideOver_Drawer
    TabBrowse -->|"Review & Tailor"| SlideOver_Drawer
    TabApps -->|"Inspect Materials"| SlideOver_Drawer

    SlideOver_Drawer --> DTabResume
    SlideOver_Drawer --> DTabCover
    SlideOver_Drawer --> DTabLusha
    SlideOver_Drawer --> DTabDetails

    AuthBtn --> Auth_System
```

---

### 2. Core User Journeys

#### A. Role Discovery & Autonomous Scoring
1. **Scout Ingestion**: The system queries LinkedIn via Apify (`curious_coder/linkedin-jobs-scraper`) or loads the cached offline feed.
2. **ATS Scoring Engine**:
   - **Title Alignment (40%)**: Role keyword matching against your target title.
   - **Core Competencies (40%)**: Skill extraction (e.g. AI/ML, Python, System Architecture, Agile).
   - **Seniority & Stability (20%)**: Experience level match and company health check.
3. **Card Display**: Evaluated roles appear in the **Dashboard** and **Browse** feed with radial score indicators and color-coded badges.

#### B. Human-in-the-Loop Tailoring & Application
1. **Open Review**: Click **Review & Tailor** on any high-scoring job card to slide open `#role-drawer`.
2. **Resume Inspection (`#dtab-content-resume`)**:
   - Review AI-targeted bullet points emphasizing skills required by the employer.
   - Edit the tailored resume directly in the text editor.
   - Use the **AI Rephrase** tool to rewrite specific bullets for maximum impact.
3. **Cover Letter Generation (`#dtab-content-cover`)**:
   - Read the auto-generated cover letter addressing the hiring team and referencing role specifics.
   - Edit tone, length, and personal notes.
4. **Recruiter Outreach (`#dtab-content-lusha`)**:
   - View identified hiring managers and recruiters.
   - Copy a pre-crafted 300-character LinkedIn connection note or formal email.
5. **Finalize**: Click **Approve & Mark Applied** to advance the role to the **Applications** ledger and **Pipeline Tracker**.

#### C. Updating Master Profile & Dynamic Re-Scoring
1. Navigate to **Master Resume Hub** (`#tab-resume`).
2. Upload a new resume or edit your Markdown in the editor.
3. Click **Save & Re-Score All Roles**: The agent recalculates ATS fit scores for every active listing immediately.

---

## 📁 Repository Directory Structure

```text
job_scout_agent/
├── main.py                     # Single CLI entry point: serve | app | scout | parse
├── app.py                      # Streamlit dashboard (UI only; logic lives in job_scout/)
├── job-hunt-dashboard.html     # Modern SPA dashboard (Tabs, Modals, Drawer, ATS Editor)
├── index.html                  # Symlink → job-hunt-dashboard.html
├── favicon.svg
│
├── job_scout/                  # Core package
│   ├── config.py               # Settings + .env loader
│   ├── agent.py                # JobScoutAgent orchestrator (discover → score → tailor → store → digest)
│   ├── linkedin_scraper.py     # LinkedIn URL builder, async Apify crawler, job normalizer
│   ├── resume_parser.py        # Docling resume parser + document-link import
│   ├── resume_builder.py       # ATS tailoring (Gemini / heuristic) + ModernCV LaTeX
│   ├── scoring.py              # Fit scoring engine
│   ├── storage.py              # Local ledger + Supabase dedupe/storage
│   ├── contacts.py             # Lusha decision-maker enrichment
│   ├── digest.py               # Daily email digest HTML
│   ├── server.py               # Dashboard HTTP server + /api/resume/parse
│   ├── sample_jobs.py          # Curated offline job feed
│   └── utils.py
│
├── server.py                   # Compat shim → job_scout.server (for Render/Railway)
├── daily_job_scout.py          # Compat shim → JobScoutAgent.run_daily (for existing cron jobs)
├── master_resume.template.md   # Placeholder resume template for new users
├── supabase_schema.sql
├── requirements.txt
└── .env.example
```

---

## 🚀 Quickstart & Setup

### 1. Clone the Repository
```bash
git clone https://github.com/swapniljathar/job_scout_agent.git
cd job_scout_agent
```

### 2. Set Up Virtual Environment & Dependencies
```bash
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
```

### 3. Configure Environment Variables (Optional)
Copy `.env.example` to `.env` and fill in your API credentials:
```bash
cp .env.example .env
```
```env
APIFY_API_TOKEN=your_apify_api_token_here
SUPABASE_URL=https://your-project.supabase.co
SUPABASE_KEY=your_supabase_anon_key
PORT=8080
```

### 4. Create Your Local Master Resume
Copy the included template:
```bash
cp master_resume.template.md master_resume.md
```
Edit `master_resume.md` with your genuine experience and skills. *(Note: `master_resume.md` is strictly git-ignored and will never be pushed).*

### 5. Launch the Modern Web Dashboard
```bash
python3 main.py serve
```
Open your browser at **`http://localhost:8080`**. Running through the server enables PDF/DOCX parsing and document-link import in the Master Resume Hub.

### 6. (Alternative) Launch the Streamlit Dashboard
```bash
python3 main.py app
```
Open your browser at **`http://localhost:8501`**.

### 7. Other Commands
```bash
python3 main.py scout --query "AI Product Manager" --max-jobs 5   # headless daily pipeline (cron)
python3 main.py parse resume.pdf                                  # parse a resume file
python3 main.py parse "https://docs.google.com/document/d/<id>/edit" --save   # parse a doc link → master_resume.md
```

### 📄 Resume Parsing with Docling
The resume parser uses [Docling](https://github.com/docling-project/docling) to convert PDF, DOCX, PPTX, HTML and images into structured Markdown, preserving headings, reading order, bullets and tables (with OCR for scanned PDFs). The parser then detects sections (summary, experience, skills, education, certifications…), contact details and a de-duplicated skill list.

- **Sources:** local files, uploads (web dashboard, Streamlit), and **document links**: Google Docs, Google Drive, Dropbox, OneDrive or any direct PDF/DOCX URL. Links must be shared as *Anyone with the link can view*.
- **Fallback:** if Docling isn't installed (or `USE_DOCLING=false`), the parser falls back to `pypdf` / `python-docx`.
- **API:** `POST /api/resume/parse?filename=resume.pdf` with the file bytes, or `POST /api/resume/parse` with JSON `{"url": "<doc link>"}`.

### ✍️ Plain-English Drafts (unslop)
Tailored resumes, cover letters and recruiter notes go through an "unslop" pass based on the [pstack unslop skill](https://github.com/cursor/plugins/blob/main/pstack/skills/unslop/SKILL.md). LLM prompts include its writing rules. The generated text is then cleaned by [job_scout/unslop.py](job_scout/unslop.py) (Python) and an identical function in the dashboard. The cleanup replaces buzzwords ("spearheaded", "leveraged", "results-driven"), em dashes, curly quotes, emojis and stock cover-letter openers. Text you edit yourself is never rewritten.

---

## 🔒 Privacy & Secret Protection

Job Scout Agent is engineered from the ground up to protect your sensitive personal data:

- **Local Storage Isolation**: Your `master_resume.md`, generated PDF resumes (`resumes/`), and application history (`job_ledger.json`) are stored exclusively on your local machine.
- **Strict `.gitignore` Policy**: Private files, API keys, virtual environments, and LaTeX compilation artifacts are hardcoded into `.gitignore`.
- **Zero Leak Tracking**: Sanitized templates ([master_resume.template.md](master_resume.template.md)) and mock placeholders are used across all committed code.

---

## ☁️ Deployment Guide

| Platform | Deployment Method | Recommended Command / Setting |
| :--- | :--- | :--- |
| **Vercel** | Static Web App | Deploy `index.html` & `job-hunt-dashboard.html` using the static preset |
| **Firebase Hosting** | Firebase CLI | `firebase deploy --only hosting` (configure `public: "."`) |
| **Render / Railway** | Python Web Service | Start command: `python3 main.py serve` (binds to `PORT`) |
| **Streamlit Community Cloud** | Streamlit App | Connect GitHub repo and point entry to `app.py` |

---

## 📄 License

Distributed under the **MIT License**. Feel free to adapt and expand this agent for your own career search.
