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

RUN pip install --no-cache-dir pytrf parasail cyvcf2 tqdm

# You might not need to use python-slim
# DOWNLOAD UV instead of doing this then run "uv sync"
# RUN pip install --no-cache-dir pytrf parasail

# Bundle the pipeline's scripts directly into the image, so containerized
# runs are self-contained and don't depend on the container being able
# to see paths outside the pipeline's own folder on the host machine.
COPY src/python/sv_trfcaller.py /opt/scripts/sv_trfcaller.py

# More `pip install` and `COPY` lines go here as later pipeline stages
# get added.