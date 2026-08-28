# inTRuder

[![Python](https://img.shields.io/badge/Python-3.13-3776AB?logo=python&logoColor=white)](.python-version)
[![uv](https://img.shields.io/badge/uv-managed-DE5FE9?logo=uv&logoColor=white)](https://docs.astral.sh/uv/)
[![R](https://img.shields.io/badge/R-4.5.2-276DC3?logo=r&logoColor=white)](renv.lock)
[![renv](https://img.shields.io/badge/renv-locked-276DC3?logo=rstudio&logoColor=white)](https://rstudio.github.io/renv/)
[![Nextflow](https://img.shields.io/badge/Nextflow-DSL2-0DC09D?logo=nextflow&logoColor=white)](https://www.nextflow.io/)
[![Sniffles2](https://img.shields.io/badge/SV%20calls-Sniffles2-4C8CBF)](https://github.com/fritzsedlazeck/Sniffles)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)

<p align="center">
  <img src="docs/images/logo.png" alt="inTRuder logo" width="480">
</p>

## Overview

Tandem repeat (TR) genotypers rely on a catalog of known loci and motifs, and that catalog is
built by annotating repeats in the reference genome — so any TR that's individual- or
population-specific is invisible to it from the start. We distinguish two kinds of novelty:

- **Novel locus** — present in an individual, absent from the reference genome entirely.
- **Novel motif** — the locus exists in the reference, but the individual carries a different
  repeat motif there.

Finding these normally means whole-genome assembly, which is expensive to run just to surface
non-reference sequence. inTRuder takes a cheaper route: long-read structural variant (SV) callers
already detect insertions accurately as a standard part of most long-read workflows, and an
expanded TR is, by construction, a repetitive subset of those insertions. Scanning the inserted
sequence itself — rather than assembling the whole genome — is enough to surface candidate TR
expansions, including ones no existing catalog knows about.

**Pipeline stages:**

1. **Preprocessing** *(upstream, assumed already done)* — alignment ([minimap2](https://github.com/lh3/minimap2)),
   SNV calling ([Clair3](https://github.com/HKU-BAL/Clair3)), haplotagging
   ([WhatsHap](https://github.com/whatshap/whatshap)), SV calling
   ([Sniffles2](https://github.com/fritzsedlazeck/Sniffles)), joint SV calling/merging (Sniffles2)
2. **TR detection** — find tandem repeats within inserted allele sequences
   ([`pytrf`](https://github.com/lmdu/pytrf)), filtering out homopolymers and low-purity or
   low-coverage calls
3. **Novelty assessment** — flag which candidate loci/motifs are absent from the reference genome
   and known TR catalogs
4. **Annotation** — genic and clinical context ([`AnnotSV`](https://github.com/lgmgeo/AnnotSV)),
   known-TR/disease-locus comparison ([STRchive](https://github.com/dashnowlab/STRchive))
5. **Validation** — compare calls against high-quality HPRC long-read assemblies and trio data

See [Methods outline](docs/Methods_overview.md) for the full write-up of each stage.

## Table of Contents

- [Overview](#overview)
- [Important Links](#important-links-hackathon-purposes---to-delete-on-friday)
- [Quickstart guide](#quickstart-guide)
- [Repository layout](#repository-layout)
- [Documentation](#documentation)
  - [Data](#data)
  - [Tools](#tools)
  - [Code and environments](#code-and-environments)
- [Web interface](#web-interface)
- [Flowchart](#flowchart)
- [Contributing](#contributing)
- [Team](#team)

## Important Links (Hackathon purposes - to delete on Friday!)

- [Slack](https://baylorncbisvc-1jk9469.slack.com/archives/C0BRNLZDTL3) `#2026_group2_group10_tandem_repeats`
- [Hackathon Schedule](https://docs.google.com/document/d/1XlZMGJdudr1C0jS9j1bWgZh4_OWm9lE0Qm8pbTQVRd8/edit?usp=sharing)
- [Zoom](https://cuanschutz.zoom.us/j/94705840498)
- [Team roles and subgroups](https://docs.google.com/document/d/17ginimXqbUi-xEAUXwJttZUjnYb8Fi3xF4hUsY9ry7k/edit?tab=t.0)
- [Shared Google Drive Directory](https://drive.google.com/drive/folders/1jXJAgrP3To92SYn5w0bqxMdEu0wF66nd?usp=sharing)
    - [Hackathon Paper Draft](https://docs.google.com/document/d/10qZ_TYCXGT-6oQeLkNYA6dTP95qblCw60p-mwLw-pfY/edit?usp=sharing)
    - [Detailed project proposal, including background](https://docs.google.com/document/d/18JEbKyxauTkjYTZojyhRf58wiZ7YvwZixZ-JOBXl74c/edit?usp=sharing)
  * **Final Files for Plotting**
    * [HG002 Trio](https://drive.google.com/file/d/1ppH3vSswUobjRUMFrTC-4MPwbmW_63L5/view?usp=drive_link)
    * [HPRC Samples](https://drive.google.com/file/d/10Byv-tfCglKLdArRO9sW8dqmd-rwrh0W/view?usp=drive_link)

## Quickstart guide


## Repository layout

```
novelTRs/
├── src/
│   ├── python/intruder/     # the pipeline, as one installed package (uv-managed)
│   │   ├── trcore/             # shared primitives — coords, motifs, downloads
│   │   ├── pipeline/           # the steps: trf, novelty, strchive, annotation
│   │   └── analysis/           # post-hoc analysis of pipeline output
│   └── R/                   # R analysis code (renv-managed)
├── scripts/                 # every shell script in the repo
│   ├── dnanexus/               # rent a DNAnexus box, run something, terminate it
│   └── merge-SV/               # Sniffles single- and multi-sample SV merging runs
├── workflows/               # Nextflow entrypoint (main.nf, nextflow.config)
├── pipelines/               # Nextflow subworkflows and their scripts
├── notebooks/               # Jupyter and R Markdown / Quarto notebooks
├── frontend/                # Next.js web interface (proof of concept)
├── backend/                 # FastAPI + LangGraph service (its own uv project)
├── docker/                  # Container images for frontend/backend
├── data/                    # Sample lists, SV output, catalogs (mostly gitignored)
├── docs/                    # Data, tool and methods documentation
├── tests/python/            # Python tests, mirroring src/python/intruder/
└── justfile                 # task runner — `just` lists all recipes
```

Where code goes: Python in `src/python/intruder/`, R in `src/R/`, shell in
`scripts/`, Nextflow in `workflows/` and `pipelines/`. Tests never sit beside the
code they cover — they mirror it under `tests/`.

## Documentation

### Data

| Document | Contents |
|---|---|
| [67-genome HPRC cohort](docs/data/67_genome_HPRC_cohort.md) | Cohort composition, read extraction and alignment, Sniffles2 SV calling and filtering, data availability |
| [UCSC hg38 Simple Repeats (TRF)](docs/data/UCSC_hg38_Simple_TRF_Repeats.md) | Reference TR annotation used for comparison — download, column schema, coordinate conventions, provenance |
| [`data/aws_hprc_cram.list`](data/aws_hprc_cram.list) | AWS S3 locations of the processed HPRC CRAM files |
| [`data/aws_giab_cram.list`](data/aws_giab_cram.list) | AWS S3 locations of the processed GIAB CRAM files |
| [`data/sv_output/`](data/sv_output/) | Per-sample raw and filtered Sniffles VCFs, plus the merged multi-sample VCF subset |
| [Plotting inputs](docs/analysis/PLOTTING.md) | The uncommitted tables in `data/plots/` that the figures are drawn from — what each one is, which step produces it, how to regenerate |

### Tools

| Document | Contents |
|---|---|
| [Novelty screen](docs/tools/NOVELTY_SCREEN.md) | Is this repeat absent from the reference? Catalogues, motif equivalence and tolerance, the known/novel verdict |
| [STRchive comparison](docs/tools/STRCHIVE_COMPARE.md) | Is it a known disease locus? Motif classes, allele-class thresholds, the annotated output table |

### Code and environments

| Document | Contents |
|---|---|
| [Python source](src/python/README.md) | uv-managed environment, adding dependencies, running scripts, linting and tests |
| [Run programs on DNAnexus](docs/scripts/DNANexus.md) | `scripts/dnanexus/dx-*.sh`: start a machine, get a terminal or run one program on it, then stop the machine. Token setup, options, and instance types |
| [R source](src/R/README.md) | renv-managed environment, `renv::restore()`, snapshotting new packages |
| [Notebooks](notebooks/README.md) | Jupyter and R Markdown / Quarto notebooks for exploration and reporting |

## Web interface

<p align="center">
  <b>An interactive browser for the callset, with an agent that queries the same tables the charts read.</b>
</p>

<p align="center">
  <img src="docs/images/web/web-catalog.jpg" alt="inTRuder catalog view: the discovery funnel on the left, candidate loci drawn as motif barcodes in the centre, the assistant on the right" width="900">
</p>

<p align="center">
  <sub>The 67-genome HPRC callset — 17,270 candidate insertion loci, 3,467 of them absent from every catalog.</sub>
</p>

<p align="center">
  <img src="https://img.shields.io/badge/Next.js-16-000000?logo=nextdotjs&logoColor=white" alt="Next.js 16">
  <img src="https://img.shields.io/badge/Tailwind-v4-06B6D4?logo=tailwindcss&logoColor=white" alt="Tailwind v4">
  <img src="https://img.shields.io/badge/FastAPI-009688?logo=fastapi&logoColor=white" alt="FastAPI">
  <img src="https://img.shields.io/badge/LangGraph-1C3C3C?logo=langchain&logoColor=white" alt="LangGraph">
  <img src="https://img.shields.io/badge/DuckDB-FFF000?logo=duckdb&logoColor=black" alt="DuckDB">
</p>

```bash
just setup     # installs everything, generates the synthetic demo dataset
just dev       # backend on :8000, frontend on :3000
```

Or in containers, with no toolchain to install:

```bash
docker compose up --build      # same two ports
```

---

### The funnel is the filter

Every stage in the left rail is a click, not a caption. 17,270 merged insertion calls
narrow to 17,226 non-homopolymer, to 3,467 with no equivalent motif in any catalog, to
1,795 inside an annotated gene, to 412 inside a gene with an OMIM disease entry — and
clicking any stage filters the list beside it. The motif-class chart below it does the
same, so "which class carries the novelty" is one hover away.

### One primitive, three zoom levels

An inserted allele is drawn as a **strip of motif blocks**, not as bases. Base-level
rendering fails on tandem repeats — a GCC and a CGG expansion are the same coloured mush —
so the encoding moves up a level to where the information actually is.

| Level | What it shows | Colour carries | Width scale |
|---|---|---|---|
| Catalog | Every locus, one strip each | Novel vs catalogued | sqrt-compressed per row |
| Locus | One locus, every carrier | Motif identity | Shared linear |
| Allele | One strip, hovered | Motif identity | Shared linear |

### Ask it in English

<img src="docs/images/web/web-agent.jpg" alt="The assistant answering a question about novel VNTRs and setting the catalog filters to match" width="900">

The assistant is not a sidebar bolted onto a dashboard — it is a second way to edit the
same state. It writes SQL against the same DuckDB tables the charts read, shows you every
query it ran under **Agent actions**, and calls `set_view` to move the screen: here it set
the VNTR, novel-only and ≥10-carrier chips and re-sorted by carrier count, so the answer
and the view agree. Type the same thing into the filter bar and you get the same result.

### Drill into one locus

<img src="docs/images/web/web-locus.jpg" alt="Locus detail for chr3:37,708,652 in ITGA9 — a novel locus carried by 61 of 67 samples, with neither catalog annotating a repeat there" width="900">

Every candidate gets the whole argument for its verdict on one screen: what both catalogs
say at that position, how far the observed motif is from the catalogued one, and where the
insertion point falls in the gene. `chr3:37,708,652` sits in intron 18 of *ITGA9*, is
carried by 61 of 67 samples — and neither UCSC simpleRepeat nor TRExplorer annotates any
repeat within 10 bp of it.

<img src="docs/images/web/web-alleles.jpg" alt="Allele-length histogram across 61 carriers, and the five distinct allele structures at the locus" width="900">

Below that, the locus across the cohort: allele lengths from 1.2 kb to 4.4 kb, and the five
distinct architectures those 85 alleles collapse into — same repeat blocks, same order,
same copy number. Click a bar to isolate its carriers.

### Compare against what is already known

<img src="docs/images/web/web-disease-loci.jpg" alt="The STRchive disease-locus view — 82 curated loci, 11 whose pathogenic motif is not in hg38" width="900">

The STRchive view is reference knowledge, not a result: the 82 curated repeat-expansion
disease loci our candidates are compared against. Eleven of them have a pathogenic motif
that does not exist in hg38 at all — a genotyper working from a reference-derived catalog
has no locus to genotype. That is exactly the shape this pipeline detects.

### Bring your own data

<img src="docs/images/web/web-datasets.jpg" alt="The datasets view — every table is a YAML manifest, with per-table switches" width="900">

**Adding a dataset is one YAML file, no code changes.** Every table is a manifest
describing a file on this machine, and the prose in it is what the assistant reads when
deciding whether a table can answer a question. Switch a table off and it leaves the whole
interface — no page draws it, and the assistant is not told it exists. Manifests point at
paths on your own machine; nothing is uploaded.

---

Add a model credential to `backend/.env` to enable chat — the data views work without one.
Anthropic, Google, Ollama and OpenAI are all selectable via `LLM_PROVIDER`. Or set
`LLM_PROVIDER=claude-code` to run chat on the Claude Code CLI you already have, with no key
at all — see [`backend/README.md`](./backend/README.md#running-on-claude-code).

| Directory | What it is |
|---|---|
| [`frontend/`](./frontend) | Next.js + Tailwind + assistant-ui |
| [`backend/`](./backend) | FastAPI + LangGraph + DuckDB (its own uv project) |
| [`data/web/`](./data/web) | Dataset manifests — add your own data here |
| [`docker/`](./docker) | Images for both services; `data/` is bind-mounted, not baked in |

> **About these screenshots.** They show the real 67-genome HPRC callset, which is not
> committed to this repository. What ships with `just setup` is a small **synthetic** demo
> set: sample names and the motif-length mix mirror the real callset so the shapes look
> right, but every locus, coordinate and catalog membership is generated. The demo data is
> not a result. See [`data/web/README.md`](./data/web/README.md) for pointing the app at
> your own tables.

## Flowchart

Project overview

[![Click to view interactive Miro Board](./docs/images/flowchart_05_08_2026.png)](https://miro.com/app/board/uXjVHuDLcpE=/?share_link_id=710821883698)

## Contributing

See [CONTRIBUTING.md](./CONTRIBUTING.md) for the quick workflow on submitting changes via a pull request.

## Team
Harriet Dashnow, Akshay Kumar Avvaru, Bharati Jadhav, Amit R Indap, Garth Kong, Achisha Saikia
Sriram Sudarsanam, Andrew Scouten, Jordi Valls, Ammara Saleem, Elbay Aliyev, Garrison Arner, Gavin Monahan, Anukrati Sharma, Liedewei Van de Vondel, Ramakrishnan Rajagopalan, Divya Kalra, Chantera Lazard, Taimoor Khan and Medhat Mahmoud.
