"use client";

import { MotifText } from "@/components/MotifText";
import { formatBp } from "@/lib/palette";
import {
  NOVELTY_LABELS,
  PLATFORM_LABELS,
  type Locus,
  type NoveltyStatus,
  type PlatformName,
} from "@/lib/types";

/**
 * What hg38 annotates at this locus, above everything else on the page.
 *
 * The whole claim of this project is a comparison — this repeat is or is not
 * already in the reference — and a page that opens with our own alleles alone
 * shows the reader one side of it. So the reference goes first, in both the
 * forms the comparison actually takes: the numbers, and the size.
 *
 * The empty case is rendered, not omitted. "The reference annotates no repeat
 * here" is the strongest finding this pipeline produces, and a panel that simply
 * disappeared when a catalog found nothing would hide exactly the loci worth
 * looking at.
 *
 * COORDINATE CAVEAT, and the reason the track is drawn unlike an allele: a
 * reference repeat's start/end are GRCh38 coordinates, while an allele's
 * segments are offsets *inside the inserted sequence*. Both are lengths in bp,
 * so comparing their widths is meaningful — that is the point — but they are not
 * one axis, and the track says so rather than letting the alignment imply it.
 */

const PLATFORMS: PlatformName[] = ["ucsc", "trexplorer"];

/** One catalog's answer at this locus, pulled out of the flat Locus row. */
export interface ReferenceHit {
  platform: PlatformName;
  novelty: NoveltyStatus;
  /** Null throughout when this catalog annotates nothing here. */
  start: number | null;
  end: number | null;
  span: number | null;
  distance: number | null;
  motif: string | null;
  nNearby: number | null;
  /** UCSC only — TRExplorer carries position and motif and nothing else. */
  period?: number | null;
  copyNum?: number | null;
  perMatch?: number | null;
}

/**
 * Read the per-catalog blocks off a locus.
 *
 * Returns an empty array when the table carries no screen at all, which is a
 * different state from a screen that found nothing and is reported differently.
 */
export function referenceHits(locus: Locus): ReferenceHit[] {
  const hits: ReferenceHit[] = [];
  for (const platform of PLATFORMS) {
    const novelty = locus[`${platform}_novelty` as const];
    if (!novelty) continue;
    const start = locus[`${platform}_start` as const] ?? null;
    const end = locus[`${platform}_end` as const] ?? null;
    hits.push({
      platform,
      novelty,
      start,
      end,
      span: start !== null && end !== null ? end - start : null,
      distance: locus[`${platform}_distance` as const] ?? null,
      motif: locus[`${platform}_motif` as const] ?? null,
      nNearby: locus[`${platform}_n_nearby` as const] ?? null,
      ...(platform === "ucsc"
        ? {
            period: locus.ucsc_period ?? null,
            copyNum: locus.ucsc_copy_num ?? null,
            perMatch: locus.ucsc_per_match ?? null,
          }
        : {}),
    });
  }
  return hits;
}

/** Widest reference repeat at this locus, for sharing the track's bp scale. */
export function referenceSpan(hits: ReferenceHit[]): number {
  return Math.max(0, ...hits.map((hit) => hit.span ?? 0));
}

function formatRange(chrom: string, start: number, end: number): string {
  return `${chrom}:${start.toLocaleString("en-US")}–${end.toLocaleString("en-US")}`;
}

/** Where the insertion point sits relative to the annotated repeat. */
function placement(distance: number | null): string {
  if (distance === null) return "";
  return distance === 0 ? "insertion point inside it" : `${distance} bp away`;
}

