"use client";

import { useEffect, useMemo, useState, type ReactNode } from "react";

import { AlleleHistogram } from "@/components/AlleleHistogram";
import { AlleleStructures, groupStructures } from "@/components/AlleleStructures";
import { type Selection, segmentKey } from "@/components/Inspector";
import { MotifBarcode, SegmentTooltip } from "@/components/MotifBarcode";
import { MotifText } from "@/components/MotifText";
import { NoveltyBadge, PlatformAgreement, noveltyOf } from "@/components/NoveltyBadge";
import { ReferenceComparison, referenceHits, trackScale } from "@/components/ReferenceTrack";
import { fetchLocus } from "@/lib/api";
import { buildMotifScale, formatBp, formatPos, motifColor } from "@/lib/palette";
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

function Stat({
  label,
  value,
  wrap = false,
}: {
  label: string;
  value: ReactNode;
  /** Elide by default; a value that can unfold in place must be allowed to. */
  wrap?: boolean;
}) {
  return (
    <div className="min-w-0">
      <dt className="text-[11px] uppercase tracking-wide text-ink-muted">{label}</dt>
      <dd className={`text-sm text-ink ${wrap ? "" : "tabular truncate"}`}>{value}</dd>
    </div>
  );
}

/**
 * Carrier rows or architecture rows.
 *
 * A segmented control rather than a checkbox: these are two readings of one
 * list, neither of them a modifier of the other, and the counts on the faces
 * say what switching would cost before you switch.
 */
function GroupToggle({
  grouped,
  onChange,
  /** Whether grouping actually merges anything here. */
  collapses: { carriers, structures },
}: {
  grouped: boolean;
  onChange: (grouped: boolean) => void;
  collapses: { carriers: number; structures: number };
}) {
  const options: { value: boolean; label: string; count: number; note: string }[] = [
    {
      value: true,
      label: "Structures",
      count: structures,
      note: "One row per distinct architecture, with how many carriers have it.",
    },
    {
      value: false,
      label: "Carriers",
      count: carriers,
      note: "One row per sample.",
    },
  ];

  return (
    <div
      className="flex items-center gap-0.5 rounded-full p-0.5"
      style={{ background: "var(--surface-raised)", border: "1px solid var(--hairline)" }}
      role="group"
      aria-label="How to group the allele rows"
    >
      {options.map((option) => {
        const on = option.value === grouped;
        return (
          <button
            key={option.label}
            type="button"
            onClick={() => onChange(option.value)}
            aria-pressed={on}
            title={option.note}
            className="rounded-full px-2 py-0.5 text-[11px] transition-colors focus-visible:outline-2 focus-visible:outline-offset-1 focus-visible:outline-[var(--motif-1)]"
            style={{
              background: on ? "var(--plane)" : "transparent",
              color: on ? "var(--ink)" : "var(--ink-muted)",
            }}
          >
            {option.label}{" "}
            <span className="tabular" style={{ opacity: 0.7 }}>
              {option.count}
            </span>
          </button>
        );
      })}
    </div>
  );
}

