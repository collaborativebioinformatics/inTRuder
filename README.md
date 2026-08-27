# Novel Tandem Repeats

[![Python](https://img.shields.io/badge/Python-3.13-3776AB?logo=python&logoColor=white)](.python-version)
[![uv](https://img.shields.io/badge/uv-managed-DE5FE9?logo=uv&logoColor=white)](https://docs.astral.sh/uv/)
[![R](https://img.shields.io/badge/R-4.5.2-276DC3?logo=r&logoColor=white)](renv.lock)
[![renv](https://img.shields.io/badge/renv-locked-276DC3?logo=rstudio&logoColor=white)](https://rstudio.github.io/renv/)
[![Nextflow](https://img.shields.io/badge/Nextflow-DSL2-0DC09D?logo=nextflow&logoColor=white)](https://www.nextflow.io/)
[![Sniffles2](https://img.shields.io/badge/SV%20calls-Sniffles2-4C8CBF)](https://github.com/fritzsedlazeck/Sniffles)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)

## Motivation 
Tandem repeat catalogs are built from the reference genome, so TR loci the reference lacks are invisible to every genotyper that depends on them. novelTRs recovers these loci from long-read SV insertion calls — where, by construction, any reference-absent repeat expansion already sits — without whole-genome assembly.

## Table of Contents

- [Motivation](#motivation)
- [Important Links](#important-links-hackathon-purposes---to-delete-on-friday)
- [Quickstart guide](#quickstart-guide)
- [Documentation](#documentation)
  - [Data](#data)
  - [Code and environments](#code-and-environments)
  - [Project](#project)
- [Flowchart](#flowchart)
- [Contributing](#contributing)
- [Team](#team)

## Important Links (Hackathon purposes - to delete on Friday!)

- [Slack](https://baylorncbisvc-1jk9469.slack.com/archives/C0BRNLZDTL3) `#2026_group2_group10_tandem_repeats`
- [Hackathon Document](https://nam04.safelinks.protection.outlook.com/?url=https%3A%2F%2Fdocs.google.com%2Fdocument%2Fd%2F1XlZMGJdudr1C0jS9j1bWgZh4_OWm9lE0Qm8pbTQVRd8%2Fedit%3Fusp%3Dsharing&data=05%7C02%7Cyzb2%40txstate.edu%7C6cd5a1653219475caf8708df02a62c2f%7Cb19c134a14c94d4caf65c420f94c8cbb%7C0%7C0%7C639232584875699222%7CUnknown%7CTWFpbGZsb3d8eyJFbXB0eU1hcGkiOnRydWUsIlYiOiIwLjAuMDAwMCIsIlAiOiJXaW4zMiIsIkFOIjoiTWFpbCIsIldUIjoyfQ%3D%3D%7C0%7C%7C%7C&sdata=iEWgDTcm1XTYKKFT%2FwmVRQZA38vrz86x0gUgEVGzGIE%3D&reserved=0)
- [Zoom](https://cuanschutz.zoom.us/j/94705840498)
- [Team roles and subgroups](https://docs.google.com/document/d/17ginimXqbUi-xEAUXwJttZUjnYb8Fi3xF4hUsY9ry7k/edit?tab=t.0)
- [Detailed project proposal, including background](https://docs.google.com/document/d/18JEbKyxauTkjYTZojyhRf58wiZ7YvwZixZ-JOBXl74c/edit?usp=sharing)
- [Shared Google Drive Directory](https://drive.google.com/drive/folders/1jXJAgrP3To92SYn5w0bqxMdEu0wF66nd?usp=sharing)
- [Data description](docs/data/67_genome_HPRC_cohort.md) — samples, data sources, methods
- [Hackathon Paper draft](https://drive.google.com/drive/folders/1jXJAgrP3To92SYn5w0bqxMdEu0wF66nd?usp=sharing)

## Quickstart guide

For the complete annotation sequence, see
[SV annotation workflow](SV_annotsv_JVM/workflow.md). The individual stages
have focused documentation:

- [AnnotSV](pipelines/annotsv/README.md)
- [SV preprocessing](pipelines/sv_preprocess/README.md)
- [PhenoGenius enrichment](pipelines/phenogenius_enrich/README.md)

## Documentation

### Data

| Document | Contents |
|---|---|
| [67-genome HPRC cohort](docs/data/67_genome_HPRC_cohort.md) | Cohort composition, read extraction and alignment, Sniffles2 SV calling and filtering, data availability |
| [UCSC hg38 Simple Repeats (TRF)](docs/data/UCSC_hg38_Simple_TRF_Repeats.md) | Reference TR annotation used for comparison — download, column schema, coordinate conventions, provenance |
| [`data/aws_hprc_cram.list`](data/aws_hprc_cram.list) | AWS S3 locations of the processed HPRC CRAM files |
| [`data/aws_giab_cram.list`](data/aws_giab_cram.list) | AWS S3 locations of the processed GIAB CRAM files |
| [`data/sv_output/`](data/sv_output/) | Per-sample raw and filtered Sniffles VCFs, plus the merged multi-sample VCF subset |

### Code and environments

| Document | Contents |
|---|---|
| [Python source](src/python/README.md) | uv-managed environment, adding dependencies, running scripts, linting and tests |
| [R source](src/R/README.md) | renv-managed environment, `renv::restore()`, snapshotting new packages |
| [Notebooks](notebooks/README.md) | Jupyter and R Markdown / Quarto notebooks for exploration and reporting |
| [TR Annotation Pipeline](pipelines/annotsv/README.md) | Nextflow DSL2 workflow for functional and clinical annotation using AnnotSV |
| [SV annotation workflow](SV_annotsv_JVM/workflow.md) | End-to-end local and DNAnexus execution order |

## Flowchart

Project overview

[![Click to view interactive Miro Board](./docs/images/flowchart_05_08_2026.png)](https://miro.com/app/board/uXjVHuDLcpE=/?share_link_id=710821883698)

## Contributing

See [CONTRIBUTING.md](./CONTRIBUTING.md) for the quick workflow on submitting changes via a pull request.

## Team
Harriet Dashnow, Akshay Kumar Avvaru, Bharati Jadhav, Amit R Indap, Garth Kong, Achisha Saikia
Sriram Sudarsanam, Andrew Scouten, Jordi Valls, Ammara Saleem, Elbay Aliyev, Garrison Arner, Gavin Monahan, Anukrati Sharma, Liedewei Van de Vondel, Ramakrishnan Rajagopalan, Divya Kalra, Chantera Lazard, Taimoor Khan and Medhat Mahmoud.