/** One row of the numeric panel. */
function HitRow({ hit, chrom }: { hit: ReferenceHit; chrom: string }) {
  const label = PLATFORM_LABELS[hit.platform];

  if (hit.novelty === "novel_locus") {
    return (
      <div className="grid grid-cols-[9.5rem_1fr] items-baseline gap-x-3 gap-y-0.5">
        <dt className="text-[11px] text-ink-secondary">{label}</dt>
        <dd className="text-xs text-ink-muted">no repeat annotated within 10 bp</dd>
      </div>
    );
  }

  // Copy number and identity are UCSC-only; TRExplorer records position and
  // motif and nothing else, so its row is deliberately shorter rather than
  // padded with placeholders.
  const facts = [
    hit.copyNum != null ? `×${hit.copyNum.toFixed(1)}` : null,
    hit.span != null ? formatBp(hit.span) : null,
    hit.perMatch != null ? `${hit.perMatch}% identity` : null,
  ].filter(Boolean);

  return (
    <div className="grid grid-cols-[9.5rem_1fr] items-baseline gap-x-3 gap-y-0.5">
      <dt className="text-[11px] text-ink-secondary">{label}</dt>
      <dd className="min-w-0">
        <div className="flex flex-wrap items-baseline gap-x-2">
          {hit.motif ? (
            <MotifText
              motif={hit.motif}
              max={22}
              className="text-xs text-ink"
              label={`${label} motif`}
            />
          ) : (
            <span className="tabular text-xs text-ink">—</span>
          )}
          <span className="tabular text-[11px] text-ink-muted">{facts.join(" · ")}</span>
        </div>
        <div className="tabular text-[11px] text-ink-muted">
          {hit.start !== null && hit.end !== null && formatRange(chrom, hit.start, hit.end)}
          {hit.distance !== null && ` · ${placement(hit.distance)}`}
          {hit.nNearby != null && hit.nNearby > 1 && ` · ${hit.nNearby} repeats in window`}
        </div>
      </dd>
    </div>
  );
}

/** How our motif came out against the reference — the comparison in one line. */
function VerdictRow({ locus, verdict }: { locus: Locus; verdict: NoveltyStatus }) {
  const outcome: Record<NoveltyStatus, string> = {
    known: "equivalent to a catalogued motif",
    novel_motif: "no catalogued motif here matches it",
    novel_locus: "nothing catalogued here to compare against",
  };
  const edits = Math.min(
    ...[locus.ucsc_motif_edits, locus.trexplorer_motif_edits]
      .filter((value): value is number => typeof value === "number")
      .concat(Number.POSITIVE_INFINITY),
  );

  return (
    <div className="grid grid-cols-[9.5rem_1fr] items-baseline gap-x-3 border-t border-hairline pt-1.5">
      <dt className="text-[11px] font-medium text-ink">This locus</dt>
      <dd className="min-w-0">
        <div className="flex flex-wrap items-baseline gap-x-2">
          <MotifText
            motif={locus.motif}
            max={22}
            className="text-xs text-ink"
            label="locus motif"
          />
          <span className="text-[11px] text-ink-secondary">→ {outcome[verdict]}</span>
        </div>
        {/* A near miss is the routine explanation for novel_motif, and it is a
            reason to doubt the call rather than a second finding. */}
        {verdict === "novel_motif" && edits === 1 && (
          <div className="text-[11px] text-ink-muted">
            one edit from the catalogued motif — likely a near miss, not a discovery
          </div>
        )}
      </dd>
    </div>
  );
}

/**
 * How far past the longest allele the shared scale is allowed to stretch.
 *
 * Sharing the scale is the entire point of the track, but a reference repeat can
 * be an order of magnitude longer than anything inserted into it, and letting one
 * 16 kb bar set the denominator would flatten all 68 allele rows into slivers —
 * destroying the comparison it was meant to serve. Past this multiple the bar is
 * clipped and says so; its label always carries the true span.
 */
export const TRACK_SCALE_CAP = 3;

/** The shared bp scale for the reference track and the allele rows below it. */
export function trackScale(hits: ReferenceHit[], longestAllele: number): number {
  return Math.max(1, longestAllele, Math.min(referenceSpan(hits), longestAllele * TRACK_SCALE_CAP));
}

/**
 * The comparable-width bar. Shares `maxLen` with the allele rows below, and is
 * drawn hatched rather than filled so it never reads as one more sample.
 */
