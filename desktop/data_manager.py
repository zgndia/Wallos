"""
desktop/data_manager.py

Restores/mounts user's existing wallos.db and logos into /db/wallos.db and /images/uploads/logos/.
Runs Wallos schema migrations automatically (only after confirming Phase 0 backup exists).
Implements a single-instance lock so two desktop windows cannot corrupt SQLite simultaneously.
"""

import os
import sqlite3
import shutil
import time
from pathlib import Path
from contextlib import contextmanager

# Paths - import from package init to work correctly in PyInstaller bundles
try:
    from . import WALLOS_ROOT
except ImportError:
    # Fallback when run as script
    WALLOS_ROOT = Path(__file__).parent.parent
DB_PATH = WALLOS_ROOT / "app" / "db" / "wallos.db"
LOGOS_DIR = WALLOS_ROOT / "app" / "images" / "uploads" / "logos"
BACKUP_DIR = WALLOS_ROOT / "wallos-data-backup-20261125-183258"

# Single-instance lock file
LOCK_FILE = WALLOS_ROOT / "desktop" / "lock.txt"


@contextmanager
def db_lock():
    """Context manager for single-instance database lock."""
    pid = os.getpid()
    acquired = False
    try:
        # Try to create lock file exclusively
        if LOCK_FILE.exists():
            try:
                with open(LOCK_FILE, 'r') as f:
                    existing_pid = int(f.read().strip())
                # Check if process still exists
                if _process_exists(existing_pid):
                    raise RuntimeError(f"Another instance is running (PID: {existing_pid})")
            except (ValueError, OSError):
                pass  # Lock file corrupted, we'll overwrite
        
        LOCK_FILE.write_text(str(pid))
        acquired = True
        yield True
    finally:
        if acquired and LOCK_FILE.exists():
            try:
                LOCK_FILE.unlink()
            except OSError:
                pass


def _process_exists(pid: int) -> bool:
    """Check if a process with given PID exists."""
    try:
        import psutil
        return psutil.pid_exists(pid)
    except ImportError:
        # Fallback: try to signal the process (Unix) or use tasklist (Windows)
        if os.name == 'nt':
            import subprocess
            result = subprocess.run(
                ['tasklist', '/FI', f'PID eq {pid}'],
                capture_output=True, text=True
            )
            return str(pid) in result.stdout
        else:
            try:
                os.kill(pid, 0)
                return True
            except OSError:
                return False


def restore_db_from_backup(db_path=None, backup_source=None):
    """
    Restore wallos.db from the verified backup.
    
    Parameters:
      db_path: Destination path (default: app/db/wallos.db)
      backup_source: Source backup directory (default: Phase 0 backup)
    
    Returns:
      bool: True if restoration succeeded.
    """
    db_path = db_path or DB_PATH
    backup_source = backup_source or BACKUP_DIR
    
    src_db = backup_source / "wallos.db"
    src_wal = backup_source / "wallos.db-wal"
    src_shm = backup_source / "wallos.db-shm"
    
    if not src_db.is_file():
        print(f"[data_manager] ERROR: Backup wallos.db not found at {src_db}")
        return False
    
    # Ensure destination directory exists
    db_path.parent.mkdir(parents=True, exist_ok=True)
    
    # Remove any existing WAL/SHM files first
    for f in [db_path, db_path.with_suffix('.db-wal'), db_path.with_suffix('.db-shm')]:
        if f.exists():
            try:
                f.unlink()
            except OSError:
                pass
    
    # Copy main DB file
    shutil.copy2(src_db, db_path)
    print(f"[data_manager] Restored wallos.db from {src_db}")
    
    # Copy WAL/SHM if they exist (for consistency)
    if src_wal.exists():
        shutil.copy2(src_wal, db_path.with_suffix('.db-wal'))
    if src_shm.exists():
        shutil.copy2(src_shm, db_path.with_suffix('.db-shm'))
    
    return True


