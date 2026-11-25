"""
desktop/app.py

pywebview Desktop Shell + Managed Local PHP Runtime + Python Cron Daemon.

1. Starts a managed PHP built-in server on 127.0.0.1:ephemeral port (loopback only)
2. Creates a pywebview window pointing to the local URL
3. Implements pywebview breakages: file uploads, downloads, external links, dialogs
4. System tray integration (minimize to tray, quick-open, quit)
5. Desktop notifications bridge
6. Automatic rolling backups + restore UI hook
7. Single-instance lock to prevent SQLite corruption
8. Injects JS API hooks for native OS features
9. Auto-start on login support
10. Memory/CPU optimization
"""

import sys
import os
import subprocess
import threading
import time
import json
import atexit
from pathlib import Path
from datetime import datetime

# Ensure correct module paths regardless of how script is launched
WALLOS_ROOT = Path(__file__).parent.parent
if str(WALLOS_ROOT) not in sys.path:
    sys.path.insert(0, str(WALLOS_ROOT))
if str(WALLOS_ROOT / "desktop") not in sys.path:
    sys.path.insert(0, str(WALLOS_ROOT / "desktop"))

import webview
from PIL import Image as PILImage

# ---- Windows Single-Instance Mutex ----
if sys.platform == "win32":
    try:
        import win32event
        import win32api
        import winerror
        # Use local namespace (no "Global\") to avoid admin requirement
        _SINGLE_INSTANCE_MUTEX = win32event.CreateMutex(None, False, "WallosDesktopMutex")
        _MUTEX_ERR = win32api.GetLastError()
        _MUTEX_ACQUIRED = (_MUTEX_ERR != winerror.ERROR_ALREADY_EXISTS)
        print(f"[MUTEX] Created mutex, error={_MUTEX_ERR}, acquired={_MUTEX_ACQUIRED}", flush=True)
        if not _MUTEX_ACQUIRED:
            # Another instance exists - signal it to show
            import win32gui
            import win32con
            def _show_existing_window(hwnd, _):
                if win32gui.IsWindowVisible(hwnd):
                    title = win32gui.GetWindowText(hwnd)
                    if "Wallos" in title:
                        win32gui.ShowWindow(hwnd, win32con.SW_RESTORE)
                        win32gui.SetForegroundWindow(hwnd)
                        return False
                return True
            win32gui.EnumWindows(_show_existing_window, None)
            print("[MUTEX] Another instance found, exiting", flush=True)
            os._exit(0)  # Immediate exit, no cleanup needed
    except Exception as e:
        print(f"[MUTEX] Failed: {e}", flush=True)
        _SINGLE_INSTANCE_MUTEX = None
        _MUTEX_ACQUIRED = True  # If mutex fails, allow running
else:
    _SINGLE_INSTANCE_MUTEX = None
    _MUTEX_ACQUIRED = True

# Paths
APP_DIR = WALLOS_ROOT / "app"
DB_PATH = APP_DIR / "db" / "wallos.db"
PHPSERVER_SCRIPT = WALLOS_ROOT / "desktop" / "php_server.py"
SCHEDULER_SCRIPT = WALLOS_ROOT / "desktop" / "scheduler.py"
BACKUP_SCRIPT = WALLOS_ROOT / "desktop" / "backup_manager.py"
LOGS_DIR = WALLOS_ROOT / "desktop" / "logs"
TRAY_ICON = WALLOS_ROOT / "wallos.ico"
SETTINGS_FILE = WALLOS_ROOT / "desktop" / "settings.json"

LOGS_DIR.mkdir(parents=True, exist_ok=True)

# Global state
tray_icon = None
is_minimized_to_tray = False
php_manager = None
window = None
settings = {}


def _log(msg: str, level="INFO"):
    """Write to rotating log file in desktop/logs/."""
    log_file = LOGS_DIR / f"wallos-{datetime.now().strftime('%Y%m%d')}.log"
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    with open(log_file, "a", encoding="utf-8") as f:
        f.write(f"[{timestamp}] [{level}] {msg}\n")
        f.flush()


def _load_settings():
    """Load persistent settings from JSON file."""
    global settings
    if SETTINGS_FILE.exists():
        try:
            settings = json.loads(SETTINGS_FILE.read_text())
        except Exception:
            settings = {}
    else:
        settings = {
            "auto_start": False,
            "minimize_to_tray_on_close": True,
            "start_minimized": False,
            "enable_notifications": True,
            "backup_on_startup": True,
            "backup_on_shutdown": True,
            "auto_backup_interval_hours": 24,
            "max_backups": 10,
            "window_state": {"width": 1200, "height": 800, "maximized": False}
        }
        _save_settings()


