import logging
from pathlib import Path
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


# 1. State Schema Definition
class AgentState(TypedDict):
  job_data: Dict[str, Any]
  url_hash: str
  tailored_content: Optional[Dict[str, Any]]
  pdf_path: Optional[str]
  approval_status: Optional[str]  # "PENDING", "APPROVED", "REJECTED"


# 2. Node Implementations
def tailor_cv_node(state: AgentState) -> Dict[str, Any]:
  """Tailors CV content against job description using Groq API."""
  job = state["job_data"]
  logger.info(
      f"[Node: Tailor CV] Tailoring profile for {job['title']} at"
      f" {job['company']}"
  )

  tailored_dict = cv_tailor_engine.generate_tailored_cv_data(
      job_description=job.get("description", "")
  )
  return {"tailored_content": tailored_dict}


def generate_pdf_node(state: AgentState) -> Dict[str, Any]:
  """Compiles tailored state data into a PDF on disk."""
  job = state["job_data"]
  url_hash = state["url_hash"]
  logger.info(
      f"[Node: Generate PDF] Compiling Typst resume for target hash {url_hash}"
  )

  output_filename = f"CV_{job['company']}_{url_hash[:8]}.pdf".replace(" ", "_")
  output_path = settings.OUTPUT_DIR / output_filename

  compiled_pdf_path = pdf_compiler.compile_cv(
      tailored_data=state["tailored_content"], output_path=output_path
  )

  return {"pdf_path": str(compiled_pdf_path)}


def send_telegram_node(state: AgentState) -> Dict[str, Any]:
  """Dispatches generated PDF to Telegram channel with inline interactive buttons."""
  job = state["job_data"]
  pdf_path = state["pdf_path"]
  url_hash = state["url_hash"]

  logger.info(f"[Node: Telegram Notification] Dispatching approval for {url_hash}")

  # Trigger Telegram bot gateway (runs async call synchronously in node step)
  import asyncio

  asyncio.run(
      send_approval_request(
          pdf_path=pdf_path,
          job_title=job["title"],
          company=job["company"],
          job_url=job["url"],
          url_hash=url_hash,
      )
  )

  return {"approval_status": "PENDING"}


def finalize_application_node(state: AgentState) -> Dict[str, Any]:
  """Updates database logs based on human approval/rejection decision."""
  url_hash = state["url_hash"]
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

  # Add Nodes
  builder.add_node("tailor_cv", tailor_cv_node)
  builder.add_node("generate_pdf", generate_pdf_node)
  builder.add_node("send_telegram", send_telegram_node)
  builder.add_node("finalize_application", finalize_application_node)

  # Set Flow Edges
  builder.set_entry_point("tailor_cv")
  builder.add_edge("tailor_cv", "generate_pdf")
  builder.add_edge("generate_pdf", "send_telegram")
  builder.add_edge("send_telegram", "finalize_application")
  builder.add_edge("finalize_application", END)

  # Memory Checkpointer enables state pauses across process resets
  memory = MemorySaver()

  # Halt execution before finalize_application node for human approval
  return builder.compile(
      checkpointer=memory, interrupt_before=["finalize_application"]
  )


# Compiled Graph Instance
job_agent_graph = build_agent_graph()