export function LocusView({
  locusId,
  selection,
  onSelect,
}: {
  locusId: string;
  /** The pinned block, so the strip can show which one it is. */
  selection: Selection | null;
  onSelect: (selection: Selection) => void;
}) {
  const { focusLocus } = useView();
  const [detail, setDetail] = useState<LocusDetail | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [hover, setHover] = useState<{ segment: Segment; x: number; y: number } | null>(null);
  // Carriers isolated by clicking a histogram bin. The distribution and the
  // strips are two views of one cohort, so picking a bin up there dims
  // everything down here that is not in it.
  const [highlighted, setHighlighted] = useState<Set<string> | null>(null);
  // null means nobody has chosen, so the panel picks — see `grouped` below.
  const [groupedPref, setGroupedPref] = useState<boolean | null>(null);

  useEffect(() => {
    const controller = new AbortController();
    setDetail(null);
    setError(null);
    setHighlighted(null);
    setGroupedPref(null);
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

  // The reference track shares this scale with the allele rows, so the widths
  // can be read against each other — see the coordinate caveat in
  // ReferenceTrack. `trackScale` caps how far one very long reference repeat is
  // allowed to stretch the denominator.
  const hits = useMemo(() => (detail ? referenceHits(detail.locus) : []), [detail]);
  const maxLen = useMemo(
    () =>
      trackScale(hits, Math.max(1, ...(detail?.alleles.map((a) => a.allele_len) ?? [1]))),
    [detail, hits],
  );

  const structures = useMemo(
    () => (detail ? groupStructures(detail.alleles) : []),
    [detail],
  );

  // Grouped unless it would merge nothing. A locus where every carrier has its
  // own architecture gains nothing from the collapsed view but loses the sample
  // names, so it opens on the carrier list; a compound locus, which is the case
  // this panel is for, opens collapsed. Either way one click switches, and the
  // choice sticks until the page moves to another locus.
  const grouped = groupedPref ?? structures.length < (detail?.alleles.length ?? 0);

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
    <section aria-labelledby="locus-heading" className="flex flex-col">
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
          <Stat
            label="Motif"
            wrap
            value={<MotifText motif={locus.motif} max={16} label="locus motif" />}
          />
          <Stat label="Class" value={`${locus.motif_class} · ${locus.motif_len} bp`} />
          <Stat label="Carriers" value={`${locus.n_samples} / 68`} />
          <Stat
            label="Allele range"
            value={`${formatBp(locus.min_len)} – ${formatBp(locus.max_len)}`}
          />
        </dl>
      </header>

      {/* The reference scrolls with everything else. It is read once, against
          the allele rows it shares a scale with, and pinning something this tall
          to the top of the column costs a third of the viewport for the whole
          time you are reading rows you have already placed it against. */}
      <ReferenceComparison locus={locus} maxLen={maxLen} verdict={noveltyOf(locus)} />

      <AlleleHistogram
        alleles={alleles}
        highlighted={highlighted}
        onHighlight={setHighlighted}
      />

      {/* The motif legend is the one thing every row below is read against, and
          it is one line tall, so it pins while the rest of the page scrolls
          under it. Sitting directly above the rows it decodes, it covers
          nothing you were reading. The negative margin lets its background span
          the column's full width; the matching padding keeps it aligned to the
          allele grid. The column carries no top padding, so it pins flush and
          nothing shows through above it. */}
      <div className="sticky top-0 z-20 -mx-4 mt-3 bg-plane px-4 pt-3 pb-2">
        <div className="flex flex-wrap items-center gap-x-4 gap-y-1.5 text-xs">
          <span className="text-ink-muted">Motifs:</span>
          {legend.map(({ color, motif }) => (
            <span key={color} className="flex items-center gap-1.5 text-ink-secondary">
              <span
                className="inline-block h-2.5 w-2.5 rounded-sm"
                style={{ background: color }}
              />
              {color === "var(--motif-other)" ? (
                <span className="tabular">other</span>
              ) : (
                <MotifText motif={motif} max={10} label="motif" />
              )}
            </span>
          ))}
          <span className="flex items-center gap-1.5 text-ink-secondary">
            <span
              className="inline-block h-1 w-2.5 rounded-sm"
              style={{ background: "var(--flank)" }}
            />
            flank
          </span>
        </div>

        {/* Rows dissolve into the band rather than being sliced by a rule at
            its edge — a hard line there reads as a second panel border stacked
            on the one the allele list already has. */}
        <div
          aria-hidden
          className="pointer-events-none absolute inset-x-0 top-full h-4"
          style={{ background: "linear-gradient(to bottom, var(--plane), transparent)" }}
        />
      </div>

      <div className="rounded-lg border border-hairline bg-surface p-3">
        <div className="mb-2 flex flex-wrap items-baseline justify-between gap-x-4 gap-y-1">
          <h3 className="text-sm font-medium text-ink">
            {grouped ? "Distinct allele structures" : "Alleles by carrier"}{" "}
            <span className="tabular font-normal text-ink-muted">
              {grouped
                ? `${structures.length} of ${alleles.length} carriers`
                : `${alleles.length} carriers`}
            </span>
          </h3>
          <GroupToggle
            grouped={grouped}
            onChange={setGroupedPref}
            collapses={{ carriers: alleles.length, structures: structures.length }}
          />
        </div>

        {grouped ? (
          <AlleleStructures
            structures={structures}
            maxLen={maxLen}
            colorFor={(segment) => motifColor(motifScale, segment.motif)}
            highlighted={highlighted}
            onHighlight={setHighlighted}
            onHover={(segment, at) => setHover(segment && at ? { segment, ...at } : null)}
            onSelect={(segment) =>
              onSelect({ segment, locusLabel: formatPos(locus.chrom, locus.pos) })
            }
            selectedKey={selection ? segmentKey(selection.segment) : null}
          />
        ) : (
          <ul className="space-y-1">
            {alleles.map((allele) => (
              <li
                key={allele.sample}
                className="grid grid-cols-[7rem_1fr_4.5rem] items-center gap-3 transition-opacity"
                style={{
                  opacity: highlighted && !highlighted.has(allele.sample) ? 0.25 : 1,
                }}
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
                  onHover={(segment, at) =>
                    setHover(segment && at ? { segment, ...at } : null)
                  }
                  onSelect={(segment) =>
                    onSelect({ segment, locusLabel: formatPos(locus.chrom, locus.pos) })
                  }
                  selectedKey={selection ? segmentKey(selection.segment) : null}
                />
                <span className="tabular text-right text-[11px] text-ink-muted">
                  {formatBp(allele.allele_len)}
                </span>
              </li>
            ))}
          </ul>
        )}

        <p className="mt-2 text-[11px] leading-relaxed text-ink-muted">
          {grouped
            ? "One row per architecture — the same repeat blocks, in the same order, at the same copy number. The bar on the right is how many carriers have it; click it to isolate them. A ± marks a group whose members vary in length, and the row draws the median one."
            : "One row per carrier, longest allele first. Click a block to pin its numbers."}
        </p>
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
