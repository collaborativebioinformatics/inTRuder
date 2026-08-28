"""Running the agent on a local Claude Code install.

`LLM_PROVIDER=claude-code` is the one provider that does not build a chat model.
It hands the turn to the Claude Code CLI through the Claude Agent SDK, which
bundles that CLI and signs in with the credentials under `~/.claude` — so a
contributor who uses Claude Code can run chat without an API key of their own.

Claude Code brings its own agent loop, so this module stands in for the LangGraph
graph rather than plugging into it: the tools in `app.tools` are handed to it as
an in-process MCP server, and its message stream is translated back into the
events in `app.agent.graph`'s docstring. The frontend cannot tell the two paths
apart — same event shapes, same tool names.

The session is deliberately stripped down. Every built-in tool is off, so this
cannot read or write files or run commands; the system prompt is this app's, not
Claude Code's; and `~/.claude`, `.claude/`, `CLAUDE.md`, and project MCP servers
are not loaded. What is left is our prompt and our tools.
"""

from __future__ import annotations

import logging
import shutil
from collections.abc import AsyncIterator
from pathlib import Path
from typing import Any

from app.config import BACKEND_DIR, settings
from app.tools import ALL_TOOLS

logger = logging.getLogger(__name__)

# The MCP server the tools are served from. Claude Code namespaces MCP tools as
# `mcp__<server>__<tool>`; the prefix is stripped again on the way out so the
# frontend sees `run_sql`, the same name the LangGraph path emits.
MCP_SERVER = "noveltrs"
TOOL_PREFIX = f"mcp__{MCP_SERVER}__"

# Where the SDK looks for the CLI when it is not on PATH, mirrored so that
# /api/health can answer "is Claude Code usable here?" without spawning a
# subprocess to find out. Keep this in step with the SDK's own list, or health
# will claim a working install is missing.
_CLI_LOCATIONS = (
    Path("/usr/local/bin/claude"),
    Path.home() / ".npm-global/bin/claude",
    Path.home() / ".local/bin/claude",
    Path.home() / "node_modules/.bin/claude",
    Path.home() / ".yarn/bin/claude",
    Path.home() / ".claude/local/claude",
)

# `AssistantMessage.error` is a short machine token. These are the ones a user
# can act on; anything else is passed through as-is.
_ERROR_HELP = {
    "authentication_failed": (
        "Claude Code is not logged in. Run `claude` once in a terminal and sign "
        "in, then retry."
    ),
    "billing_error": "Claude Code reported a billing problem with this account.",
    "rate_limit": "Claude Code is rate limited right now. Retry shortly.",
}


def cli_path() -> str | None:
    """The Claude Code CLI this machine would run, or None if there is none.

    Same order the SDK searches in, and the bundled copy comes first for a
    reason: `claude-agent-sdk` ships a CLI binary, so installing the package is
    usually enough on its own. Checking PATH alone would have health report a
    working install as missing.
    """
    try:
        import claude_agent_sdk

        bundled = Path(claude_agent_sdk.__file__).parent / "_bundled" / "claude"
        if bundled.is_file():
            return str(bundled)
    except ImportError:
        return None  # without the SDK there is nothing to run the CLI from

    found = shutil.which("claude")
    if found:
        return found
    for candidate in _CLI_LOCATIONS:
        if candidate.is_file():
            return str(candidate)
    return None


def _require_sdk():
    """Import the SDK, or explain how to install it."""
    try:
        import claude_agent_sdk
    except ImportError as exc:  # pragma: no cover - install-time path
        raise RuntimeError(
            "LLM_PROVIDER=claude-code needs the 'claude-agent-sdk' package. "
            "Install it with:  cd backend && uv add claude-agent-sdk"
        ) from exc
    return claude_agent_sdk


def _as_mcp_tool(sdk: Any, lc_tool: Any) -> Any:
    """Expose one LangChain tool over MCP, unchanged.

    The name, the description and the JSON schema are the tool's own, so the two
    providers put the same tool surface in front of the model. `ainvoke` runs
    these synchronous tools in a worker thread, which keeps a slow query off the
    event loop serving the SSE stream.
    """
    schema = lc_tool.tool_call_schema.model_json_schema()

    async def handler(args: dict[str, Any]) -> dict[str, Any]:
        try:
            result = await lc_tool.ainvoke(args or {})
        except Exception as exc:  # a tool error is the model's problem to handle
            logger.exception("tool %s failed", lc_tool.name)
            return {
                "content": [{"type": "text", "text": f"{type(exc).__name__}: {exc}"}],
                "is_error": True,
            }
        return {"content": [{"type": "text", "text": result if isinstance(result, str) else str(result)}]}

    return sdk.tool(lc_tool.name, lc_tool.description, schema)(handler)


def build_options(sdk: Any, system_prompt: str) -> Any:
    """The session Claude Code runs this turn in.

    Everything here narrows it: no built-in tools, our prompt instead of Claude
    Code's, no settings files, no MCP servers but ours, and no permission prompt
    to block on in a process with no terminal attached.
    """
    server = sdk.create_sdk_mcp_server(
        MCP_SERVER, tools=[_as_mcp_tool(sdk, lc_tool) for lc_tool in ALL_TOOLS]
    )
    return sdk.ClaudeAgentOptions(
        system_prompt=system_prompt,
        mcp_servers={MCP_SERVER: server},
        strict_mcp_config=True,        # ignore .mcp.json and any global servers
        tools=[],                      # no Read/Write/Edit/Bash — ours are the only tools
        allowed_tools=[f"{TOOL_PREFIX}{lc_tool.name}" for lc_tool in ALL_TOOLS],
        permission_mode="dontAsk",     # never prompt; deny anything not allowed above
        setting_sources=[],            # ignore ~/.claude, .claude/, and CLAUDE.md
        model=settings.llm_model or None,
        effort=settings.llm_effort,
        thinking={"type": "adaptive", "display": "summarized"},
        include_partial_messages=True,  # token deltas, so the UI streams as it does elsewhere
        max_turns=settings.claude_code_max_turns,
        cwd=str(BACKEND_DIR),
    )


