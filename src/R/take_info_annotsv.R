library(dplyr)
library(tidyr)
library(stringr)
library(data.table)
library(ggplot2)
library(forcats)
library(scales)

args <- commandArgs(trailingOnly = TRUE)
if (length(args) < 1 || length(args) > 2) {
  stop("Usage: Rscript take_info_annotsv.R <annotated.tsv> [output.tsv]")
}
input_file <- args[[1]]
output_file <- if (length(args) == 2) args[[2]] else "results/TR_annotsv.tsv"
dir.create(dirname(output_file), recursive = TRUE, showWarnings = FALSE)
dup_annot <- fread(input_file)

# The standalone PhenoGenius stage uses these five columns. Keep aliases for
# older AnnotSV outputs so the analysis remains readable across prior runs.
if (!"PhenoGenius_score" %in% names(dup_annot) && "PhenoGenius_best_score" %in% names(dup_annot))
  dup_annot[, PhenoGenius_score := suppressWarnings(as.numeric(PhenoGenius_best_score))]
if (!"PhenoGenius_specificity" %in% names(dup_annot) && "PhenoGenius_best_specificity" %in% names(dup_annot))
  dup_annot[, PhenoGenius_specificity := PhenoGenius_best_specificity]
if (!"PhenoGenius_phenotype" %in% names(dup_annot))
  dup_annot[, PhenoGenius_phenotype := NA_character_]

dup_split <- dup_annot %>% filter("split" == Annotation_mode)
split_cols <- c("AnnotSV_ID","Tx","Overlapped_tx_length","Overlapped_CDS_percent","Frameshift","Location","Location2","Dist_nearest_SS","GenCC_disease","GenCC_moi",
                "GenCC_classification","OMIM_phenotype","OMIM_inheritance","PhenoGenius_score","PhenoGenius_phenotype","Human_pheno_evidence")
dup_split <- dup_split[, intersect(split_cols, names(dup_split)), with = FALSE]
dup_full <- dup_annot %>% filter("full" == Annotation_mode)
cols_to_remove <- c(
  "Tx", "Overlapped_tx_length",
  "Overlapped_CDS_percent", "Frameshift", "Location",
  "Location2", "Dist_nearest_SS", "GenCC_disease",
  "GenCC_moi", "GenCC_classification", "OMIM_phenotype",
  "OMIM_inheritance", "PhenoGenius_score",
  "PhenoGenius_phenotype", "Human_pheno_evidence"
)

dup_full <- dup_full %>%
  dplyr::select(-dplyr::any_of(cols_to_remove))


dup_full<- merge(dup_full,dup_split,by.x="AnnotSV_ID",by.y="AnnotSV_ID", all.x=T)

output_cols <- c("AnnotSV_ID", "SV_chrom", "SV_start", "SV_end", "SV_length", "SV_type", "REF", "ALT", "Gene_name", "Location", "Location2", "Tx", "Overlapped_tx_length", "Overlapped_CDS_percent", "Frameshift", "RE_gene", "P_gain_source", "B_gain_source", "TAD_coordinate",
                 "Repeat_type_left", "Repeat_type_right", "SegDup_left", "SegDup_right", "ACMG", "HI", "TS", "DDD_HI_percent", "ExAC_dupZ", "ExAC_cnvZ", "LOEUF_bin", "GnomAD_pLI", "ExAC_pLI", "Exomiser_gene_pheno_score", "PhenoGenius_score", "PhenoGenius_specificity", "PhenoGenius_phenotype", "GenCC_disease", "GenCC_classification", "Human_pheno_evidence", "AnnotSV_ranking_criteria", "AnnotSV_ranking_score", "ACMG_class")
dup_full <- dup_full %>% dplyr::select(dplyr::any_of(output_cols))
# AnnotSV databases and input type determine which optional fields exist.
# Add absent analysis fields as NA so plotting remains valid for both the
# AnnotSV-only and PhenoGenius-enriched outputs.
analysis_cols <- c("Gene_name", "Location", "Location2", "Frameshift", "ACMG_class",
                   "GenCC_disease", "Human_pheno_evidence", "Exomiser_gene_pheno_score",
                   "PhenoGenius_score", "B_gain_source")
for (col in setdiff(analysis_cols, names(dup_full))) dup_full[[col]] <- NA
for (col in c("Exomiser_gene_pheno_score", "PhenoGenius_score", "AnnotSV_ranking_score")) {
  if (col %in% names(dup_full)) dup_full[[col]] <- suppressWarnings(as.numeric(as.character(dup_full[[col]])))
}
fwrite(dup_full, output_file, sep = "\t")


