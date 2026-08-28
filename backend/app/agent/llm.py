"""Provider-pluggable chat model factory.

The provider is chosen with `LLM_PROVIDER` in `backend/.env`. Only the Anthropic
client is installed by default; the others are optional extras so that a clone
does not pull every SDK to run one. Each entry records the package to install and
the environment variable that carries the credential, so a misconfiguration
produces an actionable message instead of an ImportError traceback.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class Provider:
    name: str
    default_model: str
    package: str          # pip/uv package supplying the LangChain integration
    credential_env: str    # "" when the provider needs no credential (local models)
    notes: str = ""
    # True for a provider that is not a chat model at all but a local harness
    # running its own agent loop. `build_chat_model` cannot build one; the graph
    # hands the turn to `app.agent.claude_code` instead.
    local_harness: bool = False


PROVIDERS: dict[str, Provider] = {
    "anthropic": Provider(
        name="anthropic",
        default_model="claude-opus-5",
        package="langchain-anthropic",
        credential_env="ANTHROPIC_API_KEY",
        notes="Installed by default. Adaptive thinking and effort are wired up below.",
    ),
    "claude-code": Provider(
        name="claude-code",
        default_model="",     # whatever the local Claude Code is configured to use
        package="claude-agent-sdk",
        credential_env="",    # signs in as the CLI, so there is no key to set
        notes=(
            "Runs the turn through the Claude Code CLI on this machine, on its own "
            "login. No API key. Claude Code supplies the agent loop, so the LangGraph "
            "graph is not used - see app/agent/claude_code.py."
        ),
        local_harness=True,
    ),
    "google": Provider(
        name="google",
        default_model="gemini-2.5-pro",
        package="langchain-google-genai",
        credential_env="GOOGLE_API_KEY",
    ),
    "ollama": Provider(
        name="ollama",
        default_model="llama3.1",
        package="langchain-ollama",
        credential_env="",
        notes="Local models. Set OLLAMA_BASE_URL if the daemon is not on localhost:11434.",
    ),
    "openai": Provider(
        name="openai",
        default_model="gpt-4o",
        package="langchain-openai",
        credential_env="OPENAI_API_KEY",
    ),
}


def provider_credential_present(provider_name: str) -> bool:
    """True when the selected provider has whatever credential it needs."""
    provider = PROVIDERS.get(provider_name)
    if provider is None:
        return False
    if provider.local_harness:
        from app.agent.claude_code import cli_path

        return cli_path() is not None
    if not provider.credential_env:
        return True  # local providers such as Ollama need no key
    return bool(os.getenv(provider.credential_env))


def describe_provider(provider_name: str) -> dict[str, Any]:
    """Config summary for the /api/health endpoint, with no secret values."""
    provider = PROVIDERS.get(provider_name)
    if provider is None:
        return {"provider": provider_name, "known": False, "supported": sorted(PROVIDERS)}
    return {
        "provider": provider.name,
        "known": True,
        "default_model": provider.default_model,
        "credential_env": provider.credential_env or None,
        "credential_present": provider_credential_present(provider_name),
        # What credential_present actually looked for, since it is not always a key.
        "credential": (
            "the Claude Code CLI" if provider.local_harness else provider.credential_env or None
        ),
        "notes": provider.notes,
    }


def _missing_package(provider: Provider) -> RuntimeError:
    return RuntimeError(
        f"LLM_PROVIDER={provider.name} needs the {provider.package!r} package. "
        f"Install it with:  cd backend && uv add {provider.package}"
    )


def build_chat_model(
    provider_name: str,
    model: str = "",
    *,
    effort: str = "high",
    max_tokens: int = 8000,
):
    """Construct a streaming LangChain chat model for the configured provider."""
    provider = PROVIDERS.get(provider_name)
    if provider is None:
        raise RuntimeError(
            f"Unknown LLM_PROVIDER={provider_name!r}. Supported: {', '.join(sorted(PROVIDERS))}"
        )

    if provider.local_harness:
        raise RuntimeError(
            f"LLM_PROVIDER={provider.name} has no chat model to build - it brings its "
            "own agent loop. Route the turn through app.agent.stream_agent, which "
            "dispatches to app.agent.claude_code."
        )

    if provider.credential_env and not os.getenv(provider.credential_env):
        raise RuntimeError(
            f"LLM_PROVIDER={provider.name} requires {provider.credential_env} to be set. "
            f"Add it to backend/.env (see backend/.env.example)."
        )

    model_id = model or provider.default_model

    if provider.name == "anthropic":
        try:
            from langchain_anthropic import ChatAnthropic
        except ImportError as exc:  # pragma: no cover - install-time path
            raise _missing_package(provider) from exc

        # Adaptive thinking is the current API for Claude 4.6+; `budget_tokens` is
        # rejected on Opus 5. `display: summarized` matters for UX - the default
        # emits empty thinking blocks, which reads as a long pause before output.
        # Temperature is deliberately not set: it is removed on Opus 5.
        return ChatAnthropic(
            model=model_id,
            max_tokens=max_tokens,
            streaming=True,
            thinking={"type": "adaptive", "display": "summarized"},
            output_config={"effort": effort},
        )

    if provider.name == "google":
        try:
            from langchain_google_genai import ChatGoogleGenerativeAI
        except ImportError as exc:
            raise _missing_package(provider) from exc
        return ChatGoogleGenerativeAI(model=model_id, max_output_tokens=max_tokens)

    if provider.name == "ollama":
        try:
            from langchain_ollama import ChatOllama
        except ImportError as exc:
            raise _missing_package(provider) from exc
        return ChatOllama(
            model=model_id,
            base_url=os.getenv("OLLAMA_BASE_URL", "http://localhost:11434"),
            num_predict=max_tokens,
        )

    if provider.name == "openai":
        try:
            from langchain_openai import ChatOpenAI
        except ImportError as exc:
            raise _missing_package(provider) from exc
        return ChatOpenAI(model=model_id, max_tokens=max_tokens, streaming=True)

    raise RuntimeError(f"Provider {provider.name!r} is listed but not constructible.")
