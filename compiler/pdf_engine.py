import logging
from pathlib import Path
from typing import Any, Dict, List
import typst
from config import settings

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


class TypstCompilerEngine:
    """Engine for converting structured candidate and tailored CV data into ATS-friendly PDFs."""

    def __init__(self, template_path: Path = settings.TYPST_TEMPLATE_PATH):
        self.template_path = template_path
        if not self.template_path.exists():
            raise FileNotFoundError(
                f"Typst template missing at {self.template_path}"
            )

    def _escape_typst(self, text: str) -> str:
        """Escapes all special Typst syntax characters in dynamic text strings."""
        if not text:
            return ""
        text = str(text)
        text = text.replace("\\", "\\\\")  # backslash first
        text = text.replace('"', '\\"')
        text = text.replace("#", "\\#")
        text = text.replace("$", "\\$")
        text = text.replace("@", "\\@")
        text = text.replace("[", "\\[")
        text = text.replace("]", "\\]")
        text = text.replace("<", "\\<")
        text = text.replace(">", "\\>")
        return text

    def _format_bullets(self, bullets: List[str]) -> str:
        """Converts raw text bullets into clean Typst list syntax."""
        formatted = []
        for bullet in bullets:
            clean = bullet.strip().lstrip("-").lstrip("*").strip()
            escaped = self._escape_typst(clean)
            if escaped:
                formatted.append(f"- {escaped}")
        return "\n".join(formatted)

    def compile_cv(
        self, tailored_data: Dict[str, Any], output_path: Path
    ) -> Path:
        """Renders tailored data into a temporary Typst file and compiles it to a PDF."""
        candidate_info = tailored_data.get("candidate_info", {})
        contact = candidate_info.get("contact", {})
        location_data = candidate_info.get("location", {})

        # Resolve location string from nested dict or plain string
        if isinstance(location_data, dict):
            location_str = ", ".join(filter(None, [
                location_data.get("city", ""),
                location_data.get("country", ""),
            ]))
        else:
            location_str = str(location_data) if location_data else ""

        raw_contacts = [
            contact.get("email", ""),
            contact.get("phone", ""),
            location_str,
            contact.get("github", ""),
            contact.get("linkedin", ""),
            contact.get("portfolio", ""),
        ]

        # Ensure all values are strings before escaping
        valid_contacts = [
            self._escape_typst(str(c)) for c in raw_contacts if c and str(c).strip()
        ]

        # Format as valid Typst array syntax (including trailing comma for single items)
        if not valid_contacts:
            contact_items_str = ""
        elif len(valid_contacts) == 1:
            contact_items_str = f'"{valid_contacts[0]}",'
        else:
            contact_items_str = ", ".join([f'"{c}"' for c in valid_contacts])

        name = self._escape_typst(candidate_info.get("full_name", "Candidate"))
        summary = self._escape_typst(tailored_data.get("professional_summary", ""))

        # 1. Base Typst document assembly
        # Import uses just the filename — temp .typ is written to the same dir as the template
        typst_code = f"""#import "template.typ": cv, cv_section, job_header

#show: cv.with(
  name: "{name}",
  contact_info: ({contact_items_str}),
  summary: "{summary}"
)

#cv_section("Technical Experience")
"""

        # 2. Append Tailored Experience Sections
        for exp in tailored_data.get("experiences", []):
            role = self._escape_typst(exp.get("role", ""))
            company = self._escape_typst(exp.get("company", ""))
            dates = self._escape_typst(exp.get("dates", ""))
            location = self._escape_typst(exp.get("location", ""))
            bullets_markup = self._format_bullets(exp.get("bullet_points", []))

            typst_code += f"""
#job_header("{role}", "{company}", "{dates}", "{location}")
{bullets_markup}
"""

        # 3. Append Core Competencies / Skills Section
        skills = tailored_data.get("skills", [])
        if skills:
            if isinstance(skills, list):
                escaped_skills = [self._escape_typst(str(s)) for s in skills if s]
                skills_str = ", ".join(escaped_skills)
            else:
                skills_str = self._escape_typst(str(skills))

            typst_code += f"""
#cv_section("Core Competencies & Technologies")
#par[{skills_str}]
"""

        # 4. Write temp .typ alongside the template so the import resolves, then compile
        output_path.parent.mkdir(parents=True, exist_ok=True)
        temp_typ_path = self.template_path.parent / f"_cv_{output_path.stem}.typ"

        try:
            temp_typ_path.write_text(typst_code, encoding="utf-8")
            logger.info(f"Compiling Typst PDF to: {output_path}")
            typst.compile(str(temp_typ_path), output=str(output_path))
            logger.info("[✓] PDF compilation successful.")
            return output_path
        except Exception as e:
            logger.error(f"Failed to compile Typst document: {e}")
            raise e
        finally:
            if temp_typ_path.exists():
                temp_typ_path.unlink()


# Exported singleton instance
pdf_compiler = TypstCompilerEngine()