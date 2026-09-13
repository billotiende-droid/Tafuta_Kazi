import os
from pathlib import Path
from typing import List, Optional
from pydantic import DirectoryPath, Field, FilePath, HttpUrl
from pydantic_settings import BaseSettings, SettingsConfigDict

# Base directory setup ( __file__ is the current file path)
BASE_DIR = Path(__file__).resolve().parent

class Settings(BaseSettings):
    """Central configuration schema using Pydantic Settings v2.

    Auto-reads environment variables and validates types across the app runtime.
    """

    APP_NAME: str = Field(default="TafutaKaziAgent")
    ENV: str = Field(default="production")
    DEBUG: bool = Field(default=False, alias="APP_DEBUG")

    # --- Paths & Local Storage ---
    DATA_DIR: Path = Field(default=BASE_DIR / "data")
    OUTPUT_DIR: Path = Field(default=BASE_DIR / "output")
    DATABASE_PATH: Path = Field(default=BASE_DIR / "data" / "jobs.db")
    PROFILE_PATH: Path = Field(default=BASE_DIR / "data" / "profile.json")
    TYPST_TEMPLATE_PATH: Path = Field(
        default=BASE_DIR / "data" / "templates" / "template.typ"
    )

    # --- Target search Criteria ---
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
            "Web Developer"
            "UI UX Developer"

        ]
    )
    KEYWORDS: List[str] = Field(
        default=["Javascript", "React", "Nextjs", "Typescript", "Node.js", "Python", "FastAPI", "PostgreSQL", "LangGraph", "Docker", "Part-time", "contract", "full-time"]
    )
    IS_REMOTE_ONLY: bool = Field(default=True)
    MAX_JOBS_PER_RUN: int = Field(default=3)

    # --- LLM Provider Settings (Groq API Free Tier) ---
    GROQ_API_KEY: str = Field(
      ..., description="Groq API key required for fast Llama 3 inference"
    )

    LLM_MODEL: str = Field(
      default="openai/gpt-oss-120b",
      description="Groq free model deployment identifier",
    )
    LLM_TEMPERATURE: float = Field(default=0.2)

    # --- Telegram Bot Gateway ---
    TELEGRAM_BOT_TOKEN: str = Field(
      ..., description="Bot API Token issued by @BotFather"
    )
    TELEGRAM_CHAT_ID: int = Field(
      ..., description="Your private numeric Telegram user Chat ID"
    )

    # --- Scheduler Configuration ---
    CRON_INTERVAL_HOURS: int = Field(
      default=6, description="Execution interval in hours"
    )

    # Pydantic configuration Options
    model_config = SettingsConfigDict(
        env_file=str(BASE_DIR / ".env"),
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    def ensure_directories(self) -> None:
        """ Creates required data and output directories if they do not exist"""
        self.DATA_DIR.mkdir(parents=True, exist_ok=True)
        self.OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
        (self.DATA_DIR / "templates").mkdir(parents=True, exist_ok=True)


# instantiates singleton configuration instance
settings = Settings()
settings.ensure_directories()
