"use client";

import { useMemo } from "react";

import { formatBp } from "@/lib/palette";
import { REGION_LABELS, type Locus } from "@/lib/types";

/**
 * Where the insertion lands inside the gene — the Gviz/UCSC question, answered
 * with only what AnnotSV actually knows.
 *
 * WHAT THIS DRAWS, AND WHAT IT REFUSES TO. AnnotSV gives the exon *count* of one
 * transcript, the SV's *ordinal* location within it (`intron12-intron12`), and
 * the transcript's start and end. It does NOT give per-exon coordinates. So the
 * ladder below is explicitly a schematic: every exon is drawn the same width and
 * every intron the same width, because drawing them at invented widths would be
 * a genome browser's picture with none of a genome browser's evidence.
 *
 * What IS real is the ORDER and the ORDINAL. Exon 4 really is the fourth exon and
 * really does sit between introns 3 and 4, so the numbers under the track can be
 * counted and pointed at even though the distances between them cannot be
 * measured. The insertion's slot is real for the same reason, and
 * `dist_nearest_ss` in the caption places it against a real splice site.
 *
 * WHY THE TRANSCRIPT IS NAMED, NOT THE GENE. Exon count is a property of the
 * transcript AnnotSV happened to pick, and its pick is not stable: 929 genes get
 * more than one across their loci, and more than half the transcripts used are
 * `XM_` predicted models. A header reading "PTPRN2 · 22 exons" would state as a
 * fact about the gene something that is a fact about one model of it — PTPRN2
 * draws 22 exons at 26 of its loci and 23 at the other 18. So the accession is
 * shown, linked, and the count is attributed to it.
 */

/** Exons drawn before the ladder starts eliding. Past this the boxes are thinner
    than the gaps between them and the drawing stops carrying information; the
    longest transcript in the HPRC callset has 313. */
const MAX_DRAWN = 15;
/** Exons kept either side of the insertion when eliding. */
const CONTEXT = 4;

/**
 * One position along the transcript.
 *
 * Introns are slots in their own right rather than the space left over between
 * exons, because they are half of what this drawing is for: most insertions land
 * in one, and an intron the reader cannot point at cannot be numbered. Intron
 * `n` is the one between exon `n` and exon `n + 1`, which is the convention the
 * `Location_merged` ordinals already use.
 */
export type Slot =
  | { kind: "exon"; index: number }
  | { kind: "intron"; index: number }
  | { kind: "gap" };

/**
 * The slots to draw, left to right, with a `gap` where a run has been elided.
 *
 * A short transcript draws whole. A long one keeps the first exon, the last, and
 * a window around the insertion — the three things the reader is placing — and
 * marks what it dropped. This is what a browser does when you zoom, and it keeps
 * a 313-exon transcript legible without pretending it is short.
 *
 * An elided run becomes ONE `gap`, never a numbered intron: the space between
 * exon 1 and exon 7 contains six introns, and labelling it "intron 1" would be a
 * lie about a stretch the drawing has already admitted it is not showing.
 */
export function ladder(exonCount: number, at: number | null): Slot[] {
  const kept =
    exonCount <= MAX_DRAWN
      ? Array.from({ length: exonCount }, (_, i) => i + 1)
      : (() => {
          const focus = at ?? Math.ceil(exonCount / 2);
          const keep = new Set<number>([1, exonCount]);
          for (let i = focus - CONTEXT; i <= focus + CONTEXT + 1; i += 1) {
            if (i >= 1 && i <= exonCount) keep.add(i);
          }
          return [...keep].sort((a, b) => a - b);
        })();

  const slots: Slot[] = [];
  kept.forEach((exon, i) => {
    if (i > 0) {
      const previous = kept[i - 1];
      slots.push(
        exon === previous + 1 ? { kind: "intron", index: previous } : { kind: "gap" },
      );
    }
    slots.push({ kind: "exon", index: exon });
  });
  return slots;
}

/** The exon the ladder centres its window on when it has to elide. */
function focusExon(locus: Locus): number | null {
  return locus.feature_index ?? null;
}

/** "intron 12 of 22", or "exon 1 of 8". */
function featureLabel(locus: Locus): string | null {
  if (!locus.feature || locus.feature_index == null) return null;
  const total = locus.exon_count;
  const of = locus.feature === "exon" ? total : total != null ? total - 1 : null;
  return `${locus.feature} ${locus.feature_index}${of != null ? ` of ${of}` : ""}`;
}

/** The distance to the nearest splice site, which is a real measured number. */
function spliceLabel(locus: Locus): string | null {
  if (locus.dist_nearest_ss == null) return null;
  const end = locus.nearest_ss_type === "5'" ? "5′" : locus.nearest_ss_type === "3'" ? "3′" : null;
  return `${formatBp(locus.dist_nearest_ss)} from the ${end ? `${end} ` : ""}splice site`;
}

/**
 * The insertion marker: a tick with a downward arrowhead.
 *
 * Only ever drawn in an INTRON slot. An exon hit is marked by filling its box
 * instead — see the note there — so this can assume the empty band above it and
 * put its arrowhead there without colliding with a number.
 */
