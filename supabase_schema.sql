-- ============================================================
-- Supabase Schema for Job Scout & Resume Customizer Agent
-- ============================================================
-- Run this in your Supabase Dashboard -> SQL Editor -> New Query.
-- Safe to run more than once: it creates the table or upgrades an existing one.

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

-- 3. Review status: new -> reviewed -> applied (or skipped)
UPDATE public.jobs SET status = 'new' WHERE status IS NULL OR status NOT IN ('new', 'reviewed', 'applied', 'skipped');
ALTER TABLE public.jobs ALTER COLUMN status SET DEFAULT 'new';
ALTER TABLE public.jobs ALTER COLUMN status SET NOT NULL;
ALTER TABLE public.jobs DROP CONSTRAINT IF EXISTS jobs_status_check;
ALTER TABLE public.jobs ADD CONSTRAINT jobs_status_check CHECK (status IN ('new', 'reviewed', 'applied', 'skipped'));

CREATE INDEX IF NOT EXISTS idx_jobs_processed_at ON public.jobs (processed_at DESC);

-- 4. Lock the table: tailored resumes contain your phone number and email.
--    Only the server's secret key (sb_secret_...) can read or write; it bypasses RLS.
--    The dashboard reads jobs through the server, which checks your login (ALLOWED_EMAILS).
ALTER TABLE public.jobs ENABLE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS "Allow anon read and insert" ON public.jobs;
DROP POLICY IF EXISTS "app can read jobs" ON public.jobs;
DROP POLICY IF EXISTS "app can add jobs" ON public.jobs;
REVOKE ALL ON public.jobs FROM anon, authenticated;

-- 5. Check: list the final columns
SELECT column_name, data_type, is_nullable
FROM information_schema.columns
WHERE table_schema = 'public' AND table_name = 'jobs'
ORDER BY ordinal_position;
