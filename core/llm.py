import json
import logging
import re
from pathlib import Path
from typing import Any, Dict, List
from langchain_core.output_parsers import PydanticOutputParser
from langchain_core.prompts import ChatPromptTemplate
from langchain_groq import ChatGroq
from pydantic import BaseModel, Field
from config import settings

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Explicit JSON schema injected directly into the prompt — no PydanticOutputParser format_instructions
JSON_SCHEMA = """
{{
  "professional_summary": "<string: tailored executive summary>",
  "experiences": [
    {{
      "role": "<string: job title>",
      "company": "<string: company name>",
      "dates": "<string: employment duration>",
      "location": "<string: location or Remote>",
      "bullet_points": ["<string: achievement 1>", "<string: achievement 2>", "<string: achievement 3>"]
    }}
  ]
}}
"""


class TailoredExperience(BaseModel):
    role: str = Field(description="Job title")
    company: str = Field(description="Company name")
    dates: str = Field(description="Employment duration string")
    location: str = Field(description="Location or Remote")
    bullet_points: List[str] = Field(
        description="3-4 achievement bullet points optimized for target role keywords"
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
        self.parser = PydanticOutputParser(pydantic_object=TailoredCVContent)

        # No response_format or tool-calling — plain chat completion with explicit JSON prompt
        self.llm = ChatGroq(
            groq_api_key=settings.GROQ_API_KEY,
            model=settings.LLM_MODEL,
            temperature=settings.LLM_TEMPERATURE,
        )

    def _load_profile(self, path: Path) -> Dict[str, Any]:
        """Loads candidate master profile JSON."""
        if not path.exists():
            raise FileNotFoundError(
                f"Master profile file missing at {path}. Please populate data/profile.json."
            )
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)

    @staticmethod
    def _strip_fences(text: str) -> str:
        """Strips <think> reasoning blocks and markdown code fences before parsing."""
        text = re.sub(r"<think>.*?</think>", "", text, flags=re.DOTALL)
        text = text.strip()
        text = re.sub(r"^```(?:json)?\s*", "", text)
        text = re.sub(r"\s*```$", "", text)
        return text.strip()

    @staticmethod
    def _unwrap_json(text: str) -> str:
        """If the model wraps the payload under a single top-level key, unwrap it."""
        try:
            parsed = json.loads(text)
            if isinstance(parsed, dict):
                # Check if expected keys are present directly
                if "professional_summary" in parsed and "experiences" in parsed:
                    return text
                # Search one level deeper for a wrapped payload
                for v in parsed.values():
                    if isinstance(v, dict) and "professional_summary" in v and "experiences" in v:
                        return json.dumps(v)
        except (json.JSONDecodeError, AttributeError):
            pass
        return text

    def generate_tailored_cv_data(self, job_description: str) -> Dict[str, Any]:
        """Evaluates target job description against profile data and returns structured tailored content."""
        prompt_template = ChatPromptTemplate.from_messages([
            (
                "system",
                (
                    "You are an expert Executive Resume Writer and Systems Architect.\n"
                    "Your objective is to tailor the candidate's master profile to match the provided Job Description.\n\n"
                    "CRITICAL RULES:\n"
                    "1. NEVER hallucinate experience, credentials, or technologies not present in the Candidate Master Profile.\n"
                    "2. Emphasize matching technical skills, frameworks, and quantifiable results.\n"
                    "3. Ensure bullet points begin with strong action verbs and highlight relevant achievements.\n"
                    "4. You MUST respond with ONLY a valid JSON object. No preamble, no explanation, no markdown fences.\n"
                    "5. Bullet points MUST be plain text only — no brackets [], parentheses (), markdown, or special characters.\n"
                    "6. The JSON object MUST follow this exact schema:\n"
                    f"{JSON_SCHEMA}"
                ),
            ),
            (
                "human",
                "Candidate Master Profile:\n{master_profile}\n\nTarget Job Description:\n{job_description}\n\n"
                "Respond with the JSON object only.",
            ),
        ])

        formatted_prompt = prompt_template.format_messages(
            master_profile=json.dumps(self.profile_data, indent=2),
            job_description=job_description,
        )

        try:
            logger.info(f"Invoking {settings.LLM_MODEL} for CV tailoring...")
            raw_response = self.llm.invoke(formatted_prompt)
            logger.debug(f"Raw LLM response: {raw_response.content[:500]}")
            clean_content = self._strip_fences(raw_response.content)
            clean_content = self._unwrap_json(clean_content)
            structured_response: TailoredCVContent = self.parser.parse(clean_content)

            return {
                "candidate_info": self.profile_data.get("personal_info", {}),
                "skills": [
                    skill
                    for skill_list in self.profile_data.get("technical_skills", {}).values()
                    for skill in skill_list
                ],
                "professional_summary": structured_response.professional_summary,
                "experiences": [
                    exp.model_dump() for exp in structured_response.experiences
                ],
            }

        except Exception as e:
            logger.error(f"Error during LLM tailoring invocation: {e}")
            raise e


# Utility engine instance
cv_tailor_engine = CVTailoringEngine()
