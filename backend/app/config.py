"""Runtime configuration, read from the environment and `backend/.env`.

Nothing here is secret by itself — secrets live in `.env`, which is gitignored.
See `.env.example` for the full set of supported variables.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

from dotenv import load_dotenv

BACKEND_DIR = Path(__file__).resolve().parents[1]
REPO_ROOT = BACKEND_DIR.parent

# `backend/.env` wins over an already-exported variable only if it is not set.
load_dotenv(BACKEND_DIR / ".env")


def _env_path(name: str, default: Path) -> Path:
    raw = os.getenv(name)
    return Path(raw).expanduser().resolve() if raw else default


def _env_list(name: str, default: list[str]) -> list[str]:
    raw = os.getenv(name)
    if not raw:
        return default
    return [item.strip() for item in raw.split(",") if item.strip()]


@dataclass(frozen=True)
class Settings:
    # Where user data lives. Manifests may reference this as ${NOVELTRS_DATA_DIR}.
    data_dir: Path = field(default_factory=lambda: _env_path("NOVELTRS_DATA_DIR", REPO_ROOT / "data"))
    # Directory scanned for *.yaml dataset manifests.
    registry_dir: Path = field(
        default_factory=lambda: _env_path("NOVELTRS_REGISTRY_DIR", REPO_ROOT / "data" / "web")
    )
    # The only directory `describe_vcf` will open a file from. Agent SQL gets no
    # filesystem access at all, so the one tool that does read a file is confined
    # to this root rather than left to take any path the model writes.
    vcf_root: Path = field(
        default_factory=lambda: _env_path(
            "NOVELTRS_VCF_ROOT", _env_path("NOVELTRS_DATA_DIR", REPO_ROOT / "data")
        )
    )

    # Model selection. See app/agent/llm.py for the supported providers.
    llm_provider: str = field(default_factory=lambda: os.getenv("LLM_PROVIDER", "anthropic").lower())
    llm_model: str = field(default_factory=lambda: os.getenv("LLM_MODEL", ""))
    llm_effort: str = field(default_factory=lambda: os.getenv("LLM_EFFORT", "high"))
    llm_max_tokens: int = field(default_factory=lambda: int(os.getenv("LLM_MAX_TOKENS", "8000")))
    # LLM_PROVIDER=claude-code only: how many tool-calling turns Claude Code may
    # take before it has to answer. The loop is its own, not LangGraph's, so this
    # is the ceiling on one chat request's work.
    claude_code_max_turns: int = field(
        default_factory=lambda: int(os.getenv("CLAUDE_CODE_MAX_TURNS", "12"))
    )

    # Guardrails on the SQL tool. The model writes the SQL, so these are load-bearing.
    max_sql_rows: int = field(default_factory=lambda: int(os.getenv("MAX_SQL_ROWS", "500")))
    sql_timeout_s: float = field(default_factory=lambda: float(os.getenv("SQL_TIMEOUT_S", "15")))
    # Records `describe_vcf` reads before it stops and says the scan is partial.
    vcf_max_records: int = field(
        default_factory=lambda: int(os.getenv("VCF_MAX_RECORDS", "2000"))
    )

    cors_origins: list[str] = field(
        default_factory=lambda: _env_list("CORS_ORIGINS", ["http://localhost:3000"])
    )

    @property
    def agent_enabled(self) -> bool:
        """Whether a credential for the selected provider is present.

        The rest of the app (data API, visualizations) works without one, so this
        is checked rather than enforced at import time.
        """
        from app.agent.llm import provider_credential_present

        return provider_credential_present(self.llm_provider)


settings = Settings()
