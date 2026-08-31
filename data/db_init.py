import sqlite3
from pathlib import Path
from config import settings

def init_sqlite_db(db_path: Path = settings.DATABASE_PATH) -> None:
    """ Initializes the SQLite database schemas for job tracking and applications log."""

    # Ensure target parent directory exists
    db_path.parent.mkdir(parents=True, exist_ok=True)

    #Connects to SQLite(Creates File if missing)
    with sqlite3.connect(db_path) as conn:
        cursor = conn.cursor()

        # Enable Write-Ahead Logging (WAL) mode for better concurrent read/write performance
        cursor.execute("PRAGMA journal_mode=WAL;")
        