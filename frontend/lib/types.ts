export type MotifClass = "homopolymer" | "STR" | "mid" | "VNTR";

/**
 * The novelty screen's verdict. Three-valued, not boolean: "the reference has
 * repeats here but none with this motif" and "the reference annotates nothing
 * here" are different findings, and collapsing them loses the distinction the
 * pipeline exists to draw. See docs/tools/NOVELTY_SCREEN.md.
 */
export type NoveltyStatus = "known" | "novel_motif" | "novel_locus";

/**
 * What the interface can actually display today. `novel` is the coarse fallback
 * for a table that records only a boolean; any table carrying the reference
 * screen — the demo fixtures included — resolves it into one of the three above.
 */
export type NoveltyDisplay = NoveltyStatus | "novel";

export const NOVELTY_LABELS: Record<NoveltyDisplay, string> = {
  known: "Catalogued",
  novel_motif: "Novel motif",
  novel_locus: "Novel locus",
  novel: "Novel",
};

export const NOVELTY_NOTES: Record<NoveltyDisplay, string> = {
  known: "A reference repeat with an equivalent motif sits at this locus.",
  novel_motif:
    "The reference has repeats here, but none with this motif. Check the edit distance — a single substitution reads as novel.",
  novel_locus: "The reference annotates no repeat at all near this locus.",
  novel: "No catalog contains this locus. Run the novelty screen to resolve motif- from locus-novelty.",
};

/** The reference catalogs a locus is screened against, each independently. */
export type PlatformName = "ucsc" | "trexplorer";

export const PLATFORM_LABELS: Record<PlatformName, string> = {
  ucsc: "UCSC simpleRepeat",
  trexplorer: "TRExplorer",
};

export interface Locus {
  locus_id: string;
  chrom: string;
  pos: number;
  motif: string;
  motif_len: number;
  motif_class: MotifClass;
  n_samples: number;
  median_len: number;
  min_len: number;
  max_len: number;
  mean_purity: number;
  /** Coarse verdict, true when no catalog contains this repeat. Always equal to
      `novelty !== "known"` where the screen has been run, and superseded by it. */
  novel: boolean;
  catalogs: string;
  gene: string | null;
  disease_gene: boolean;

  /* ---- Present once the novelty screen (PR #37) has been run. Optional so a
     table without it keeps rendering, and so the UI can say what it does not
     know rather than implying the reference is empty. */
  novelty?: NoveltyStatus;
  /** Per-catalog verdicts. Where they agree, the call is a property of the data. */
  ucsc_novelty?: NoveltyStatus;
  trexplorer_novelty?: NoveltyStatus;
  /** Edit distance to the nearest catalog motif. 1 on a novel_motif call is a near miss. */
  ucsc_motif_edits?: number | null;
  trexplorer_motif_edits?: number | null;
  ucsc_motif?: string | null;
  trexplorer_motif?: string | null;
  /** Fraction of the insertion that is tandem repeat at all, 0-1. */
  insertion_purity?: number | null;

  /* ---- What the reference actually annotates here, per catalog. These are what
     let the locus view open with a comparison rather than with our call alone.
     All are null when that catalog found nothing: "no repeat annotated" is not
     "a repeat of length zero". `start`/`end` are GRCh38 coordinates, so they are
     NOT on the same axis as a Segment's offsets inside the insertion. */
  ucsc_n_nearby?: number | null;
  ucsc_start?: number | null;
  ucsc_end?: number | null;
  ucsc_distance?: number | null;
  ucsc_period?: number | null;
  ucsc_copy_num?: number | null;
  ucsc_per_match?: number | null;
  trexplorer_n_nearby?: number | null;
  trexplorer_start?: number | null;
  trexplorer_end?: number | null;
  trexplorer_distance?: number | null;
  /* ---- Present once the STRchive step (PR #42) has been run. */
  strchive_status?: StrchiveStatus;
  strchive_id?: string | null;
  strchive_disease?: string | null;
}

export interface Segment {
  sample: string;
  seg_index: number;
  seg_type: "repeat" | "flank";
  start: number;
  end: number;
  motif: string | null;
  purity: number | null;
  units: number | null;
}

export interface Allele {
  sample: string;
  allele_len: number;
  segments: Segment[];
}

export interface LocusDetail {
  locus: Locus;
  alleles: Allele[];
}

export interface LociResponse {
  total: number;
  returned: number;
  offset: number;
  loci: Locus[];
  /** Segments of one representative allele per locus, keyed by locus_id. */
  strips: Record<string, Segment[]>;
  /**
   * Filters the current table cannot honour, because the screened callset that
   * supplies their column is not registered. Shown as inactive rather than
   * dropped — a control that silently matches everything reads as a result.
   */
  ignored_filters: (keyof ViewFilters)[];
  /**
   * The ordering actually applied. Normally the one that was asked for; it
   * differs when the sort needs a table this deployment has not registered, and
   * the control says so rather than showing an order the list is not in.
   */
  sort: SortKey;
  sort_dir: SortDirection;
}

