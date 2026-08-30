"""What the `claude-code` provider promises, checked without spending a turn.

Nothing here spawns the Claude Code CLI: the value of these tests is that they
pin the two things a live run cannot show you cheaply — that the session really
is locked down to this app's tools, and that a missing CLI or a missing package
comes back as an error event the UI can render rather than a traceback.

The `claude-agent-sdk` package is an optional extra, so the tests that need it
skip when it is not installed.
"""

from __future__ import annotations

import asyncio
import sys
from dataclasses import replace
from pathlib import Path

import pytest

from app.agent.claude_code import (
    _ERROR_HELP,
    TOOL_PREFIX,
    _as_mcp_tool,
    _deltas,
    _starts_block,
    build_options,
    cli_path,
    render_prompt,
    stream_claude_code,
)
from app.agent.llm import PROVIDERS, build_chat_model, describe_provider
from app.tools import ALL_TOOLS, run_sql

sdk = pytest.importorskip("claude_agent_sdk", reason="claude-agent-sdk is an optional extra")


def drain(stream) -> list[dict]:
    """Collect an async event stream. There is no async test plugin here."""

    async def collect():
        return [event async for event in stream]

    return asyncio.run(collect())


# --------------------------------------------------------------------------- #
# The provider entry
# --------------------------------------------------------------------------- #

def test_the_credential_is_the_cli_rather_than_an_environment_variable():
    """Health has to say what it checked.

    Every other provider answers "is $KEY set?". This one answers "is Claude Code
    installed?", so reporting a `credential_env` of None without saying what stood
    in for it would read as "no credential needed".
    """
    described = describe_provider("claude-code")
    assert described["known"] is True
    assert described["credential_env"] is None
    assert described["credential"] == "the Claude Code CLI"


def test_asking_for_a_chat_model_says_where_the_turn_goes_instead():
    """`build_chat_model` cannot serve this provider, and must not pretend to.

    A silent fall-through would build nothing and fail later inside LangGraph.
    """
    assert PROVIDERS["claude-code"].local_harness is True
    with pytest.raises(RuntimeError, match="own agent loop"):
        build_chat_model("claude-code")


# --------------------------------------------------------------------------- #
# The session
# --------------------------------------------------------------------------- #

@pytest.fixture(scope="module")
def options():
    return build_options(sdk, "system prompt")


def test_the_session_has_no_built_in_tools_at_all(options):
    """The one property worth a test: this cannot touch the filesystem.

    Claude Code's default tool set includes Read, Write, Edit and Bash. Serving a
    web request, none of them are wanted — an empty `tools` list is what keeps a
    chat message from becoming shell access.
    """
    assert options.tools == []
    assert options.allowed_tools == [f"{TOOL_PREFIX}{tool.name}" for tool in ALL_TOOLS]
    assert options.permission_mode == "dontAsk"


def test_the_session_ignores_the_machine_it_is_running_on(options):
    """No settings files, no CLAUDE.md, no MCP servers but ours.

    Otherwise the agent's behaviour would depend on whose laptop the backend
    happens to be running on, and two contributors would see different answers to
    the same question.
    """
    assert options.setting_sources == []
    assert options.strict_mcp_config is True
    assert options.system_prompt == "system prompt"
    assert list(options.mcp_servers) == ["intruder"]


def test_the_model_sees_the_same_tools_the_graph_gives_it(options):
    """Same names, same descriptions, same schemas — only the transport differs."""
    served = options.mcp_servers["intruder"]["instance"]
    assert served is not None
    adapted = _as_mcp_tool(sdk, run_sql)
    assert adapted.name == run_sql.name
    assert adapted.description == run_sql.description
    assert adapted.input_schema == run_sql.tool_call_schema.model_json_schema()