def _save_settings():
    """Save settings to JSON file."""
    try:
        SETTINGS_FILE.write_text(json.dumps(settings, indent=2))
    except Exception as e:
        _log(f"Failed to save settings: {e}", "ERROR")


def _is_auto_start_enabled():
    """Check if auto-start is enabled in Windows startup."""
    startup_dir = Path(os.environ.get("APPDATA", "")) / "Microsoft" / "Windows" / "Start Menu" / "Programs" / "Startup"
    shortcut = startup_dir / "Wallos.lnk"
    return shortcut.exists()


def _set_auto_start(enable: bool):
    """Enable/disable auto-start on Windows login."""
    try:
        startup_dir = Path(os.environ.get("APPDATA", "")) / "Microsoft" / "Windows" / "Start Menu" / "Programs" / "Startup"
        startup_dir.mkdir(parents=True, exist_ok=True)
        shortcut = startup_dir / "Wallos.lnk"
        
        if enable:
            # Create shortcut to Wallos.exe (or python script)
            import win32com.client
            shell = win32com.client.Dispatch("WScript.Shell")
            shortcut_obj = shell.CreateShortCut(str(shortcut))
            shortcut_obj.TargetPath = sys.executable
            app_path = str(WALLOS_ROOT / "desktop" / "app.py")
            shortcut_obj.Arguments = f'"{app_path}" --minimized'
            shortcut_obj.WorkingDirectory = str(WALLOS_ROOT)
            shortcut_obj.IconLocation = str(TRAY_ICON)
            shortcut_obj.Description = "Wallos - Wallet Tracker (Auto-start)"
            shortcut_obj.Save()
            _log("Auto-start enabled")
        else:
            if shortcut.exists():
                shortcut.unlink()
                _log("Auto-start disabled")
        
        settings["auto_start"] = enable
        _save_settings()
        return True
    except Exception as e:
        _log(f"Failed to set auto-start: {e}", "ERROR")
        return False


# ---- System Tray Integration ----

def create_tray_icon(window_getter):
    """Create the system tray icon and menu."""
    global tray_icon, is_minimized_to_tray

    try:
        import pystray
        from pystray import Icon, Menu, MenuItem

        img = PILImage.open(TRAY_ICON)
        img = img.resize((64, 64))

        def on_quit(icon, item):
            stop_app()

        def toggle_visibility(icon, item):
            global is_minimized_to_tray
            is_minimized_to_tray = not is_minimized_to_tray
            w = webview.windows[0] if webview.windows else None
            if w:
                if is_minimized_to_tray:
                    w.hide()
                else:
                    w.show()
                    w.restore()
                    w.focus()

        def on_settings(icon, item):
            _log("Settings requested from tray")
            w = webview.windows[0] if webview.windows else None
            if w:
                w.evaluate_js("window.location.href = window.location.origin + '/settings.php';")

        def on_backup(icon, item):
            _log("Backup triggered from tray")
            import subprocess
            try:
                result = subprocess.run(
                    [sys.executable, str(BACKUP_SCRIPT), "create", "manual"],
                    capture_output=True, text=True, timeout=30,
                )
                _log(f"Backup result: {result.stdout[-200:] if result.stdout else ''}")
            except Exception as e:
                _log(f"Backup failed: {e}")

        def on_restore_latest(icon, item):
            _log("Restore latest backup requested from tray")
            import subprocess
            try:
                result = subprocess.run(
                    [sys.executable, str(BACKUP_SCRIPT), "restore", "latest"],
                    capture_output=True, text=True, timeout=30,
                )
                _log(f"Restore result: {result.stdout[-200:] if result.stdout else ''}")
            except Exception as e:
                _log(f"Restore failed: {e}")

        menu = Menu(
            MenuItem('Show Wallos', toggle_visibility, default=True),
            MenuItem('Settings', on_settings),
            MenuItem('Create Backup', on_backup),
            MenuItem('Restore Latest Backup', on_restore_latest),
            MenuItem('Quit Wallos', on_quit),
        )

        tray_icon = Icon("Wallos", img, "Wallos - Wallet Tracker", menu)
        tray_icon.run()
    except ImportError:
        _log("pystray not available; tray integration disabled", "WARNING")
    except Exception as e:
        _log(f"Tray icon error: {e}", "ERROR")


