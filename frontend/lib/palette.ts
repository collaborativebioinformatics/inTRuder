/**
 * Chart color assignment.
 *
 * The categorical slots below are the first three of a validated palette. Three,
 * not eight, is deliberate: in a barcode any two motif blocks can end up
 * adjacent, so the palette has to clear the all-pairs colorblind-separation
 * floors rather than the easier adjacent-pairs ones. Only the first three slots
 * do. Every motif past the top three at a locus folds into a neutral "Other",
 * which is also how the data behaves — loci are dominated by one or two motifs.
 *
 * Colors resolve from CSS custom properties so light/dark swap in one place.
 */

export const MOTIF_SLOTS = ["var(--motif-1)", "var(--motif-2)", "var(--motif-3)"] as const;
export const MOTIF_OTHER = "var(--motif-other)";
export const FLANK = "var(--flank)";

export const FUNNEL_STEPS = [
  "var(--step-1)",
  "var(--step-2)",
  "var(--step-3)",
  "var(--step-4)",
  "var(--step-5)",
] as const;

/**
 * Rank the motifs at a locus by how much sequence they account for, then assign
 * the three categorical slots in that fixed order. Color follows the motif, not
 * its position, so filtering the sample list never repaints the survivors.
 */
export function buildMotifScale(
  segments: { motif: string | null; start: number; end: number }[],
): Map<string, string> {
  const spanByMotif = new Map<string, number>();
  for (const segment of segments) {
    if (!segment.motif) continue;
    spanByMotif.set(
      segment.motif,
      (spanByMotif.get(segment.motif) ?? 0) + (segment.end - segment.start),
    );
  }

  const ranked = [...spanByMotif.entries()]
    .sort((a, b) => b[1] - a[1] || a[0].localeCompare(b[0]))
    .map(([motif]) => motif);

  const scale = new Map<string, string>();
  ranked.forEach((motif, index) => {
    scale.set(motif, index < MOTIF_SLOTS.length ? MOTIF_SLOTS[index] : MOTIF_OTHER);
  });
  return scale;
}

export function motifColor(scale: Map<string, string>, motif: string | null): string {
  if (!motif) return FLANK;
  return scale.get(motif) ?? MOTIF_OTHER;
}

/** Motifs long enough to display in full get shown; the rest are elided. */
export function shortMotif(motif: string, max = 12): string {
  return motif.length <= max ? motif : `${motif.slice(0, max - 1)}…`;
}

export function formatBp(value: number): string {
  if (value >= 1000) return `${(value / 1000).toFixed(value >= 10000 ? 0 : 1)} kb`;
  return `${value} bp`;
}

export function formatPos(chrom: string, pos: number): string {
  return `${chrom}:${pos.toLocaleString("en-US")}`;
}
