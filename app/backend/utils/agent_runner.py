"""Run a Foundry-managed Prompt Agent via WorkflowBuilder streaming."""
from __future__ import annotations

from collections.abc import AsyncGenerator

from agent_framework import AgentResponseUpdate, WorkflowBuilder

from config import get_foundry_agent


async def run_foundry_agent(agent_name: str, input_text: str) -> str:
    """Run a Foundry-managed Prompt Agent and return its full text output."""
    agent = get_foundry_agent(agent_name)
    text = ""
    workflow = WorkflowBuilder(start_executor=agent).build()
    async for event in workflow.run(input_text, stream=True):
        if event.type == "output" and isinstance(event.data, AgentResponseUpdate):
            text += event.data.text or ""
    return text


async def stream_foundry_agent(
    agent_name: str, input_text: str,
) -> AsyncGenerator[str, None]:
    """Yield token chunks as the Foundry agent streams its response."""
    agent = get_foundry_agent(agent_name)
    workflow = WorkflowBuilder(start_executor=agent).build()
    async for event in workflow.run(input_text, stream=True):
        if event.type == "output" and isinstance(event.data, AgentResponseUpdate):
            if event.data.text:
                yield event.data.text
