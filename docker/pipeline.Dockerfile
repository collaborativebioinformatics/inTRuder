# Minimal environment for the novel TR pipeline's Python-based processes.
# Extend this as new steps (samtools, minimap2, etc.) get added.

FROM python:3.11-slim

# System-level build tools some Python packages need to compile against
# - autoconf/automake/libtool/pkg-config: needed by parasail's C build
# - zlib1g-dev/libbz2-dev/liblzma-dev/libcurl4-openssl-dev: needed by
#   cyvcf2, which wraps htslib and compiles against these
# - procps: provides `ps`, which Nextflow needs from inside the
#   container to collect task resource metrics
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    autoconf \
    automake \
    libtool \
    pkg-config \
    zlib1g-dev \
    libbz2-dev \
    liblzma-dev \
    libcurl4-openssl-dev \
    procps \
    && rm -rf /var/lib/apt/lists/*

# --- uv setup ---
# Pinned to 0.12.6 (released 2026-08-25) for reproducible builds
COPY --from=ghcr.io/astral-sh/uv:0.12.6 /uv /uvx /bin/

# Install directly into the system Python (no venv) - keeps this a
# simple single-purpose container.
ENV UV_PROJECT_ENVIRONMENT=/usr/local

WORKDIR /app

# The real pyproject.toml + uv.lock already exist in the repo (built by
# a teammate) - copy both so `uv sync --locked` installs the EXACT
# pinned versions already resolved, not a fresh re-resolution.
   COPY pyproject.toml uv.lock README.md ./

# `intruder` is declared as a real installable package built from
# src/python (see [tool.uv.build-backend] in pyproject.toml), so the
# source needs to be present before `uv sync` runs - it's not just
# installing third-party deps, it's building this project too.
COPY src/python ./src/python

RUN uv sync --locked

# Bundle sv_trfcaller.py at a stable, simple path for FIND_TRS to call
# (in addition to it already being installed as part of the novelty
# package above).
COPY src/python/intruder/pipeline/trf/sv_trfcaller.py /opt/scripts/sv_trfcaller.py

# Bundle normalize_svtype.py (from the annotation team's sv_preprocess
# pipeline - not yet merged to their main branch, so this is a local
# copy for now) for the PREPROCESS process to call directly. It's pure
# standard-library Python (argparse + gzip only), so no extra
# dependencies are needed for it.
COPY pipelines/sv_preprocess/scripts/normalize_svtype.py /opt/scripts/normalize_svtype.py

# Bundle filter_ins_trf.py (from the teammate who built the 02B
# filtering stage) for the FILTER_BY_COVERAGE process to call directly.
# It's pure standard-library Python (no external dependencies), so no
# extra packages are needed for it.
COPY src/python/intruder/pipeline/trf/filter_ins_trf.py /opt/scripts/filter_ins_trf.py

# --- Pre-bake novelty's reference catalogs (UCSC simpleRepeat ~30MB,
# TRExplorer ~45MB) at build time, so runs never need network access
# and are instant.
#
# IMPORTANT: novelty's default cache dir ("data/reference") is a
# RELATIVE path. Nextflow runs each task in its own work directory
# (not /app), so a relative path baked in at /app/data/reference would
# NOT be found at runtime - the container would silently look in the
# wrong place and re-download every run, defeating the whole point.
# Setting NOVELTY_CACHE as an absolute path fixes the location
# regardless of what directory a command is actually run from.
ENV NOVELTY_CACHE=/opt/novelty_cache

# Dummy query forces both catalogs to download and cache now, at build
# time, rather than on first real use.
RUN mkdir -p /opt/novelty_cache && \
    uv run novelty --platform ucsc,trexplorer query --chrom chr1 --pos 1000000 --motif AT
# More dependencies go in pyproject.toml as later pipeline stages need
# them - then re-run `uv lock` locally, commit the updated uv.lock, and
# rebuild.