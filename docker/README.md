# Docker (`docker/`)

Container images for the two web services. The compose file that wires them
together lives at the repository root.

```bash
docker compose up --build     # frontend on :3000, API on :8000
docker compose down
```

| File | Image |
|---|---|
| `backend.Dockerfile` | FastAPI + LangGraph + DuckDB (`uv sync --frozen --no-dev`, runs as uid 10001) |
| `frontend.Dockerfile` | Next.js production build served by `next start` (runs as `node`) |

Both build from the **repository root** as context, governed by the root
`.dockerignore`. Nothing under `data/` is copied into either image.

## Your own data

`./data` is bind-mounted at `/data`, and the backend is pointed at it with
`NOVELTRS_DATA_DIR=/data` / `NOVELTRS_REGISTRY_DIR=/data/web`. The registry
reads every `*.yaml` in `/data/web` and resolves each manifest's `path:`
against `/data`, so the whole dataset registry is swappable without rebuilding:

1. Put your Parquet/CSV/TSV anywhere under `./data`.
2. Copy `data/web/demo-loci.yaml` to `data/web/my-dataset.yaml` and edit it —
   the `description` and `columns` prose is what the agent reads.
3. `docker compose restart backend`.

The manifest format and why it is a YAML file rather than a code change are in
[`data/web/README.md`](../data/web/README.md).

Data you keep **outside** the repository needs a second mount. Uncomment the
example in `docker-compose.yml`, point it at your directory, and have the
manifest's `path:` refer to the container path:

```yaml
- /scratch/callsets:/mnt/extra:ro     # then: path: /mnt/extra/my_calls.parquet
```

The mount is read-write so the dataset scripts can run in the container too:

```bash
docker compose run --rm backend python scripts/make_demo_data.py   # synthetic demo tables
docker compose run --rm backend python scripts/fetch_strchive.py   # disease-locus catalog
```

A manifest whose file is missing is reported as unavailable rather than
crashing the backend, so a partial `./data` still comes up. `GET
/api/health` lists what loaded and what did not.

## Credentials

Chat needs a model credential; the data views do not. The backend reads
`backend/.env` if it exists (`cp backend/.env.example backend/.env`), and any
of the same variables exported in your shell override it for that run:

```bash
ANTHROPIC_API_KEY=sk-... docker compose up
```

## Serving from somewhere other than localhost

`NEXT_PUBLIC_API_BASE` is inlined into the browser bundle at **build** time, so
it is the URL your browser resolves — not `backend:8000`, which only exists
inside the compose network. Point it at the host and rebuild, and let the
backend's CORS allowlist know about the new origin:

```bash
NEXT_PUBLIC_API_BASE=https://api.example.org docker compose build frontend
CORS_ORIGINS=https://app.example.org docker compose up
```

## Development

These images are production-shaped: the source is baked in and there is no
reloader. For day-to-day work use the host toolchain, which reloads on save:

```bash
just setup && just dev
```