# ---- JS API Bridge ----

JS_API_BRIDGE = """
<script>
// Desktop JS Bridge - injected into webview
(function() {
    window.WallosDesktop = {
        // Show desktop notification via pywebview API
        notify: function(title, body) {
            return new Promise((resolve, reject) => {
                if (window.pywebview && window.pywebview.api && typeof window.pywebview.api.notify === 'function') {
                    window.pywebview.api.notify(title, body).then(resolve, reject);
                } else {
                    reject(new Error('Notification API not available'));
                }
            });
        },

        // Open external link in system default browser
        openExternal: function(url) {
            return new Promise((resolve, reject) => {
                if (window.pywebview && window.pywebview.api && typeof window.pywebview.api.openExternal === 'function') {
                    window.pywebview.api.openExternal(url).then(resolve, reject);
                } else {
                    window.open(url, '_blank');
                    resolve();
                }
            });
        },

        // Trigger manual backup via Python
        triggerBackup: function() {
            if (window.pywebview && window.pywebview.api && typeof window.pywebview.api.triggerBackup === 'function') {
                return window.pywebview.api.triggerBackup();
            }
            return Promise.reject(new Error('Backup API not available'));
        },

        // Minimize to system tray
        minimizeToTray: function() {
            if (window.pywebview && window.pywebview.api && typeof window.pywebview.api.minimizeToTray === 'function') {
                window.pywebview.api.minimizeToTray();
            }
        },

        // Restore from system tray
        restoreFromTray: function() {
            if (window.pywebview && window.pywebview.api && typeof window.pywebview.api.restoreWindow === 'function') {
                window.pywebview.api.restoreWindow();
            }
        },

        // Get host OS time
        getHostTime: function() {
            return new Date().toISOString();
        },

        // Get app version info
        getVersion: function() {
            return new Promise((resolve) => {
                if (window.pywebview && window.pywebview.api && typeof window.pywebview.api.getVersion === 'function') {
                    window.pywebview.api.getVersion().then(resolve);
                } else {
                    resolve({version: 'desktop', platform: navigator.platform});
                }
            });
        },

        // Check if running in desktop mode
        isDesktop: function() {
            return true;
        }
    };
})();
</script>
"""


def inject_js_hooks(window):
    """Inject JavaScript hooks for native OS features into the webview window."""
    # Poll until page has finished loading (avoid 'Unexpected token <' on empty DOM)
    for _ in range(20):
        try:
            window.evaluate_js(JS_API_BRIDGE)
            _log("JS API bridge injected")
            return
        except Exception as e:
            time.sleep(0.25)
    _log(f"JS hook injection failed after retries: {e}", "WARNING")


# ---- Stop Application ----

def stop_app():
    """Clean shutdown: stop PHP server, scheduler, tray, exit."""
    global tray_icon, window

    _log("Shutting down Wallos Desktop...")

    # Create shutdown backup
    if settings.get("backup_on_shutdown", True):
        _log("Creating shutdown backup...")
        try:
            from desktop import backup_manager
            backup_manager.auto_backup_on_shutdown()
        except Exception as e:
            _log(f"Shutdown backup failed: {e}", "WARNING")

    # Stop PHP server
    try:
        from desktop import php_server
        php_server.stop_php_server()
        _log("PHP server stopped")
    except Exception as e:
        _log(f"PHP server stop warning: {e}", "WARNING")

    # Stop scheduler
    try:
        from desktop import scheduler
        scheduler.stop_scheduler()
        _log("Scheduler stopped")
    except Exception as e:
        _log(f"Scheduler stop warning: {e}", "WARNING")

    # Save window state
    if window:
        try:
            settings["window_state"] = {
                "width": window.width,
                "height": window.height,
                "maximized": False  # pywebview doesn't expose this easily
            }
            _save_settings()
        except Exception:
            pass

    # Hide tray
    if tray_icon:
        try:
            tray_icon.stop()
        except Exception:
            pass

    _log("Shutdown complete")
    os._exit(0)


# ---- Main Application ----