function Caret({ title }: { title?: string }) {
  return (
    <span
      className="pointer-events-none absolute -top-1.5 bottom-0 left-1/2 z-20 w-0.5 -translate-x-1/2"
      style={{ background: "var(--novel)" }}
      title={title}
      aria-hidden
    >
      <span
        className="absolute -top-1 left-1/2 h-0 w-0 -translate-x-1/2"
        style={{
          borderLeft: "3.5px solid transparent",
          borderRight: "3.5px solid transparent",
          borderTop: "5px solid var(--novel)",
        }}
      />
    </span>
  );
}

/**
 * The ladder itself: exon boxes on an intron line, filling the column.
 *
 * THE WIDTH RULE, which is also a fidelity rule. Exons are capped and introns
 * take every pixel left over, so the row always fills the panel. That is not
 * only to use the space: in a real gene introns dwarf exons — PTPRN2 spans
 * 780 kb of which a few kb is exonic — so letting the intron slots absorb the
 * slack puts the drawing on the right side of the distortion. A three-exon gene
 * gets long introns and small boxes, which is what it is.
 *
 * Three bands, so nothing collides: exon numbers above the line, the track
 * itself, intron numbers below. Both are drawn because numbering only one half
 * of an alternating sequence makes the other half harder to count, not easier.
 */
function ExonLadder({ locus }: { locus: Locus }) {
  const exonCount = locus.exon_count ?? 0;
  const focus = focusExon(locus);
  const slots = useMemo(() => ladder(exonCount, focus), [exonCount, focus]);
  const label = featureLabel(locus);

  const hitIntron = locus.feature === "intron" ? locus.feature_index : null;
  const hitExon = locus.feature === "exon" ? locus.feature_index : null;

  return (
    <div
      className="relative flex w-full items-stretch py-1"
      role="img"
      aria-label={
        `Schematic of ${locus.tx ?? "the transcript"}, ${exonCount} exons; ` +
        `insertion in ${label ?? "an unplaced feature"}`
      }
    >
      {/* 5′ and 3′ ends, so the reader knows which way the transcript runs. They
          sit in the middle band with the track, not above it. */}
      <span className="relative z-10 self-center pr-1 text-[10px] text-ink-muted">5′</span>

      <div className="relative flex min-w-0 flex-1 items-stretch">
        {/* The backbone runs the full width behind everything, so an elided run
            still reads as continuous sequence rather than a break in the gene. */}
        <span
          aria-hidden
          className="absolute inset-x-0 top-1/2 h-px -translate-y-1/2"
          style={{ background: "var(--baseline)" }}
        />

        {slots.map((slot, index) => {
          if (slot.kind === "gap") {
            return (
              <span
                key={`gap-${index}`}
                className="relative grid shrink-0 grid-rows-[11px_18px_11px] justify-items-center px-1"
                title="exons not drawn to keep the transcript legible"
              >
                <span />
                <span className="self-center text-[10px] leading-none text-ink-muted">⋯</span>
                <span />
              </span>
            );
          }

          if (slot.kind === "intron") {
            const isHit = slot.index === hitIntron;
            return (
              <span
                key={`i${slot.index}`}
                // flex-[3]: introns absorb the slack the capped exons leave.
                className="relative grid min-w-[14px] flex-[3] grid-rows-[11px_18px_11px] justify-items-center"
                title={`intron ${slot.index}${isHit ? " — insertion here" : ""}`}
              >
                <span />
                <span className="relative w-full self-stretch">
                  {/* The gridline. Faint on purpose: it marks a FEATURE BOUNDARY,
                      not a distance — this drawing has no bp scale to rule — so
                      it has to read as a tick you can count against, never as a
                      measurement you could read off. */}
                  <span
                    aria-hidden
                    className="absolute left-1/2 top-0 bottom-0 w-px -translate-x-1/2"
                    style={{ background: "var(--hairline)", opacity: 0.9 }}
                  />
                  {isHit && <Caret title={label ?? undefined} />}
                </span>
                <span
                  className="self-start text-[9px] leading-none tabular"
                  style={{ color: isHit ? "var(--novel)" : "var(--ink-muted)" }}
                >
                  {slot.index}
                </span>
              </span>
            );
          }

          const isHit = slot.index === hitExon;
          return (
            <span
              key={`e${slot.index}`}
              // Capped: past ~44px an exon box stops looking like a feature and
              // starts looking like a bar with a length, which it does not have.
              className="relative grid min-w-[7px] max-w-[44px] flex-1 grid-rows-[11px_18px_11px] justify-items-center"
              title={`exon ${slot.index}${isHit ? " — insertion here" : ""}`}
            >
              <span
                className="self-end text-[9px] leading-none tabular"
                style={{ color: isHit ? "var(--novel)" : "var(--ink-muted)" }}
              >
                {slot.index}
              </span>
              {/* No caret on an exon hit. It would be orange drawn on orange —
                  invisible — and its arrowhead would land on the exon number
                  directly above. The filled, outlined box and the orange number
                  already are the marker; the caret exists for the intron case,
                  where the slot is otherwise empty and needs something to point. */}
              <span className="relative flex w-full items-center justify-center">
                <span
                  className="relative z-10 block h-3.5 w-full rounded-[1px]"
                  style={{
                    background: isHit ? "var(--novel)" : "var(--known)",
                    outline: isHit ? "1px solid var(--novel)" : undefined,
                    outlineOffset: 1,
                  }}
                />
              </span>
              <span />
            </span>
          );
        })}
      </div>

      <span className="relative z-10 self-center pl-1 text-[10px] text-ink-muted">3′</span>
    </div>
  );
}

