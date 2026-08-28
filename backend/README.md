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
| `app/tools/data.py` | `list_datasets`, `describe_dataset`, `run_sql`, `list_uploads` |
| `app/tools/view.py` | `set_view` — moves the frontend |
| `app/tools/vcf.py` | `describe_vcf` — reads a file, not a table |
| `app/tools/literature.py` | `search_literature` — reads Europe PMC, not us |
| `app/tools/hpo.py` | `resolve_phenotype` — free text to validated HPO terms to genes |
| `app/util/registry.py` | Manifests → DuckDB tables; the guarded SQL path |
| `app/util/vcf/` | The VCF reader behind `describe_vcf` |
| `app/util/europepmc.py` | Europe PMC client: the query ladder, scoring, rate limiting |
| `app/util/hpo_pipeline.py` | The phenotype-to-genes pipeline behind `resolve_phenotype` |
| `scripts/make_demo_data.py` | Generates the synthetic demo dataset |
| `scripts/fetch_strchive.py` | Downloads + checksums the STRchive disease catalog |
| `scripts/fetch_hpo.py` | Downloads + checksums the HPO gene-phenotype release |
| `scripts/build_hpo_index.py` | One-time: builds the HPO term embedding index |

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
any gene symbol containing the text. `genes` is an exact, case-insensitive match
against a specific list of symbols — the shape `resolve_phenotype` returns.

`/api/loci` accepts filters that need columns only the screened callset supplies
(`novelty`, `platform_agreement`, `min_insertion_purity`, `sample`,
`strchive_status`). Against a table lacking them the filter is **not** applied and
comes back in `ignored_filters`; the frontend draws it struck-through. A control
that silently matches everything reads as a result, which is worse than an error.

## The agent

A prebuilt LangGraph ReAct graph over seven tools:

- `list_datasets` — what data exists
- `describe_dataset` — per-column docs from the manifest
- `run_sql` — read-only DuckDB over the registered tables
- `list_uploads` — the files someone has handed the interface, and whether each
  one is queryable yet. A VCF is not a table until the pipeline has run on it,
  and the tool says so rather than implying the data is available.
- `set_view` — **moves the frontend**, which is what makes chat and the charts
  two views of one state rather than two panels. It also switches surface
  (`page="catalog" | "strchive"`), so a question about disease can land the user
  on the disease-locus view.
- `describe_vcf` — **reads a file rather than a table**, for the one question the
  registry cannot answer: what is this VCF?
- `search_literature` — **reads a third-party index rather than our own data**,
  and is the only source of citations.
- `resolve_phenotype` — free-text clinical description in, a gene list out, via
  HPO terms validated against the live ontology. See below.

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

### `search_literature`

Europe PMC, no API key. It is the only tool whose data nobody here curated, and
its failure mode is not an empty answer but a confident one built on the wrong
search: a broken query comes back as a large, plausible, relevance-sorted result
set rather than an error.

Two ways that happens, both measured against the live API and pinned in
`tests/test_literature.py`:

**Malformed.** `GENE:` does not survive a boolean `OR`, in either direction:

| Query | Hits | What actually happened |
|---|---|---|
| `GENE:"RFC1" OR GENE:"XYLT1"` | 1,260 | `= GENE:"XYLT1"` alone — only the last disjunct survives |
| `GENE:"RFC1" OR TITLE_ABS:"RFC1"` | 5,634,780 | the GENE clause becomes *any gene-annotated record* |
| `TITLE_ABS:"RFC1" OR GENE:"RFC1"` | 2,659 | `= ` bare `RFC1` — collapses to unfielded free text |
| `FOOBAR:"RFC1"` | 0 | unknown field, no error — a typo reads as "no papers exist" |

So `_or_group` takes **one field for the whole group**, which makes a cross-field
OR unrepresentable rather than merely discouraged, and field names come from a
frozen allowlist. A regression test parses every composed query and fails if any
`OR` group mentions two fields.

**Well-formed but wrong**, which is the harder one. `RFC1 AND (tandem repeat OR
…)` is a perfectly good query returning 227 papers, of which 30% mention RFC1 in
the title or abstract — the bare term matches full text, so citation-sorting
floats papers that mention the gene once in passing. On an ambiguous symbol it is
worse: `AR AND (…)` returns 3,712 whose top hit is about JAK2. Neither hit count
reveals it.

So the tool does not compose one query. It composes several framings, runs them
concurrently, and scores each **against the records it returned** — what fraction
carry the terms the caller said must be there:

```
AR / CAG / SBMA                       must_mention=["androgen"]
  WIN strict        hits=    50  spec=4  cov= 90%  pass
      gene+motif    hits=   259  spec=3  cov= 60%  pass
      gene+disease  hits=    64  spec=3  cov= 90%  pass
      gene+context  hits=  3809  spec=2  cov= 10%  off_target
      gene_fielded  hits=   420  spec=2  cov= 80%  pass
      gene          hits=942435  spec=1  cov=  0%  degenerate
```

The most specific framing that passes wins; fewest hits breaks a tie. Specificity
rather than size leads, because "smallest result set" alone would reward a query
that is precise about the wrong thing — and more clauses means fewer hits anyway.
The **whole scoreboard** ships with the answer, so the transcript shows what was
tried and why one was chosen, the same way `describe_vcf` reports both readings of
a record instead of asserting one.