show_missing <- function(x) {
  x <- as.character(x)
  x[is.na(x) | trimws(x) == ""] <- "Missing"
  x
}


df_plot <- dup_full %>%
  mutate(
    Location = show_missing(Location),
    Location2 = show_missing(Location2),
    Frameshift = show_missing(Frameshift),
    ACMG_class = show_missing(ACMG_class),
    GenCC_disease = show_missing(GenCC_disease),
    Human_pheno_evidence = show_missing(Human_pheno_evidence)
  )


location_counts <- df_plot %>%
  count(Location, sort = TRUE)

ggplot(location_counts, aes(
  x = fct_reorder(Location, n),
  y = n
)) +
  geom_col(fill = "#2C7FB8") +
  coord_flip() +
  labs(
    title = "Distribution of SV location within genes",
    x = "SV location",
    y = "Number of annotations"
  ) +
  theme_minimal(base_size = 12)



#This shows whether the SVs most often overlap exons, introns, transcript boundaries, or other gene regions.


ggplot(df_plot, aes(x = fct_infreq(Location2))) +
  geom_bar(fill = "#41AE76") +
  labs(
    title = "Distribution of SV location relative to coding regions",
    x = "Location2",
    y = "Number of annotations"
  ) +
  theme_minimal(base_size = 12)



#This distinguishes annotations such as 5′ UTR, CDS, 3′ UTR, and regions without a CDS.

#FRAMESHIFT distribution

ggplot(df_plot, aes(x = fct_infreq(Frameshift))) +
  geom_bar(fill = "#D95F0E") +
  labs(
    title = "Frameshift status of annotated SVs",
    x = "Frameshift status",
    y = "Number of annotations"
  ) +
  theme_minimal(base_size = 12)



#Relationship between Location2 and Frameshift


ggplot(df_plot, aes(
  x = Location2,
  fill = Frameshift
)) +
  geom_bar(position = "fill") +
  scale_y_continuous(labels = percent_format()) +
  labs(
    title = "Frameshift status by coding-region location",
    x = "Location2",
    y = "Percentage of annotations",
    fill = "Frameshift"
  ) +
  theme_minimal(base_size = 12)




#Distribution of AnnotSV_ranking_score

ggplot(df_plot, aes(x = AnnotSV_ranking_score)) +
  geom_histogram(
    bins = 30,
    fill = "#756BB1",
    color = "white",
    na.rm = TRUE
  ) +
  geom_vline(xintercept = c(-0.99, -0.90, 0.90, 0.99),
             linetype = "dashed",
             color = "red") +
  labs(
    title = "Distribution of AnnotSV ranking scores",
    x = "AnnotSV ranking score",
    y = "Number of annotations"
  ) +
  theme_minimal(base_size = 12)



#Distribution of ACMG_class


ggplot(df_plot, aes(x = ACMG_class)) +
  geom_bar(fill = "#8856A7") +
  labs(
    title = "Distribution of ACMG SV classes",
    x = "ACMG class",
    y = "Number of annotations"
  ) +
  theme_minimal(base_size = 12) +
  theme(axis.text.x = element_text(angle = 45, hjust = 1))

ggplot(df_plot, aes(
  x = ACMG_class,
  y = AnnotSV_ranking_score,
  fill = ACMG_class
)) +
  geom_boxplot(na.rm = TRUE) +
  geom_hline(
    yintercept = c(-0.90, 0.90),
    linetype = "dashed",
    color = "red"
  ) +
  labs(
    title = "AnnotSV ranking score by ACMG class",
    x = "ACMG class",
    y = "AnnotSV ranking score"
  ) +
  theme_minimal(base_size = 12) +
  theme(
    legend.position = "none",
    axis.text.x = element_text(angle = 45, hjust = 1)
  )




#Figures for Exomiser_gene_pheno_score and PhenoGenius_score
#9. Distribution of both phenotype scores

phenotype_scores <- df_plot %>%
  select(
    Exomiser_gene_pheno_score,
    PhenoGenius_score
  ) %>%
  pivot_longer(
    cols = everything(),
    names_to = "Score_type",
    values_to = "Score"
  )