def test_a_tool_that_raises_comes_back_as_a_result_not_a_crash():
    """A failing tool is the model's problem to work around, not the stream's.

    `run_sql` on a table that does not exist has to reach the model as text it can
    read and retry from; letting it propagate would end the turn with nothing said.
    """
    adapted = _as_mcp_tool(sdk, run_sql)
    result = asyncio.run(adapted.handler({"query": "SELECT * FROM no_such_table"}))
    assert result["content"][0]["type"] == "text"
    assert result["content"][0]["text"]


# --------------------------------------------------------------------------- #
# The conversation
# --------------------------------------------------------------------------- #

def test_a_first_turn_is_sent_as_itself():
    assert render_prompt([{"role": "user", "content": "how many loci?"}]) == "how many loci?"


def test_earlier_turns_are_rendered_ahead_of_the_current_one():
    """`query()` is stateless and the frontend re-sends everything each turn.

    The prompt has to carry the history, and the current message has to come last
    — a follow-up that reads as part of the transcript gets answered as history.
    """
    prompt = render_prompt(
        [
            {"role": "user", "content": "how many loci?"},
            {"role": "assistant", "content": "1,200."},
            {"role": "user", "content": "how many on chr1?"},
        ]
    )
    assert prompt.endswith("how many on chr1?")
    assert "User: how many loci?" in prompt
    assert "Assistant: 1,200." in prompt


def test_empty_turns_are_dropped_rather_than_sent_as_blanks():
    assert render_prompt([]) == ""
    assert render_prompt([{"role": "user", "content": ""}]) == ""


# --------------------------------------------------------------------------- #
# The event stream
# --------------------------------------------------------------------------- #

@pytest.mark.parametrize(
    ("event", "expected"),
    [
        (
            {"type": "content_block_delta", "delta": {"type": "text_delta", "text": "hi"}},
            [{"type": "text", "delta": "hi"}],
        ),
        (
            {"type": "content_block_delta", "delta": {"type": "thinking_delta", "thinking": "hm"}},
            [{"type": "thinking", "delta": "hm"}],
        ),
        # Tool arguments stream as JSON fragments; they are yielded whole later,
        # from the assistant message, so the partials are dropped here.
        (
            {"type": "content_block_delta", "delta": {"type": "input_json_delta", "partial_json": "{"}},
            [],
        ),
        ({"type": "message_start", "message": {}}, []),
    ],
)
def test_only_text_and_reasoning_deltas_become_ui_events(event, expected):
    assert _deltas(event) == expected


def test_a_missing_package_is_reported_the_way_the_other_providers_report_one(monkeypatch):
    """The install line is the whole point of the message.

    `claude-agent-sdk` is an optional extra, exactly like `langchain-openai`, so a
    clone that sets LLM_PROVIDER=claude-code without installing it must be told
    what to run rather than shown an ImportError.
    """
    monkeypatch.setitem(sys.modules, "claude_agent_sdk", None)
    events = drain(stream_claude_code([{"role": "user", "content": "hello"}]))
    assert [event["type"] for event in events] == ["error"]
    assert "uv add claude-agent-sdk" in events[0]["message"]


def test_the_graph_hands_the_turn_over_instead_of_building_a_model(monkeypatch):
    """`stream_agent` stays the one entry point the API calls.

    `app/main.py` knows nothing about providers, so the choice has to be made
    here — and the `done` event has to be emitted exactly once either way.
    """
    from app.agent import graph

    async def fake_stream(messages):
        yield {"type": "text", "delta": messages[0]["content"]}

    monkeypatch.setattr(
        graph, "settings", replace(graph.settings, llm_provider="claude-code")
    )
    monkeypatch.setattr("app.agent.claude_code.stream_claude_code", fake_stream)
    events = drain(graph.stream_agent([{"role": "user", "content": "hi"}]))
    assert events == [{"type": "text", "delta": "hi"}, {"type": "done"}]