`must_mention` is the model's domain knowledge entering as a **falsifiable test**
rather than a claim — "if these papers do not mention androgen, my query went
wrong." A self-reported confidence score would not be checkable; this is. It
defaults to the gene symbol, and coverage reports as `null` rather than as a pass
when there is nothing to check against.

Finding nothing returns `results: []` with an explicit instruction not to fill in
from memory. For a project about repeats nobody has catalogued, that is a real
finding.

#### Rate limiting

Europe PMC publishes **no quota**. The "10 requests/second" figure in circulation
comes from a forum poster; asked directly, Europe PMC confirmed only that *"the
API limit is applied per IP address"* and gave no number ([epmc-webservices, Dec
2024](https://groups.google.com/a/ebi.ac.uk/g/epmc-webservices/c/cZLnV1JhCj8)).
Responses carry no `RateLimit-*` or `Retry-After` headers, so there is nothing to
read a budget from at runtime either.

Two consequences, and they are the whole design:

1. **Per IP means per process, not per session.** Every conversation this backend
   serves shares one address, so the limiter is a module-level singleton and
   concurrent turns queue behind each other rather than each getting an allowance.
2. **With no verifiable ceiling, stay far under the unofficial one** and handle
   rejection properly, rather than pacing up to a number nobody has confirmed.
   The default 5 rps is half the folklore figure and ~30x what a turn needs: one
   question is about six requests, cached.

Token bucket at `EUROPEPMC_RATE_LIMIT_RPS`, a separate concurrency semaphore, up
to 3 attempts with `Retry-After` honoured and jittered exponential backoff
otherwise, and a TTL cache keyed on the exact query so overlapping ladders share
rungs. The one policy Europe PMC *does* state — no automated bulk downloading —
is respected by never paginating: one page, capped at `LITERATURE_MAX_RESULTS`.

### `resolve_phenotype`

Free-text clinical language is not a controlled vocabulary, so it has to be
mapped to real HPO terms before it can drive a gene lookup — and the central
risk in that mapping is a hallucinated HPO id reaching the interface. Six
steps, four of them behind this one tool:

1. **Embed** the free text with `sentence-transformers` (`all-mpnet-base-v2`).
2. **Nearest-neighbor search** against a precomputed index of every HPO term's
   name and synonyms, embedded with the same model (`scripts/build_hpo_index.py`,
   a one-time build, not part of the request path).
3. **`resolve_hpo()`** — the one mandatory checkpoint. A pure existence check
   against `PyHPO`'s live `Ontology`, nothing else: is this id real, and not
   obsolete? A candidate that fails is dropped and never reaches steps 4-6 or
   the UI, regardless of how it was proposed. Rejects for exactly two reasons:
   the id does not exist, or it existed once and was retired/merged
   (`Ontology` exposes `is_obsolete` / `replaced_by` for that second case).
4. **Related terms** — the validated term's parents/children, read directly off
   the `PyHPO` term object (already wired up when it loaded), shown as
   informational context. Deliberately does **not** feed step 5: the gene query
   stays traceable to what was actually validated, not silently widened.
5. **Gene join** — validated term(s) only, against `hpo_gene_phenotype`
   (`scripts/fetch_hpo.py`, the official HPO Consortium release).
6. **`set_view(genes=[...])`** — the agent's own follow-up call, not part of
   the tool.

**The threshold is load-bearing, and it has a real gap, not a rule of thumb.**
Five nonsense phrases best-matched the index at 0.194-0.486; five phrases with
an obvious correct HPO concept matched at 0.709-0.754 (`all-mpnet-base-v2`,
this index — reproduce with `tests/test_hpo_pipeline.py::test_threshold_calibration`).
The gap does not overlap, so `DEFAULT_SIMILARITY_THRESHOLD = 0.6` in
`app/util/hpo_pipeline.py` is placed in the middle of it.

**What the threshold does not catch:** a confidently-scored match can still be
the wrong concept. "curved spine" — the phenotype-to-loci spec's own worked
example, expected to match Scoliosis — actually matches "Abnormally straight
spine" top-1 with this model (score 0.726, comfortably above threshold), and
Scoliosis does not appear even in the top 8 candidates. `resolve_hpo()`
correctly does not reject it — it *is* a real, current term — but it is
arguably the wrong one. This is inherent to a general-purpose text embedding
on clinical phrasing, not a bug, and is the documented motivation for the
spec's own suggested upgrade to a clinical embedding model (e.g. ClinicalBERT).
The tool's docstring tells the agent to sanity-check a validated term's name
against what the user actually described rather than trust the score alone.

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
uv run pytest                 # offline; the network canaries are deselected
uv run pytest -m network      # the two that call Europe PMC
```

The `network` canaries assert that the Europe PMC quirks `app/util/europepmc.py`
works around are *still* quirks. If upstream fixes its parser they fail, which is
how we find out the workaround is obsolete instead of leaving it fossilized.

`tests/test_vcf.py` runs against the committed callsets under
`data/sv_output` — one single-sample Sniffles VCF and one SURVIVOR merge of 69 of
them. Both are needed: a reader that reports the same thing about both is not
reporting anything.

To read a VCF outside the API:

```bash
uv run python -m app.util.vcf ../data/sv_output/sniffles/raw/HG00290.raw.sniffles.vcf
```