def render_prompt(messages: list[dict[str, str]]) -> str:
    """Flatten the conversation into the single prompt `query()` takes.

    The SDK's `query()` is stateless and the frontend re-sends the whole
    conversation each turn, so earlier turns are rendered into the prompt rather
    than resumed from a Claude Code session. Tool calls from earlier turns are
    dropped — `graph._to_langchain` drops them too, so both providers see the
    same history.
    """
    turns = [m for m in messages if m.get("content")]
    if not turns:
        return ""
    current = turns[-1]["content"]
    earlier = turns[:-1]
    if not earlier:
        return current
    transcript = "\n\n".join(
        f"{'Assistant' if turn.get('role') == 'assistant' else 'User'}: {turn['content']}"
        for turn in earlier
    )
    return f"Earlier in this conversation:\n\n{transcript}\n\n---\n\n{current}"


def _starts_block(event: dict[str, Any]) -> str | None:
    """Which UI stream a new content block belongs to, if this event opens one.

    Returns the event type the break should be written into — `text` or
    `thinking` — or None for anything else (tool input blocks, deltas, message
    framing).
    """
    if event.get("type") != "content_block_start":
        return None
    kind = (event.get("content_block") or {}).get("type")
    return kind if kind in ("text", "thinking") else None


def _deltas(event: dict[str, Any]) -> list[dict[str, Any]]:
    """Text and reasoning deltas out of one raw streaming event."""
    if event.get("type") != "content_block_delta":
        return []
    delta = event.get("delta") or {}
    kind = delta.get("type")
    if kind == "text_delta" and delta.get("text"):
        return [{"type": "text", "delta": delta["text"]}]
    if kind == "thinking_delta" and delta.get("thinking"):
        return [{"type": "thinking", "delta": delta["thinking"]}]
    return []


async def stream_claude_code(messages: list[dict[str, str]]) -> AsyncIterator[dict[str, Any]]:
    """Yield UI events for one turn run through Claude Code.

    Emits the same events as `app.agent.graph.stream_agent`, minus the trailing
    `done`, which the caller adds for both providers.
    """
    try:
        sdk = _require_sdk()
    except RuntimeError as exc:
        yield {"type": "error", "message": str(exc)}
        return

    from app.agent.prompt import system_text

    options = build_options(sdk, system_text())
    seen_tool_calls: set[str] = set()
    # One failure reaches us up to three ways — on the assistant message, on the
    # result message, and as the exception that ends the iteration. The first is
    # the most specific, so later ones are dropped rather than stacked in the UI.
    reported = False
    # Claude Code opens a fresh text block, and a fresh thinking block, after
    # every tool call. Concatenated raw they run together mid-sentence
    # ("...directly.If you want"), so each block after the first in its own
    # stream gets a paragraph break in front of it.
    blocks = {"text": 0, "thinking": 0}

    try:
        async for message in sdk.query(prompt=render_prompt(messages), options=options):
            # Text and thinking arrive as deltas; whole blocks arrive again on the
            # AssistantMessage that follows, so only tool calls are read there.
            if isinstance(message, sdk.StreamEvent):
                event = message.event
                opened = _starts_block(event)
                if opened:
                    if blocks[opened]:
                        yield {"type": opened, "delta": "\n\n"}
                    blocks[opened] += 1
                for ui_event in _deltas(event):
                    yield ui_event

            elif isinstance(message, sdk.AssistantMessage):
                if message.error and not reported:
                    reported = True
                    yield {
                        "type": "error",
                        "message": _ERROR_HELP.get(message.error, message.error),
                    }
                for block in message.content:
                    if not isinstance(block, sdk.ToolUseBlock) or block.id in seen_tool_calls:
                        continue
                    seen_tool_calls.add(block.id)
                    name = block.name.removeprefix(TOOL_PREFIX)
                    args = block.input or {}
                    yield {"type": "tool", "name": name, "args": args}
                    # The same hook the graph has: chat drives the interface.
                    if name == "set_view" and args:
                        yield {"type": "view", "filters": args}

            elif isinstance(message, sdk.ResultMessage) and message.is_error and not reported:
                reported = True
                detail = "; ".join(message.errors or []) or message.result or message.subtype
                yield {"type": "error", "message": f"Claude Code ended the turn: {detail}"}

    except sdk.CLINotFoundError:
        logger.warning("claude code CLI not found")
        if not reported:
            yield {
                "type": "error",
                "message": (
                    "LLM_PROVIDER=claude-code, but the Claude Code CLI was not found. "
                    "Install it from https://claude.com/claude-code, or set another "
                    "LLM_PROVIDER in backend/.env."
                ),
            }
    except Exception as exc:  # surface any provider/runtime failure to the UI
        logger.exception("claude code stream failed")
        if not reported:
            yield {"type": "error", "message": f"{type(exc).__name__}: {exc}"}
