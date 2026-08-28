"use client";

import { useEffect } from "react";

import { CopyButton } from "@/components/CopyButton";
import { formatBp } from "@/lib/palette";
import type { Segment } from "@/lib/types";

/**
 * The block you clicked, held still.
 *
 * A hover tooltip is the right way to read a barcode — you sweep the strip and
 * the numbers follow — but it is the wrong way to *keep* anything: it tracks the
 * cursor, so moving toward it destroys it, and the motif inside it can never be
 * selected. Clicking a block therefore pins its contents here, in the rail,
 * where the panel is in the same place every time, cannot cover the strip it
 * came from, and is wide enough for a ninety-base motif to wrap.
 *
 * Because it persists, it also compares: pin a block, hover the next sample's,
 * and the two sets of numbers are on screen at once.
 */

export interface Selection {
  segment: Segment;
  /** Which locus the block belongs to, already formatted for display. */
  locusLabel: string;
}

/** Identifies one block within a locus, for highlighting the pinned one. */
export function segmentKey(segment: Segment): string {
  return `${segment.sample}-${segment.seg_index}`;
}

function Row({ label, value }: { label: string; value: string }) {
  return (
    <div className="flex items-baseline justify-between gap-3">
      <dt className="text-[11px] text-ink-muted">{label}</dt>
      <dd className="tabular text-[11px] text-ink-secondary">{value}</dd>
    </div>
  );
}

/** Tab-separated, so it pastes into a spreadsheet as two columns. */
function asText(selection: Selection): string {
  const { segment, locusLabel } = selection;
  const lines: [string, string][] = [
    ["locus", locusLabel],
    ["sample", segment.sample],
    ["type", segment.seg_type],
  ];
  if (segment.seg_type === "repeat") {
    lines.push(["motif", segment.motif ?? ""]);
    if (segment.units != null) lines.push(["copies", segment.units.toFixed(1)]);
    if (segment.purity != null) lines.push(["purity", segment.purity.toFixed(2)]);
  }
  lines.push(["length_bp", String(segment.end - segment.start)]);
  lines.push(["offset_in_allele", `${segment.start}-${segment.end}`]);
  return lines.map(([key, value]) => `${key}\t${value}`).join("\n");
}

export function Inspector({
  selection,
  onClear,
}: {
  selection: Selection;
  onClear: () => void;
}) {
  const { segment, locusLabel } = selection;
  const length = segment.end - segment.start;
  const isRepeat = segment.seg_type === "repeat";

  // Escape dismisses it, the way it dismisses every other transient layer.
  useEffect(() => {
    function onKey(event: KeyboardEvent) {
      if (event.key === "Escape") onClear();
    }
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [onClear]);

  return (
    <section
      aria-labelledby="inspector-heading"
      aria-live="polite"
      className="space-y-2 rounded-lg border border-hairline bg-surface p-3"
    >
      <div className="flex items-baseline justify-between gap-2">
        <h2 id="inspector-heading" className="text-sm font-medium text-ink">
          Selected block
        </h2>
        <button
          type="button"
          onClick={onClear}
          aria-label="Clear the selection"
          className="text-xs text-ink-muted transition-colors hover:text-ink"
        >
          ×
        </button>
      </div>

      {isRepeat ? (
        <div className="space-y-1">
          <div className="text-[11px] uppercase tracking-wide text-ink-muted">Motif</div>
          <div className="flex flex-wrap items-baseline gap-x-2 gap-y-1">
            <span className="tabular text-xs text-ink break-all select-all">
              {segment.motif}
            </span>
            <CopyButton text={segment.motif ?? ""} label="Copy motif" />
          </div>
        </div>
      ) : (
        <p className="text-xs text-ink">Non-repetitive flank</p>
      )}

      <dl className="space-y-0.5 border-t border-hairline pt-2">
        {isRepeat && segment.units != null && (
          <Row label="Copies" value={`×${segment.units.toFixed(1)}`} />
        )}
        <Row label="Length" value={formatBp(length)} />
        {isRepeat && segment.purity != null && (
          <Row label="Purity" value={segment.purity.toFixed(2)} />
        )}
        {/* Offsets are inside the inserted allele, not genomic coordinates — the
            reference band above the strips is on a different axis entirely. */}
        <Row label="Offset in allele" value={`${segment.start}–${segment.end} bp`} />
        <Row label="Sample" value={segment.sample} />
        <Row label="Locus" value={locusLabel} />
      </dl>

      <CopyButton
        text={asText(selection)}
        label="Copy every field of this block"
        idleText="Copy all fields"
        className="w-full"
      />
    </section>
  );
}
