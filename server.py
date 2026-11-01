"""Compatibility entry point for hosts that run `python3 server.py` (Render/Railway). Prefer `python main.py serve`."""
from job_scout.server import run_server

if __name__ == '__main__':
    run_server()
