"""
desktop/ - Wallos Desktop Integration Package

This package provides:
- Managed PHP runtime (php_server.py)
- Cron daemon (scheduler.py)  
- Database backup/restore (backup_manager.py)
- Data management (data_manager.py)
- Main application entry point (app.py)
"""

from pathlib import Path
import sys

# Ensure WALLOS_ROOT is set correctly regardless of how this package is imported
DESKTOP_DIR = Path(__file__).parent
WALLOS_ROOT = DESKTOP_DIR.parent

# Update paths in submodules if needed
sys.path.insert(0, str(DESKTOP_DIR))