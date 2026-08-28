library(readr)
library(dplyr)

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
  main_file = paste0(
    "../../data/",
    "02_HG002_03_04_multisample.trf.novelyFilter.tsv"
  ),
  annotation_file = paste0(
    "../../data/",
    "04_HG002_03_04_multisample.trf.novelyFilter.tsv.processed.tsv"
  ),
  output_file = paste0(
    "../../data/",
    "05_HG002_03_04_multisample.tsv"
  )
)


# ============================================================
# HPRC
# ============================================================

left_join_annotation(
  main_file = paste0(
    "../../data/",
    "02_hprc_multisample.trf.noveltyFiltered.tsv"
  ),
  annotation_file = paste0(
    "../../data/",
    "04_hprc_multisample.trf.noveltyFiltered.tsv.processed.tsv"
  ),
  output_file = paste0(
    "../../data/",
    "05_hprc_multisample.tsv"
  )
)