export type MotifClass = "homopolymer" | "STR" | "mid" | "VNTR";

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
  novel: boolean;
  catalogs: string;
  gene: string | null;
  disease_gene: boolean;
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

/** Filter state. Mirrors the `set_view` tool arguments on the backend so the
 *  agent and the controls manipulate exactly the same object. */
export interface ViewFilters {
  novel_only?: boolean;
  chrom?: string | null;
  motif_class?: MotifClass | null;
  min_motif_len?: number | null;
  min_samples?: number | null;
  min_purity?: number | null;
  disease_gene_only?: boolean;
  gene?: string | null;
  focus_locus_id?: string | null;
}

/** Events streamed by POST /api/chat. */
export type AgentEvent =
  | { type: "text"; delta: string }
  | { type: "thinking"; delta: string }
  | { type: "tool"; name: string; args: Record<string, unknown> }
  | { type: "view"; filters: ViewFilters }
  | { type: "error"; message: string }
  | { type: "done" };
