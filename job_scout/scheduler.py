"""
Daily scout runs for every dashboard user: one at SCOUT_DAILY_TIME (default 06:30 Asia/Kolkata) plus
on-demand runs from the dashboard.

Runs go through one queue and execute one after another, so users never overlap (Apify and Gemini are shared).
Each user's search, resume and last run live in their Supabase profile. If the server was down at 06:30,
the day's runs start as soon as it is back up that day.
"""
import logging
import threading
import time
from collections import deque
from datetime import datetime, timedelta, timezone

from job_scout.config import settings
from job_scout.storage import get_profile, list_scheduled_profiles, save_profile

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


def today():
    """Today's date in the scout timezone (used for the daily manual-run limit)."""
    return datetime.now(_tz()).date()


def criteria_for(profile):
    from job_scout.agent import ScoutCriteria

    query = (profile.get("search_query") or "").strip() or settings.scout_query
    location = (profile.get("search_location") or "").strip() or settings.scout_location
    keywords = [k.strip() for k in (profile.get("keywords") or "").split(",") if k.strip()]
    return ScoutCriteria(query=query, location=location, target_roles=[query], must_haves=keywords,
                         max_jobs=settings.scout_max_jobs)


class ScoutRunner:
    def __init__(self):
        self._lock = threading.Lock()
        self._wake = threading.Event()
        self._queue = deque()  # (user_id, trigger)
        self._running = None  # {"user_id", "trigger", "started_at"} while a run is in progress
        self._logs = {}  # user_id -> deque of progress lines from their latest run
        self._last_runs = {}  # user_id -> last_run, cached from their profile
        self._swept_on = None  # date the scheduled runs were last queued
        self._worker = None

    def next_run_at(self):
        now = datetime.now(_tz())
        slot = _slot(now)
        return slot if now < slot else _slot(now + timedelta(days=1))

    def _last_run(self, user_id):
        if user_id not in self._last_runs:
            profile, err = get_profile(user_id)
            if err:
                return None
            self._last_runs[user_id] = (profile or {}).get("last_run")
        return self._last_runs[user_id]

    def status(self, user_id):
        with self._lock:
            running = self._running if self._running and self._running["user_id"] == user_id else None
            waiting = [uid for uid, _ in self._queue]
        enabled = settings.scout_schedule_enabled
        return {
            "running": {"trigger": running["trigger"], "started_at": running["started_at"]} if running else None,
            "queued": waiting.index(user_id) + 1 if user_id in waiting else None,
            "last_run": self._last_run(user_id),
            "next_run": self.next_run_at().isoformat() if enabled else None,
            "schedule": f"{settings.scout_daily_time} {settings.scout_timezone}" if enabled else None,
            "log": list(self._logs.get(user_id, ()))[-15:],
        }

    # ---------------- Runs ----------------
    def start(self, user_id, trigger):
        """Queues a run for the user. Returns False if they already have one queued or running."""
        with self._lock:
            if (self._running and self._running["user_id"] == user_id) or any(uid == user_id for uid, _ in self._queue):
                return False
            self._queue.append((user_id, trigger))
            if not self._worker:
                self._worker = threading.Thread(target=self._work, name="scout-worker", daemon=True)
                self._worker.start()
        self._wake.set()
        return True

    def _work(self):
        while True:
            with self._lock:
                job = self._queue.popleft() if self._queue else None
                if job:
                    self._running = {"user_id": job[0], "trigger": job[1], "started_at": datetime.now(_tz()).isoformat()}
                    self._logs[job[0]] = deque(maxlen=200)
            if not job:
                self._wake.wait()
                self._wake.clear()
                continue
            self._run(*job)

    def _run(self, user_id, trigger):
        from job_scout.agent import JobScoutAgent

        log = self._logs[user_id]

        def append_log(line):
            print(line, flush=True)
            log.append(str(line))

        result = {"trigger": trigger, "started_at": self._running["started_at"], "new_jobs": 0, "error": None}
        try:
            profile, err = get_profile(user_id)
            if err:
                raise RuntimeError(err)
            profile = profile or {}
            processed = JobScoutAgent(log=append_log).run_daily(
                criteria_for(profile), resume_text=profile.get("master_resume") or "", user_id=user_id)
            result["new_jobs"] = len(processed)
        except Exception as err:
            from job_scout.agent import ScoutError

            if isinstance(err, ScoutError):
                logger.error("Scout run (%s) for %s failed: %s", trigger, user_id, err)
            else:  # anything unexpected: keep the traceback, still report it on the dashboard
                logger.exception("Scout run (%s) for %s failed", trigger, user_id)
            result["error"] = str(err)
        finally:
            result["finished_at"] = datetime.now(_tz()).isoformat()
            self._last_runs[user_id] = result
            ok, err = save_profile(user_id, {"last_run": result})
            if not ok:
                logger.error("Could not save the last run for %s: %s", user_id, err)
            with self._lock:
                self._running = None

    # ---------------- Schedule ----------------
    def _queue_scheduled_runs(self):
        """Once today's slot has passed, queues every user whose last run started before it."""
        now = datetime.now(_tz())
        slot = _slot(now)
        if now < slot or self._swept_on == now.date():
            return
        profiles, err = list_scheduled_profiles()
        if err:
            logger.error("Could not load users for the daily scout run: %s", err)
            return
        queued = 0
        for profile in profiles:
            last = (profile.get("last_run") or {}).get("started_at")
            if (not last or datetime.fromisoformat(last) < slot) and self.start(profile["user_id"], "schedule"):
                queued += 1
        self._swept_on = now.date()
        logger.info("Queued the daily scout run for %d user(s)", queued)

    def start_schedule(self, poll_seconds=30):
        def loop():
            logger.info("Daily scout scheduled at %s %s", settings.scout_daily_time, settings.scout_timezone)
            while True:
                try:
                    self._queue_scheduled_runs()
                except Exception:
                    logger.exception("Daily scout scheduling failed")
                time.sleep(poll_seconds)

        threading.Thread(target=loop, name="scout-schedule", daemon=True).start()


runner = ScoutRunner()
