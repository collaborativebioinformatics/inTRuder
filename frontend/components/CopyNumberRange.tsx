"use client";

import { useMemo, useState } from "react";

import {
  ALLELE_COLORS,
  buildBands,
  buildCopyScale,
  classifyCopies,
  formatCopies,
} from "@/lib/strchive";
import type { StrchiveLocus } from "@/lib/types";

/**
 * The curated allele ranges at one disease locus, as one axis.
 *
 * This is the chart the STRchive comparison is actually about. The question
 * "does this insertion matter" is answered by where a copy number falls against
 * three curated ranges, and that is a position on a line — not a table of six
 * numbers the reader has to hold in their head and compare by hand.
 *
 * Encoding notes:
 *
 * - The bands are STATUS, not a series. Benign/intermediate/pathogenic are
 *   states with reserved meaning, so they take the fixed status steps rather
 *   than categorical slots, and they never carry meaning by color alone: each
 *   band sits at a fixed position on the axis and is directly labelled with its
 *   range. That labelling is also the required relief for the intermediate step,
 *   which is deliberately sub-3:1 on the light surface.
 *
 * - The markers are OURS, and they use `--novel`, the same channel the rest of
 *   the interface uses for "what this pipeline found". Two sources, two color
 *   channels: curated knowledge in status colors, our result in the finding
 *   color. A reader never has to ask which is which.
 *
 * - The axis is logarithmic (log1p — see lib/strchive.ts). Pathogenic thresholds
 *   run from 1 copy to 11,000, and a linear axis collapses almost every locus.
 */

interface Props {
  locus: StrchiveLocus;
  /** Our estimate for a candidate insertion at this locus, if we have one. */
  estCopies?: number | null;
  height?: number;
  /** Compact form for list rows: no axis, no labels, no hover. */
  dense?: boolean;
  /** Shared domain maximum. Required in lists so rows stay comparable. */
  scaleMax?: number;
}

const TRACK = 10;

