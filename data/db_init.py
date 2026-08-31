import sqlite3
from pathlib import Path
import sys
# Add project root directory to sys.path
sys.path.append(str(Path(__file__).resolve().parent.parent))

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

        # Processed Jobs Table (Deduplication)
        cursor.execute(""" 
            CREATE TABLE IF NOT EXISTS processed_jobs(
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                url_hash TEXT UNIQUE NOT NULL,
                job_title TEXT NOT NULL,
                company TEXT NOT NULL,
                job_url TEXT NOT NULL,
                source TEXT NOT NULL,
                scrapped_at DATETIME DEFAULT CURRENT_TIMESTAMP  

                );
   """ )

        # Application Log Table( Approval Table )
        cursor.execute(""" 
                 CREATE TABLE IF NOT EXISTS applications (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    url_hash TEXT UNIQUE NOT NULL,
                    job_title TEXT NOT NULL,
                    company TEXT NOT NULL,
                    pdf_path TEXT,
                    status TEXT CHECK(status IN ( 'PENDING', 'APPROVED', 'REJECTED')) NOT NULL DEFAULT 'PENDING',
                    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                    updated_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                    FOREIGN KEY (url_hash) REFERENCES processed_jobs(url_hash)ON DELETE CASCADE
                 );
    """ )

        # Create indexes for high frequency hash lookups
        cursor.execute(
            "CREATE INDEX IF NOT EXISTS idx_processed_jobs_hash ON"
            " processed_jobs(url_hash);"
        )

        cursor.execute(
            "CREATE INDEX IF NOT EXISTS idx_applications_status ON"
            " applications(status);"
        )

        conn.commit()
        print(f"SQLite database initialized at {db_path}")

if __name__ == "__main__":
    init_sqlite_db()
