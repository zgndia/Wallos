#!/usr/bin/env python3
"""
Phase 6 Integrity Check for Wallos Desktop
"""
import os
import sys
import time
import sqlite3
from pathlib import Path

# Add wallos root to path
WALLOS_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(WALLOS_ROOT))
os.chdir(WALLOS_ROOT)

print("=" * 60)
print("WALLOS DESKTOP - PHASE 6 INTEGRITY CHECK")
print("=" * 60)
print()

passed = 0
failed = 0

def check(name, condition, detail=""):
    global passed, failed
    if condition:
        print(f"  [PASS] {name}")
        passed += 1
    else:
        print(f"  [FAIL] {name} - {detail}")
        failed += 1
    return condition

# ============================================================================
# 1. Backup Verification
# ============================================================================
print("1. BACKUP VERIFICATION")
try:
    from desktop import data_manager
    ok, msg = data_manager.verify_backup_exists()
    check("Backup exists and valid", ok, msg)
except Exception as e:
    check("Backup exists and valid", False, str(e))

# ============================================================================
# 2. Row Count Comparison
# ============================================================================
print("\n2. ROW COUNT COMPARISON")
try:
    current = data_manager.get_db_info()
    backup_conn = sqlite3.connect(r"C:\Users\zgn\wallos-data-backup-20261125-183258\wallos.db")
    backup_cur = backup_conn.cursor()
    
    rows_match = True
    for table in ["user", "subscriptions", "categories", "currencies", "payment_methods"]:
        try:
            current_count = current["tables"].get(table, "N/A")
            backup_cur.execute(f"SELECT COUNT(*) FROM {table}")
            backup_count = backup_cur.fetchone()[0]
            
            if current_count != backup_count:
                rows_match = False
                print(f"       MISMATCH: {table} - current: {current_count}, backup: {backup_count}")
        except Exception as e:
            rows_match = False
            print(f"       ERROR checking {table}: {e}")
    
    backup_conn.close()
    check("Row counts match backup", rows_match)
except Exception as e:
    check("Row counts match backup", False, str(e))

# ============================================================================
# 3. Database Integrity
# ============================================================================
print("\n3. DATABASE INTEGRITY")
try:
    db_path = WALLOS_ROOT / "app" / "db" / "wallos.db"
    conn = sqlite3.connect(str(db_path.resolve()))
    cur = conn.cursor()
    cur.execute("PRAGMA integrity_check")
    result = cur.fetchone()[0]
    conn.close()
    check("DB integrity check", result == "ok", result)
except Exception as e:
    check("DB integrity check", False, str(e))

# ============================================================================
# 4. PHP Server Health
# ============================================================================
print("\n4. PHP SERVER HEALTH")
try:
    from desktop import php_server
    port = php_server.start_php_server()
    ready = php_server.wait_until_ready(10)
    base_url = php_server.get_base_url() if ready else ""
    php_server.stop_php_server()
    check("PHP server starts and responds", ready)
    check("Server bound to loopback only", ready and base_url.startswith("http://127.0.0.1"))
except Exception as e:
    check("PHP server starts and responds", False, str(e))

# ============================================================================
# 5. WebView Profile
# ============================================================================
print("\n5. WEBVIEW PROFILE")
try:
    profile_dir = WALLOS_ROOT / "desktop" / "webview_profile"
    profile_dir.mkdir(exist_ok=True)
    check("WebView profile directory accessible", profile_dir.exists())
except Exception as e:
    check("WebView profile directory accessible", False, str(e))

# ============================================================================
# 6. Logs Directory
# ============================================================================
print("\n6. LOGS DIRECTORY")
try:
    logs_dir = WALLOS_ROOT / "desktop" / "logs"
    logs_dir.mkdir(exist_ok=True)
    check("Logs directory accessible", logs_dir.exists())
    
    log_files = list(logs_dir.glob("*.log"))
    check("Log files created", len(log_files) > 0, f"Found {len(log_files)} log files")
except Exception as e:
    check("Logs directory accessible", False, str(e))

# ============================================================================
# 7. Backup System
# ============================================================================
print("\n7. BACKUP SYSTEM")
try:
    from desktop import backup_manager
    backups = backup_manager.list_backups()
    check("Backup system functional", True, f"{len(backups)} backup(s) found")
    
    latest = backup_manager.get_latest_backup()
    check("Can retrieve latest backup", latest is not None)
except Exception as e:
    check("Backup system functional", False, str(e))

# ============================================================================
# 8. Scheduler Test
# ============================================================================
print("\n8. SCHEDULER TEST")
try:
    from desktop import scheduler
    scheduler.start_scheduler()
    time.sleep(1)
    # Test that scheduler can be stopped cleanly
    scheduler.stop_scheduler()
    check("Scheduler starts/stops cleanly", True)
except Exception as e:
    check("Scheduler starts/stops cleanly", False, str(e))

# ============================================================================
# 9. Settings Persistence
# ============================================================================
print("\n9. SETTINGS PERSISTENCE")
try:
    # Need to call _load_settings() first to populate the global
    from desktop.app import _load_settings
    _load_settings()
    from desktop.app import settings
    check("Settings loaded successfully", bool(settings))
    check("Settings contains expected keys", all(k in settings for k in 
          ["auto_start", "minimize_to_tray_on_close", "window_state"]))
except Exception as e:
    check("Settings loaded successfully", False, str(e))

# ============================================================================
# 10. Git Hygiene (if in repo)
# ============================================================================
print("\n10. GIT HYGIENE")
try:
    git_dir = WALLOS_ROOT / ".git"
    if git_dir.exists():
        check("Git repository initialized", True)
        
        # Check .gitignore covers key dirs
        gitignore = WALLOS_ROOT / ".gitignore"
        if gitignore.exists():
            content = gitignore.read_text()
            # Check for database and image paths
            db_ok = any(p in content for p in ["/db/", "app/db/"])
            logos_ok = any(p in content for p in ["logos/", "/images/uploads/logos/"])
            build_ok = any(p in content for p in ["/build/", "build/"])
            dist_ok = any(p in content for p in ["/dist/", "dist/"])
            check(".gitignore Contains app/db/", db_ok)
            check(".gitignore Contains logos/", logos_ok)
            check(".gitignore Contains build/", build_ok)
            check(".gitignore Contains dist/", dist_ok)
        else:
            check(".gitignore exists", False)
    else:
        check("Git repository initialized", False, "No .git directory found")
except Exception as e:
    check("Git hygiene", False, str(e))

# ============================================================================
# Summary
# ============================================================================
print()
print("=" * 60)
print(f"RESULTS: {passed} passed, {failed} failed")
print("=" * 60)

sys.exit(0 if failed == 0 else 1)