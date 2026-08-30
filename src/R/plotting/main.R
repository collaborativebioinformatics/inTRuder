library(readr)
library(dplyr)

# Directory holding the 02_/04_ inputs, and where the 05_ merges are written.
# None of these tables are committed - they are derived pipeline output. See
# docs/analysis/PLOTTING.md for what each file is and how to regenerate it.
#
# Defaults to data/plots relative to the working directory, so run this from the
# repo root (which is also where renv activates):
#
#   Rscript src/R/plotting/main.R
#   Rscript src/R/plotting/main.R /some/other/dir   # or set INTRUDER_PLOT_DATA
args <- commandArgs(trailingOnly = TRUE)
data_dir <- if (length(args) >= 1) {
  args[[1]]
} else {
  Sys.getenv("INTRUDER_PLOT_DATA", unset = "data/plots")
}

if (!dir.exists(data_dir)) {
  stop(
    "Plotting data directory not found: ", data_dir, "\n",
    "See docs/analysis/PLOTTING.md for how to obtain or regenerate these files."
  )
}

left_join_annotation <- function(main_file, annotation_file, output_file) {
  
  message("Reading: ", main_file)
  
  main_02 <- read_tsv(
    main_file,
    show_col_types = FALSE
  )
  
  annotation_04 <- read_tsv(
    annotation_file,
    show_col_types = FALSE
  )
  
  original_rows <- nrow(main_02)
  original_columns <- names(main_02)
  
  merged <- main_02 %>%
    left_join(
      annotation_04,
      by = "SVID",
      suffix = c("", "_04"),
      relationship = "many-to-one"
    )
  
  # Confirm rows and columns from 02 were preserved
  stopifnot(nrow(merged) == original_rows)
  stopifnot(all(original_columns %in% names(merged)))
  
  write_tsv(
    merged,
    output_file,
    na = "NA"
  )
  
  message("Rows in 02: ", original_rows)
  message("Rows in output: ", nrow(merged))
  message("Output: ", normalizePath(output_file))
  message("")
}


# ============================================================
# HG002
# ============================================================

left_join_annotation(
  main_file = file.path(
    data_dir,
    "02_HG002_03_04_multisample.trf.novelyFilter.tsv"
  ),
  annotation_file = file.path(
    data_dir,
    "04_HG002_03_04_multisample.trf.novelyFilter.tsv.processed.tsv"
  ),
  output_file = file.path(
    data_dir,
    "05_HG002_03_04_multisample.tsv"
  )
)


# ============================================================
# HPRC
# ============================================================

left_join_annotation(
  main_file = file.path(
    data_dir,
    "02_hprc_multisample.trf.noveltyFiltered.tsv"
  ),
  annotation_file = file.path(
    data_dir,
    "04_hprc_multisample.trf.noveltyFiltered.tsv.processed.tsv"
  ),
  output_file = file.path(
    data_dir,
    "05_hprc_multisample.tsv"
  )
)