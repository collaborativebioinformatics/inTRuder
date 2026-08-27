"use client";

import { useMemo, useState } from "react";

import { MotifBarcode, SegmentTooltip } from "@/components/MotifBarcode";
import { NoveltyBadge, PlatformAgreement, noveltyOf } from "@/components/NoveltyBadge";
import { formatBp, formatPos, shortMotif } from "@/lib/palette";
import { NOVELTY_LABELS, type Locus, type Segment } from "@/lib/types";
import { useView } from "@/lib/viewStore";

/**
 * Level 1 — the catalog. Every locus is one barcode row.
 *
 * At this zoom the block color drops motif identity and carries the finding
 * instead: warm means no catalog contains this locus, recessive grey means it is
 * already known. That makes the novel fraction readable as texture down the
 * page, before anyone touches a control. Motif identity comes back at level 2,
 * where novelty is constant and no longer needs the channel.
 *
 * The screen's verdict is three-valued, and the strip deliberately does not try
 * to carry that third value: opacity is already spoken for by purity, so
 * motif-novelty versus locus-novelty rides on the text badge instead. Colour
 * answers "is this new"; the badge answers "new in what way".
 */

export function CatalogView({
  loci,
  strips,
  total,
  loading,
}: {
  loci: Locus[];
  strips: Record<string, Segment[]>;
  total: number;
  loading: boolean;
}) {
  const { focusLocus } = useView();
  const [hover, setHover] = useState<{ segment: Segment; x: number; y: number } | null>(null);

  // Row lengths span two orders of magnitude here (tens of bp to several kb), so
  // a shared linear scale renders most rows as a 1px sliver. Each row's overall
  // width is sqrt-compressed against the global maximum — longer still reads as
  // wider, but the small end stays legible — while segments *within* a row keep
  // strictly linear proportions, so composition is never distorted. Level 2 goes
  // back to a shared linear scale, where the range is narrow and comparing
  // allele lengths between samples is the whole point.
  const { rowLength, globalMax } = useMemo(() => {
    const lengths = new Map<string, number>();
    let max = 1;
    for (const [locusId, segments] of Object.entries(strips)) {
      let end = 0;
      for (const segment of segments) end = Math.max(end, segment.end);
      lengths.set(locusId, end);
      max = Math.max(max, end);
    }
    return { rowLength: lengths, globalMax: max };
  }, [strips]);

  return (
    <section aria-labelledby="catalog-heading" className="flex min-h-0 flex-col">
      <header className="flex flex-wrap items-baseline justify-between gap-x-6 gap-y-2 pb-3">
        <h2 id="catalog-heading" className="text-sm font-medium text-ink">
          Candidate loci{" "}
          <span className="tabular font-normal text-ink-muted">
            {loci.length.toLocaleString("en-US")} of {total.toLocaleString("en-US")}
          </span>
        </h2>

        <div className="flex items-center gap-4 text-xs text-ink-secondary">
          <span className="flex items-center gap-1.5">
            <span
              className="inline-block h-2.5 w-2.5 rounded-sm"
              style={{ background: "var(--novel)" }}
            />
            Absent from catalogs
          </span>
          <span className="flex items-center gap-1.5">
            <span
              className="inline-block h-2.5 w-2.5 rounded-sm"
              style={{ background: "var(--known)" }}
            />
            Already catalogued
          </span>
          <span className="flex items-center gap-1.5">
            <span
              className="inline-block h-1 w-2.5 rounded-sm"
              style={{ background: "var(--flank)" }}
            />
            Flank
          </span>
        </div>
      </header>

      <div className="min-h-0 flex-1 overflow-y-auto rounded-lg border border-hairline bg-surface">
        {loading && loci.length === 0 ? (
          <p className="p-6 text-sm text-ink-muted">Loading loci…</p>
        ) : loci.length === 0 ? (
          <p className="p-6 text-sm text-ink-muted">
            No loci match these filters. Try clearing one.
          </p>
        ) : (
          <ul className="divide-y divide-hairline">
            {loci.map((locus) => {
              const segments = strips[locus.locus_id] ?? [];
              return (
                <li key={locus.locus_id}>
                  <button
                    type="button"
                    onClick={() => focusLocus(locus.locus_id)}
                    className="grid w-full grid-cols-[minmax(9rem,1fr)_2fr_minmax(7rem,auto)] items-center gap-4 px-3 py-2 text-left transition-colors hover:bg-surface-raised focus-visible:outline-2 focus-visible:-outline-offset-2 focus-visible:outline-[var(--motif-1)]"
                  >
                    <div className="min-w-0">
                      <div className="flex items-center gap-1.5">
                        <span className="tabular truncate text-xs text-ink">
                          {formatPos(locus.chrom, locus.pos)}
                        </span>
                        {locus.disease_gene && (
                          <span
                            title="Known repeat-expansion gene"
                            className="shrink-0 rounded-sm px-1 text-[10px] font-medium text-novel"
                            style={{ background: "var(--novel-soft)" }}
                          >
                            {locus.gene}
                          </span>
                        )}
                      </div>
                      <div className="mt-0.5 flex items-center gap-1.5">
                        <NoveltyBadge status={noveltyOf(locus)} />
                        <PlatformAgreement
                          ucsc={locus.ucsc_novelty}
                          trexplorer={locus.trexplorer_novelty}
                          ucscEdits={locus.ucsc_motif_edits}
                          trexplorerEdits={locus.trexplorer_motif_edits}
                        />
                      </div>
                      <div className="tabular truncate text-[11px] text-ink-muted">
                        {shortMotif(locus.motif)} ×{locus.motif_len}bp · {locus.motif_class}
                      </div>
                    </div>

                    <div
                      style={{
                        width: `${Math.max(2, Math.sqrt((rowLength.get(locus.locus_id) ?? 1) / globalMax) * 100)}%`,
                      }}
                    >
                      <MotifBarcode
                        segments={segments}
                        maxLen={rowLength.get(locus.locus_id) ?? 1}
                        height={14}
                        ariaLabel={`${locus.locus_id}: ${NOVELTY_LABELS[noveltyOf(locus)]} ${locus.motif_class}, ${formatBp(locus.median_len)}`}
                        colorFor={(segment) =>
                          segment.seg_type === "flank"
                            ? "var(--flank)"
                            : noveltyOf(locus) === "known"
                              ? "var(--known)"
                              : "var(--novel)"
                        }
                        onHover={(segment, event) =>
                          setHover(
                            segment && event
                              ? { segment, x: event.clientX, y: event.clientY }
                              : null,
                          )
                        }
                      />
                    </div>

                    <div className="tabular flex items-center justify-end gap-3 text-xs">
                      <span className="text-ink-secondary">{formatBp(locus.median_len)}</span>
                      <span
                        className="flex items-center gap-1 text-ink-muted"
                        title={`${locus.n_samples} of 68 samples carry this insertion`}
                      >
                        <span
                          className="inline-block h-1.5 w-8 overflow-hidden rounded-full"
                          style={{ background: "var(--hairline)" }}
                        >
                          <span
                            className="block h-full rounded-full"
                            style={{
                              width: `${(locus.n_samples / 68) * 100}%`,
                              background: "var(--baseline)",
                            }}
                          />
                        </span>
                        {locus.n_samples}
                      </span>
                    </div>
                  </button>
                </li>
              );
            })}
          </ul>
        )}
      </div>

      {hover && (
        <div
          role="tooltip"
          className="pointer-events-none fixed z-50 max-w-xs rounded-md border border-hairline bg-surface-raised px-2.5 py-1.5 text-xs shadow-lg"
          style={{ left: hover.x + 12, top: hover.y + 12 }}
        >
          <SegmentTooltip segment={hover.segment} />
        </div>
      )}
    </section>
  );
}
