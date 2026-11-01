import asyncio
import json
import logging
from pathlib import Path
from typing import Any, Dict, List, Set
import httpx
from config import settings
from ingestion.deduplicator import deduplicator

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

HTTP_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like"
        " Gecko) Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept": "application/json",
}

# Target boards for ATS endpoints (Greenhouse & Lever)
GREENHOUSE_BOARDS = ["stripe", "gitlab", "canonical", "automattic"]
LEVER_BOARDS = ["postman", "vercel", "cloudflare"]


def _build_profile_keywords(profile_path: Path) -> Set[str]:
    """Derives a flat lowercase keyword set from profile.json target roles and tech skills."""
    try:
        with open(profile_path, "r", encoding="utf-8") as f:
            profile = json.load(f)
    except Exception as e:
        logger.warning(f"Could not load profile.json for keyword extraction: {e}")
        return set()

    keywords: Set[str] = set()

    for role in profile.get("meta", {}).get("target_roles", []):
        keywords.update(w.lower() for w in role.split())

    skills = profile.get("technical_skills", {})
    for skill_list in skills.values():
        for skill in skill_list:
            keywords.add(skill.lower())

    return keywords


_PROFILE_KEYWORDS: Set[str] = _build_profile_keywords(settings.PROFILE_PATH)

_TARGET_TITLE_KEYWORDS = [
    "software", "developer", "engineer", "fullstack", "full-stack", "full stack",
    "frontend", "front-end", "backend", "back-end", "python", "react", "next.js",
    "node", "fastapi", "typescript", "javascript", "web developer", "web engineer",
    "ai engineer", "ml engineer", "systems engineer", "devops", "cloud engineer",
    "junior", "associate", "entry level", "entry-level", "graduate",
]

_BLOCKLIST_TITLE_KEYWORDS = [
    "maintenance", "technician", "estimator", "shunter", "driver", "cleaner",
    "warehouse", "logistics", "supply chain", "building", "construction",
    "equipment", "mechanical", "electrical", "plumber", "hvac",
]

_SENIORITY_BLOCKLIST = [
    "principal", "staff", "lead", "senior", " sr ", "sr.", "director",
    "vp ", "vice president", "head of", "manager", "architect",
]

_NON_ENGLISH_TITLE_FRAGMENTS = [
    "desarrollador", "développeur", "ingénieur", "ingeniero", "programmeur",
    "entwickler", "programador", "analista",
]


