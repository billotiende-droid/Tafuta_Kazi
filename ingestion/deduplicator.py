import hashlib
import sqlite3
from pathlib import Path
from typing import Optional
from config import settings


def generate_url_hash(url: str) -> str:
    """ Generate a normalized MD5 hash for a given job URL to ensure unique tracking."""
    # Strip query parameters, trailing slashes, and lower-case to standardize hashes
    normalized_url = url.split("?")[0].rstrip("/").lower()
    return hashlib.md5(normalized_url.encode("utf-8")).hexdigest()

class JobDeduplicator:
    """ Manages job deduplication checks and SQLite state persistence."""

    def __init__(self, db_path: Path = settings.DATABASE_PATH):
        self.db_path = db_path

    def get_connection(self) -> sqlite3.Connection:
        """ Helper method to open a database connection with dictionary-like rows.""" 
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        return conn


    def is_duplicate(self, url: str) -> bool:
        """ Checks if a job URL has already been processed or logged in SQLite.
        Returns True if duplicate, False if new
        """

        url_hash = generate_url_hash(url)

        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                "SELECT 1 FROM processed_jobs WHERE url_hash = ? LIMIT 1;",
                (url_hash,),
            )

            result = cursor.fetchone()

        return result is not None

    def register_job(self, job_title: str, company: str, job_url: str, source: str) -> Optional[str]:
        """ Logs a newly discovered job in the 'processed_job' table and prepares a 'PENDING' entry in 'applications'.
             
        Returns the generated url_hash if successful, or None if it was already duplicate.
        """
        url_hash = generate_url_hash(job_url)

        if self.is_duplicate(job_url):
            print(f"[⇄] Skipping duplicate job: {job_title} at {company}")
            return None

        try:
            with self.get_connection() as conn:
                cursor = conn.cursor()

                # Insert into processed_jobs table
                cursor.execute(
                    """
                    INSERT INTO processed_jobs (url_hash, job_title, company, job_url, source)
                    VALUES (?, ?, ?, ?, ?);
                """,
                (url_hash, job_title, company, job_url, source),
            )
                # initialize pending application tracking record
                cursor.execute(
                    """ 
                        INSERT INTO  applications (url_hash, job_title, company, status)
                        VALUES (?, ?, ?, 'PENDING'); 

                     """,
                    (url_hash, job_title, company)
                )

                conn.commit()

                print(f"[✓] Registered new job: {job_title} at {company}")
                return url_hash

        except sqlite3.IntegrityError:
            # Safe guard against race conditions or unexpected duplicates
            print(f"[⇄] Integrity check caught duplicate: {url_hash}")
            return None  

        
    def update_application_status(
            self, url_hash: str, status: str, pdf_path: Optional[str] = None
    ) -> bool:
        """ Update status ('APPROVED' or 'REJECTED') and final PDF path in applications table."""
        valid_statuses = ('PENDING', 'APPROVED', 'REJECTED')
        if status not in valid_statuses:
            raise ValueError(f"Invalid status. Must be one of {valid_statuses}"
    )
        
        with self.get_connection() as conn:
            cursor = conn.cursor()
            if pdf_path:
                cursor.execute(
                    """ 
                    UPDATE applications 
                    SET status = ?, pdf_path = ?, updated_at = CURRENT_TIMESTAMP
                    WHERE url_hash = ?;
                    """,
                    (status, pdf_path, url_hash)
                )
            else:
                cursor.execute(
                    """ 
                    UPDATE applications 
                    SET status = ?, updated_at = CURRENT_TIMESTAMP
                    WHERE url_hash = ?;
                    """,
                    (status, url_hash)
                )

            conn.commit()
            return cursor.rowcount > 0

# Utility instance for direct import across modules
deduplicator = JobDeduplicator()

         

                
