"""Which datasets the caller has switched off, for the length of one request.

One backend serves many browsers, so "is the demo data showing?" cannot be a
property of the server. The split is:

* the **default** is the server's, because only it knows what data exists — a
  synthetic fixture defaults off once real data is driving a surface
  (`registry._apply_defaults`);
* the **choice** is the browser's, kept in its own local storage and sent on
  every request as a header.

So a client transmits only what somebody explicitly flipped. A first-time visitor
sends nothing and still gets the right defaults, and nobody's switches move
anybody else's screen.

The value travels in a context variable rather than as an argument through every
function because the agent's tools are module-level and are called by LangGraph,
not by us — there is no parameter to thread. `SwitchesMiddleware` in `app.main`
sets it for the whole request, including the SSE body streamed after the handler
returns.
"""

from __future__ import annotations

from collections.abc import Mapping
from contextvars import ContextVar, Token

#: Header carrying the caller's choices: `name=on|off`, comma separated. Only
#: datasets somebody actually switched appear; everything else is the default.
HEADER = "X-Dataset-Switches"

_EMPTY: Mapping[str, bool] = {}

_overrides: ContextVar[Mapping[str, bool]] = ContextVar("dataset_switches", default=_EMPTY)


def parse(header: str | None) -> Mapping[str, bool]:
    """Read the header. Anything malformed is dropped rather than raising.

    A stale name from a browser whose registry has since changed is not an error
    — it is a switch for a dataset that no longer exists, and the registry
    resolves overrides against the datasets it actually has.
    """
    if not header:
        return _EMPTY
    overrides: dict[str, bool] = {}
    for item in header.split(","):
        name, sep, state = item.strip().partition("=")
        name = name.strip()
        if not name or not sep:
            continue
        state = state.strip().lower()
        if state in {"on", "off"}:
            overrides[name] = state == "on"
    return overrides


def current() -> Mapping[str, bool]:
    """The switches for the request being served, or none outside one."""
    return _overrides.get()


def bind(overrides: Mapping[str, bool]) -> Token:
    """Make these the switches for the current context. Returns the token to
    hand back to `reset` when the request is over."""
    return _overrides.set(overrides)


def reset(token: Token) -> None:
    _overrides.reset(token)
