import os
from pathlib import Path
from typing import List, Literal, Optional
from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

# Base directory is the directory containing this file (project root)
BASE_DIR = Path(__file__).resolve().parent


class Settings(BaseSettings):
    """Central configuration schema using Pydantic Settings v2.

    Auto-reads environment variables and validates types across the app runtime.
    Local dev: values come from .env file.
    Cloud Run: values come from environment variables injected by Secret Manager.
    """

    APP_NAME: str = Field(default="TafutaKaziAgent")
    ENV: str = Field(default="production")
    DEBUG: bool = Field(default=False, alias="APP_DEBUG")

    # --- Deployment Mode ---
    # "polling"  → local development: bot uses long-polling, APScheduler drives sweeps
    # "webhook"  → Cloud Run: Telegram pushes updates via HTTPS, Cloud Scheduler drives sweeps
    DEPLOYMENT_MODE: Literal["polling", "webhook"] = Field(default="polling")

    # Cloud Run injects PORT automatically. Must listen on this value.
    # Locally this is unused (polling mode has no HTTP server).
    PORT: int = Field(default=8080)

    # Public HTTPS URL of the Cloud Run service — required in webhook mode so
    # Telegram knows where to push updates. Leave empty for local polling.
    # Example: https://tafuta-kazi-abc123-uc.a.run.app
    WEBHOOK_URL: str = Field(default="")

    # --- Paths & Local Storage ---
    DATA_DIR: Path = Field(default=BASE_DIR / "data")
    OUTPUT_DIR: Path = Field(default=BASE_DIR / "output")
    DATABASE_PATH: Path = Field(default=BASE_DIR / "data" / "jobs.db")
    PROFILE_PATH: Path = Field(default=BASE_DIR / "data" / "profile.json")
    TYPST_TEMPLATE_PATH: Path = Field(
        default=BASE_DIR / "data" / "templates" / "template.typ"
    )

    # --- Target Search Criteria ---
    JOB_TITLES: List[str] = Field(
        default=[
            "Associate Frontend Developer",
            "Frontend Developer",
            "Junior React Developer",
            "Python Developer",
            "Backend Engineer",
            "Junior Fullstack Developer",
            "Software Engineer",
            "AI Systems Engineer",
            "Web Developer",
            "UI UX Developer",
        ]
    )
    KEYWORDS: List[str] = Field(
        default=[
            "Javascript", "React", "Nextjs", "Typescript", "Node.js",
            "Python", "FastAPI", "PostgreSQL", "LangGraph", "Docker",
            "Part-time", "contract", "full-time",
        ]
    )
    IS_REMOTE_ONLY: bool = Field(default=True)
    MAX_JOBS_PER_RUN: int = Field(default=3)

    # --- LLM Provider Settings (Groq API) ---
    GROQ_API_KEY: str = Field(..., description="Groq API key")
    LLM_MODEL: str = Field(default="openai/gpt-oss-120b")
    LLM_TEMPERATURE: float = Field(default=0.2)

    # --- Telegram Bot Gateway ---
    TELEGRAM_BOT_TOKEN: str = Field(..., description="Bot token from @BotFather")
    TELEGRAM_CHAT_ID: int = Field(..., description="Your numeric Telegram user ID")

    # --- Scheduler (polling mode only — webhook mode uses Cloud Scheduler) ---
    CRON_INTERVAL_HOURS: int = Field(default=6)

    # Pydantic v2 config: reads .env locally; on Cloud Run the file won't exist
    # and Pydantic falls back to real environment variables automatically.
    model_config = SettingsConfigDict(
        env_file=str(BASE_DIR / ".env"),
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    def ensure_directories(self) -> None:
        """Creates required data and output directories if they do not exist."""
        self.DATA_DIR.mkdir(parents=True, exist_ok=True)
        self.OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
        (self.DATA_DIR / "templates").mkdir(parents=True, exist_ok=True)


# Singleton — imported everywhere else in the codebase
settings = Settings()
settings.ensure_directories()
