import asyncio
import logging
from typing import Any, Dict, List
import httpx
from config import settings
from ingestion.deduplicator import deduplicator

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Standard browser User-Agent to avoid client blocks on public endpoints
HTTP_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like"
        " Gecko) Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept": "application/json",
}