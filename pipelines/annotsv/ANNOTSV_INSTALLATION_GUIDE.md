# AnnotSV Installation Guide

> **Version**: AnnotSV 3.5.10  
> **Date**: August 2026  
> **System**: Linux (Ubuntu), x86_64  
> **Prepared by**: BCM Hackathon 2026 — novelTRs project  

---

## Table of Contents

1. [Overview](#overview)
2. [Prerequisites](#prerequisites)
3. [Method 1 — Install from Source (GitHub)](#method-1--install-from-source-github)
4. [Method 2 — Install via Mamba / Conda](#method-2--install-via-mamba--conda)
5. [Downloading Annotation Databases](#downloading-annotation-databases)
6. [Known Issues and Fixes](#known-issues-and-fixes)
7. [Running a Test](#running-a-test)
8. [Quick-Start Wrapper Script](#quick-start-wrapper-script)
9. [Permanent Environment Setup](#permanent-environment-setup)

---

## Overview

AnnotSV is a tool for annotation and ranking of structural variants (SVs) and copy number variants (CNVs). It integrates annotations from ClinVar, gnomAD, ClinGen, OMIM, DGV, 1000 Genomes, and many more.

- **GitHub**: https://github.com/lgmgeo/AnnotSV  
- **Documentation**: https://lbgi.fr/AnnotSV/  
- **Dependencies**: `tclsh` (Tcl/Tk ≥ 8.5), `bedtools`, `bcftools`

---

## Prerequisites

Install the following before proceeding:

```bash
# Check if tclsh is available
which tclsh || echo "tclsh missing"
tclsh <<< "puts [info tclversion]"   # should print 8.5 or higher

# Install tclsh via conda/mamba if missing
mamba install -c conda-forge tcl

# bedtools and bcftools (install in your active environment)
mamba install -c bioconda bedtools bcftools
```

---

## Method 1 — Install from Source (GitHub)

This is the recommended method for the latest version.

### Step 1 — Clone the repository

```bash
# Choose an install location WITHOUT SPACES in the path (critical — see Known Issues)
git clone https://github.com/lgmgeo/AnnotSV.git /home/$USER/tools/AnnotSV
cd /home/$USER/tools/AnnotSV
```

### Step 2 — Install AnnotSV

AnnotSV uses a `Makefile`-based install that copies files to a prefix directory.

```bash
# Install into the repo directory itself (self-contained)
make PREFIX=/home/$USER/tools/AnnotSV install

# Or install system-wide (requires sudo)
sudo make install
```

> **Note**: If you clone into the default location and run `make install` with no `PREFIX`, it installs to `/usr/local/`. Using a local `PREFIX` keeps everything self-contained.

### Step 3 — Verify the binary

```bash
export ANNOTSV=/home/$USER/tools/AnnotSV
$ANNOTSV/bin/AnnotSV -help | head -5
```

Expected output:
```
AnnotSV 3.5.10
Copyright (C) 2017-current GEOFFROY Veronique
Tcl/Tk version: 8.6
```

---

## Method 2 — Install via Mamba / Conda

> **Note**: The conda package typically lags behind the GitHub release by a few versions. Use Method 1 for the latest version.

```bash
# Create a dedicated environment
mamba create -n annotsv -c bioconda -c conda-forge annotsv bedtools bcftools

# Activate
conda activate annotsv

# Verify
AnnotSV -help | head -3
```

When installed via conda, AnnotSV is in `$CONDA_PREFIX/bin/AnnotSV` and the `ANNOTSV` environment variable is set automatically.

> **Important**: Conda installs AnnotSV **without** annotation databases. You must download them separately (see next section).

---

## Downloading Annotation Databases

AnnotSV requires two sets of annotation databases:

| Database set | Size (compressed) | Extracted size |
|---|---|---|
| `Annotations_Human_3.5.tar.gz` | ~5 GB | ~30 GB |
| Exomiser phenotype data (`2406_phenotype.zip`) | ~1 GB | ~3 GB |

### Option A — Use the provided install script

```bash
export ANNOTSV=/home/$USER/tools/AnnotSV

# This script downloads and extracts both databases automatically
bash $ANNOTSV/bin/INSTALL_annotations.sh
```

By default, databases are placed in `./AnnotSV_annotations/`. Pass the directory to AnnotSV at runtime with `-annotationsDir`.

### Option B — Manual download and extraction (recommended for large files)

This is what was done for this installation since the tarball was already downloaded.

```bash
export ANNOTSV=/home/$USER/tools/AnnotSV

# ---- Human annotation database ----
# Download the tarball (if not already downloaded)
cd $ANNOTSV
curl -C - -LO "https://www.lbgi.fr/~geoffroy/Annotations/Annotations_Human_3.5.tar.gz"

# Extract INTO share/AnnotSV/ — this is where AnnotSV looks by default
cd "$ANNOTSV/share/AnnotSV/"
tar -xzf "$ANNOTSV/Annotations_Human_3.5.tar.gz"
# Creates: $ANNOTSV/share/AnnotSV/Annotations_Human/

# ---- Exomiser phenotype database ----
EXOMISER_VERSION="2406"
cd "$ANNOTSV/share/AnnotSV/"
curl -C - -LO "https://data.monarchinitiative.org/exomiser/data/${EXOMISER_VERSION}_phenotype.zip"
mkdir -p "Annotations_Exomiser/${EXOMISER_VERSION}/"
unzip "${EXOMISER_VERSION}_phenotype.zip" -d "Annotations_Exomiser/${EXOMISER_VERSION}/"
rm -f "${EXOMISER_VERSION}_phenotype.zip"
```

### Verify the database structure

After extraction, `share/AnnotSV/` should look like:

```
share/AnnotSV/
├── Annotations_Human/
│   ├── AnyOverlap/
│   ├── BreakpointsAnnotations/
│   ├── FtIncludedInSV/
│   ├── Gene-based/
│   ├── Genes/
│   │   ├── GRCh37/
│   │   └── GRCh38/
│   ├── SVincludedInFt/
│   └── Users/
├── Annotations_Exomiser/
│   └── 2406/
└── jar/
```

---

## Known Issues and Fixes

### ❌ Issue 1 — Spaces in the installation path break `bedtools` calls

**Symptom**:
```
Error: Unable to open file {/path/with spaces/AnnotSV/share/AnnotSV/Annotations_Human/Genes/GRCh37/genes.RefSeq.sorted.bed}
```

**Root cause**: AnnotSV is written in Tcl. When Tcl passes paths to external commands (like `bedtools`), it wraps paths containing spaces in curly braces `{...}`. Bash interprets these literally and `bedtools` cannot find the file.

**Fix**: Create a permanent symlink from a space-free path to the actual AnnotSV directory:

```bash
# Create the symlink once
mkdir -p /home/$USER/tools
ln -sfn "/path/with spaces/to/AnnotSV" /home/$USER/tools/AnnotSV

# Always use the symlink path, never the space-containing path
export ANNOTSV=/home/$USER/tools/AnnotSV
```

For this installation:
```bash
ln -sfn "/home/taimoor/taimoor-data/genomics/research/Other research project/bcm-hackathon26/novelTRs/AnnotSV" \
        /home/taimoor/tools/AnnotSV
```

> **Best practice**: Always install AnnotSV to a path with no spaces from the start (e.g., `/home/$USER/tools/AnnotSV`).

---

### ❌ Issue 2 — `bedtools` or `bcftools` not found

**Symptom**:
```
Bad value for the bedtools option (bedtools)
couldn't execute "bedtools": no such file or directory
```

**Root cause**: AnnotSV calls `bedtools` and `bcftools` by name. They must be on `$PATH` or passed explicitly.

**Fix**: Pass full paths via command-line flags:

```bash
$ANNOTSV/bin/AnnotSV \
  -bedtools /home/$USER/miniforge3/envs/vardigs/bin/bedtools \
  -bcftools /home/$USER/miniforge3/envs/vardigs/bin/bcftools \
  ...
```

Or set them permanently in `etc/AnnotSV/configfile`:
```
-bedtools: "/home/taimoor/miniforge3/envs/vardigs/bin/bedtools"
-bcftools: "/home/taimoor/miniforge3/envs/vardigs/bin/bcftools"
```

---

### ❌ Issue 3 — `bcftools` from conda `pkgs/` cache fails with missing shared libraries

**Symptom**:
```
bcftools: error while loading shared libraries: libhts.so.3: cannot open shared object file: No such file or directory
```

**Root cause**: Binaries in `~/miniforge3/pkgs/` (the package download cache) are not linked to their runtime libraries. Only binaries inside an actual conda environment (`envs/<name>/bin/`) have their RPATH and library paths correctly configured.

**Fix**: Use the binary from a real conda environment, not the pkgs cache:

```bash
# ❌ Don't use — pkgs cache binaries have broken shared lib links
/home/$USER/miniforge3/pkgs/bcftools-1.24-.../bin/bcftools

# ✅ Use — from an actual conda environment
/home/$USER/miniforge3/envs/vardigs/bin/bcftools
```

If you don't have an environment with `bcftools`:
```bash
mamba create -n sv_tools -c bioconda bedtools bcftools
/home/$USER/miniforge3/envs/sv_tools/bin/bcftools --version
```

---

### ❌ Issue 4 — Wrong `tar` command silently fails to extract

**Symptom**: `AnnotSV` runs but finds no genes overlapping SVs; `share/AnnotSV/Annotations_Human/` does not exist.

**Root cause**: Running `tar -xzf archive.tar.gz .` with a trailing `.` causes:
```
tar: .: Not found in archive
tar: Exiting with failure status due to previous errors
```
The `.` is interpreted as a member name to extract, not a destination directory.

**Fix**: `cd` to the target directory first, then extract without specifying a path:

```bash
# ❌ Wrong
tar -xzf Annotations_Human_3.5.tar.gz .

# ✅ Correct
cd "$ANNOTSV/share/AnnotSV/"
tar -xzf "$ANNOTSV/Annotations_Human_3.5.tar.gz"
```

---

### ⚠️ Warning — GeneHancer not available (non-fatal)

**Symptom**:
```
WARNING: No GeneHancer annotations available.
```

**Explanation**: GeneHancer data requires a license from the GeneCards team. This is a **non-fatal warning** — AnnotSV completes the analysis fully without it, but enhancer-gene regulatory links will be absent.

**Fix (optional)**: Contact GeneCards at https://www.genecards.org and request academic access. Place the downloaded file in `share/AnnotSV/Annotations_Human/Regulatory_regions/GeneHancer/`.

---

## Running a Test

This installation includes 39 test cases in `tests/AnnotSV/`. The standard smoke test uses the HG00096 (1000 Genomes) SV call set:

```bash
export ANNOTSV=/home/taimoor/tools/AnnotSV   # the symlink — no spaces

mkdir -p "$ANNOTSV/test_output"

"$ANNOTSV/bin/AnnotSV" \
  -SVinputFile "$ANNOTSV/tests/AnnotSV/test_02_HG00096/input/HG00096.wgs.mergedSV.v8.20130502.svs.genotypes.bed" \
  -svtBEDcol 4 \
  -SVinputInfo 1 \
  -outputFile "$ANNOTSV/test_output/test02_HG00096.annotated.tsv" \
  -genomeBuild GRCh37 \
  -bedtools "/home/taimoor/miniforge3/envs/vardigs/bin/bedtools" \
  -bcftools "/home/taimoor/miniforge3/envs/vardigs/bin/bcftools" \
  -annotationsDir "$ANNOTSV/share/AnnotSV"
```

### Expected output

```
...AnnotSV is done with the analysis (August 26 2026 - 23:09)
```

| Metric | Value |
|---|---|
| Output file | `test_output/test02_HG00096.annotated.tsv` |
| Output lines | 6,889 rows (full + split annotations) |
| Output size | ~8.3 MB |
| Annotation columns | 107 (ACMG class, ClinVar, gnomAD, OMIM, ClinGen HI/TS, ExAC pLI, etc.) |

A pre-computed output is already saved at: `test_output/test02_HG00096.annotated.tsv`

---

## Quick-Start Wrapper Script

Save as `run_annotsv.sh` in the project directory for easy reuse. All paths are pre-configured.

```bash
#!/usr/bin/env bash
# run_annotsv.sh — AnnotSV wrapper with pre-configured paths for this installation
# Usage: bash run_annotsv.sh -SVinputFile my_svs.vcf -outputFile test_output/result.tsv [options]
#
# Outputs go to test_output/ inside the AnnotSV project directory.

set -euo pipefail

ANNOTSV="/home/taimoor/tools/AnnotSV"
BEDTOOLS="/home/taimoor/miniforge3/envs/vardigs/bin/bedtools"
BCFTOOLS="/home/taimoor/miniforge3/envs/vardigs/bin/bcftools"
ANNOTATIONS_DIR="$ANNOTSV/share/AnnotSV"

mkdir -p "$ANNOTSV/test_output"

"$ANNOTSV/bin/AnnotSV" \
  -bedtools        "$BEDTOOLS" \
  -bcftools        "$BCFTOOLS" \
  -annotationsDir  "$ANNOTATIONS_DIR" \
  "$@"
```

Make it executable:
```bash
chmod +x run_annotsv.sh
```

Example usage:
```bash
bash run_annotsv.sh \
  -SVinputFile my_svs.vcf \
  -outputFile test_output/my_output.tsv \
  -genomeBuild GRCh38
```

---

## Permanent Environment Setup

Add to `~/.bashrc` or `~/.bash_profile` to avoid passing paths every time:

```bash
# AnnotSV — use the symlink (no spaces in path)
export ANNOTSV="/home/taimoor/tools/AnnotSV"
export PATH="$ANNOTSV/bin:$PATH"

# Dependency binaries (conda env vardigs — tested and working)
export BEDTOOLS="/home/taimoor/miniforge3/envs/vardigs/bin/bedtools"
export BCFTOOLS="/home/taimoor/miniforge3/envs/vardigs/bin/bcftools"
```

Reload:
```bash
source ~/.bashrc
AnnotSV -help | head -3
```

---

## Installation Summary (this machine)

| Component | Path | Version |
|---|---|---|
| AnnotSV binary (via symlink) | `/home/taimoor/tools/AnnotSV/bin/AnnotSV` | 3.5.10 |
| Real install path | `/home/taimoor/taimoor-data/genomics/research/Other research project/bcm-hackathon26/novelTRs/AnnotSV` | — |
| Annotations Human | `…/share/AnnotSV/Annotations_Human/` | 3.5 |
| Annotations Exomiser | `…/share/AnnotSV/Annotations_Exomiser/2406/` | 2406 |
| bedtools | `/home/taimoor/miniforge3/envs/vardigs/bin/bedtools` | 2.31.1 |
| bcftools | `/home/taimoor/miniforge3/envs/vardigs/bin/bcftools` | 1.23 |
| Tcl/Tk | `/home/taimoor/miniforge3/bin/tclsh` | 8.6 |
| Test output | `…/AnnotSV/test_output/test02_HG00096.annotated.tsv` | 6,889 rows / 8.3 MB |
