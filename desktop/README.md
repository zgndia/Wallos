# Wallos Desktop - pywebview Desktop Shell

A native desktop application wrapper for [Wallos](https://github.com/ellite/Wallos) wallet tracker using pywebview (WebView2/Edge backend on Windows).

## Features

### Core Desktop Integration
- **Native Window**: Runs Wallos in a clean desktop window without browser chrome
- **System Tray**: Minimize to tray with quick-access menu (show/hide, settings, backup, quit)
- **Hidden Console**: No console window visible during normal operation
- **Auto-start on Login**: Optional Windows startup integration
- **Window State Persistence**: Remembers size, position, and minimized state between sessions

### Data Protection
- **SQLite Online Backup API**: Consistent snapshots without locking conflicts
- **Rolling Auto-Backups**: Creates timestamped backups of `wallos.db` + logos
- **One-Click Restore**: Restore from any previous backup via tray menu
- **Single-Instance Lock**: Prevents SQLite corruption from multiple instances

### Cron Daemon
- Python-based cron replacing Linux crontab
- Replicates all Wallos `endpoints/cronjobs/` tasks
- **Missed-job catch-up**: Runs overdue jobs on startup
- Rotating log files in `desktop/logs/`

### Notifications
- Native Windows toast notifications for subscription renewals
- Desktop notification bridge via JS API (`window.WallosDesktop.notify()`)
- Configurable enable/disable per user

### Optimizations
- Ephemeral port binding (loopback only, never public)
- Worker pool management (PHP CLI workers)
- Memory/CPU efficient background threads
- Reduced render frequency when minimized to tray

## Requirements

- Python 3.10+
- Windows 10/11 (WebView2 runtime included)
- PHP 8.3+ at `C:\Users\zgn\php\php.exe` (portable)
- Existing Wallos database with verified backup

## Installation

```bash
# Install dependencies
pip install -r requirements.txt

# Test individual components
python -m desktop.php_server
python -m desktop.scheduler
python -m desktop.backup_manager create manual
```

## Usage

### Launch App
```bash
# Normal launch
python desktop/app.py

# Start minimized to tray (for auto-start)
python desktop/app.py --minimized
```

### Command Line Interface
```bash
# View settings
python desktop/app.py --settings

# Create backup manually
python desktop/app.py --test-backup

# Restore latest backup (use with caution)
python desktop/app.py --test-restore
```

### System Tray Menu
- **Show Wallos**: Toggle window visibility
- **Settings**: Jump to Wallos settings page
- **Create Backup**: Immediate backup of database
- **Restore Latest Backup**: One-click restore from newest backup
- **Quit Wallos**: Clean shutdown with backup

### Auto-Start Configuration
Toggle via UI or programmatically:
```python
from desktop.app import _set_auto_start
_set_auto_start(True)   # Enable auto-start
_set_auto_start(False)  # Disable auto-start
```

## File Structure

```
desktop/
├── __init__.py          # Package init
├── app.py               # Main entry point & window manager
├── php_server.py        # PHP runtime lifecycle
├── scheduler.py         # Cron daemon
├── backup_manager.py    # Rolling backups
├── data_manager.py      # Database ops & migrations
├── requirements.txt     # Python dependencies
├── wallos_desktop.spec  # PyInstaller spec
├── settings.json        # User preferences (created on first run)
├── lock.txt             # Single-instance lock (runtime)
├── webview_profile/     # Browser storage & cookies
├── logs/                # Application logs
│   ├── wallos-YYYYMMDD.log
│   ├── wallos-cron-YYYYMMDD.log
│   └── wallos-backup-YYYYMMDD.log
└── backups/             # Backup archives
    ├── wallos-backup-YYYYMMDD-HHMMSS/
    │   ├── db/wallos.db
    │   ├── logos/
    │   └── metadata.json
    └── .last_backup_time
```

## Architecture

```
┌─────────────────────────────────────────┐
│            pywebview Window              │
│  ┌─────────────────────────────────────┐│
│  │       Wallos PHP/Web App            ││
│  │    (http://127.0.0.1:ephemeral)     ││
│  └─────────────────────────────────────┘│
├─────────────────────────────────────────┤
│  JS Bridge (window.WallosDesktop)       │
│  ├─ notify() → Win10Toast             │
│  ├─ openExternal() → default browser   │
│  ├─ triggerBackup() → backup_manager   │
│  └─ minimizeToTray/restoreFromTray     │
├─────────────────────────────────────────┤
│  System Tray (pystray)                  │
│  ├─ Show Wallos                         │
│  ├─ Settings                            │
│  ├─ Create Backup                       │
│  └─ Quit                                │
├─────────────────────────────────────────┤
│  Background Services                    │
│  ├─ PHP Server (managed lifecycle)      │
│  ├─ Cron Scheduler (12 jobs)           │
│  └─ Backup Manager (on startup/exit)   │
└─────────────────────────────────────────┘
```

## Troubleshooting

### PHP Server Fails to Start
- Verify PHP installed at `C:\Users\zgn\php\php.exe`
- Check logs: `desktop/logs/wallos-*.log`
- Ensure no other process uses the selected port

### Cron Jobs Fail with SQL Errors
- Database schema version mismatch (check migration status)
- Run `CREATE DATABASE` job manually after confirming schema

### Notification Not Showing
- Request permission on first use
- Check Windows notification settings for the app

### Multiple Instances Blocked
- Delete stale `desktop/lock.txt` if process crashed
- Use task manager to kill lingering PHP/python processes

## Build Standalone EXE

```bash
# Install PyInstaller
pip install pyinstaller

# Build one-file executable
pyinstaller desktop/wallos_desktop.spec

# Output in dist/Wallos.exe
```

## License

Same as upstream Wallos (MIT).

## Upstream Parity

This desktop wrapper maintains 100% feature parity with the original Wallos web application. All features are accessible through the embedded web interface; the desktop layer provides only platform-specific enhancements (tray, notifications, backups, auto-start).

---

**Version**: desktop-1.0  
**Python**: 3.10+  
**PHP**: 8.3+ required