"""
Ingestion module for scraping external job boards and managing URL deduplication.
"""

from ingestion.deduplicator import JobDeduplicator, deduplicator
from ingestion.scrappers import RemoteJobScrapper, job_scraper, scrape_all_new_jobs

__all__ = [
    "RemoteJobScrapper",
    "job_scraper",
    "scrape_all_new_jobs",
    "JobDeduplicator",
    "deduplicator",
]