"use client";

import { memo } from "react";

import type { Segment } from "@/lib/types";

/**
 * One inserted allele drawn as a strip of blocks.
 *
 * This is the whole visual idea: stop rendering the insertion as bases and
 * render it as a sequence of *motifs*. A block is one repeat array, its width is
 * how much sequence it accounts for, its color is which motif it is; grey is
 * non-repetitive flank. The same encoding then works whether the strip is 14px
 * tall in a list of a thousand loci or 20px tall for one locus across 68
 * samples, which is what makes one visual vocabulary cover the whole interface.
 *
 * Widths are scaled against a shared `maxLen` so strips are comparable between
 * rows — allele-length differences are meant to be readable as width alone.
 *
 * Positioned HTML rather than SVG on purpose: an SVG with a stretched viewBox
 * scales x and y unequally, which turns a corner radius into an ellipse and a
 * pixel gap into a variable one. `calc()` on percentage offsets keeps radii and
 * gaps in real pixels at any container width.
 */

export interface BarcodeProps {
  segments: Segment[];
  /** Denominator for the width scale; share it across rows to keep them comparable. */
  maxLen: number;
  height?: number;
  colorFor: (segment: Segment) => string;
  onHover?: (segment: Segment | null, event?: React.MouseEvent) => void;
  className?: string;
  ariaLabel?: string;
}

const GAP = 2; // surface gap between adjacent fills, per mark spec
const RADIUS = 2;

function BarcodeImpl({
  segments,
  maxLen,
  height = 18,
  colorFor,
  onHover,
  className = "",
  ariaLabel,
}: BarcodeProps) {
  if (!segments.length || maxLen <= 0) {
    return <div style={{ height }} className={className} aria-hidden />;
  }

  return (
    <div
      role="img"
      aria-label={ariaLabel}
      className={`relative w-full ${className}`}
      style={{ height }}
      onMouseLeave={() => onHover?.(null)}
    >
      {segments.map((segment) => {
        const left = (segment.start / maxLen) * 100;
        const width = ((segment.end - segment.start) / maxLen) * 100;
        const isFlank = segment.seg_type === "flank";

        return (
          <div
            key={`${segment.sample}-${segment.seg_index}`}
            onMouseEnter={(event) => onHover?.(segment, event)}
            style={{
              position: "absolute",
              left: `calc(${left}% + ${GAP / 2}px)`,
              // Never let the gap eat a thin block entirely.
              width: `max(1.5px, calc(${width}% - ${GAP}px))`,
              top: isFlank ? height * 0.34 : 0,
              height: isFlank ? Math.max(2, height * 0.32) : height,
              borderRadius: isFlank ? 1 : RADIUS,
              background: colorFor(segment),
              // Purity reads as opacity: a ragged array looks washed out.
              opacity: isFlank
                ? 1
                : 0.5 + 0.5 * Math.min(1, Math.max(0, segment.purity ?? 1)),
            }}
          />
        );
      })}
    </div>
  );
}

export const MotifBarcode = memo(BarcodeImpl);

/** Tooltip body for a hovered block. Kept next to the barcode so the two agree. */
export function SegmentTooltip({ segment }: { segment: Segment }) {
  const length = segment.end - segment.start;
  if (segment.seg_type === "flank") {
    return (
      <div className="space-y-0.5">
        <div className="font-medium">Non-repetitive flank</div>
        <div className="tabular text-ink-secondary">{length} bp</div>
      </div>
    );
  }
  return (
    <div className="space-y-0.5">
      <div className="tabular font-medium break-all">{segment.motif}</div>
      <div className="tabular text-ink-secondary">
        {segment.units?.toFixed(0)} copies · {length} bp · purity{" "}
        {segment.purity?.toFixed(2)}
      </div>
      <div className="text-ink-muted">{segment.sample}</div>
    </div>
  );
}