ggplot(phenotype_scores, aes(
  x = Score,
  fill = Score_type
)) +
  geom_histogram(
    bins = 30,
    alpha = 0.7,
    position = "identity",
    na.rm = TRUE
  ) +
  facet_wrap(~ Score_type, scales = "free") +
  labs(
    title = "Distribution of phenotype–gene association scores",
    x = "Score",
    y = "Number of annotations",
    fill = "Score type"
  ) +
  theme_minimal(base_size = 12) +
  theme(legend.position = "none")



ggplot(
  df_plot,
  aes(
    x = Exomiser_gene_pheno_score,
    y = PhenoGenius_score
  )
) +
  geom_point(
    alpha = 0.6,
    color = "#1F78B4",
    na.rm = TRUE
  ) +
  geom_smooth(
    method = "lm",
    se = TRUE,
    color = "black",
    na.rm = TRUE
  ) +
  labs(
    title = "Comparison of Exomiser and PhenoGenius scores",
    x = "Exomiser gene phenotype score",
    y = "PhenoGenius score"
  ) +
  theme_minimal(base_size = 12)




top_genes <- df_plot %>%
  filter(!is.na(Gene_name)) %>%
  group_by(Gene_name) %>%
  summarise(
    Exomiser_score = max(
      Exomiser_gene_pheno_score,
      na.rm = TRUE
    ),
    PhenoGenius_score = max(
      PhenoGenius_score,
      na.rm = TRUE
    ),
    .groups = "drop"
  ) %>%
  filter(is.finite(Exomiser_score) | is.finite(PhenoGenius_score)) %>%
  arrange(desc(Exomiser_score)) %>%
  slice_head(n = 20)


ggplot(
  top_genes,
  aes(
    x = fct_reorder(Gene_name, Exomiser_score),
    y = Exomiser_score
  )
) +
  geom_col(fill = "#3182BD") +
  coord_flip() +
  labs(
    title = "Top genes by Exomiser phenotype score",
    x = "Gene",
    y = "Exomiser gene phenotype score"
  ) +
  theme_minimal(base_size = 12)


top_pheno <- df_plot %>%
  filter(!is.na(Gene_name)) %>%
  group_by(Gene_name) %>%
  summarise(
    PhenoGenius_score = max(PhenoGenius_score, na.rm = TRUE),
    .groups = "drop"
  ) %>%
  filter(is.finite(PhenoGenius_score)) %>%
  arrange(desc(PhenoGenius_score)) %>%
  slice_head(n = 20)

ggplot(
  top_pheno,
  aes(
    x = fct_reorder(Gene_name, PhenoGenius_score),
    y = PhenoGenius_score
  )
) +
  geom_col(fill = "#31A354") +
  coord_flip() +
  labs(
    title = "Top genes by PhenoGenius score",
    x = "Gene",
    y = "PhenoGenius score"
  ) +
  theme_minimal(base_size = 12)


#Most frequent GenCC diseases

gencc_disease_counts <- df_plot %>%
  filter(GenCC_disease != "Missing") %>%
  count(GenCC_disease, sort = TRUE) %>%
  slice_head(n = 20)

ggplot(
  gencc_disease_counts,
  aes(
    x = fct_reorder(GenCC_disease, n),
    y = n
  )
) +
  geom_col(fill = "#E6550D") +
  coord_flip() +
  labs(
    title = "Most frequent GenCC disease annotations",
    x = "GenCC disease",
    y = "Number of annotations"
  ) +
  theme_minimal(base_size = 12)



## Know dups already described or are new

variant_status <- dup_full %>%
  mutate(
    Variant_status = case_when(
      is.na(B_gain_source) | trimws(B_gain_source) == "" ~ "New",
      TRUE ~ "Described"
    )
  ) %>%
  count(Variant_status) %>%
  mutate(
    Variant_status = factor(
      Variant_status,
      levels = c("Described", "New")
    )
  )

ggplot(variant_status, aes(x = Variant_status, y = n, fill = Variant_status)) +
  geom_col(width = 0.65) +
  geom_text(
    aes(label = paste0(n, " (", percent(n / sum(n)), ")")),
    vjust = -0.3,
    size = 5
  ) +
  scale_fill_manual(
    values = c(
      "Described" = "#2C7FB8",
      "New" = "#D95F0E"
    )
  ) +
  labs(
    title = "Variants with and without benign gain annotations",
    subtitle = "Classification based on B_gain_source",
    x = NULL,
    y = "Number of variants",
    fill = "Variant status"
  ) +
  theme_minimal(base_size = 13) +
  theme(
    legend.position = "none",
    plot.title = element_text(face = "bold")
  ) +
  expand_limits(y = max(variant_status$n) * 1.15)
