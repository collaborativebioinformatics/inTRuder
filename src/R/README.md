# R source (`src/R`)

R code for the project. Environment is managed with [renv](https://rstudio.github.io/renv/).

## Setup

```r
renv::restore()
install.packages(c("data.table", "dplyr", "tidyr", "stringr", "ggplot2", "forcats", "scales"))
```

`renv` activates automatically when R is started from the project root (via
`.Rprofile`). The current analysis script requires the packages listed above.

## Common tasks

```r
renv::snapshot()                 # record newly used packages into renv.lock
renv::status()                   # check whether the library and lockfile agree
```

## Layout

R code goes here, grouped into a directory per subject the way `src/python` is —
not as loose scripts at the top level. Tests mirror it under `../../tests/R/`,
never beside the code.

| Subject | Contents |
|---|---|
| `plotting/` | `main.R` joins novelty-screen output onto AnnotSV annotation for each cohort — see [plotting inputs](../../docs/analysis/PLOTTING.md) |

`plotting/main.R` needs **readr** and **dplyr**, which are not in `renv.lock` yet —
it only records renv itself. Install them and run `renv::snapshot()` to add them.

renv discovers dependencies by scanning the project for `library()` / `require()` /
`pkg::fun()` calls, so simply using a package in code here is enough for
`renv::snapshot()` to pick it up. Commit `renv.lock` (and the `renv/` support files)
whenever it changes.

## AnnotSV analysis

The analysis script accepts an AnnotSV or PhenoGenius-enriched TSV and writes a
selected table plus plots under the chosen output directory:

```bash
Rscript src/R/take_info_annotsv.R \
  SV_annotsv_JVM/examples/first_500_INS.phenogenius.tsv \
  results/TR_annotsv.tsv
```
