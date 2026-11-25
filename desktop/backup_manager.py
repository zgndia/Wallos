"""
desktop/backup_manager.py

Automatic rolling local backups of wallos.db + logos on startup/exit
with one-click restore UI hook.
"""

import os
import shutil
import sqlite3
import time
from pathlib import Path
from datetime import datetime
from contextlib import contextmanager

# Paths
WALLOS_ROOT = Path(__file__).parent.parent
DB_PATH = WALLOS_ROOT / "app" / "db" / "wallos.db"
LOGOS_DIR = WALLOS_ROOT / "app" / "images" / "uploads" / "logos"
BACKUP_ROOT = WALLOS_ROOT / "desktop" / "backups"
LOGS_DIR = WALLOS_ROOT / "desktop" / "logs"

# Backup retention
MAX_BACKUPS = 10  # Keep last 10 backups
BACKUP_INTERVAL_HOURS = 24  # Minimum hours between auto-backups


@contextmanager
def db_lock():
    """Context manager for single-instance database lock (same as data_manager)."""
    import psutil
    LOCK_FILE = WALLOS_ROOT / "desktop" / "lock.txt"
    pid = os.getpid()
    acquired = False
    try:
        if LOCK_FILE.exists():
            try:
                existing_pid = int(LOCK_FILE.read_text().strip())
                if psutil.pid_exists(existing_pid):
                    raise RuntimeError(f"Another instance is running (PID: {existing_pid})")
            except (ValueError, OSError):
                pass
        LOCK_FILE.write_text(str(pid))
        acquired = True
        yield True
    finally:
        if acquired and LOCK_FILE.exists():
            try:
                LOCK_FILE.unlink()
            except OSError:
                pass


def _log(msg: str):
    """Write to rotating log file."""
    LOGS_DIR.mkdir(parents=True, exist_ok=True)
    log_file = LOGS_DIR / f"wallos-backup-{datetime.now().strftime('%Y%m%d')}.log"
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    with open(log_file, "a", encoding="utf-8") as f:
        f.write(f"[{timestamp}] {msg}\n")


def _get_backup_dir():
    """Get or create backup directory with timestamp."""
    BACKUP_ROOT.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    backup_dir = BACKUP_ROOT / f"wallos-backup-{timestamp}"
    backup_dir.mkdir(parents=True, exist_ok=True)
    return backup_dir


def _cleanup_old_backups():
    """Remove backups beyond MAX_BACKUPS, keeping the most recent."""
    if not BACKUP_ROOT.exists():
        return
    
    backups = sorted(
        [d for d in BACKUP_ROOT.iterdir() if d.is_dir() and d.name.startswith("wallos-backup-")],
        key=lambda x: x.stat().st_mtime,
        reverse=True
    )
    
    for old_backup in backups[MAX_BACKUPS:]:
        try:
            shutil.rmtree(old_backup)
            _log(f"Removed old backup: {old_backup.name}")
        except Exception as e:
            _log(f"Failed to remove old backup {old_backup.name}: {e}")


def create_backup(reason="manual"):
    """
    Create a full backup of wallos.db (+ WAL/SHM) and logos directory.
    
    Uses SQLite online backup API for consistent snapshot without locking.
    
    Parameters:
      reason: "startup", "shutdown", "scheduled", "manual", "pre-migration"
    
    Returns:
      Path: Path to backup directory, or None if failed.
    """
    _log(f"Creating backup (reason: {reason})...")
    
    # Check if we should skip (too soon since last backup)
    if reason in ("scheduled", "startup", "shutdown"):
        last_backup_file = BACKUP_ROOT / ".last_backup_time"
        if last_backup_file.exists():
            try:
                last_time = float(last_backup_file.read_text().strip())
                if time.time() - last_time < BACKUP_INTERVAL_HOURS * 3600:
                    _log(f"Skipping backup - last backup was {(time.time() - last_time)/3600:.1f}h ago")
                    return None
            except Exception:
                pass
    
    backup_dir = _get_backup_dir()
    db_backup_dir = backup_dir / "db"
    logos_backup_dir = backup_dir / "logos"
    db_backup_dir.mkdir(parents=True, exist_ok=True)
    logos_backup_dir.mkdir(parents=True, exist_ok=True)
    
    try:
        # 1. Backup database using SQLite online backup API (consistent, no locks)
        if DB_PATH.exists():
            # Copy main DB file (simple approach - works if no write in progress)
            # For true online backup, use sqlite3 backup API:
            dest_db = db_backup_dir / "wallos.db"
            
            # Use SQLite backup API for consistent snapshot
            source_conn = sqlite3.connect(f"file:{DB_PATH}?mode=ro", uri=True)
            dest_conn = sqlite3.connect(dest_db)
            source_conn.backup(dest_conn)
            source_conn.close()
            dest_conn.close()
            
            _log(f"Database backed up to {dest_db}")
        else:
            _log("WARNING: Database file not found")
        
        # 2. Backup logos directory
        logo_count = 0
        if LOGOS_DIR.exists():
            for logo_file in LOGOS_DIR.iterdir():
                if logo_file.is_file():
                    shutil.copy2(logo_file, logos_backup_dir / logo_file.name)
                    logo_count += 1
            _log(f"Backed up {logo_count} logo files")
        
        # 3. Write metadata
        metadata = {
            "timestamp": datetime.now().isoformat(),
            "reason": reason,
            "db_size": DB_PATH.stat().st_size if DB_PATH.exists() else 0,
            "logo_count": logo_count,
            "db_path": str(DB_PATH),
            "logos_path": str(LOGOS_DIR),
        }
        import json
        (backup_dir / "metadata.json").write_text(json.dumps(metadata, indent=2))
        
        # 4. Update last backup time
        last_backup_file = BACKUP_ROOT / ".last_backup_time"
        last_backup_file.write_text(str(time.time()))
        
        # 5. Cleanup old backups
        _cleanup_old_backups()
        
        _log(f"Backup completed: {backup_dir.name} (DB: {metadata['db_size']} bytes, Logos: {logo_count})")
        return backup_dir
        
    except Exception as e:
        _log(f"Backup failed: {e}")
        # Cleanup failed backup
        try:
            shutil.rmtree(backup_dir)
        except Exception:
            pass
        return None