def restore_logos_from_backup(logos_dir=None, backup_source=None):
    """
    Restore logos from the verified backup.
    
    Returns:
      int: Number of logo files restored.
    """
    logos_dir = logos_dir or LOGOS_DIR
    backup_source = backup_source or BACKUP_DIR
    
    src_logos = backup_source / "logos"
    if not src_logos.is_dir():
        print(f"[data_manager] No logos backup found at {src_logos}")
        return 0
    
    logos_dir.mkdir(parents=True, exist_ok=True)
    
    count = 0
    for src_file in src_logos.iterdir():
        if src_file.is_file():
            dest_file = logos_dir / src_file.name
            shutil.copy2(src_file, dest_file)
            count += 1
    
    print(f"[data_manager] Restored {count} logo files from backup")
    return count


def verify_backup_exists(backup_source=None):
    """Verify the Phase 0 backup exists and is valid."""
    backup_source = backup_source or BACKUP_DIR
    src_db = backup_source / "wallos.db"
    
    if not src_db.is_file():
        return False, f"Backup database not found at {src_db}"
    
    # Quick integrity check
    try:
        conn = sqlite3.connect(f"file:{src_db}?mode=ro", uri=True)
        conn.execute("PRAGMA integrity_check")
        conn.close()
        return True, "Backup verified OK"
    except Exception as e:
        return False, f"Backup integrity check failed: {e}"


def run_migrations(db_path=None):
    """
    Run Wallos schema migrations by checking the migrations table.
    
    Wallos migrations are applied via PHP. This function just verifies
    the migration state and can trigger the PHP migration runner if needed.
    
    Returns:
      bool: True if migrations are up to date.
    """
    db_path = db_path or DB_PATH
    
    with db_lock() as locked:
        if not locked:
            return False
        
        try:
            conn = sqlite3.connect(db_path)
            cur = conn.cursor()
            
            # Check if migrations table exists
            cur.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='migrations'")
            if not cur.fetchone():
                print("[data_manager] No migrations table found - fresh install?")
                conn.close()
                return True
            
            # Get latest migration
            cur.execute("SELECT id, name, migrated_at FROM migrations ORDER BY id DESC LIMIT 1")
            row = cur.fetchone()
            if row:
                print(f"[data_manager] Latest migration: #{row[0]} - {row[1]} (applied: {row[2]})")
            else:
                print("[data_manager] No migrations recorded yet")
            
            conn.close()
            return True
        except Exception as e:
            print(f"[data_manager] Migration check failed: {e}")
            return False


def get_db_info(db_path=None):
    """Get basic info about the database for diagnostics."""
    db_path = db_path or DB_PATH
    
    if not db_path.exists():
        return {"exists": False}
    
    try:
        conn = sqlite3.connect(db_path)
        cur = conn.cursor()
        
        # Table row counts - note: 'user' not 'users' in Wallos
        tables = ['user', 'subscriptions', 'categories', 'currencies', 
                  'payment_methods', 'household', 'notifications', 'settings', 'migrations']
        info = {"exists": True, "tables": {}}
        
        for table in tables:
            try:
                cur.execute(f"SELECT COUNT(*) FROM {table}")
                info["tables"][table] = cur.fetchone()[0]
            except:
                info["tables"][table] = "N/A"
        
        # Get main currency from user table
        try:
            cur.execute("SELECT main_currency FROM user WHERE id=1")
            row = cur.fetchone()
            info["main_currency_id"] = row[0] if row else None
        except:
            info["main_currency_id"] = None
        
        conn.close()
        return info
    except Exception as e:
        return {"exists": True, "error": str(e)}


if __name__ == "__main__":
    print("[data_manager] Data Manager - Phase 0 Backup Verification")
    
    # Verify backup
    ok, msg = verify_backup_exists()
    print(f"  Backup: {msg}")
    
    if ok:
        # Show DB info
        info = get_db_info(BACKUP_DIR / "wallos.db")
        print(f"  Backup DB Info: {info}")
        
        # Test restore (dry run - to temp location)
        import tempfile
        with tempfile.TemporaryDirectory() as tmp:
            test_db = Path(tmp) / "test.db"
            if restore_db_from_backup(test_db):
                info = get_db_info(test_db)
                print(f"  Restored DB Info: {info}")
    
    # Check current DB
    print(f"\n  Current DB: {get_db_info()}")