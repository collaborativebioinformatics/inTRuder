# Backend (`backend/`)

FastAPI service backing the web interface: a DuckDB-backed data API for the
visualizations, and a LangGraph agent streamed over server-sent events.

This is a **standalone uv project**. It deliberately does not share a lockfile or
an environment with the repository root, which manages the research pipeline
under `src/python`. Two separate dependency sets, two `.venv`s.

## Setup

```bash
cd backend
uv sync                                   # creates backend/.venv
cp .env.example .env                      # then add a model credential
uv run python scripts/make_demo_data.py   # writes data/web/demo/*.parquet
uv run python scripts/fetch_strchive.py   # writes data/web/strchive/loci.parquet
uv run uvicorn app.main:app --reload
```

The API comes up on <http://localhost:8000>. Interactive docs at `/docs`.

The data API works without any model credential — only chat needs one.
`GET /api/health` reports which provider is configured and whether its key is present.

## Model providers

Selected with `LLM_PROVIDER` in `.env`. Only the Anthropic integration is
installed by default; the rest are optional so a clone does not pull four SDKs.

| `LLM_PROVIDER` | Default model | Credential | Install |
|---|---|---|---|
| `anthropic` | `claude-opus-5` | `ANTHROPIC_API_KEY` | included |
| `google` | `gemini-2.5-pro` | `GOOGLE_API_KEY` | `uv add langchain-google-genai` |
| `ollama` | `llama3.1` | none (local) | `uv add langchain-ollama` |
| `openai` | `gpt-4o` | `OPENAI_API_KEY` | `uv add langchain-openai` |

The Anthropic path is the tuned one: adaptive thinking with a summarized display
(the default emits empty thinking blocks, which reads as a long pause), effort via
`LLM_EFFORT`, and no `temperature` — it is rejected on Opus 5.

## Layout

| Path | Role |
|---|---|
| `app/config.py` | Settings from environment + `.env` |
| `app/llm.py` | Provider-pluggable chat model factory |
| `app/registry.py` | Manifests → DuckDB tables; the guarded SQL path |
| `app/tools.py` | The four agent tools |
| `app/agent.py` | LangGraph graph + the UI event stream |
| `app/main.py` | FastAPI routes |
| `scripts/make_demo_data.py` | Generates the synthetic demo dataset |
| `scripts/fetch_strchive.py` | Downloads + checksums the STRchive disease catalog |

## Endpoints

| Route | Purpose |
|---|---|
| `GET /api/health` | Dataset and provider status |
| `GET /api/datasets` | Full manifest detail for every registered dataset |
| `GET /api/summary` | Cohort funnel, novel fraction by class and chromosome |
| `GET /api/loci` | Filtered locus list; `include_strips=true` adds barcode segments |
| `GET /api/loci/{id}` | One locus plus every carrier's segment structure |
| `GET /api/strchive/summary` | Disease-catalog counts, plus this cohort's screen if run |
| `GET /api/strchive/loci` | The 82 curated disease loci, filtered |
| `GET /api/strchive/matches` | Our candidates that landed on a disease locus |
| `POST /api/chat` | SSE stream of one agent turn |

`/api/loci` accepts filters that need columns only the screened callset supplies
(`novelty`, `platform_agreement`, `min_insertion_purity`, `sample`,
`strchive_status`). Against a table lacking them the filter is **not** applied and
comes back in `ignored_filters`; the frontend draws it struck-through. A control
that silently matches everything reads as a result, which is worse than an error.

## The agent

A prebuilt LangGraph ReAct graph over four tools:

- `list_datasets` — what data exists
- `describe_dataset` — per-column docs from the manifest
- `run_sql` — read-only DuckDB over the registered tables
- `set_view` — **moves the frontend**, which is what makes chat and the charts
  two views of one state rather than two panels

The tool count does not grow with the number of datasets. Contributors add a
manifest; the agent surface is unchanged. See `data/web/README.md`.

Swapping `create_react_agent` for a custom `StateGraph` is a change to
`app/agent.py` alone — the tools, the SSE protocol, and the frontend are unaffected.

### SQL sandbox

The model writes the SQL, so the query path is narrow by construction:

1. Datasets are materialized into a DuckDB file at startup.
2. The file is reopened **read-only**; that connection serves agent queries.
3. `enable_external_access=false` — no filesystem reads (`read_parquet('/etc/…')` fails).
4. Only a single `SELECT`/`WITH` statement is accepted.
5. Results are capped at `MAX_SQL_ROWS` and report truncation.

Tradeoff: materializing costs memory. Fine for the demo and mid-sized callsets;
switch to views for multi-GB inputs and re-do step 3 accordingly.

## Development

```bash
uv run ruff check app scripts
uv run pytest
```