function Track({ span, maxLen }: { span: number; maxLen: number }) {
  const clipped = span > maxLen;
  const width = maxLen > 0 ? Math.min(100, (span / maxLen) * 100) : 0;
  return (
    <div
      className="relative h-5 w-full"
      role="img"
      aria-label={
        clipped
          ? `Reference repeat, ${formatBp(span)}, drawn clipped`
          : `Reference repeat, ${formatBp(span)}`
      }
    >
      <div
        className="absolute inset-y-0 left-0 rounded-sm"
        style={{
          width: `max(2px, ${width}%)`,
          // Hatching, not a fill: the reference is a different kind of object
          // from an allele, and the texture says so without spending a hue.
          backgroundImage:
            "repeating-linear-gradient(45deg, var(--known) 0 3px, transparent 3px 6px)",
          border: "1px solid var(--known)",
          // A clipped bar loses its right edge and fades, so it cannot be read as
          // ending where the drawing ends.
          borderRightWidth: clipped ? 0 : 1,
          borderTopRightRadius: clipped ? 0 : undefined,
          borderBottomRightRadius: clipped ? 0 : undefined,
          maskImage: clipped
            ? "linear-gradient(to right, black 0 85%, transparent 100%)"
            : undefined,
        }}
      />
    </div>
  );
}

/** The empty track: an outline where a repeat would be, and why there isn't one. */
function EmptyTrack() {
  return (
    <div className="flex h-5 items-center">
      <div
        className="flex h-full w-full items-center rounded-sm px-2"
        style={{ border: "1px dashed var(--baseline)" }}
      >
        <span className="text-[10px] text-ink-muted">
          no repeat annotated within 10 bp of the insertion point
        </span>
      </div>
    </div>
  );
}

export function ReferenceComparison({
  locus,
  maxLen,
  verdict,
}: {
  locus: Locus;
  /** The allele stack's bp scale, so the track's width is comparable to a row. */
  maxLen: number;
  verdict: NoveltyStatus | "novel";
}) {
  const hits = referenceHits(locus);

  // No screen at all: say so plainly. An empty reference panel would read as
  // "the reference has nothing here", which is a finding we did not compute.
  if (hits.length === 0) {
    return (
      <div className="rounded-lg border border-hairline bg-surface p-3">
        <h3 className="text-[11px] font-medium tracking-wide text-ink-secondary uppercase">
          hg38 reference
        </h3>
        <p className="mt-1 text-[11px] text-ink-muted">
          This table carries no reference screen, so there is nothing to compare
          against — not the same as the reference being empty here. Run{" "}
          <span className="tabular">novelty annotate</span> and register the output.
        </p>
      </div>
    );
  }

  const span = referenceSpan(hits);
  const everyCatalogEmpty = hits.every((hit) => hit.novelty === "novel_locus");

  return (
    <div className="space-y-2">
      <div className="rounded-lg border border-hairline bg-surface p-3">
        <div className="flex flex-wrap items-baseline justify-between gap-2">
          <h3 className="text-[11px] font-medium tracking-wide text-ink-secondary uppercase">
            hg38 reference
          </h3>
          <span className="text-[11px] text-ink-muted">
            screened at a 10 bp window, exact motif matching
          </span>
        </div>

        <dl className="mt-2 space-y-1.5">
          {hits.map((hit) => (
            <HitRow key={hit.platform} hit={hit} chrom={locus.chrom} />
          ))}
          {verdict !== "novel" && <VerdictRow locus={locus} verdict={verdict} />}
        </dl>
      </div>

      {/* The track sits on the allele grid so its width is read against the rows
          below it, which is the comparison the panel above cannot make. The
          transparent border and padding are not decoration: they reproduce the
          1px border and p-3 of the panel the allele rows live in, so the two
          grids share a left edge. Without them the bars are offset by
          13px and the widths stop being comparable — which is the whole point. */}
      <div className="grid grid-cols-[7rem_1fr_4.5rem] items-center gap-3 rounded-lg border border-transparent px-3">
        <span className="truncate text-[11px] font-medium text-ink-secondary">
          hg38 reference
        </span>
        {everyCatalogEmpty ? <EmptyTrack /> : <Track span={span} maxLen={maxLen} />}
        <span className="tabular text-right text-[11px] text-ink-muted">
          {everyCatalogEmpty ? "—" : formatBp(span)}
        </span>
      </div>

      <p className="px-3 text-[10px] leading-relaxed text-ink-muted">
        {everyCatalogEmpty
          ? "Every carrier below inserts sequence where the reference annotates no repeat at all."
          : "Bar widths are comparable in bp, but not on one axis: the reference span is genomic, the rows below are offsets inside each inserted allele."}
        {!everyCatalogEmpty && span > maxLen && (
          <>
            {" "}
            The reference bar is clipped — at {formatBp(span)} it runs past the scale
            the allele rows need to stay readable.
          </>
        )}
      </p>
    </div>
  );
}
