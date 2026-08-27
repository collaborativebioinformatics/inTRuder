# Minimal environment for the novel TR pipeline's Python-based processes.
# Extend this as new steps (samtools, minimap2, etc.) get added.

FROM python:3.11-slim

# System-level build tools some Python packages need to compile against
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    autoconf \
    automake \
    libtool \
    pkg-config \
    procps \
    && rm -rf /var/lib/apt/lists/*


RUN pip install --no-cache-dir pytrf parasail

# Bundle the pipeline's scripts directly into the image, so containerized
# runs are self-contained and don't depend on the container being able
# to see paths outside the pipeline's own folder on the host machine.
COPY src/python/sv_trfcaller.py /opt/scripts/sv_trfcaller.py

# More `pip install` and `COPY` lines go here as later pipeline stages
# get added.