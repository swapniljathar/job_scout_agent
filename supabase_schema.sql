-- ============================================================
-- Supabase Schema for Job Scout & Resume Customizer Agent
-- ============================================================
-- Run this in your Supabase Dashboard -> SQL Editor -> New Query.
-- Safe to run more than once: it creates the tables or upgrades existing ones.

-- 1. The 'jobs' table: one row per LinkedIn job found by the daily scout run
CREATE TABLE IF NOT EXISTS public.jobs (
    id BIGSERIAL PRIMARY KEY,
    job_url TEXT UNIQUE NOT NULL,
    job_title TEXT,
    company TEXT,
    processed_at TIMESTAMPTZ DEFAULT NOW()
);

-- 2. Columns the dashboard uses to show and review each job
ALTER TABLE public.jobs ADD COLUMN IF NOT EXISTS location TEXT;
ALTER TABLE public.jobs ADD COLUMN IF NOT EXISTS posted_at TEXT;
ALTER TABLE public.jobs ADD COLUMN IF NOT EXISTS score INT;
ALTER TABLE public.jobs ADD COLUMN IF NOT EXISTS reason TEXT;
ALTER TABLE public.jobs ADD COLUMN IF NOT EXISTS matched_keywords JSONB DEFAULT '[]'::jsonb;
ALTER TABLE public.jobs ADD COLUMN IF NOT EXISTS job_description TEXT;
ALTER TABLE public.jobs ADD COLUMN IF NOT EXISTS tailored_resume TEXT;
ALTER TABLE public.jobs ADD COLUMN IF NOT EXISTS cover_letter TEXT;
ALTER TABLE public.jobs ADD COLUMN IF NOT EXISTS status TEXT;
ALTER TABLE public.jobs ADD COLUMN IF NOT EXISTS applied_at TIMESTAMPTZ;
ALTER TABLE public.jobs ADD COLUMN IF NOT EXISTS updated_at TIMESTAMPTZ DEFAULT NOW();
ALTER TABLE public.jobs ADD COLUMN IF NOT EXISTS apply_url TEXT;  -- company application link (shows the ATS, e.g. Greenhouse)

-- 3. Review status: new -> reviewed -> applied (or skipped)
UPDATE public.jobs SET status = 'new' WHERE status IS NULL OR status NOT IN ('new', 'reviewed', 'applied', 'skipped');
ALTER TABLE public.jobs ALTER COLUMN status SET DEFAULT 'new';
ALTER TABLE public.jobs ALTER COLUMN status SET NOT NULL;
ALTER TABLE public.jobs DROP CONSTRAINT IF EXISTS jobs_status_check;
ALTER TABLE public.jobs ADD CONSTRAINT jobs_status_check CHECK (status IN ('new', 'reviewed', 'applied', 'skipped'));

CREATE INDEX IF NOT EXISTS idx_jobs_processed_at ON public.jobs (processed_at DESC);

-- 4. Multi-user: each job belongs to one dashboard user, who is the only one who can see it.
--    The same LinkedIn job can be saved once per user.
ALTER TABLE public.jobs ADD COLUMN IF NOT EXISTS user_id UUID REFERENCES auth.users(id) ON DELETE CASCADE;
ALTER TABLE public.jobs DROP CONSTRAINT IF EXISTS jobs_job_url_key;
ALTER TABLE public.jobs DROP CONSTRAINT IF EXISTS jobs_user_job_url_key;
ALTER TABLE public.jobs ADD CONSTRAINT jobs_user_job_url_key UNIQUE (user_id, job_url);
CREATE INDEX IF NOT EXISTS idx_jobs_user_processed_at ON public.jobs (user_id, processed_at DESC);

-- To keep jobs saved before multi-user, give them to your account (they are hidden until you do):
-- UPDATE public.jobs SET user_id = (SELECT id FROM auth.users WHERE email = 'you@example.com') WHERE user_id IS NULL;

-- 5. Profiles: each user's master resume, LinkedIn search and daily-run history
CREATE TABLE IF NOT EXISTS public.profiles (
    user_id UUID PRIMARY KEY REFERENCES auth.users(id) ON DELETE CASCADE,
    email TEXT,
    master_resume TEXT DEFAULT '',
    search_query TEXT,
    search_location TEXT,
    keywords TEXT DEFAULT '',
    daily_enabled BOOLEAN NOT NULL DEFAULT TRUE,
    last_run JSONB,
    manual_runs_date DATE,
    manual_runs_count INT NOT NULL DEFAULT 0,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW()
);
-- Search filters: several roles and locations, work type (onsite / hybrid / remote) and posting age (24h / 3d / 7d / 30d)
ALTER TABLE public.profiles ADD COLUMN IF NOT EXISTS search_roles JSONB;
ALTER TABLE public.profiles ADD COLUMN IF NOT EXISTS search_locations JSONB;
ALTER TABLE public.profiles ADD COLUMN IF NOT EXISTS work_types JSONB DEFAULT '[]'::jsonb;
ALTER TABLE public.profiles ADD COLUMN IF NOT EXISTS posted_within TEXT DEFAULT '7d';

-- 6. Lock both tables: resumes contain phone numbers and emails.
--    Only the server's secret key (sb_secret_...) can read or write; it bypasses RLS.
--    The dashboard goes through the server, which checks the login and only returns the user's own rows.
ALTER TABLE public.jobs ENABLE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS "Allow anon read and insert" ON public.jobs;
DROP POLICY IF EXISTS "app can read jobs" ON public.jobs;
DROP POLICY IF EXISTS "app can add jobs" ON public.jobs;
REVOKE ALL ON public.jobs FROM anon, authenticated;
ALTER TABLE public.profiles ENABLE ROW LEVEL SECURITY;
REVOKE ALL ON public.profiles FROM anon, authenticated;

-- 7. Check: list the final columns
SELECT table_name, column_name, data_type, is_nullable
FROM information_schema.columns
WHERE table_schema = 'public' AND table_name IN ('jobs', 'profiles')
ORDER BY table_name, ordinal_position;