export interface FunnelStage {
  stage: string;
  count: number;
  note: string;
}

export interface Summary {
  funnel: FunnelStage[];
  by_class: { motif_class: MotifClass; n: number; novel: number }[];
  by_chrom: { chrom: string; n: number; novel: number }[];
  synthetic: boolean;
}

/* --------------------------------------------------------------------------
   STRchive — the curated catalog of tandem repeats known to cause disease.
   Reference knowledge, not a result from this cohort.
   -------------------------------------------------------------------------- */

/**
 * The rollup verdict from screening one candidate against STRchive. Ordered
 * most to least interesting; `no_locus_match` is the expected answer for nearly
 * every row, because 82 disease loci in 3 Gb makes the base rate ~zero.
 */
export type StrchiveStatus =
  | "pathogenic_expansion"
  | "pathogenic_motif"
  | "locus_novel_motif"
  | "locus_known_motif"
  | "no_locus_match";

export const STRCHIVE_STATUS_LABELS: Record<StrchiveStatus, string> = {
  pathogenic_expansion: "Pathogenic expansion",
  pathogenic_motif: "Pathogenic motif",
  locus_novel_motif: "Novel motif at a disease locus",
  locus_known_motif: "Known motif at a disease locus",
  no_locus_match: "No disease locus nearby",
};

/** Where a copy-number estimate falls against the locus's curated ranges. */
export type AlleleClass = "benign" | "intermediate" | "pathogenic" | "unknown";

/** How a called motif classifies against the motifs STRchive records at a locus. */
export type StrchiveMotifClass =
  | "pathogenic"
  | "reference"
  | "benign"
  | "unknown"
  | "interruption"
  | "none";

/** One curated disease locus. Semicolon-separated strings are STRchive lists. */
export interface StrchiveLocus {
  id: string;
  disease_id: string;
  gene: string;
  disease: string;
  disease_description: string;
  chrom: string;
  start_hg38: number | null;
  stop_hg38: number | null;
  start_hg19: number | null;
  stop_hg19: number | null;
  start_t2t: number | null;
  stop_t2t: number | null;
  gene_strand: string;
  location_in_gene: string;
  motif_len: number | null;
  ref_copies: number | null;
  benign_min: number | null;
  benign_max: number | null;
  intermediate_min: number | null;
  intermediate_max: number | null;
  pathogenic_min: number | null;
  pathogenic_max: number | null;
  /** True when the PATHOGENIC motif is absent from hg38 entirely — 11 of 82 loci. */
  novel_in_reference: boolean;
  novel_flag: string;
  reference_motif: string;
  pathogenic_motif: string;
  benign_motif: string;
  unknown_motif: string;
  interruption_motif: string;
  evidence: string;
  inheritance: string;
  association_type: string;
  mechanism: string;
  age_onset: string;
  typ_age_onset_min: number | null;
  typ_age_onset_max: number | null;
  prevalence: string;
  year: string;
  disease_tags: string;
  locus_tags: string;
  omim: string;
  genereviews: string;
  gnomad: string;
  stripy: string;
  catalog_version: string;
}

/** One of our candidate repeats that landed on a disease locus. */
export interface StrchiveMatch {
  chrom: string;
  ins_coord: number;
  SVID: string;
  sample: string;
  motif: string;
  canonical_motif: string;
  rep_units: number | null;
  purity: number | null;
  insertion_purity: number | null;
  novelty: NoveltyStatus;
  ucsc_novelty: NoveltyStatus | null;
  trexplorer_novelty: NoveltyStatus | null;
  strchive_status: StrchiveStatus;
  strchive_id: string;
  strchive_gene: string;
  strchive_disease: string;
  strchive_inheritance: string;
  strchive_evidence: string;
  strchive_distance_bp: number | null;
  strchive_motif_class: StrchiveMotifClass;
  strchive_motif_edits: number | null;
  strchive_matched_motif: string;
  strchive_ref_copies: number | null;
  strchive_est_copies: number | null;
  strchive_allele_class: AlleleClass;
  strchive_pathogenic_min: number | null;
  strchive_pathogenic_max: number | null;
  strchive_novel_in_ref: boolean | null;
  strchive_catalog: string;
}

export interface StrchiveSummary {
  n_loci: number;
  n_novel_in_reference: number;
  n_with_range: number;
  n_without_ref_copies: number;
  catalog_version: string;
  by_evidence: { evidence: string; n: number; novel: number }[];
  by_inheritance: { inheritance: string; n: number }[];
  /** Null until the pipeline's STRchive step has been run against this cohort. */
  screen: {
    available: boolean;
    n_rows: number;
    n_loci: number;
    nearest_hit_bp: number | null;
    by_status: { status: StrchiveStatus; rows: number; loci: number }[];
  } | null;
}

