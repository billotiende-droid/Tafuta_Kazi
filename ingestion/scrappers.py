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


def _build_profile_keywords(profile_path: Path) -> Set[str]:
    """Derives a flat lowercase keyword set from profile.json target roles and tech skills."""
    try:
        with open(profile_path, "r", encoding="utf-8") as f:
            profile = json.load(f)
    except Exception as e:
        logger.warning(f"Could not load profile.json for keyword extraction: {e}")
        return set()

    keywords: Set[str] = set()

    # Target roles from meta
    for role in profile.get("meta", {}).get("target_roles", []):
        keywords.update(w.lower() for w in role.split())

    # All tech skill values (languages, frameworks, tools)
    skills = profile.get("technical_skills", {})
    for skill_list in skills.values():
        for skill in skill_list:
            keywords.add(skill.lower())

    return keywords


# Build once at module load — avoids re-reading on every request
_PROFILE_KEYWORDS: Set[str] = _build_profile_keywords(settings.PROFILE_PATH)

# Title-level pre-filter — requires an explicit software/tech signal in the job title
_TARGET_TITLE_KEYWORDS = [
    "software", "developer", "engineer", "fullstack", "full-stack", "full stack",
    "frontend", "front-end", "backend", "back-end", "python", "react", "next.js",
    "node", "fastapi", "typescript", "javascript", "web developer", "web engineer",
    "ai engineer", "ml engineer", "systems engineer", "devops", "cloud engineer",
    "junior", "associate", "entry level", "entry-level", "graduate",
]

# Explicit blocklist — titles containing these are rejected even if they pass keyword match
_BLOCKLIST_TITLE_KEYWORDS = [
    "maintenance", "technician", "estimator", "shunter", "driver", "cleaner",
    "warehouse", "logistics", "supply chain", "building", "construction",
    "equipment", "mechanical", "electrical", "plumber", "hvac",
]

# Seniority blocklist — candidate targets associate/mid roles, not principal/staff/lead
_SENIORITY_BLOCKLIST = [
    "principal", "staff", "lead", "senior", " sr ", "sr.", "director",
    "vp ", "vice president", "head of", "manager", "architect",
]

# Non-English title fragments — reject foreign-language listings
_NON_ENGLISH_TITLE_FRAGMENTS = [
    "desarrollador", "développeur", "ingénieur", "ingeniero", "programmeur",
    "entwickler", "programador", "analista",
]


class RemoteJobScrapper:
    """Asynchronous scrapper pulling remote jobs from free REST endpoints."""

    def __init__(self):
        self.timeout = httpx.Timeout(15.0, connect=5.0)

    async def fetch_remoteok_jobs(self) -> List[Dict[str, Any]]:
        """Fetches broad RemoteOK feed and filters Python-side against profile keywords."""
        url = "https://remoteok.com/api"
        jobs: List[Dict[str, Any]] = []

        try:
            async with httpx.AsyncClient(
                headers=HTTP_HEADERS, timeout=self.timeout, follow_redirects=True
            ) as client:
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
        """Fetches broad Jobicy feed and filters Python-side against profile keywords."""
        url = "https://jobicy.com/api/v2/remote-jobs?count=50"
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

                        if self._is_relevant_job(title, description, tags):
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

    def _is_relevant_job(
            self, title: str, description: str, tags: List[str]
    ) -> bool:
        """Three-gate relevance check: title keywords → profile keywords → config keywords."""
        title_lower = title.lower()
        combined_text = f"{title} {description} {' '.join(tags)}".lower()

        # Gate 1: reject blocklisted non-tech titles immediately
        if any(kw in title_lower for kw in _BLOCKLIST_TITLE_KEYWORDS):
            return False

        # Gate 1b: reject over-seniority roles the candidate is not targeting
        if any(kw in title_lower for kw in _SENIORITY_BLOCKLIST):
            return False

        # Gate 1c: reject non-English job titles
        if any(fragment in title_lower for fragment in _NON_ENGLISH_TITLE_FRAGMENTS):
            return False

        # Gate 1d: must have at least one software/tech signal in title
        if not any(kw in title_lower for kw in _TARGET_TITLE_KEYWORDS):
            return False

        # Gate 2: profile-derived keyword match across full combined text
        profile_match = any(kw in combined_text for kw in _PROFILE_KEYWORDS)

        # Gate 3: config keyword match (tech stack, contract types)
        keyword_match = any(kw.lower() in combined_text for kw in settings.KEYWORDS)

        return profile_match or keyword_match

async def scrape_all_new_jobs() -> List[Dict[str, Any]]:
    """ Aggregates jobs across all sources and filters out previously seen duplicates."""
    logger.info("Starting ingestion sweep across job providers..")

    remoteok_task = job_scraper.fetch_remoteok_jobs()
    jobicy_task = job_scraper.fetch_jobicy_jobs()

    results = await asyncio.gather(remoteok_task, jobicy_task, return_exceptions=True)
    all_raw_jobs = [job for sublist in results for job in sublist]

    new_jobs: List[Dict[str, Any]] = []
    for job in all_raw_jobs:
        if not deduplicator.is_duplicate(job["url"]):
            url_hash = deduplicator.register_job(
                job_title=job["title"],
                company=job["company"],
                job_url=job["url"],
                source=job["source"]
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

# Instantiable scrapper helper
job_scraper = RemoteJobScrapper()
