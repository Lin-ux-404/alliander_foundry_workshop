"""Q&A workflow: single-agent path for non-incident queries."""
from __future__ import annotations

from agents.qa import QA_NAME
from config import MODEL
from models.responses import ChatResponse
from utils.agent_runner import run_foundry_agent


async def run_qa(user_message: str) -> ChatResponse:
    """Run the Q&A agent and return a typed response."""
    text = await run_foundry_agent(QA_NAME, user_message)
    return ChatResponse(
        type="qa",
        response=text.strip(),
        model=MODEL,
        sources=[],
    )
