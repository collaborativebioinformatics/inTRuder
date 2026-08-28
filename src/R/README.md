# R source (`src/R`)

R code for the project. Environment is managed with [renv](https://rstudio.github.io/renv/).

## Setup

```r
renv::restore()   # install the exact package versions recorded in renv.lock
```

renv activates automatically when R is started from the project root (via `.Rprofile`),
using a project-local library.

## Common tasks

```r
install.packages("data.table")   # install into the project library
renv::snapshot()                 # record newly used packages into renv.lock
renv::status()                   # check whether the library and lockfile agree
```

## Layout

R code goes here, grouped into a directory per subject the way `src/python` is —
not as loose scripts at the top level. Tests mirror it under `../../tests/R/`,
never beside the code.

renv discovers dependencies by scanning the project for `library()` / `require()` /
`pkg::fun()` calls, so simply using a package in code here is enough for
`renv::snapshot()` to pick it up. Commit `renv.lock` (and the `renv/` support files)
whenever it changes.
