/**
 * Reading a locus string the way a genome browser does.
 *
 * One box takes both a genomic range and a gene name, because that is the box
 * every genome browser has and the one this project's readers already have in
 * their fingers. Parsing decides which filter the text becomes; the chip row
 * then says which one it became, so a mistyped range lands visibly as a gene
 * search rather than silently doing nothing.
 */

/** `chr3:1,000-50,000` — the `chr` and the separators optional, `..` allowed. */
const RANGE = /^(?:chr)?(\d{1,2}|X|Y|M|MT)\s*:\s*([\d,_ ]+?)\s*(?:\.\.|-)\s*([\d,_ ]+)$/i;

/**
 * A whole chromosome, `chr` prefix required.
 *
 * A range can drop the prefix — `3:1000-50000` is not a gene by any reading —
 * but a bare one cannot: someone typing `X` is looking for XYLT1, not for the
 * X chromosome, and a search box that swallowed that would be worse than one
 * that asked for three more characters.
 */
const CHROM = /^chr(\d{1,2}|X|Y|M|MT)$/i;

/** What a line of text in the search box turns out to mean. */
export type LocusQuery =
  | { kind: "empty" }
  | { kind: "region"; region: string; chrom: string; start: number; end: number }
  | { kind: "chrom"; chrom: string }
  | { kind: "gene"; text: string };

/** `3` → `chr3`, `x` → `chrX`, `MT` → `chrM`. Mirrors _normalize_chrom in the API. */
function normalizeChrom(name: string): string {
  const upper = name.toUpperCase();
  return `chr${upper === "MT" ? "M" : upper}`;
}

function toInt(text: string): number {
  return Number.parseInt(text.replace(/[,_ ]/g, ""), 10);
}

export function parseLocusQuery(input: string): LocusQuery {
  const text = input.trim();
  if (!text) return { kind: "empty" };

  const range = RANGE.exec(text);
  if (range) {
    const chrom = normalizeChrom(range[1]);
    // A backwards range is read in the order it was meant. Returning nothing
    // for chr3:500-100 would be correct and useless.
    const [start, end] = [toInt(range[2]), toInt(range[3])].sort((a, b) => a - b);
    return { kind: "region", region: `${chrom}:${start}-${end}`, chrom, start, end };
  }

  const chrom = CHROM.exec(text);
  if (chrom) return { kind: "chrom", chrom: normalizeChrom(chrom[1]) };

  return { kind: "gene", text };
}

/** `chr3:1000-50000` → `chr3:1,000–50,000`, for a chip or a hint. */
export function formatRegion(region: string): string {
  const parsed = parseLocusQuery(region);
  if (parsed.kind !== "region") return region;
  const { chrom, start, end } = parsed;
  return `${chrom}:${start.toLocaleString("en-US")}–${end.toLocaleString("en-US")}`;
}

/**
 * How wide the range is, both ends inclusive — the API reads it the same way.
 *
 * Windows are read in Mb where allele lengths (formatBp) top out at kb, so this
 * does its own units rather than reporting a chromosome arm as "63000 kb".
 */
export function formatSpan(region: string): string | null {
  const parsed = parseLocusQuery(region);
  if (parsed.kind !== "region") return null;
  const span = parsed.end - parsed.start + 1;
  if (span >= 1_000_000) return `${+(span / 1_000_000).toFixed(span >= 10_000_000 ? 0 : 1)} Mb`;
  if (span >= 1_000) return `${+(span / 1_000).toFixed(span >= 10_000 ? 0 : 1)} kb`;
  return `${span} bp`;
}
