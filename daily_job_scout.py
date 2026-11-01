#!/usr/bin/env python3
"""Compatibility entry point for existing cron jobs. Prefer `python main.py scout`."""
from job_scout.agent import JobScoutAgent

if __name__ == "__main__":
    JobScoutAgent().run_daily()
