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
installed by default; the rest are optional so a clone does not pull every SDK
to run one.

| `LLM_PROVIDER` | Default model | Credential | Install |
|---|---|---|---|
| `anthropic` | `claude-opus-5` | `ANTHROPIC_API_KEY` | included |
| `claude-code` | the CLI's own | none — the Claude Code login | `uv add claude-agent-sdk` (bundles the CLI) |
| `google` | `gemini-2.5-pro` | `GOOGLE_API_KEY` | `uv add langchain-google-genai` |
| `ollama` | `llama3.1` | none (local) | `uv add langchain-ollama` |
| `openai` | `gpt-4o` | `OPENAI_API_KEY` | `uv add langchain-openai` |

The Anthropic path is the tuned one: adaptive thinking with a summarized display
(the default emits empty thinking blocks, which reads as a long pause), effort via
`LLM_EFFORT`, and no `temperature` — it is rejected on Opus 5.

`GET /api/health` reports which provider is configured and whether its credential
is present, including for `claude-code`, where "credential" means the CLI.

## Running on Claude Code

`LLM_PROVIDER=claude-code` runs chat through the Claude Code CLI already on your
machine, on that CLI's own login. It is the way to try the agent without an API
key of your own.

```bash
cd backend
uv add claude-agent-sdk    # ships its own CLI binary — no separate install needed
claude                     # once, to sign in — then quit it
echo "LLM_PROVIDER=claude-code" >> .env
uv run uvicorn app.main:app --reload
```

The SDK bundles a Claude Code binary, so the package is the whole install. What
it does not bring is a login: the credentials it uses are the ones under
`~/.claude`, which is what signing in once with `claude` puts there. Without them
chat answers "Claude Code is not logged in" and the data views carry on as
normal.

On an Intel Mac the SDK's transitive `cryptography` dependency has no wheel above
48.x for `macosx_x86_64` and will try to build from source; pin it in the same
command to stay on a prebuilt one: `uv add claude-agent-sdk 'cryptography<49'`.

Ask a question in the web UI. Nothing else changes: the same tools, the same
system prompt, the same streamed text, reasoning and `set_view` events, so the
frontend cannot tell which provider answered.

**What is different under the hood.** Claude Code brings its own agent loop, so
this provider does not build a chat model and the LangGraph graph is not used.
`app/agent/claude_code.py` hands the turn to the CLI instead, with the tools in
`app/tools/` attached as an in-process MCP server, and translates the reply back
into the same UI events. `app/agent/graph.py` picks between the two; `app/main.py`
does not know there are two.

**What the session can do.** Only what the agent can do anywhere else here:

- Every built-in Claude Code tool is off — no Read, Write, Edit, Bash or web
  access. The five tools in `app/tools/` are the whole surface, and `run_sql`
  keeps the same row and timeout guardrails.
- The system prompt is this app's, not Claude Code's.
- `~/.claude/settings.json`, `.claude/`, `CLAUDE.md` and any project `.mcp.json`
  are not loaded, so the answer does not depend on whose machine is serving.
- `CLAUDE_CODE_MAX_TURNS` (default 12) caps the tool-calling turns one chat
  request may take, since the loop is Claude Code's rather than LangGraph's.

`LLM_MODEL` and `LLM_EFFORT` are passed through; `LLM_MAX_TOKENS` is not, because
Claude Code manages its own output budget. Conversation history is re-sent as
text on each turn rather than resumed as a Claude Code session, which is what the
LangGraph path does too.

**When it does not work.** Every failure arrives as an error message in the chat
pane rather than a traceback: the SDK not installed says `uv add claude-agent-sdk`,
a missing CLI says where to get it, and a signed-out CLI says to run `claude`.

## Layout

| Path | Role |
|---|---|
| `app/main.py` | FastAPI routes |
| `app/config.py` | Settings from environment + `.env` |
| `app/agent/` | The model, the prompt, and the graph |
| `app/agent/llm.py` | Provider-pluggable chat model factory |
| `app/agent/claude_code.py` | The `claude-code` provider — runs the turn on the local CLI |
| `app/agent/prompt.py` | System prompt + the generated schema block |
| `app/agent/graph.py` | LangGraph graph + the UI event stream |
| `app/tools/` | What the agent can do |
| `app/tools/data.py` | `list_datasets`, `describe_dataset`, `run_sql` |
| `app/tools/view.py` | `set_view` — moves the frontend |
| `app/tools/vcf.py` | `describe_vcf` — reads a file, not a table |
| `app/util/registry.py` | Manifests → DuckDB tables; the guarded SQL path |
| `app/util/vcf/` | The VCF reader behind `describe_vcf` |
| `scripts/make_demo_data.py` | Generates the synthetic demo dataset |
| `scripts/fetch_strchive.py` | Downloads + checksums the STRchive disease catalog |

