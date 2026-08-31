"""
Ingestion module for scraping external job boards and managing URL deduplication.
"""

from ingestion.deduplicator import ApplicationDeduplicator, deduplicator
from ingestion.scrappers import RemoteJobScrapper, job_scraper

__all__ = [
    "RemoteJobScrapper",
    "job_scraper",
    "ApplicationDeduplicator",
    "deduplicator",
]