"use client";

import { useState } from "react";

import { CopyButton } from "@/components/CopyButton";
import { shortMotif } from "@/lib/palette";

/**
 * A motif, elided when long and expanded by clicking it.
 *
 * VNTR motifs run to ninety bases, so every list that shows one has to elide it
 * or lose its layout. The ellipsis is the right default — but it is also a dead
 * end, because a motif is a sequence somebody wants to paste into BLAST, not a
 * decorative label. So the elided form is a button: click it and the full
 * sequence unfolds in place, selectable, next to a copy control, and stays there
 * until it is dismissed.
 *
 * Unfolding in place rather than in a popover is deliberate. This renders inside
 * scroll containers and a sticky band, both of which would clip a floating
 * layer, and a card that vanishes on the next mouse move is exactly the problem
 * being fixed.
 *
 * Short motifs render as plain text: an affordance that reveals nothing is worse
 * than none, since it advertises hidden content that does not exist.
 */

export function MotifText({
  motif,
  max = 12,
  className = "",
  label = "motif",
}: {
  motif: string;
  /** Characters shown before eliding. */
  max?: number;
  className?: string;
  /** What this motif is, for the accessible name of the expand control. */
  label?: string;
}) {
  const [open, setOpen] = useState(false);

  if (!motif) return <span className={`tabular ${className}`}>—</span>;

  if (motif.length <= max) {
    return <span className={`tabular ${className}`}>{motif}</span>;
  }

  if (!open) {
    return (
      <button
        type="button"
        onClick={() => setOpen(true)}
        aria-expanded={false}
        aria-label={`Show the full ${label}, ${motif.length} bp`}
        title={`${motif.length} bp — click to show in full`}
        className={`tabular cursor-pointer underline decoration-dotted decoration-from-font underline-offset-2 transition-colors hover:text-ink ${className}`}
      >
        {shortMotif(motif, max)}
      </button>
    );
  }

  return (
    <span className={`inline-flex flex-wrap items-baseline gap-x-1.5 gap-y-1 ${className}`}>
      {/* select-all makes one click take the whole sequence, which is what you
          want from a string with no word boundaries in it. */}
      <span className="tabular text-ink break-all select-all">{motif}</span>
      <CopyButton text={motif} label={`Copy ${label}`} />
      <button
        type="button"
        onClick={() => setOpen(false)}
        aria-expanded
        aria-label={`Collapse the ${label}`}
        className="shrink-0 text-[10px] text-ink-muted underline underline-offset-2 transition-colors hover:text-ink"
      >
        less
      </button>
    </span>
  );
}
