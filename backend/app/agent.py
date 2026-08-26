"""The LangGraph agent and its event stream.

Deliberately small: a prebuilt ReAct graph over the four tools in `app.tools`. It
is a real LangGraph graph, so replacing `create_react_agent` with a custom
`StateGraph` later is a change to this file only — the tools, the streaming
protocol, and the frontend stay as they are.
"""

from __future__ import annotations

import json
import logging
from collections.abc import AsyncIterator
from typing import Any

from langchain_core.messages import AIMessage, AIMessageChunk, HumanMessage, SystemMessage
from langgraph.prebuilt import create_react_agent

from app.config import settings
from app.llm import build_chat_model
from app.registry import registry
from app.tools import ALL_TOOLS

logger = logging.getLogger(__name__)

SYSTEM_PROMPT = """\
You are the analysis assistant for novelTRs, a tool that discovers tandem repeat
(TR) loci from structural-variant insertion calls in long-read genomes.

The scientific point of this project: most TR genotypers only look at loci in a
predefined reference-derived catalog, so they are blind to repeats that are not in
the reference at all. Insertions called by SV callers contain those sequences. A
locus here is "novel" when it matches no existing catalog — that is the finding
users care about most, so surface it.

You have two jobs, and usually you should do both in one turn:

1. Answer the question, using `run_sql` against the registered datasets. Prefer
   aggregates over row dumps. Quote real numbers from the query, never estimates.
2. Move the interface with `set_view` so the user is looking at what you are
   talking about. The chat and the visualization are two views of one dataset; a
   good answer leaves the screen showing the relevant loci.

Start with `list_datasets` / `describe_dataset` if you are unsure what exists.
Write DuckDB SQL. Be concise — a few sentences plus the numbers, not an essay.

If a dataset is flagged synthetic, say so plainly when reporting results from it.
Never present demo fixtures as real findings.

Available data:

{schema}
"""


def build_agent():
    """Construct the graph. Raises if the configured provider is unusable."""
    model = build_chat_model(
        settings.llm_provider,
        settings.llm_model,
        effort=settings.llm_effort,
        max_tokens=settings.llm_max_tokens,
    )
    return create_react_agent(model, ALL_TOOLS)


def _system_message() -> SystemMessage:
    return SystemMessage(content=SYSTEM_PROMPT.format(schema=registry.schema_prompt()))


def _to_langchain(messages: list[dict[str, str]]) -> list[Any]:
    converted: list[Any] = [_system_message()]
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
