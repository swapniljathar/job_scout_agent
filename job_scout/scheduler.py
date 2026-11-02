"""
Daily scout runs: one at SCOUT_DAILY_TIME (default 06:30 Asia/Kolkata) plus on-demand runs from the dashboard.

A single ScoutRunner owns the lock, so a scheduled run and a "Run now" click can never overlap.
If the server was down at 06:30, the run starts as soon as it is back up that day.
"""
import json
import logging
import threading
import time
from collections import deque
from datetime import datetime, timedelta, timezone

from job_scout.config import settings

logger = logging.getLogger(__name__)

try:
    from zoneinfo import ZoneInfo
except ImportError:  # Python < 3.9
    ZoneInfo = None


def _tz():
    try:
        return ZoneInfo(settings.scout_timezone)
    except Exception:
        logger.warning("Unknown SCOUT_TIMEZONE %r, using UTC", settings.scout_timezone)
        return timezone.utc


def _slot(day):
    """The scheduled run time on `day` (a tz-aware datetime)."""
    hour, minute = (int(part) for part in settings.scout_daily_time.split(":"))
    return day.replace(hour=hour, minute=minute, second=0, microsecond=0)


class ScoutRunner:
    def __init__(self, state_file=None):
        self.state_file = state_file or settings.scout_state_file
        self._lock = threading.Lock()
        self._running = None  # {"trigger", "started_at"} while a run is in progress
        self._log = deque(maxlen=200)
        self._state = self._load_state()

    # ---------------- State ----------------
    def _load_state(self):
        try:
            return json.loads(self.state_file.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return {}

    def _save_state(self):
        try:
            self.state_file.write_text(json.dumps(self._state, indent=2), encoding="utf-8")
        except OSError as err:
            logger.error("Could not save scout state to %s: %s", self.state_file, err)

    def next_run_at(self):
        now = datetime.now(_tz())
        slot = _slot(now)
        return slot if now < slot else _slot(now + timedelta(days=1))

    def status(self):
        return {
            "running": self._running,
            "last_run": self._state.get("last_run"),
            "next_run": self.next_run_at().isoformat() if settings.scout_schedule_enabled else None,
            "schedule": f"{settings.scout_daily_time} {settings.scout_timezone}" if settings.scout_schedule_enabled else None,
            "log": list(self._log)[-15:],
        }

    # ---------------- Runs ----------------
    def start(self, trigger):
        """Starts a run in the background. Returns False if one is already running."""
        with self._lock:
            if self._running:
                return False
            self._running = {"trigger": trigger, "started_at": datetime.now(_tz()).isoformat()}
            self._log.clear()
        threading.Thread(target=self._run, args=(trigger,), name=f"scout-{trigger}", daemon=True).start()
        return True

    def _append_log(self, line):
        print(line, flush=True)
        self._log.append(str(line))

    def _run(self, trigger):
        from job_scout.agent import JobScoutAgent, ScoutCriteria, ScoutError

        started_at = self._running["started_at"]
        result = {"trigger": trigger, "started_at": started_at, "new_jobs": 0, "error": None}
        try:
            criteria = ScoutCriteria(query=settings.scout_query, location=settings.scout_location, max_jobs=settings.scout_max_jobs)
            processed = JobScoutAgent(log=self._append_log).run_daily(criteria)
            result["new_jobs"] = len(processed)
        except ScoutError as err:
            logger.error("Scout run (%s) failed: %s", trigger, err)
            result["error"] = str(err)
        except Exception as err:  # anything unexpected: keep the traceback, still report it on the dashboard
            logger.exception("Scout run (%s) failed", trigger)
            result["error"] = str(err)
        finally:
            result["finished_at"] = datetime.now(_tz()).isoformat()
            self._state["last_run"] = result
            self._save_state()
            self._running = None

    # ---------------- Schedule ----------------
    def _due(self):
        """True once today's slot has passed and no run has started since it."""
        now = datetime.now(_tz())
        slot = _slot(now)
        if now < slot:
            return False
        last = (self._state.get("last_run") or {}).get("started_at")
        return not last or datetime.fromisoformat(last) < slot

    def start_schedule(self, poll_seconds=30):
        def loop():
            logger.info("Daily scout scheduled at %s %s", settings.scout_daily_time, settings.scout_timezone)
            while True:
                if not self._running and self._due():
                    self.start("schedule")
                time.sleep(poll_seconds)

        threading.Thread(target=loop, name="scout-schedule", daemon=True).start()


runner = ScoutRunner()