class RemoteJobScrapper:
    """Asynchronous scrapper pulling remote jobs from free REST and ATS endpoints."""

    def __init__(self):
        self.timeout = httpx.Timeout(15.0, connect=5.0)

    async def fetch_remoteok_jobs(self) -> List[Dict[str, Any]]:
        """Fetches RemoteOK feed."""
        url = "https://remoteok.com/api"
        jobs: List[Dict[str, Any]] = []
        try:
            async with httpx.AsyncClient(headers=HTTP_HEADERS, timeout=self.timeout, follow_redirects=True) as client:
                response = await client.get(url)
                if response.status_code == 200:
                    data = response.json()
                    job_items = data[1:] if isinstance(data, list) else []
                    for item in job_items:
                        title = item.get("position", "")
                        company = item.get("company", "")
                        job_url = item.get("url", "")
                        description = item.get("description", "")
                        tags = [t.lower() for t in item.get("tags", [])]
                        if self._is_relevant_job(title, description, tags):
                            jobs.append({
                                "title": title, "company": company, "url": job_url,
                                "source": "remoteok", "description": description, "tags": tags,
                            })
        except Exception as e:
            logger.error(f"Error fetching RemoteOK jobs: {e}")
        return jobs

    async def fetch_jobicy_jobs(self) -> List[Dict[str, Any]]:
        """Fetches Jobicy feed."""
        url = "https://jobicy.com/api/v2/remote-jobs?count=50"
        jobs: List[Dict[str, Any]] = []
        try:
            async with httpx.AsyncClient(headers=HTTP_HEADERS, timeout=self.timeout, follow_redirects=True) as client:
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
                        if self._is_relevant_job(title, description, tags):
                            jobs.append({
                                "title": title, "company": company, "url": job_url,
                                "source": "Jobicy", "description": description, "tags": tags,
                            })
        except Exception as e:
            logger.error(f"Error fetching Jobicy jobs: {e}")
        return jobs

    async def fetch_arbeitnow_jobs(self) -> List[Dict[str, Any]]:
        """Fetches Arbeitnow feed."""
        url = "https://www.arbeitnow.com/api/v1/jobs"
        jobs: List[Dict[str, Any]] = []
        try:
            async with httpx.AsyncClient(headers=HTTP_HEADERS, timeout=self.timeout, follow_redirects=True) as client:
                response = await client.get(url)
                if response.status_code == 200:
                    data = response.json().get("data", [])
                    for item in data:
                        title = item.get("title", "")
                        company = item.get("company_name", "")
                        job_url = item.get("url", "")
                        description = item.get("description", "")
                        tags = [t.lower() for t in item.get("tags", [])]
                        if self._is_relevant_job(title, description, tags):
                            jobs.append({
                                "title": title, "company": company, "url": job_url,
                                "source": "Arbeitnow", "description": description, "tags": tags,
                            })
        except Exception as e:
            logger.error(f"Error fetching Arbeitnow jobs: {e}")
        return jobs

    async def fetch_remotive_jobs(self) -> List[Dict[str, Any]]:
        """Fetches Remotive software development feed."""
        url = "https://remotive.com/api/remote-jobs?category=software-dev"
        jobs: List[Dict[str, Any]] = []
        try:
            async with httpx.AsyncClient(headers=HTTP_HEADERS, timeout=self.timeout, follow_redirects=True) as client:
                response = await client.get(url)
                if response.status_code == 200:
                    data = response.json().get("jobs", [])
                    for item in data:
                        title = item.get("title", "")
                        company = item.get("company_name", "")
                        job_url = item.get("url", "")
                        description = item.get("description", "")
                        tags = [t.lower() for t in item.get("tags", [])]
                        if self._is_relevant_job(title, description, tags):
                            jobs.append({
                                "title": title, "company": company, "url": job_url,
                                "source": "Remotive", "description": description, "tags": tags,
                            })
        except Exception as e:
            logger.error(f"Error fetching Remotive jobs: {e}")
        return jobs

    async def fetch_hacker_news_jobs(self) -> List[Dict[str, Any]]:
        """Fetches job listings directly from Hacker News Official Job IDs."""
        url = "https://hacker-news.firebaseio.com/v0/jobstories.json"
        jobs: List[Dict[str, Any]] = []
        try:
            async with httpx.AsyncClient(headers=HTTP_HEADERS, timeout=self.timeout, follow_redirects=True) as client:
                response = await client.get(url)
                if response.status_code == 200:
                    job_ids = response.json()[:15]  # Limit to top 15 recent HN job posts
                    for item_id in job_ids:
                        item_url = f"https://hacker-news.firebaseio.com/v0/item/{item_id}.json"
                        item_res = await client.get(item_url)
                        if item_res.status_code == 200:
                            item = item_res.json()
                            if not item:
                                continue
                            title = item.get("title", "")
                            description = item.get("text", "")
                            job_url = item.get("url", f"https://news.ycombinator.com/item?id={item_id}")
                            if self._is_relevant_job(title, description, []):
                                jobs.append({
                                    "title": title, "company": "HN Startup", "url": job_url,
                                    "source": "HackerNews", "description": description, "tags": ["hn"],
                                })
        except Exception as e:
            logger.error(f"Error fetching Hacker News jobs: {e}")
        return jobs

    async def fetch_greenhouse_jobs(self) -> List[Dict[str, Any]]:
        """Queries public Greenhouse ATS JSON endpoints for target company boards."""
        jobs: List[Dict[str, Any]] = []
        async with httpx.AsyncClient(headers=HTTP_HEADERS, timeout=self.timeout, follow_redirects=True) as client:
            for board in GREENHOUSE_BOARDS:
                url = f"https://boards-api.greenhouse.io/v1/boards/{board}/jobs"
                try:
                    response = await client.get(url)
                    if response.status_code == 200:
                        data = response.json().get("jobs", [])
                        for item in data:
                            title = item.get("title", "")
                            job_url = item.get("absolute_url", "")
                            if self._is_relevant_job(title, "", []):
                                jobs.append({
                                    "title": title, "company": board.capitalize(), "url": job_url,
                                    "source": f"Greenhouse ({board})", "description": title, "tags": ["ats"],
                                })
                except Exception as e:
                    logger.error(f"Error fetching Greenhouse board {board}: {e}")
        return jobs

    async def fetch_lever_jobs(self) -> List[Dict[str, Any]]:
        """Queries public Lever ATS JSON endpoints for target company boards."""
        jobs: List[Dict[str, Any]] = []
        async with httpx.AsyncClient(headers=HTTP_HEADERS, timeout=self.timeout, follow_redirects=True) as client:
            for board in LEVER_BOARDS:
                url = f"https://api.lever.co/v0/postings/{board}?mode=json"
                try:
                    response = await client.get(url)
                    if response.status_code == 200:
                        data = response.json()
                        for item in data:
                            title = item.get("text", "")
                            job_url = item.get("hostedUrl", "")
                            description = item.get("descriptionPlain", "")
                            if self._is_relevant_job(title, description, []):
                                jobs.append({
                                    "title": title, "company": board.capitalize(), "url": job_url,
                                    "source": f"Lever ({board})", "description": description, "tags": ["ats"],
                                })
                except Exception as e:
                    logger.error(f"Error fetching Lever board {board}: {e}")
        return jobs

    def _is_relevant_job(
            self, title: str, description: str, tags: List[str]
    ) -> bool:
        """Three-gate relevance check."""
        title_lower = title.lower()
        combined_text = f"{title} {description} {' '.join(tags)}".lower()

        if any(kw in title_lower for kw in _BLOCKLIST_TITLE_KEYWORDS):
            return False
        if any(kw in title_lower for kw in _SENIORITY_BLOCKLIST):
            return False
        if any(fragment in title_lower for fragment in _NON_ENGLISH_TITLE_FRAGMENTS):
            return False
        if not any(kw in title_lower for kw in _TARGET_TITLE_KEYWORDS):
            return False

        profile_match = any(kw in combined_text for kw in _PROFILE_KEYWORDS)
        keyword_match = any(kw.lower() in combined_text for kw in settings.KEYWORDS)

        return profile_match or keyword_match


