import type { AlleleClass, StrchiveLocus } from "./types";

/**
 * Domain helpers for the disease-locus view.
 *
 * The one non-obvious piece is the copy-number scale. Pathogenic thresholds
 * across STRchive span three orders of magnitude — HMNR7_VWA1 becomes pathogenic
 * at 1 copy, DM2_CNBP runs to 11,000 — so a linear axis renders almost every
 * locus as a sliver pinned to the left edge. The scale is therefore logarithmic,
 * via log1p rather than log: copy counts legitimately reach exactly 0 (SCA37_DAB1
 * has ref_copies 0.0, and several benign ranges start at 0), and log(0) is not a
 * position on an axis.
 */

/**
 * Strip STRchive's inline citation tokens from prose meant for display.
 *
 * Curated text carries machine-readable references — `[@pmid:36870750]`,
 * `[@genereviews:NBK564656]` — which are provenance for the catalog, not
 * sentences for a reader. They stay in the underlying table (the agent may want
 * them); they do not belong in a paragraph on screen.
 */
export function cleanProse(value: string | null | undefined): string {
  if (!value) return "";
  return value
    .replace(/\s*\[@[^\]]*\]/g, "")
    .replace(/\s+([.,;:])/g, "$1")
    .replace(/\s{2,}/g, " ")
    .trim();
}

/** STRchive stores list fields as semicolon-joined strings. */
export function splitList(value: string | null | undefined): string[] {
  if (!value) return [];
  return value
    .split(";")
    .map((item) => item.trim())
    .filter(Boolean);
}

export interface CopyScale {
  min: number;
  max: number;
  /** Position of a copy number along the axis, as a percentage 0-100. */
  toPercent: (copies: number) => number;
  /** Round copy numbers spanning the domain, for axis ticks. */
  ticks: number[];
}

const LOG = (value: number) => Math.log1p(Math.max(0, value));

export function buildCopyScale(
  locus: Pick<
    StrchiveLocus,
    "benign_min" | "benign_max" | "intermediate_min" | "intermediate_max" |
    "pathogenic_min" | "pathogenic_max" | "ref_copies"
  >,
  extra: (number | null | undefined)[] = [],
  /**
   * Force the domain's upper bound. Rows stacked in a list must share one scale
   * or the reader compares band widths that are not comparable — a per-row
   * domain silently rescales every row to its own maximum.
   */
  fixedMax?: number,
): CopyScale {
  const candidates = [
    locus.benign_max,
    locus.intermediate_max,
    locus.pathogenic_max,
    locus.pathogenic_min,
    locus.ref_copies,
    ...extra,
  ].filter((value): value is number => value != null && Number.isFinite(value));

  const max = fixedMax ?? Math.max(10, ...candidates) * 1.15;
  const min = 0;
  const span = LOG(max) - LOG(min) || 1;

  // One tick per power of ten inside the domain, plus the endpoints. Enough to
  // read the scale as logarithmic without crowding a 3rem-tall strip.
  const ticks: number[] = [0];
  for (let power = 0; Math.pow(10, power) <= max; power += 1) {
    ticks.push(Math.pow(10, power));
  }

  return {
    min,
    max,
    ticks,
    toPercent: (copies: number) =>
      Math.max(0, Math.min(100, ((LOG(copies) - LOG(min)) / span) * 100)),
  };
}

export interface Band {
  key: AlleleClass;
  label: string;
  from: number;
  to: number;
  color: string;
}

/**
 * The curated ranges as drawable bands, lowest first. A locus may record none of
 * them — 3 of the 82 have no pathogenic range at all — so the caller must handle
 * an empty result rather than assuming three bands.
 */
export function buildBands(locus: StrchiveLocus): Band[] {
  const bands: Band[] = [];
  const push = (
    key: AlleleClass,
    label: string,
    from: number | null,
    to: number | null,
    color: string,
  ) => {
    if (from == null || to == null) return;
    bands.push({ key, label, from, to: Math.max(to, from), color });
  };

  push("benign", "Benign", locus.benign_min, locus.benign_max, "var(--benign)");
  push(
    "intermediate",
    "Intermediate",
    locus.intermediate_min,
    locus.intermediate_max,
    "var(--intermediate)",
  );
  push(
    "pathogenic",
    "Pathogenic",
    locus.pathogenic_min,
    locus.pathogenic_max,
    "var(--pathogenic)",
  );
  return bands;
}

/**
 * Which class a copy number falls in.
 *
 * Mirrors the pipeline's rule rather than inventing a second one: where the
 * benign and intermediate ranges overlap at their edges (RFC1: benign 0-11,
 * intermediate 11-200) the more actionable class wins, so the test runs from
 * pathogenic downward. A locus with no range for a class simply cannot return it.
 */
export function classifyCopies(
  locus: StrchiveLocus,
  copies: number | null | undefined,
): AlleleClass {
  if (copies == null || !Number.isFinite(copies)) return "unknown";
  const within = (min: number | null, max: number | null) =>
    min != null && copies >= min && (max == null || copies <= max);

  if (within(locus.pathogenic_min, locus.pathogenic_max)) return "pathogenic";
  if (within(locus.intermediate_min, locus.intermediate_max)) return "intermediate";
  if (within(locus.benign_min, locus.benign_max)) return "benign";
  // Above every recorded range still reads as pathogenic where one exists: the
  // maxima are the largest allele reported, not a ceiling on the disease.
  if (locus.pathogenic_min != null && copies > locus.pathogenic_min) return "pathogenic";
  return "unknown";
}

export const ALLELE_COLORS: Record<AlleleClass, string> = {
  benign: "var(--benign)",
  intermediate: "var(--intermediate)",
  pathogenic: "var(--pathogenic)",
  unknown: "var(--allele-unknown)",
};

/** Copy numbers are estimates carrying a decimal; whole numbers read better. */
export function formatCopies(copies: number | null | undefined): string {
  if (copies == null || !Number.isFinite(copies)) return "—";
  return copies >= 100 ? copies.toFixed(0) : copies.toFixed(1).replace(/\.0$/, "");
}

/** Evidence tiers, strongest first — STRchive's own curation confidence order. */
export const EVIDENCE_ORDER = [
  "Definitive",
  "Strong",
  "Moderate",
  "Limited",
  "Provisional",
  "Disputed",
  "Refuted",
] as const;

/**
 * The largest copy number anywhere in a set of loci, for a shared axis.
 * Rounded up to the next power of ten so the domain does not shift when the
 * filter changes and drops the current maximum.
 */
export function sharedCopyMax(loci: StrchiveLocus[]): number {
  let max = 10;
  for (const locus of loci) {
    for (const value of [locus.pathogenic_max, locus.benign_max, locus.intermediate_max]) {
      if (value != null && Number.isFinite(value)) max = Math.max(max, value);
    }
  }
  return Math.pow(10, Math.ceil(Math.log10(max)));
}
