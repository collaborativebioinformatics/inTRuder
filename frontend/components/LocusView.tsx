"use client";

import { useEffect, useMemo, useState } from "react";

import { MotifBarcode, SegmentTooltip } from "@/components/MotifBarcode";
import { NoveltyBadge, PlatformAgreement, noveltyOf } from "@/components/NoveltyBadge";
import { fetchLocus } from "@/lib/api";
import { buildMotifScale, formatBp, formatPos, motifColor, shortMotif } from "@/lib/palette";
import {
  NOVELTY_NOTES,
  STRCHIVE_STATUS_LABELS,
  type LocusDetail,
  type Segment,
} from "@/lib/types";
import { useView } from "@/lib/viewStore";

/**
 * Levels 2 and 3 — one locus, every carrier, motif structure made explicit.
 *
 * Same barcode primitive as the catalog, taller and re-colored: novelty is
 * constant here so the color channel goes back to motif identity. Rows are
 * sorted by allele length, which turns copy-number variation between samples
 * into a shape you read down the left edge rather than a column of numbers.
 */

function Stat({ label, value }: { label: string; value: string }) {
  return (
    <div className="min-w-0">
      <dt className="text-[11px] uppercase tracking-wide text-ink-muted">{label}</dt>
      <dd className="tabular truncate text-sm text-ink">{value}</dd>
    </div>
  );
}

export function LocusView({ locusId }: { locusId: string }) {
  const { focusLocus } = useView();
  const [detail, setDetail] = useState<LocusDetail | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [hover, setHover] = useState<{ segment: Segment; x: number; y: number } | null>(null);

  useEffect(() => {
    const controller = new AbortController();
    setDetail(null);
    setError(null);
    fetchLocus(locusId, controller.signal)
      .then(setDetail)
      .catch((err: Error) => {
        if (err.name !== "AbortError") setError(err.message);
      });
    return () => controller.abort();
  }, [locusId]);

  const allSegments = useMemo(
    () => detail?.alleles.flatMap((allele) => allele.segments) ?? [],
    [detail],
  );
  const motifScale = useMemo(() => buildMotifScale(allSegments), [allSegments]);
  const maxLen = useMemo(
    () => Math.max(1, ...(detail?.alleles.map((a) => a.allele_len) ?? [1])),
    [detail],
  );

  // Legend entries, in the same fixed slot order the scale assigned.
  const legend = useMemo(() => {
    const seen = new Map<string, string>();
    for (const [motif, color] of motifScale) {
      if (!seen.has(color)) seen.set(color, motif);
    }
    return [...seen.entries()].map(([color, motif]) => ({ color, motif }));
  }, [motifScale]);

  if (error) {
    return (
      <div className="rounded-lg border border-hairline bg-surface p-6">
        <p className="text-sm text-ink">Could not load {locusId}.</p>
        <p className="mt-1 text-xs text-ink-muted">{error}</p>
        <button
          type="button"
          onClick={() => focusLocus(null)}
          className="mt-4 text-xs text-ink-secondary underline underline-offset-2"
        >
          Back to catalog
        </button>
      </div>
    );
  }

  if (!detail) {
    return (
      <div className="rounded-lg border border-hairline bg-surface p-6 text-sm text-ink-muted">
        Loading {locusId}…
      </div>
    );
  }

  const { locus, alleles } = detail;

  return (
    <section aria-labelledby="locus-heading" className="flex min-h-0 flex-col">
      <header className="pb-3">
        <button
          type="button"
          onClick={() => focusLocus(null)}
          className="mb-2 text-xs text-ink-secondary transition-colors hover:text-ink"
        >
          ← Back to catalog
        </button>

        <div className="flex flex-wrap items-center gap-2">
          <h2 id="locus-heading" className="tabular text-base font-medium text-ink">
            {formatPos(locus.chrom, locus.pos)}
          </h2>
          <NoveltyBadge status={noveltyOf(locus)} size="md" />
          <PlatformAgreement
            ucsc={locus.ucsc_novelty}
            trexplorer={locus.trexplorer_novelty}
            ucscEdits={locus.ucsc_motif_edits}
            trexplorerEdits={locus.trexplorer_motif_edits}
          />
          {locus.strchive_status && locus.strchive_status !== "no_locus_match" && (
            <span
              className="rounded-sm px-1.5 py-0.5 text-[11px] font-medium"
              style={{ background: "var(--novel-soft)", color: "var(--novel)" }}
              title={locus.strchive_disease ?? undefined}
            >
              {STRCHIVE_STATUS_LABELS[locus.strchive_status]}
            </span>
          )}
          {locus.gene && (
            <span className="text-xs text-ink-secondary">
              {locus.gene}
              {locus.disease_gene && " · known expansion gene"}
            </span>
          )}
        </div>

        {/* The verdict's meaning, spelled out. "novel_motif" is not
            self-explanatory, and the near-miss caveat belongs beside it rather
            than in the docs. */}
        <p className="mt-2 max-w-2xl text-[11px] leading-relaxed text-ink-muted">
          {NOVELTY_NOTES[noveltyOf(locus)]}
          {!locus.novelty && locus.catalogs && ` Catalogs: ${locus.catalogs.split(";").join(", ")}.`}
        </p>

        <dl className="mt-3 grid grid-cols-2 gap-x-6 gap-y-2 sm:grid-cols-4">
          <Stat label="Motif" value={shortMotif(locus.motif, 16)} />
          <Stat label="Class" value={`${locus.motif_class} · ${locus.motif_len} bp`} />
          <Stat label="Carriers" value={`${locus.n_samples} / 68`} />
          <Stat
            label="Allele range"
            value={`${formatBp(locus.min_len)} – ${formatBp(locus.max_len)}`}
          />
        </dl>
      </header>

      <div className="flex flex-wrap items-center gap-x-4 gap-y-1.5 border-t border-hairline pt-2.5 pb-3 text-xs">
        <span className="text-ink-muted">Motifs:</span>
        {legend.map(({ color, motif }) => (
          <span key={color} className="flex items-center gap-1.5 text-ink-secondary">
            <span
              className="inline-block h-2.5 w-2.5 rounded-sm"
              style={{ background: color }}
            />
            <span className="tabular">
              {color === "var(--motif-other)" ? "other" : shortMotif(motif, 10)}
            </span>
          </span>
        ))}
        <span className="flex items-center gap-1.5 text-ink-secondary">
          <span className="inline-block h-1 w-2.5 rounded-sm" style={{ background: "var(--flank)" }} />
          flank
        </span>
      </div>

      <div className="min-h-0 flex-1 overflow-y-auto rounded-lg border border-hairline bg-surface p-3">
        <ul className="space-y-1">
          {alleles.map((allele) => (
            <li
              key={allele.sample}
              className="grid grid-cols-[7rem_1fr_4.5rem] items-center gap-3"
            >
              <span className="tabular truncate text-[11px] text-ink-secondary">
                {allele.sample}
              </span>
              <MotifBarcode
                segments={allele.segments}
                maxLen={maxLen}
                height={20}
                ariaLabel={`${allele.sample}: ${formatBp(allele.allele_len)} insertion`}
                colorFor={(segment) => motifColor(motifScale, segment.motif)}
                onHover={(segment, event) =>
                  setHover(
                    segment && event ? { segment, x: event.clientX, y: event.clientY } : null,
                  )
                }
              />
              <span className="tabular text-right text-[11px] text-ink-muted">
                {formatBp(allele.allele_len)}
              </span>
            </li>
          ))}
        </ul>
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