/** The intergenic case: no gene body, and the two genes it sits between. */
function IntergenicTrack({ locus }: { locus: Locus }) {
  const left = locus.closest_left;
  const right = locus.closest_right;
  return (
    <div className="flex items-center gap-2 py-2">
      <span className="tabular truncate text-[11px] text-ink-secondary" title={left ?? undefined}>
        {left ?? "—"}
      </span>
      <span className="relative flex-1">
        <span
          aria-hidden
          className="absolute inset-x-0 top-1/2 h-px -translate-y-1/2"
          style={{ background: "var(--baseline)" }}
        />
        <span className="relative flex h-5 items-center justify-center">
          <Caret />
        </span>
      </span>
      <span className="tabular truncate text-right text-[11px] text-ink-secondary" title={right ?? undefined}>
        {right ?? "—"}
      </span>
    </div>
  );
}

export function GeneTrack({ locus }: { locus: Locus }) {
  // Three states, and they are genuinely different. `genic === undefined` means
  // this table was never gene-annotated; false means the screen ran and the site
  // is between genes. Collapsing them would report a missing column as a finding.
  if (locus.genic === undefined) {
    return (
      <div className="rounded-lg border border-hairline bg-surface p-3">
        <h3 className="text-[11px] font-medium uppercase tracking-wide text-ink-secondary">
          Gene context
        </h3>
        <p className="mt-1 text-[11px] text-ink-muted">
          This table carries no gene annotation, so there is nothing to place this
          insertion in — not the same as it being intergenic. Run it through
          AnnotSV and register the output.
        </p>
      </div>
    );
  }

  const region = locus.region ? REGION_LABELS[locus.region] : null;
  const feature = featureLabel(locus);
  const splice = spliceLabel(locus);

  return (
    <div className="rounded-lg border border-hairline bg-surface p-3">
      <div className="flex flex-wrap items-baseline justify-between gap-x-3 gap-y-1">
        <h3 className="text-[11px] font-medium uppercase tracking-wide text-ink-secondary">
          Gene context
        </h3>
        {locus.cytoband && (
          <span className="tabular text-[11px] text-ink-muted">{locus.cytoband}</span>
        )}
      </div>

      {locus.genic ? (
        <>
          <div className="mt-1 flex flex-wrap items-baseline gap-x-2 gap-y-0.5">
            <span className="text-sm font-medium text-ink">{locus.gene}</span>
            {(locus.gene_count ?? 1) > 1 && (
              <span
                className="text-[11px] text-ink-muted"
                title={locus.all_genes?.split(";").join(", ")}
              >
                +{(locus.gene_count ?? 1) - 1} more gene
                {(locus.gene_count ?? 1) > 2 ? "s" : ""} here
              </span>
            )}
            {locus.exonic && (
              <span
                className="rounded-sm px-1 text-[10px] font-medium"
                style={{ background: "var(--novel-soft)", color: "var(--novel)" }}
              >
                exonic
              </span>
            )}
            {locus.pli != null && locus.pli >= 0.9 && (
              <span className="text-[11px] text-ink-muted" title="gnomAD pLI — intolerant of loss of function">
                pLI {locus.pli.toFixed(2)}
              </span>
            )}
          </div>

          {locus.exon_count != null && <ExonLadder locus={locus} />}

          <p className="text-[11px] leading-relaxed text-ink-muted">
            {feature && <span className="text-ink-secondary">{feature}</span>}
            {feature && splice && " · "}
            {splice}
            {(feature || splice) && region && " · "}
            {region}
          </p>

          {/* The caveat travels with the picture, not with the docs. Exon widths
              are the invented part and the reader is entitled to know which part
              that is. */}
          {locus.exon_count != null && (
            <p className="mt-1 text-[10px] leading-relaxed text-ink-muted">
              Schematic, not to scale — {locus.tx} reports a count, not coordinates.
              Every exon is drawn the same width and every intron the same width, so
              the numbering and the order are real but the spacing is not; the
              gridlines mark feature boundaries, not distances.
            </p>
          )}
        </>
      ) : (
        <>
          <div className="mt-1 text-sm text-ink">Intergenic</div>
          <IntergenicTrack locus={locus} />
          <p className="text-[11px] leading-relaxed text-ink-muted">
            No gene overlaps this insertion. The names either side are the nearest
            annotated genes, which are not necessarily close.
          </p>
        </>
      )}
    </div>
  );
}
