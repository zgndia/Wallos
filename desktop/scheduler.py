"""
desktop/scheduler.py

Python Cron Daemon replacing Linux Crontab:
- Replicates every Wallos crontab job from endpoints/cronjobs/
- Runs missed-job catch-up on app launch (desktop PC isn't on 24/7)
- Logs all cron runs to rotating logs in desktop/logs/
"""

import os
import sys
import subprocess
import time
import threading
from datetime import datetime, timedelta
from pathlib import Path

# Paths - import from package init to work correctly in PyInstaller bundles
try:
    from . import WALLOS_ROOT
except ImportError:
    # Fallback when run as script
    WALLOS_ROOT = Path(__file__).parent.parent
PHP_EXE = Path(r"C:\Users\zgn\php\php.exe")
CRONJOBS_DIR = WALLOS_ROOT / "endpoints" / "cronjobs"
DB_PATH = WALLOS_ROOT / "app" / "db" / "wallos.db"
LOGS_DIR = WALLOS_ROOT / "desktop" / "logs"
LOGS_DIR.mkdir(exist_ok=True)

# Cron job definitions replicated from Wallos crontab
# Schedule is in minutes interval from app start (relative scheduling)
# We use absolute times based on last-run tracking
CRON_JOBS = {
    "updatenextpayment": {"interval_minutes": 60, "last_run": None, "script": "updatenextpayment.php"},
    "sendnotifications": {"interval_minutes": 60, "last_run": None, "script": "sendnotifications.php"},
    "sendcancellationnotifications": {"interval_minutes": 1440, "last_run": None, "script": "sendcancellationnotifications.php"},
    "updateexchange": {"interval_minutes": 60, "last_run": None, "script": "updateexchange.php"},
    "storetotalyearlycost": {"interval_minutes": 60, "last_run": None, "script": "storetotalyearlycost.php"},
    "checkforupdates": {"interval_minutes": 60, "last_run": None, "script": "checkforupdates.php"},
    "cleanupresettokens": {"interval_minutes": 60, "last_run": None, "script": "cleanupresettokens.php"},
    "generaterecommendations": {"interval_minutes": 1440, "last_run": None, "script": "generaterecommendations.php"},
    "createdatabase": {"interval_minutes": 1440, "last_run": None, "script": "createdatabase.php"},
    "settimezone": {"interval_minutes": 1440, "last_run": None, "script": "settimezone.php"},
    "sendresetpasswordemails": {"interval_minutes": 1440, "last_run": None, "script": "sendresetpasswordemails.php"},
    "sendverificationemails": {"interval_minutes": 1440, "last_run": None, "script": "sendverificationemails.php"},
}

# Track scheduler thread
scheduler_thread = None
scheduler_running = threading.Event()
scheduler_running.set()


def _log(message: str):
    """Write a log line with timestamp to rotating log file."""
    log_file = LOGS_DIR / f"wallos-cron-{datetime.now().strftime('%Y%m%d')}.log"
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    with open(log_file, "a", encoding="utf-8") as f:
        f.write(f"[{timestamp}] {message}\n")


def _get_valid_timezone() -> str:
    """Get a valid PHP timezone string from the OS timezone."""
    import winreg
    try:
        key = winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, r"SYSTEM\CurrentControlSet\Control\TimeZoneInformation")
        tz_name, _ = winreg.QueryValueEx(key, "TimeZoneKeyName")
        winreg.CloseKey(key)
        # Use the same mapping as php_server
        _WIN_TO_IANA = {
            "UTC": "Etc/UTC",
            "Pacific Standard Time": "America/Los_Angeles",
            "Mountain Standard Time": "America/Denver",
            "Central Standard Time": "America/Chicago",
            "Eastern Standard Time": "America/New_York",
            "Turkey Standard Time": "Europe/Istanbul",
            "GTB Standard Time": "Europe/Bucharest",
            "FLE Standard Time": "Europe/Helsinki",
            "West Central Time": "Africa/Lagos",
            "Russian Timezone 1": "Europe/Moscow",
            "Arab Standard Time": "Asia/Riyadh",
            "Middle East Standard Time": "Asia/Baghdad",
            "Iran Standard Time": "Asia/Tehran",
            "India Standard Time": "Asia/Kolkata",
            "China Standard Time": "Asia/Shanghai",
            "Tokyo Standard Time": "Asia/Tokyo",
            "Korea Standard Time": "Asia/Seoul",
            "AUS Eastern Standard Time": "Australia/Sydney",
            "New Zealand Standard Time": "Pacific/Auckland",
        }
        return _WIN_TO_IANA.get(tz_name, "UTC")
    except Exception:
        return "UTC"


