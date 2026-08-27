# R source (`src/R`)

R code for the project. Environment is managed with [renv](https://rstudio.github.io/renv/).

## Setup

```r
renv::restore()   # install the exact package versions recorded in renv.lock
```

`renv` activates automatically when R is started from the project root (via
`.Rprofile`), using a project-local library. `renv.lock` already records
everything the analysis script needs (`data.table`, `dplyr`, `tidyr`,
`stringr`, `ggplot2`, `forcats`, `scales`, and their dependencies), so
`renv::restore()` is the only setup step — do not `install.packages()` these
by hand, or you will silently drift from the recorded versions.

## Common tasks

```r
renv::install("pkg")             # install into the project library
renv::snapshot()                 # record newly used packages into renv.lock
renv::status()                   # check whether the library and lockfile agree
```

renv discovers dependencies by scanning the project for `library()` / `require()` /
`pkg::fun()` calls, so simply using a package in code here is enough for
`renv::snapshot()` to pick it up. Commit `renv.lock` (and the `renv/` support files)
whenever it changes.

## AnnotSV analysis

The analysis script accepts an AnnotSV or PhenoGenius-enriched TSV and writes
the selected table to the given output path. Figures are written to `Rplots.pdf`
in the current working directory:

```bash
Rscript src/R/take_info_annotsv.R \
  SV_annotsv_JVM/examples/first_500_INS.phenogenius.tsv \
  results/TR_annotsv.tsv
```