Three packages, three jobs: `agent/` is how the model is driven, `tools/` is what
it can do, `util/` is what those are built on. A contributor adding a capability
adds a module to `tools/` and a line to `app/tools/__init__.py`; nothing else
moves.

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

`/api/loci` takes a genomic range in `region`, written the way a person writes
one — `chr3:1,000-50,000`, with the `chr` and the separators optional and `..`
allowed for `-`. Both ends are inclusive, and a candidate is an insertion
*point*, so overlapping the range means the insertion site falls inside it. A
range that does not parse is a 400 rather than an empty list: an empty list would
read as a finding. `gene_query` is the free-text counterpart of `gene`, matching
any gene symbol containing the text.

`/api/loci` accepts filters that need columns only the screened callset supplies
(`novelty`, `platform_agreement`, `min_insertion_purity`, `sample`,
`strchive_status`). Against a table lacking them the filter is **not** applied and
comes back in `ignored_filters`; the frontend draws it struck-through. A control
that silently matches everything reads as a result, which is worse than an error.

## The agent

A prebuilt LangGraph ReAct graph over five tools:

- `list_datasets` — what data exists
- `describe_dataset` — per-column docs from the manifest
- `run_sql` — read-only DuckDB over the registered tables
- `set_view` — **moves the frontend**, which is what makes chat and the charts
  two views of one state rather than two panels. It also switches surface
  (`page="catalog" | "strchive"`), so a question about disease can land the user
  on the disease-locus view.
- `describe_vcf` — **reads a file rather than a table**, for the one question the
  registry cannot answer: what is this VCF?

The count of *data* tools does not grow with the number of datasets. Contributors
add a manifest; the agent surface is unchanged. See `data/web/README.md`.

Swapping `create_react_agent` for a custom `StateGraph` is a change to
`app/agent/graph.py` alone — the tools, the prompt, the SSE protocol, and the
frontend are unaffected.

### `describe_vcf`

Everything else the agent knows came from a table somebody curated. A raw VCF has
not been curated, and the first honest thing to say about one is what it *is*.

Where the inserted sequence lives is a property of the dialect, not of the
format. A single-sample Sniffles record carries the whole insertion in `ALT`. A
SURVIVOR merge carries one representative allele there and the per-sample truth
in `FORMAT/AAL` minus its `FORMAT/RAL` anchor, at the breakpoint in `FORMAT/CO`
— which in this cohort's callset sits a median of 34 bp away from record `POS`.
Reading the merged file the single-sample way does not fail; it returns the wrong
sequence at the wrong coordinate, quietly.

So the tool reports before anything extracts, and prefers observation to
assertion:

| Reported | How it is decided |
|---|---|
| samples, layout, assembly | `#CHROM` columns; `##contig` lengths, as a labelled guess |
| callers | `##source` **and** the per-sample variant IDs — `##source` names the merger, not what was merged |
| ALT representation | counted per record: literal sequence vs. symbolic `<INS>` |
| which key holds sequence / length / breakpoint / source ID | the header's declared type and description, **confirmed against the values present**; every role ships with the evidence that chose it |
| the disagreements | five insertion records extracted **both ways**, plus counts over the whole scan |

Counts are over the records actually read; `scan.complete` says whether that was
the file. `VCF_MAX_RECORDS` sets the bound, and a very wide file lowers it
further and says so, rather than spending the budget on sample columns.

Paths are confined to `NOVELTRS_VCF_ROOT` (the data directory by default),
resolved through symlinks before the check — agent SQL gets no filesystem access
at all, so the one tool that opens a file is the narrow checked path rather than
the hole in that wall. A path that does not resolve comes back with the list of
ones that do, the way `describe_dataset` answers an unknown name with the known
ones. BCF is refused with the `bcftools` command that converts it.

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
uv run ruff check app scripts tests
uv run pytest
```

`tests/test_vcf.py` runs against the committed callsets under
`data/sv_output` — one single-sample Sniffles VCF and one SURVIVOR merge of 69 of
them. Both are needed: a reader that reports the same thing about both is not
reporting anything.

To read a VCF outside the API:

```bash
uv run python -m app.util.vcf ../data/sv_output/sniffles/raw/HG00290.raw.sniffles.vcf
```