def list_backups():
    """List all available backups with metadata."""
    if not BACKUP_ROOT.exists():
        return []
    
    backups = []
    for backup_dir in sorted(
        [d for d in BACKUP_ROOT.iterdir() if d.is_dir() and d.name.startswith("wallos-backup-")],
        key=lambda x: x.stat().st_mtime,
        reverse=True
    ):
        meta_file = backup_dir / "metadata.json"
        if meta_file.exists():
            try:
                import json
                meta = json.loads(meta_file.read_text())
                meta["path"] = str(backup_dir)
                meta["name"] = backup_dir.name
                backups.append(meta)
            except Exception:
                pass
    
    return backups


def restore_backup(backup_name_or_path):
    """
    Restore wallos.db and logos from a backup.
    
    Parameters:
      backup_name_or_path: Backup directory name (e.g., "wallos-backup-20261125-120000") 
                           or full Path to backup directory.
    
    Returns:
      bool: True if restoration succeeded.
    """
    # Resolve backup path
    if isinstance(backup_name_or_path, str) and not Path(backup_name_or_path).is_absolute():
        backup_path = BACKUP_ROOT / backup_name_or_path
    else:
        backup_path = Path(backup_name_or_path)
    
    if not backup_path.exists() or not backup_path.is_dir():
        _log(f"Restore failed: Backup not found at {backup_path}")
        return False
    
    meta_file = backup_path / "metadata.json"
    meta = {}
    if meta_file.exists():
        try:
            import json
            meta = json.loads(meta_file.read_text())
        except Exception:
            pass
    
    _log(f"Restoring from backup: {backup_path.name} (original: {meta.get('timestamp', 'unknown')})")
    
    try:
        # 1. Restore database
        src_db = backup_path / "db" / "wallos.db"
        if src_db.exists():
            # Ensure no connections are open (best effort)
            with db_lock():
                # Remove existing WAL/SHM
                for f in [DB_PATH, DB_PATH.with_suffix('.db-wal'), DB_PATH.with_suffix('.db-shm')]:
                    if f.exists():
                        f.unlink()
                
                # Copy database
                shutil.copy2(src_db, DB_PATH)
                _log(f"Database restored from {src_db}")
        else:
            _log("ERROR: No database in backup")
            return False
        
        # 2. Restore logos
        src_logos = backup_path / "logos"
        if src_logos.exists():
            # Clear current logos
            if LOGOS_DIR.exists():
                shutil.rmtree(LOGOS_DIR)
            LOGOS_DIR.mkdir(parents=True, exist_ok=True)
            
            count = 0
            for logo_file in src_logos.iterdir():
                if logo_file.is_file():
                    shutil.copy2(logo_file, LOGOS_DIR / logo_file.name)
                    count += 1
            _log(f"Restored {count} logo files")
        
        _log("Restore completed successfully")
        return True
        
    except Exception as e:
        _log(f"Restore failed: {e}")
        return False


def get_latest_backup():
    """Get the most recent backup directory."""
    backups = list_backups()
    if backups:
        return Path(backups[0]["path"])
    return None


def auto_backup_on_startup():
    """Create backup on application startup (if enough time passed)."""
    return create_backup("startup")


def auto_backup_on_shutdown():
    """Create backup on application shutdown."""
    return create_backup("shutdown")


def auto_backup_scheduled():
    """Create scheduled backup (called by scheduler)."""
    return create_backup("scheduled")


# CLI interface
if __name__ == "__main__":
    import sys
    
    if len(sys.argv) < 2:
        print("Usage: python backup_manager.py [create|list|restore <name>|latest]")
        sys.exit(1)
    
    cmd = sys.argv[1]
    
    if cmd == "create":
        reason = sys.argv[2] if len(sys.argv) > 2 else "manual"
        result = create_backup(reason)
        if result:
            print(f"Backup created: {result}")
        else:
            print("Backup skipped or failed")
            sys.exit(1)
    
    elif cmd == "list":
        backups = list_backups()
        if not backups:
            print("No backups found")
        else:
            print(f"Found {len(backups)} backups:")
            for b in backups:
                ts = b.get("timestamp", "unknown")[:19].replace("T", " ")
                print(f"  {b['name']} - {ts} - {b['reason']} - DB: {b['db_size']} bytes - Logos: {b['logo_count']}")
    
    elif cmd == "restore":
        if len(sys.argv) < 3:
            print("Usage: python backup_manager.py restore <backup_name>")
            sys.exit(1)
        backup_name = sys.argv[2]
        if restore_backup(backup_name):
            print(f"Restored from {backup_name}")
        else:
            print("Restore failed")
            sys.exit(1)
    
    elif cmd == "latest":
        latest = get_latest_backup()
        if latest:
            print(f"Latest backup: {latest}")
            if restore_backup(latest):
                print("Restored from latest backup")
            else:
                print("Restore failed")
                sys.exit(1)
        else:
            print("No backups found")
            sys.exit(1)
    
    else:
        print(f"Unknown command: {cmd}")
        sys.exit(1)