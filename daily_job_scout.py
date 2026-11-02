#!/usr/bin/env python3
"""Compatibility entry point for existing cron jobs. Prefer `python main.py scout`."""
import sys

from job_scout.agent import JobScoutAgent, ScoutError

if __name__ == "__main__":
    try:
        JobScoutAgent().run_daily()
    except ScoutError as err:
        sys.exit(f"Scout run failed: {err}")
