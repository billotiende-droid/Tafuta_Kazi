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

class RemoteJobScrapper:
    """Asynchronous scrapper pulling remote jobs from free REST endpoints."""

    def __init__(self):
        self.timeout = httpx.Timeout(15.0, connect=5.0)

    async def fetch_remoteok_jobs(self) -> List[Dict[str, Any]]:
        """ Fetches and parses oublic jobs from RemoteOK API.""" 
        url = "https://remoteok.io/api"
        jobs: List[Dict[str, Any]] = []

        try:
            async with httpx.AsyncClient(
                headers=HTTP_HEADERS, timeout=self.timeout, follow_redirects=True
            )  as client:
                response = await client.get(url)
                if response.status_code == 200:
                    data = response.json() 
                    # First element in RemoteOK JSON payload is API metadata
                    job_items = data[1:] if isinstance(data,  list) else []

                    for item in job_items:
                        title = item.get("position", "")
                        company = item.get("company", "")
                        job_url = item.get("url", "")
                        description = item.get("description", "")
                        tags = [t.lower() for t in item.get("tags", [])]

                        # Relevancy Filter
                        if self._is_relevant_job(title, description, tags):
                            jobs.append({
                                "title": title,
                                "company": company,
                                "url": job_url,
                                "source": "remoteok",
                                "description": description,
                                "tags": tags,
                            
                            })
                        else:
                            logger.warning(
                                f"RemoteOK API returned status code: {response.status_code}"
                            ) 
        except Exception as e:
            logger.error(f"Error fetching RemoteOK jobs: {e}")

        return jobs 

                 

async def fetch_jobicy_jobs(self) -> List[Dict[str, Any]]:
    """Fetches public remote dev jobs from Jobicy API."""
    url = "https://jobicy.com/api/v2/remote-jobs?count=20&geo=apac,emea,latam,usa"
    jobs: List[Dict[str, Any]] = []

    try:
        async with httpx.AsyncClient(
            headers=HTTP_HEADERS, timeout=self.timeout, follow_redirects=True
        ) as client:
            response = await client.get(url)
            if response.status_code == 200:
                data = response.json()
                job_items = data.get("data", [])

                for item in job_items:
                    title = item.get("job_title", "")
                    company = item.get("company_name", "")
                    job_url = item.get("job_url", "")
                    description = item.get("job_description", "")
                    tags = [t.lower() for t in item.get("tags", [])]

                    if self._is_relevant_job(title, description, []):
                        jobs.append({
                            "title": title,
                            "company": company,
                            "url": job_url,
                            "source": "Jobicy",
                            "description": description,
                            "tags": tags,
                        })
                    else:
                        logger.warning(
                            f"Jobicy API returned status code: {response.status_code}"
                        )
    except Exception as e:
        logger.error(f"Error fetching Jobicy jobs: {e}")
        return jobs 