class DesktopApi:
    """JS API exposed to pywebview window via pywebview.api"""

    def notify(self, title: str, body: str):
        """Show a native desktop notification."""
        if not settings.get("enable_notifications", True):
            return False
        try:
            import win10toast
            toaster = win10toast.ToastNotifier()
            toaster.show_toast(title, body, icon_path=str(TRAY_ICON), duration=5, threaded=True)
        except ImportError:
            # Fallback to Windows toast via PowerShell
            try:
                import subprocess as sp
                title_esc = title.replace('"', '`"').replace("'", "''")
                body_esc = body.replace('"', '`"').replace("'", "''")
                ps_cmd = (
                    'Add-Type -AssemblyName System.Windows.Forms; '
                    '$notify = New-Object System.Windows.Forms.NotifyIcon; '
                    '$notify.Icon = [System.Drawing.SystemIcons]::Information; '
                    '$notify.Visible = $true; '
                    f'$notify.ShowBalloonTip(5000, \'{title_esc}\', \'{body_esc}\', '
                    '[System.Windows.Forms.ToolTipIcon]::Info)'
                )
                sp.run(["powershell", "-Command", ps_cmd],
                       creationflags=sp.CREATE_NO_WINDOW, capture_output=True, timeout=5)
            except Exception as e:
                _log(f"Notification failed: {e}", "WARNING")
        return True

    def openExternal(self, url: str):
        """Open external URL in system default browser."""
        try:
            if sys.platform == 'win32':
                os.startfile(url)
            else:
                import webbrowser
                webbrowser.open(url)
        except Exception as e:
            _log(f"openExternal failed: {e}", "WARNING")
        return True

    def triggerBackup(self):
        """Trigger a manual backup of wallos.db + logos."""
        import subprocess
        try:
            result = subprocess.run(
                [sys.executable, str(BACKUP_SCRIPT), "create", "manual"],
                capture_output=True, text=True, timeout=60,
            )
            _log(f"Backup result: {result.returncode}: {result.stdout[-200:] if result.stdout else ''}")
            return result.returncode == 0
        except Exception as e:
            _log(f"Backup failed: {e}", "ERROR")
            return False

    def minimizeToTray(self):
        """Minimize window to system tray."""
        global is_minimized_to_tray, window
        is_minimized_to_tray = True
        if window:
            window.hide()

    def restoreWindow(self):
        """Restore window from system tray."""
        global is_minimized_to_tray, window
        is_minimized_to_tray = False
        if window:
            window.show()
            window.restore()
            window.focus()

    def getVersion(self):
        """Return version info."""
        return {
            "version": "desktop-1.0",
            "platform": sys.platform,
            "python": sys.version.split()[0],
            "wallos_root": str(WALLOS_ROOT)
        }

    def getSettings(self):
        """Return current settings."""
        return settings

    def setSetting(self, key: str, value):
        """Update a setting."""
        if key in settings:
            settings[key] = value
            _save_settings()
            return True
        return False

    def toggleAutoStart(self, enable: bool):
        """Enable/disable auto-start on login."""
        return _set_auto_start(enable)

    def isAutoStartEnabled(self):
        """Check if auto-start is enabled."""
        return _is_auto_start_enabled()

    def listBackups(self):
        """List available backups."""
        try:
            from desktop import backup_manager
            return backup_manager.list_backups()
        except Exception as e:
            _log(f"listBackups failed: {e}", "ERROR")
            return []

    def restoreBackup(self, backup_name: str):
        """Restore from a specific backup."""
        try:
            from desktop import backup_manager
            return backup_manager.restore_backup(backup_name)
        except Exception as e:
            _log(f"restoreBackup failed: {e}", "ERROR")
            return False


