#!/usr/bin/env python3
"""
Job Scout Agent — single entry point.

  python main.py serve              Web dashboard + resume parsing API (http://localhost:8080)
  python main.py app                Streamlit dashboard (http://localhost:8501)
  python main.py scout              Headless daily pipeline (cron / scheduler friendly)
  python main.py parse <file|link>  Parse a resume with Docling and print the result
"""
import argparse
import json
import logging
import subprocess
import sys

from job_scout.config import PROJECT_ROOT


def cmd_serve(args):
    from job_scout.server import run_server
    run_server(args.port)


def cmd_app(args):
    sys.exit(subprocess.call([sys.executable, "-m", "streamlit", "run", str(PROJECT_ROOT / "app.py")]))


def cmd_scout(args):
    from job_scout.agent import JobScoutAgent, ScoutCriteria
    criteria = ScoutCriteria(query=args.query, location=args.location, max_jobs=args.max_jobs)
    JobScoutAgent().run_daily(criteria)


def cmd_parse(args):
    from job_scout.agent import JobScoutAgent
    from job_scout.resume_parser import ResumeParseError, parse_resume
    try:
        parsed = JobScoutAgent().import_resume(args.source) if args.save else parse_resume(args.source)
    except ResumeParseError as err:
        sys.exit(f"⚠️  {err}")
    if args.json:
        print(json.dumps(parsed.to_dict(), indent=2))
        return
    print(f"Source:   {parsed.source}\nEngine:   {parsed.engine}\nWords:    {parsed.word_count}")
    print(f"Contact:  {parsed.contact}")
    print(f"Sections: {', '.join(parsed.sections)}")
    print(f"Skills:   {', '.join(parsed.skills[:20])}")
    for warning in parsed.warnings:
        print(f"⚠️  {warning}")
    if args.save:
        print("✓ Saved as master_resume.md")


def build_parser():
    parser = argparse.ArgumentParser(description="Job Scout Agent")
    sub = parser.add_subparsers(dest="command", required=True)

    serve = sub.add_parser("serve", help="Run web dashboard + API")
    serve.add_argument("--port", type=int, default=None)
    serve.set_defaults(func=cmd_serve)

    sub.add_parser("app", help="Run Streamlit dashboard").set_defaults(func=cmd_app)

    scout = sub.add_parser("scout", help="Run headless daily pipeline")
    scout.add_argument("--query", default="AI Product Manager")
    scout.add_argument("--location", default="Pune, Maharashtra, India")
    scout.add_argument("--max-jobs", type=int, default=5)
    scout.set_defaults(func=cmd_scout)

    parse = sub.add_parser("parse", help="Parse a resume file or document link")
    parse.add_argument("source", help="Path to PDF/DOCX/MD/TXT or a Google Docs/Drive/Dropbox/direct link")
    parse.add_argument("--json", action="store_true", help="Print full structured output as JSON")
    parse.add_argument("--save", action="store_true", help="Save parsed text as master_resume.md")
    parse.set_defaults(func=cmd_parse)
    return parser


def main(argv=None):
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
    args = build_parser().parse_args(argv)
    args.func(args)


if __name__ == "__main__":
    main()
