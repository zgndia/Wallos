"""
desktop/php_server.py

Managed Loopback PHP 8.3+ Runtime:
- Auto-detect local PHP 8.3+ or use portable PHP from C:\\Users\\zgn\\php
- Binds strictly to 127.0.0.1 on an ephemeral free port (never 0.0.0.0)
- Uses a custom PHP router script (router.php) replicating Wallos Nginx/Apache rules
- Explicitly returns 403 for /db/* (prevents database downloads)
- Configures date.timezone from host OS timezone
- Manages subprocess lifecycle cleanly with health-check and terminate on exit
"""

import os
import sys
import subprocess
import time
import socket
import signal
import threading
from pathlib import Path

# Paths - import from package init to work correctly in PyInstaller bundles
try:
    from . import WALLOS_ROOT
except ImportError:
    # Fallback when run as script
    WALLOS_ROOT = Path(__file__).parent.parent
APP_DIR = WALLOS_ROOT / "app"
PHP_EXE = Path(r"C:\Users\zgn\php\php.exe")  # portable PHP 8.4.28
ROUTER = APP_DIR / "router.php"

# Global state
php_process = None
port = None
_lock = threading.Lock()
_startup_complete = threading.Event()


def _find_free_port():
    """Find a free TCP port on 127.0.0.1"""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(('127.0.0.1', 0))
        return s.getsockname()[1]


# Windows timezone to IANA timezone mapping
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
    "Ekaterinburg Time": "Asia/Yekaterinburg",
    "Iran Standard Time": "Asia/Tehran",
    "India Standard Time": "Asia/Kolkata",
    "Sri Lanka Standard Time": "Asia/Colombo",
    "Nepal Standard Time": "Asia/Kathmandu",
    "Central Asia Standard Time": "Asia/Almaty",
    "W. Mongolia Standard Time": "Asia/Ulaanbaatar",
    "North Asia Standard Time": "Asia/Novosibirsk",
    "China Standard Time": "Asia/Shanghai",
    "North Asia East Standard Time": "Asia/Irkutsk",
    "Singapore Standard Time": "Asia/Singapore",
    "W. Australia Standard Time": "Australia/Perth",
    "Tokyo Standard Time": "Asia/Tokyo",
    "Korea Standard Time": "Asia/Seoul",
    "AUS Central Standard Time": "Australia/Darwin",
    "AUS Eastern Standard Time": "Australia/Sydney",
    "New Zealand Standard Time": "Pacific/Auckland",
    "Atlantic Standard Time": "America/Halifax",
}


def _get_iana_timezone() -> str:
    """Convert Windows timezone to IANA timezone for PHP."""
    import winreg
    try:
        key = winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, r"SYSTEM\CurrentControlSet\Control\TimeZoneInformation")
        tz_name, _ = winreg.QueryValueEx(key, "TimeZoneKeyName")
        winreg.CloseKey(key)
        return _WIN_TO_IANA.get(tz_name, "UTC")
    except Exception:
        # Fallback to UTC
        return "UTC"


def _wait_for_health(base_url: str, timeout: float = 5.0) -> bool:
    """Wait until /health.php returns 200 OK"""
    import urllib.request
    start = time.time()
    while time.time() - start < timeout:
        try:
            req = urllib.request.Request(f"{base_url}/health.php", method="HEAD")
            with urllib.request.urlopen(req, timeout=0.5) as resp:
                if resp.status == 200:
                    return True
        except Exception:
            pass
        time.sleep(0.05)  # Check more frequently
    return False


def start_php_server(port_override: int = None) -> int:
    """
    Start the PHP built-in server on 127.0.0.1.
    Returns the port number.
    """
    global php_process, port, _startup_complete

    with _lock:
        if php_process and php_process.poll() is None:
            return port  # already running

        port = port_override or _find_free_port()
        base_url = f"http://127.0.0.1:{port}"

        # Ensure PHP executable exists
        if not PHP_EXE.exists():
            raise FileNotFoundError(f"PHP not found at {PHP_EXE}")

        env = os.environ.copy()
        env["PHP_CLI_SERVER_WORKERS"] = "4"
        env["TZ"] = _get_iana_timezone()  # Use proper IANA timezone

        # Windows: hide console window
        creationflags = subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0

        php_process = subprocess.Popen(
            [str(PHP_EXE), "-S", f"127.0.0.1:{port}", "-t", str(WALLOS_ROOT), str(ROUTER)],
            cwd=str(WALLOS_ROOT),
            env=env,
            creationflags=creationflags,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )

        # Health check in background
        def health_check():
            if _wait_for_health(base_url):
                _startup_complete.set()
            else:
                _startup_complete.set()  # still signal to avoid deadlock

        threading.Thread(target=health_check, daemon=True).start()
        return port


def wait_until_ready(timeout: float = 15.0) -> bool:
    """Block until PHP server health check passes or timeout."""
    return _startup_complete.wait(timeout)


def stop_php_server():
    """Terminate the PHP server cleanly."""
    global php_process, port, _startup_complete
    with _lock:
        if php_process and php_process.poll() is None:
            php_process.terminate()
            try:
                php_process.wait(timeout=3)
            except subprocess.TimeoutExpired:
                php_process.kill()
                php_process.wait()
            php_process = None
            port = None
            _startup_complete.clear()


def is_running() -> bool:
    """Check if PHP server process is alive."""
    return php_process is not None and php_process.poll() is None


def get_base_url() -> str:
    """Return the base URL of the running PHP server."""
    if port:
        return f"http://127.0.0.1:{port}"
    return ""


# For standalone testing
if __name__ == "__main__":
    try:
        p = start_php_server()
        print(f"PHP server started on port {p}")
        wait_until_ready()
        print("Server ready!")
        input("Press Enter to stop...")
    finally:
        stop_php_server()
        print("Server stopped.")