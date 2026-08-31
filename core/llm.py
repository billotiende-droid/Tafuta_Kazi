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

def generate_tailored_cv_data(self, job_description: str) -> Dict[str, Any]:
    """Evaluates target job description against profile data and returns structured tailored content."""
    prompt_template = ChatPromptTemplate.from_messages([
        (
            "system",
            (
                "You are an expert Executive Resume Writer and Systems"
                " Architect. Your objective is to tailor the candidate's master"
                " profile to match the provided Job Description (JD).\n\n"
                "CRITICAL RULES:\n"
                "1. NEVER hallucinate experience, credentials, or technologies"
                " not present in the Candidate Master Profile.\n"
                "2. Emphasize matching technical skills, frameworks, and"
                " quantifiable results.\n"
                "3. Ensure experience bullet points begin with strong action"
                " verbs and highlight relevant achievements.\n"
                "4. Output MUST conform strictly to the required JSON schema."
            ),
        ),
        (
            "human",
            """Candidate Master Profile:
{master_profile}

Target Job Description:
{job_description}

Generate the tailored professional summary and optimized bullet points.""",
        ),
    ])

    formatted_prompt = prompt_template.format_messages(
        master_profile=json.dumps(self.profile_data, indent=2),
        job_description=job_description,
    )

    try:
      logger.info("Invoking Groq Llama 3 for CV tailoring...")
      structured_response: TailoredCVContent = self.llm.invoke(formatted_prompt)

      # Merge candidate contact info with tailored dynamic output
      result = {
          "candidate_info": self.profile_data.get("candidate_info", {}),
          "skills": self.profile_data.get("skills", []),
          "professional_summary": structured_response.professional_summary,
          "experiences": [
              exp.model_dump() for exp in structured_response.experiences
          ],
      }
      return result

    except Exception as e:
      logger.error(f"Error during LLM tailoring invocation: {e}")
      raise e 

# Utility engine instance
cv_tailor_engine = CVTailoringEngine()    