async def scrape_all_new_jobs() -> List[Dict[str, Any]]:
    """Aggregates jobs across all sources and filters out previously seen duplicates."""
    logger.info("Starting ingestion sweep across job providers..")

    # Schedule all 7 scraper tasks concurrently
    tasks = [
        job_scraper.fetch_remoteok_jobs(),
        job_scraper.fetch_jobicy_jobs(),
        job_scraper.fetch_arbeitnow_jobs(),
        job_scraper.fetch_remotive_jobs(),
        job_scraper.fetch_hacker_news_jobs(),
        job_scraper.fetch_greenhouse_jobs(),
        job_scraper.fetch_lever_jobs(),
    ]

    results = await asyncio.gather(*tasks, return_exceptions=True)
    all_raw_jobs = [
        job for sublist in results if isinstance(sublist, list) for job in sublist
    ]

    new_jobs: List[Dict[str, Any]] = []
    for job in all_raw_jobs:
        if not deduplicator.is_duplicate(job["url"]):
            url_hash = deduplicator.register_job(
                job_title=job["title"],
                company=job["company"],
                job_url=job["url"],
                source=job["source"],
            )
            if url_hash:
                job["url_hash"] = url_hash
                new_jobs.append(job)

            if len(new_jobs) >= settings.MAX_JOBS_PER_RUN:
                logger.info(
                    f"Reached Maximum jobs limit per run ({settings.MAX_JOBS_PER_RUN})."
                )
                break

    logger.info(f"Ingestion complete. Discovered {len(new_jobs)} new jobs.")
    return new_jobs


job_scraper = RemoteJobScrapper()