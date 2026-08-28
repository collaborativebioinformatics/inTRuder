"""The LangGraph agent and its event stream.

Deliberately small: a prebuilt ReAct graph over the tools in `app.tools`. It is a
real LangGraph graph, so replacing `create_react_agent` with a custom `StateGraph`
later is a change to this file only — the tools, the prompt, the streaming
protocol, and the frontend stay as they are.

`stream_agent` is the entry point for every provider, not just the graph ones:
`LLM_PROVIDER=claude-code` brings its own agent loop, so the turn is handed to
`app.agent.claude_code`, which yields the same events documented below.
"""

from __future__ import annotations

import json
import logging
from collections.abc import AsyncIterator
from typing import Any

from langchain_core.messages import AIMessage, AIMessageChunk, HumanMessage
from langgraph.prebuilt import create_react_agent

from app.agent.llm import PROVIDERS, build_chat_model
from app.agent.prompt import system_message
from app.config import settings
from app.tools import ALL_TOOLS

logger = logging.getLogger(__name__)

def build_agent():
    """Construct the graph. Raises if the configured provider is unusable."""
    model = build_chat_model(
        settings.llm_provider,
        settings.llm_model,
        effort=settings.llm_effort,
        max_tokens=settings.llm_max_tokens,
    )
    return create_react_agent(model, ALL_TOOLS)


def _to_langchain(messages: list[dict[str, str]]) -> list[Any]:
    converted: list[Any] = [system_message()]
    for message in messages:
        role = message.get("role")
        content = message.get("content", "")
        if not content:
            continue
        if role == "assistant":
            converted.append(AIMessage(content=content))
        else:
            converted.append(HumanMessage(content=content))
    return converted


def _text_of(content: Any) -> str:
    """Pull display text out of a message chunk.

    Anthropic returns a list of typed blocks when thinking is enabled; other
    providers return a plain string. Thinking blocks are skipped here — they are
    streamed separately so the UI can render them differently.
    """
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts = []
        for block in content:
            if isinstance(block, str):
                parts.append(block)
            elif isinstance(block, dict) and block.get("type") == "text":
                parts.append(block.get("text", ""))
        return "".join(parts)
    return ""


def _thinking_of(content: Any) -> str:
    if not isinstance(content, list):
        return ""
    parts = []
    for block in content:
        if isinstance(block, dict) and block.get("type") == "thinking":
            parts.append(block.get("thinking", "") or block.get("text", ""))
    return "".join(parts)


async def stream_agent(messages: list[dict[str, str]]) -> AsyncIterator[dict[str, Any]]:
    """Yield UI events for one agent turn.

    Event shapes consumed by the frontend:
      {"type": "text",     "delta": str}      incremental assistant text
      {"type": "thinking", "delta": str}      incremental reasoning summary
      {"type": "tool",     "name": str, "args": dict}
      {"type": "view",     "filters": dict}   apply these to the visualization
      {"type": "error",    "message": str}
      {"type": "done"}
    """
    provider = PROVIDERS.get(settings.llm_provider)
    if provider is not None and provider.local_harness:
        # Claude Code runs its own loop; it yields these same events. See
        # app/agent/claude_code.py.
        from app.agent.claude_code import stream_claude_code

        async for event in stream_claude_code(messages):
            yield event
        yield {"type": "done"}
        return

    try:
        agent = build_agent()
    except RuntimeError as exc:
        yield {"type": "error", "message": str(exc)}
        yield {"type": "done"}
        return

    seen_tool_calls: set[str] = set()

    try:
        async for mode, payload in agent.astream(
            {"messages": _to_langchain(messages)},
            stream_mode=["messages", "updates"],
        ):
            if mode == "messages":
                chunk = payload[0] if isinstance(payload, tuple) else payload
                if not isinstance(chunk, AIMessageChunk):
                    continue
                thinking = _thinking_of(chunk.content)
                if thinking:
                    yield {"type": "thinking", "delta": thinking}
                text = _text_of(chunk.content)
                if text:
                    yield {"type": "text", "delta": text}

            elif mode == "updates":
                if not isinstance(payload, dict):
                    continue
                for node_state in payload.values():
                    if not isinstance(node_state, dict):
                        continue
                    for message in node_state.get("messages", []) or []:
                        for call in getattr(message, "tool_calls", None) or []:
                            call_id = call.get("id") or f"{call.get('name')}:{len(seen_tool_calls)}"
                            if call_id in seen_tool_calls:
                                continue
                            seen_tool_calls.add(call_id)
                            name = call.get("name", "")
                            args = call.get("args", {}) or {}
                            yield {"type": "tool", "name": name, "args": args}
                            # This is the hook that lets chat drive the interface.
                            if name == "set_view" and args:
                                yield {"type": "view", "filters": args}

    except Exception as exc:  # surface any provider/runtime failure to the UI
        logger.exception("agent stream failed")
        yield {"type": "error", "message": f"{type(exc).__name__}: {exc}"}

    yield {"type": "done"}


def sse(event: dict[str, Any]) -> str:
    """Server-sent-event framing for one event."""
    return f"data: {json.dumps(event, default=str)}\n\n"