export function CopyNumberRange({
  locus,
  estCopies,
  height = 10,
  dense = false,
  scaleMax,
}: Props) {
  const [hover, setHover] = useState<string | null>(null);

  const scale = useMemo(
    () => buildCopyScale(locus, [estCopies], scaleMax),
    [locus, estCopies, scaleMax],
  );
  const bands = useMemo(() => buildBands(locus), [locus]);

  const refCopies = locus.ref_copies;
  const estClass = classifyCopies(locus, estCopies);

  if (bands.length === 0) {
    return (
      <p className="text-[11px] text-ink-muted">
        STRchive records no copy-number range at this locus.
      </p>
    );
  }

  return (
    <div className="w-full">
      <div className="relative w-full" style={{ height: dense ? height : height + 18 }}>
        {/* Baseline: a hairline one shade off the surface, never dashed. */}
        <div
          className="absolute rounded-full"
          style={{
            left: 0,
            right: 0,
            top: (dense ? height : height) / 2 - 0.5,
            height: 1,
            background: "var(--hairline)",
          }}
        />

        {bands.map((band) => {
          const left = scale.toPercent(band.from);
          const right = scale.toPercent(band.to);
          return (
            <div
              key={band.key}
              onMouseEnter={() => !dense && setHover(band.key)}
              onMouseLeave={() => !dense && setHover(null)}
              title={dense ? `${band.label} ${band.from}–${band.to} copies` : undefined}
              style={{
                position: "absolute",
                // 2px surface gap between adjacent fills, per the mark spec.
                left: `calc(${left}% + 1px)`,
                width: `max(3px, calc(${right - left}% - 2px))`,
                top: 0,
                height: TRACK,
                borderRadius: 4,
                background: band.color,
                opacity: hover && hover !== band.key ? 0.45 : 1,
                transition: "opacity 120ms ease-out",
              }}
            />
          );
        })}

        {/* What the reference already carries — a tick, not a fill: it is a
            single value on the same axis, and reads as an origin for the arrow. */}
        {refCopies != null && (
          <div
            title={`Reference carries ${formatCopies(refCopies)} copies`}
            style={{
              position: "absolute",
              left: `calc(${scale.toPercent(refCopies)}% - 1px)`,
              top: -3,
              width: 2,
              height: TRACK + 6,
              borderRadius: 1,
              background: "var(--ink)",
              boxShadow: "0 0 0 1.5px var(--surface)",
            }}
          />
        )}

        {/* Our estimate. 2px surface ring so it stays legible wherever it lands. */}
        {estCopies != null && Number.isFinite(estCopies) && (
          <div
            title={`Estimated ${formatCopies(estCopies)} copies — ${estClass}`}
            style={{
              position: "absolute",
              left: `calc(${scale.toPercent(estCopies)}% - 5px)`,
              top: TRACK / 2 - 5,
              width: 10,
              height: 10,
              borderRadius: 999,
              background: "var(--novel)",
              boxShadow: "0 0 0 2px var(--surface)",
            }}
          />
        )}

        {!dense && (
          <div className="absolute inset-x-0" style={{ top: TRACK + 4 }}>
            {scale.ticks.map((tick) => (
              <span
                key={tick}
                className="tabular absolute text-[10px] text-ink-muted"
                style={{
                  left: `${scale.toPercent(tick)}%`,
                  transform: "translateX(-50%)",
                }}
              >
                {tick >= 1000 ? `${tick / 1000}k` : tick}
              </span>
            ))}
          </div>
        )}
      </div>

      {!dense && (
        <div className="mt-4 flex flex-wrap items-center gap-x-4 gap-y-1 text-[11px]">
          {bands.map((band) => (
            <span key={band.key} className="flex items-center gap-1.5 text-ink-secondary">
              <span
                className="inline-block h-2.5 w-2.5 rounded-sm"
                style={{ background: band.color }}
              />
              {band.label}{" "}
              <span className="tabular text-ink-muted">
                {formatCopies(band.from)}–{formatCopies(band.to)}
              </span>
            </span>
          ))}
          {refCopies != null && (
            <span className="flex items-center gap-1.5 text-ink-secondary">
              <span
                className="inline-block h-3 w-0.5 rounded-sm"
                style={{ background: "var(--ink)" }}
              />
              Reference <span className="tabular text-ink-muted">{formatCopies(refCopies)}</span>
            </span>
          )}
          {estCopies != null && (
            <span className="flex items-center gap-1.5 text-ink-secondary">
              <span
                className="inline-block h-2.5 w-2.5 rounded-full"
                style={{ background: "var(--novel)" }}
              />
              Estimated <span className="tabular text-ink-muted">{formatCopies(estCopies)}</span>
            </span>
          )}
        </div>
      )}
    </div>
  );
}

/**
 * The arithmetic behind the estimate, written out.
 *
 * STRCHIVE_COMPARE.md is emphatic that `ref_copies + rep_units` is a triage
 * signal and not a genotype — it assumes the insertion extends the reference
 * array rather than replacing it or landing beside it. Showing the sum as a sum,
 * rather than as a single confident number, is how that caveat survives contact
 * with the interface.
 */
export function CopyEstimate({
  refCopies,
  repUnits,
  estCopies,
  alleleClass,
}: {
  refCopies: number | null;
  repUnits: number | null;
  estCopies: number | null;
  alleleClass: string;
}) {
  if (estCopies == null) {
    return (
      <p className="text-[11px] leading-relaxed text-ink-muted">
        No copy-number estimate — STRchive records no reference copy count at this
        locus, so there is nothing to add the insertion to.
      </p>
    );
  }
  return (
    <div className="space-y-1">
      <p className="tabular text-xs text-ink">
        <span className="text-ink-secondary">{formatCopies(refCopies)} in reference</span>
        {" + "}
        <span style={{ color: "var(--novel)" }}>{formatCopies(repUnits)} inserted</span>
        {" = "}
        <span className="font-medium">{formatCopies(estCopies)} copies</span>{" "}
        <span
          className="rounded-sm px-1 py-0.5 text-[10px] font-medium"
          style={{
            background: "var(--surface-raised)",
            color: ALLELE_COLORS[alleleClass as keyof typeof ALLELE_COLORS] ?? "var(--ink-muted)",
          }}
        >
          {alleleClass}
        </span>
      </p>
      <p className="text-[11px] leading-relaxed text-ink-muted">
        An estimate: it assumes the insertion extends the reference array rather
        than replacing it, and inherits whatever error the caller&rsquo;s copy count
        carries. Triage signal, not a genotype.
      </p>
    </div>
  );
}