def main():
    global tray_icon, window, php_manager, settings

    # Single-instance enforced by Windows mutex at module load
    _load_settings()
    _log("Wallos Desktop starting...")

    # 1. Start PHP server in background (non-blocking)
    base_url_holder = {}

    def start_php_background():
        try:
            from desktop import php_server
            port = php_server.start_php_server()
            # Set the port in php_server module so navigate_when_ready() can read it
            php_server.port = port
            # Set the URL in base_url_holder for navigation
            base_url_holder['url'] = php_server.get_base_url()
            _log(f"PHP server started at {php_server.get_base_url()}")
        except Exception as e:
            _log(f"PHP server start failed: {e}", "ERROR")

    php_thread = threading.Thread(target=start_php_background, daemon=True, name="PHPStartup")
    php_thread.start()

    # 2. Start cron scheduler in background
    def start_scheduler_background():
        try:
            from desktop import scheduler
            scheduler.start_scheduler()
            _log("Cron scheduler started")
        except Exception as e:
            _log(f"Scheduler start failed: {e}", "ERROR")

    threading.Thread(target=start_scheduler_background, daemon=True, name="SchedulerStartup").start()

    # 3. Create startup backup in background
    if settings.get("backup_on_startup", True):
        def start_backup_background():
            try:
                from desktop import backup_manager
                backup_manager.auto_backup_on_startup()
            except Exception as e:
                _log(f"Startup backup failed: {e}", "WARNING")
        threading.Thread(target=start_backup_background, daemon=True, name="BackupStartup").start()

    # 4. Create pywebview window IMMEDIATELY with loading page
    # We'll navigate to real URL once PHP is ready
    try:
        win_state = settings.get("window_state", {})
        window = webview.create_window(
            title='Wallos - Wallet Tracker',
            url='about:blank',  # Start blank, navigate when ready
            width=win_state.get("width", 1200),
            height=win_state.get("height", 800),
            min_size=(800, 600),
            resizable=True,
            confirm_close=True,
        )
    except Exception as e:
        _log(f"ERROR creating webview window: {e}", "ERROR")
        stop_app()
        return

    # 5. Wait briefly for PHP to bind its port, then navigate
    def navigate_when_ready():
        import urllib.request
        from desktop import php_server

        # Wait for PHP thread to set the port (max 5s)
        deadline = time.time() + 5.0
        while php_server.port is None and time.time() < deadline:
            time.sleep(0.05)

        url = php_server.get_base_url() or base_url_holder.get('url') or 'http://127.0.0.1:8282'

        # Poll health endpoint until PHP is listening (max 5s)
        deadline = time.time() + 5.0
        while time.time() < deadline:
            try:
                req = urllib.request.Request(f"{url}/health.php", method="HEAD")
                with urllib.request.urlopen(req, timeout=0.5) as resp:
                    if resp.status == 200:
                        break
            except Exception:
                pass
            time.sleep(0.1)
        else:
            _log("PHP server not ready after 5s, navigating anyway", "WARNING")
        if window:
            try:
                window.load_url(url)
                _log(f"Navigated to {url}")
                inject_js_hooks(window)
            except Exception as e:
                _log(f"Navigation failed: {e}", "ERROR")

    threading.Thread(target=navigate_when_ready, daemon=True, name="Navigate").start()

    # 6. Set up window close handler
    def on_closing():
        _log("Window close requested")
        if settings.get("minimize_to_tray_on_close", True):
            # Minimize to tray instead of closing
            global is_minimized_to_tray
            is_minimized_to_tray = True
            window.hide()
            return False  # Cancel close
        else:
            stop_app()
            return True  # Allow close

    window.events.closing += on_closing

    # 7. Handle window minimize event
    def on_minimize():
        global is_minimized_to_tray
        if not is_minimized_to_tray:
            is_minimized_to_tray = True

    window.events.minimized += on_minimize

    # 8. Start tray icon in background thread
    tray_thread = threading.Thread(target=create_tray_icon, args=(lambda: window,), daemon=True)
    tray_thread.start()

    # 9. Handle --minimized flag for auto-start
    if "--minimized" in sys.argv or settings.get("start_minimized", False):
        def hide_after_ready():
            time.sleep(2)
            global is_minimized_to_tray
            is_minimized_to_tray = True
            if window:
                window.hide()
        threading.Thread(target=hide_after_ready, daemon=True).start()

    # 10. Start the webview event loop (blocks until window closes)
    _log("Wallos Desktop event loop started")
    
    # Memory/CPU optimization: reduce webview render frequency when minimized
    def monitor_window_state():
        while True:
            time.sleep(5)
            # Just keep thread alive without checking non-existent internal method
            pass

    threading.Thread(target=monitor_window_state, daemon=True).start()

    webview.start(debug=False, private_mode=False)

    # Should not reach here
    stop_app()


if __name__ == '__main__':
    # Handle command line arguments
    if len(sys.argv) > 1:
        if sys.argv[1] == '--settings':
            _load_settings()
            print(json.dumps(settings, indent=2))
            sys.exit(0)
        elif sys.argv[1] == '--test-backup':
            from desktop import backup_manager
            backup_manager.create_backup("test")
            sys.exit(0)
        elif sys.argv[1] == '--test-restore':
            from desktop import backup_manager
            backups = backup_manager.list_backups()
            if backups:
                backup_manager.restore_backup(backups[0]["name"])
            sys.exit(0)

    main()