def test_the_cli_the_sdk_bundles_counts_as_installed():
    """`claude-agent-sdk` ships a CLI binary, so the package can be the whole install.

    Looking only at PATH would have `/api/health` report a working setup as
    missing, and `app/main.py` warn that chat is disabled while it works fine.
    """
    found = cli_path()
    assert found is not None
    assert Path(found).is_file()


def test_one_failure_is_reported_once(monkeypatch):
    """A dead or signed-out CLI announces itself three times over.

    It arrives on the assistant message, again on the result message, and once
    more as the exception that ends the iteration. The chat pane should show the
    first and most specific of those, not a stack of three.
    """

    async def failing_query(*, prompt, options, transport=None):
        yield sdk.AssistantMessage(content=[], model="claude-opus-5", error="authentication_failed")
        yield sdk.ResultMessage(
            subtype="error_during_execution",
            duration_ms=1,
            duration_api_ms=1,
            is_error=True,
            num_turns=1,
            session_id="test",
            errors=["Not logged in"],
        )
        raise sdk.ProcessError("Command failed with exit code 1")

    monkeypatch.setattr(sdk, "query", failing_query)
    events = drain(stream_claude_code([{"role": "user", "content": "hello"}]))
    assert events == [
        {"type": "error", "message": _ERROR_HELP["authentication_failed"]}
    ]


def test_a_new_block_is_routed_to_the_stream_it_belongs_to():
    """Claude Code opens a new text and thinking block after each tool call.

    Concatenated raw, the sentence either side of a `set_view` call runs
    together — "...the view directly.If you want" — which markdown then renders
    as one paragraph. Reasoning has the same seam and needs the same break, but
    into its own stream: a break written into the wrong one would land the gap
    mid-sentence somewhere else.
    """
    def start(kind):
        return {"type": "content_block_start", "index": 0, "content_block": {"type": kind}}

    assert _starts_block(start("text")) == "text"
    assert _starts_block(start("thinking")) == "thinking"
    # Tool input blocks are streamed too, and are yielded whole from the
    # assistant message instead — they must not open a gap in either stream.
    assert _starts_block(start("tool_use")) is None
    assert _starts_block({"type": "content_block_delta", "delta": {}}) is None


def test_the_break_lands_between_blocks_and_not_before_the_first(monkeypatch):
    """End to end through the stream, since the counters are what make it correct.

    The two streams count independently: a thinking block opening must not put a
    gap in front of the first line of the answer.
    """

    def block(index, kind="text"):
        return sdk.StreamEvent(
            uuid=f"u{index}",
            session_id="test",
            event={"type": "content_block_start", "index": index, "content_block": {"type": kind}},
            parent_tool_use_id=None,
        )

    def delta(index, text):
        return sdk.StreamEvent(
            uuid=f"d{index}",
            session_id="test",
            event={
                "type": "content_block_delta",
                "index": index,
                "delta": {"type": "text_delta", "text": text},
            },
            parent_tool_use_id=None,
        )

    def thought(index, text):
        return sdk.StreamEvent(
            uuid=f"t{index}",
            session_id="test",
            event={
                "type": "content_block_delta",
                "index": index,
                "delta": {"type": "thinking_delta", "thinking": text},
            },
            parent_tool_use_id=None,
        )

    async def fake_query(*, prompt, options, transport=None):
        yield block(0, "thinking")
        yield thought(0, "First thought.")
        yield block(1)
        yield delta(1, "First answer.")
        yield block(2, "thinking")
        yield thought(2, "Second thought.")
        yield block(3)
        yield delta(3, "Second answer.")

    monkeypatch.setattr(sdk, "query", fake_query)
    events = drain(stream_claude_code([{"role": "user", "content": "hello"}]))
    joined = {
        kind: "".join(e["delta"] for e in events if e["type"] == kind)
        for kind in ("text", "thinking")
    }
    assert joined["text"] == "First answer.\n\nSecond answer."
    assert joined["thinking"] == "First thought.\n\nSecond thought."
