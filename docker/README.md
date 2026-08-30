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

A third image — the Nextflow pipeline runtime — is a root `Dockerfile` on the
`nextflow-pipeline` branch, not here. The build workflow knows about all three.

## Published images

[`.github/workflows/docker.yml`](../.github/workflows/docker.yml) builds the
images and pushes them to GHCR. It is **manual only**: there is no trigger on
push or on pull request, because the pipeline image compiles htslib and
parasail from source and downloads ~75 MB of reference catalogs during its
build. Run it from the repository's **Actions → Docker → Run workflow**, or:

```bash
gh workflow run docker.yml -f image=backend
gh workflow run docker.yml -f image=pipeline -f ref=nextflow-pipeline
gh run watch $(gh run list --workflow=docker.yml -L1 --json databaseId -q '.[0].databaseId')
```

| Input | Default | |
|---|---|---|
| `image` | `all` | `backend`, `frontend`, `pipeline`, or all three |
| `ref` | the dispatched ref | branch/tag/SHA to build **from** — this is how you build a branch that has no copy of the workflow yet |
| `push` | true | uncheck to build only, as a validation run |
| `tag` | — | an extra tag, e.g. `v0.1.0` |
| `platforms` | `linux/amd64` | adding `linux/arm64` builds it under emulation, which is slow |
| `next_public_api_base` | `http://localhost:8000` | frontend only; inlined into the browser bundle at build time |

`image=all` skips any image whose Dockerfile is absent on the chosen ref;
asking for one by name and not finding it fails the run.

Each build is tagged with the sanitized ref name (`nextflow-pipeline`,
`andrewscouten-docker`), `sha-<short>`, and — only when building `main` —
`latest`:

```bash
docker pull ghcr.io/collaborativebioinformatics/intruder/backend:latest
docker pull ghcr.io/collaborativebioinformatics/intruder/frontend:latest
docker pull ghcr.io/collaborativebioinformatics/intruder/pipeline:nextflow-pipeline
```

The path is the project name lowercased — a Docker reference cannot hold the
capitals in inTRuder.

**A new package starts private.** The first push of each image creates it
under the organization's Packages, visible only to people with repository
access — `docker pull` from anywhere else fails with `denied` until someone
with admin rights opens the package → *Package settings* → *Change visibility*
→ **Public**. This is a one-time step per image, and it is what a Nextflow run
on someone else's machine needs:

```groovy
docker {
    docker.enabled = true
    process.container = 'ghcr.io/collaborativebioinformatics/intruder/pipeline:latest'
}
```

## Your own data

`./data` is bind-mounted at `/data`, and the backend is pointed at it with
`INTRUDER_DATA_DIR=/data` / `INTRUDER_REGISTRY_DIR=/data/web`. The registry
reads every `*.yaml` in `/data/web` and resolves each manifest's `path:`
against `/data`, so the whole dataset registry is swappable without rebuilding.

**The Upload button does all of this for you.** It writes the file to
`/data/uploads` — which is `./data/uploads` on your machine — and a manifest to
`/data/web`, then reloads the registry in place. No restart, no rebuild.

Nothing about that path is Docker-specific, which is the point: without a
container `INTRUDER_DATA_DIR` defaults to the repository's own `data/`, so
`just dev` puts uploads in the same directory and the feature behaves
identically. There is no code path that asks which mode it is running in.

By hand, the same thing in three steps:

1. Put your Parquet/CSV/TSV anywhere under `./data`.
2. Copy `data/web/demo-loci.yaml` to `data/web/my-dataset.yaml` and edit it —
   the `description` and `columns` prose is what the agent reads.
3. `docker compose restart backend`, or
   `curl -X POST localhost:8000/api/registry/reload`.

### Uploads on Linux

The service runs as an unprivileged user, and a bind mount on Linux keeps its
**host** ownership — so the container user has to be one that can write your
`./data`. Docker Desktop virtualizes this and needs nothing. On Linux:

```bash
UID=$(id -u) GID=$(id -g) docker compose build backend
```

The compose file already passes those through as build args. Without it the
first upload fails with a message naming the directory and this fix, rather
than a traceback.

### Both services listen on loopback

`docker-compose.yml` publishes `127.0.0.1:8000` and `127.0.0.1:3000`, not
`0.0.0.0`. The API accepts file uploads and writes them into the mount above
with no authentication in front of it; on all interfaces that would let anyone
on your network put files in `./data`. Serving it to other machines means
putting a proxy that authenticates in front, or setting `UPLOADS_ENABLED=false`.

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
