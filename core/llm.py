import json
import logging
from pathlib import Path
from typing import Any, Dict, List
from langchain_core.prompts import ChatPromptTemplate
from langchain_groq import ChatGroq
from pydantic import BaseModel, Field
from config import settings

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Pydantic Schemas for Structured JSON Output from LLM
class TailoredExperience(BaseModel):
  role: str = Field(description="Your previous job title")
  company: str = Field(description="Company name")
  dates: str = Field(description="Employment duration string")
  location: str = Field(description="Location or Remote")
  bullet_points: List[str] = Field(
      description=(
        "3-4 achievement bullet points optimized for target role keywords"
      )
  )

class TailoredCVContent(BaseModel):
  professional_summary: str = Field(
    description="Tailored executive summary matching target job description"
  )
  experiences: List[TailoredExperience] = Field(
    description="List of tailored experience sections" 
  )

class CVTailoringEngine:
  """Engine for processing job descriptions and tailoring CV bullet points."""

  def __init__(self, profile_path: Path = settings.PROFILE_PATH):
    self.profile_data = self._load_profile(profile_path)

    # Initialize Groq LLM with forced structured JSON output
    self.llm = ChatGroq(
        groq_api_key=settings.GROQ_API_KEY,
        model_name=settings.LLM_MODEL,
        temperature=settings.LLM_TEMPERATURE,
    ).with_structured_output(TailoredCVContent)

  def _load_profile(self, path: Path) -> Dict[str, Any]:
    """Loads candidate master profile JSON."""
    if not path.exists():
      raise FileNotFoundError(
          f"Master profile file missing at {path}. Please populate"
          " data/profile.json."
      )
    with open(path, "r", encoding="utf-8") as f:
      return json.load(f)  