export interface StrchiveLociResponse {
  total: number;
  returned: number;
  loci: StrchiveLocus[];
}

export interface StrchiveMatchesResponse {
  available: boolean;
  note: string;
  total: number;
  matches: StrchiveMatch[];
}

/* -------------------------------------------------------------------------- */

/** Which surface the workspace is showing. The agent can move this too. */
export type PageName = "catalog" | "strchive";

/**
 * How the catalog list is ordered. Ordering is not filtering — it changes which
 * loci you meet first, not which exist — so it lives beside the filters in the
 * view object but is deliberately kept out of the chip row.
 *
 * `arrays` counts the repeat blocks in the allele each row actually draws, so
 * sorting by it produces a gradient you can see in the barcodes rather than a
 * number you have to take on trust.
 */
export type SortKey =
  | "position"
  | "novel"
  | "size"
  | "support"
  | "arrays"
  | "motif_len"
  | "purity";

export type SortDirection = "asc" | "desc";

/** Label, meaning, and the direction each sort means when nobody says. */
export const SORTS: {
  key: SortKey;
  label: string;
  note: string;
  natural: SortDirection;
}[] = [
  {
    key: "position",
    label: "Position",
    note: "Genomic order — chromosome, then coordinate. Novel and catalogued loci interleave, so the novel fraction reads as texture.",
    natural: "asc",
  },
  {
    key: "size",
    label: "Allele size",
    note: "Median inserted-allele length across carriers.",
    natural: "desc",
  },
  {
    key: "support",
    label: "Carriers",
    note: "How many of the 68 samples carry an insertion here.",
    natural: "desc",
  },
  {
    key: "arrays",
    label: "Repeat arrays",
    note: "How many separate repeat blocks the drawn allele is built from — compound loci first.",
    natural: "desc",
  },
  {
    key: "motif_len",
    label: "Motif length",
    note: "Length of the repeat unit in bp.",
    natural: "desc",
  },
  {
    key: "purity",
    label: "Purity",
    note: "Mean identity to a perfect repeat across carriers.",
    natural: "desc",
  },
  {
    key: "novel",
    label: "Novel first",
    note: "Loci absent from every catalog on top, longest motif first.",
    natural: "desc",
  },
];

export const SORT_LABELS: Record<SortKey, string> = Object.fromEntries(
  SORTS.map((sort) => [sort.key, sort.label]),
) as Record<SortKey, string>;

/** Filter state. Mirrors the `set_view` tool arguments on the backend so the
 *  agent and the controls manipulate exactly the same object. */
export interface ViewFilters {
  page?: PageName;
  novel_only?: boolean;
  /** Three-valued screen verdict. Supersedes novel_only where real data exists. */
  novelty?: NoveltyStatus | null;
  /** Restrict to loci the named catalogs agree on. */
  platform_agreement?: "both" | "ucsc_only" | "trexplorer_only" | "neither" | null;
  chrom?: string | null;
  /**
   * A genomic range, canonical `chr3:1000-50000`, both ends inclusive. Keeps the
   * loci whose insertion site falls inside it — a candidate is an insertion
   * *point*, so that is what overlapping a range means here.
   */
  region?: string | null;
  motif_class?: MotifClass | null;
  min_motif_len?: number | null;
  min_samples?: number | null;
  min_purity?: number | null;
  min_insertion_purity?: number | null;
  disease_gene_only?: boolean;
  gene?: string | null;
  /** Free-text gene search: a case-insensitive substring of the gene symbol.
   *  The exact `gene` is what the agent reaches for when it knows the symbol. */
  gene_query?: string | null;
  sample?: string | null;
  strchive_status?: StrchiveStatus | null;
  /** Restrict the STRchive catalog to loci whose pathogenic motif is not in hg38. */
  strchive_novel_only?: boolean;
  /** Ordering for the catalog list. Not a filter — see SortKey. */
  sort?: SortKey | null;
  /** Omit for the sort's natural direction. */
  sort_dir?: SortDirection | null;
  focus_locus_id?: string | null;
  /** Open one STRchive disease locus, e.g. 'CANVAS_RFC1'. */
  focus_strchive_id?: string | null;
}

/** Events streamed by POST /api/chat. */
export type AgentEvent =
  | { type: "text"; delta: string }
  | { type: "thinking"; delta: string }
  | { type: "tool"; name: string; args: Record<string, unknown> }
  | { type: "view"; filters: ViewFilters }
  | { type: "error"; message: string }
  | { type: "done" };