def _run_php_script(script_name: str) -> bool:
    """Execute a PHP cron script via the managed PHP CLI."""
    script_path = CRONJOBS_DIR / script_name
    if not script_path.exists():
        _log(f"ERROR: Script not found: {script_name}")
        return False

    try:
        # Read timezone from DB or use system default
        import sqlite3
        db_timezone = None
        try:
            conn = sqlite3.connect(DB_PATH)
            cur = conn.cursor()
            cur.execute("SELECT setting_value FROM settings WHERE setting_name = 'timezone' LIMIT 1")
            row = cur.fetchone()
            if row:
                db_timezone = row[0]
            conn.close()
        except Exception:
            pass
        
        valid_tz = db_timezone or _get_valid_timezone()
        
        env = os.environ.copy()
        env["PHP_CLI_SERVER_WORKERS"] = "4"
        env["TZ"] = valid_tz
        
        # Use system php.ini (which has all extensions) + override timezone via -d
        # This avoids the temp php.ini missing extensions issue
        args = [
            str(PHP_EXE), 
            "-d", f"date.timezone={valid_tz}",
            str(script_path)
        ]
        
        creationflags = subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0

        result = subprocess.run(
            args,
            cwd=str(WALLOS_ROOT),
            env=env,
            creationflags=creationflags,
            capture_output=True,
            text=True,
            timeout=120,
        )

        if result.returncode == 0:
            _log(f"OK: {script_name} completed successfully")
            return True
        else:
            err_line = result.stderr.split('\n')[0] if result.stderr else ""
            _log(f"FAIL: {script_name} returned {result.returncode}: {err_line[:200]}")
            return False
    except subprocess.TimeoutExpired:
        _log(f"TIMEOUT: {script_name} exceeded 120s")
        return False
    except Exception as e:
        _log(f"EXCEPTION: {script_name} - {str(e)}")
        return False


def _catch_up_missed_jobs():
    """Run any jobs that were missed while the app was offline."""
    now = datetime.now()
    for job_name, job in CRON_JOBS.items():
        if job["last_run"] is None:
            # Never run — schedule it now (missed catch-up)
            _log(f"Missed job catch-up: running {job_name}")
            _run_php_script(job["script"])
            job["last_run"] = now
        else:
            # Check if we missed the interval
            elapsed = (now - job["last_run"]).total_seconds() / 60.0
            if elapsed > job["interval_minutes"]:
                _log(f"Missed job catch-up: running {job_name} (overdue by {elapsed - job['interval_minutes']:.0f}m)")
                _run_php_script(job["script"])
                job["last_run"] = now


def _scheduler_loop():
    """Main scheduler loop — runs every minute."""
    while scheduler_running.is_set():
        _catch_up_missed_jobs()

        # Schedule next runs
        now = datetime.now()
        for job_name, job in CRON_JOBS.items():
            if job["last_run"] is None:
                job["last_run"] = now

        time.sleep(60)  # Check every minute


def start_scheduler():
    """Start the cron scheduler in a background thread."""
    global scheduler_thread
    if scheduler_thread and scheduler_thread.is_alive():
        return

    _log("Scheduler starting...")
    scheduler_thread = threading.Thread(target=_scheduler_loop, daemon=True, name="WallosCron")
    scheduler_thread.start()
    _log(f"Scheduler started with {len(CRON_JOBS)} jobs")


def stop_scheduler():
    """Stop the scheduler."""
    global scheduler_thread
    scheduler_running.clear()
    if scheduler_thread and scheduler_thread.is_alive():
        scheduler_thread.join(timeout=5)
    _log("Scheduler stopped")


def run_job_now(job_name: str) -> bool:
    """Manually trigger a specific cron job (for testing)."""
    if job_name not in CRON_JOBS:
        _log(f"Unknown job: {job_name}")
        return False
    _log(f"Manual trigger: {job_name}")
    return _run_php_script(CRON_JOBS[job_name]["script"])


if __name__ == "__main__":
    print("Wallos Cron Scheduler - Manual Test")
    print("Available jobs:", list(CRON_JOBS.keys()))
    start_scheduler()
    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        stop_scheduler()
        print("Stopped.")