import logging
from typing import Any, Dict, Optional, TypedDict
from langgraph.checkpoint.memory import MemorySaver
from langgraph.graph import END, StateGraph
from compiler.pdf_engine import pdf_compiler
from config import settings
from core.llm import cv_tailor_engine
from gateway.bot import send_approval_request
from ingestion.deduplicator import deduplicator

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

_FIT_THRESHOLD = 40  # minimum match score (%) to proceed to LLM tailoring


# 1. State Schema Definition
class AgentState(TypedDict):
    job_data: Dict[str, Any]
    url_hash: str
    fit_score: Optional[int]
    tailored_content: Optional[Dict[str, Any]]
    pdf_path: Optional[str]
    approval_status: Optional[str]  # "PENDING", "APPROVED", "REJECTED"


# 2. Async Node Implementations
async def evaluate_fit_node(state: AgentState) -> Dict[str, Any]:
    """Scores job against candidate profile keywords. Skips LLM if score < threshold."""
    import json
    from pathlib import Path

    job = state["job_data"]
    combined_text = f"{job.get('title','')} {job.get('description','')} {' '.join(job.get('tags', []))}".lower()

    try:
        with open(settings.PROFILE_PATH, "r", encoding="utf-8") as f:
            profile = json.load(f)
    except Exception:
        profile = {}

    # Build candidate keyword set: target roles + all tech skills
    candidate_keywords = set()
    for role in profile.get("meta", {}).get("target_roles", []):
        candidate_keywords.update(w.lower() for w in role.split())
    for skill_list in profile.get("technical_skills", {}).values():
        for skill in skill_list:
            candidate_keywords.add(skill.lower())

    if not candidate_keywords:
        return {"fit_score": 100}  # no profile data — let it through

    matched = sum(1 for kw in candidate_keywords if kw in combined_text)
    score = int((matched / len(candidate_keywords)) * 100)

    logger.info(
        f"[Node: Evaluate Fit] {job['title']} @ {job['company']} — fit score: {score}% "
        f"({matched}/{len(candidate_keywords)} keywords matched)"
    )
    return {"fit_score": score}


def _route_after_fit(state: AgentState) -> str:
    """Routes to tailor_cv if fit score meets threshold, otherwise ends the thread."""
    score = state.get("fit_score", 0)
    if score >= _FIT_THRESHOLD:
        return "tailor_cv"
    logger.info(
        f"[Router] Fit score {score}% below threshold {_FIT_THRESHOLD}% — skipping job."
    )
    deduplicator.update_application_status(
        url_hash=state["url_hash"], status="REJECTED"
    )
    return END


async def tailor_cv_node(state: AgentState) -> Dict[str, Any]:
    """Tailors CV content against job description using Groq API."""
    job = state["job_data"]
    logger.info(
        f"[Node: Tailor CV] Tailoring profile for {job['title']} at {job['company']}"
    )
    tailored_dict = cv_tailor_engine.generate_tailored_cv_data(
        job_description=job.get("description", "")
    )
    return {"tailored_content": tailored_dict}


async def generate_pdf_node(state: AgentState) -> Dict[str, Any]:
    """Compiles tailored state data into a PDF on disk."""
    job = state["job_data"]
    url_hash = state["url_hash"]
    logger.info(
        f"[Node: Generate PDF] Compiling Typst resume for target hash {url_hash}"
    )
    output_filename = f"CV_{job['company']}_{url_hash[:8]}.pdf".replace(" ", "_")
    output_path = settings.OUTPUT_DIR / output_filename

    try:
        compiled_pdf_path = pdf_compiler.compile_cv(
            tailored_data=state["tailored_content"], output_path=output_path
        )
        return {"pdf_path": str(compiled_pdf_path)}
    except Exception as e:
        logger.error(
            f"[Node: Generate PDF] Typst compilation failed for {url_hash}: {e}. Skipping job."
        )
        deduplicator.update_application_status(url_hash=url_hash, status="REJECTED")
        from langgraph.errors import GraphInterrupt
        raise GraphInterrupt(f"PDF compilation failed: {e}")


async def send_telegram_node(state: AgentState) -> Dict[str, Any]:
    """Dispatches generated PDF to Telegram channel with inline interactive buttons."""
    job = state["job_data"]
    url_hash = state["url_hash"]
    logger.info(f"[Node: Telegram Notification] Dispatching approval for {url_hash}")

    await send_approval_request(
        pdf_path=state["pdf_path"],
        job_title=job["title"],
        company=job["company"],
        job_url=job["url"],
        url_hash=url_hash,
    )
    return {"approval_status": "PENDING"}


async def finalize_application_node(state: AgentState) -> Dict[str, Any]:
    """Updates database logs based on human approval/rejection decision."""
    url_hash = state.get("url_hash")
    if not url_hash:
        logger.warning("[Node: Finalize] url_hash missing from state — cannot update DB.")
        return {}
    status = state.get("approval_status", "REJECTED")
    pdf_path = state.get("pdf_path")

    logger.info(
        f"[Node: Finalize] Application {url_hash} resolved with status: {status}"
    )
    deduplicator.update_application_status(
        url_hash=url_hash, status=status, pdf_path=pdf_path
    )
    return {}


# 3. Assemble LangGraph StateMachine
def build_agent_graph():
    builder = StateGraph(AgentState)

    builder.add_node("evaluate_fit", evaluate_fit_node)
    builder.add_node("tailor_cv", tailor_cv_node)
    builder.add_node("generate_pdf", generate_pdf_node)
    builder.add_node("send_telegram", send_telegram_node)
    builder.add_node("finalize_application", finalize_application_node)

    builder.set_entry_point("evaluate_fit")
    builder.add_conditional_edges("evaluate_fit", _route_after_fit)
    builder.add_edge("tailor_cv", "generate_pdf")
    builder.add_edge("generate_pdf", "send_telegram")
    builder.add_edge("send_telegram", "finalize_application")
    builder.add_edge("finalize_application", END)

    memory = MemorySaver()

    # Halt execution before finalize_application node for human approval
    return builder.compile(
        checkpointer=memory, interrupt_before=["finalize_application"]
    )


# Compiled Graph Instance
job_agent_graph = build_agent_graph()
