"use client";

import { MotifBarcode } from "@/components/MotifBarcode";
import { formatBp } from "@/lib/palette";
import type { Allele, Segment } from "@/lib/types";

/**
 * The allele spectrum at one locus: every distinct architecture once, with the
 * number of carriers beside it.
 *
 * A compound locus defeats the per-carrier list. Sixty-eight rows of blue-then-
 * orange-then-blue all look alike, and the question you actually have — how many
 * arrangements exist here, and is one of them the common one — is answered by
 * counting rows you cannot tell apart. Collapsing identical architectures turns
 * that into something you read in one pass: the rows are the arrangements, and
 * the bar beside each is how much of the cohort carries it.
 *
 * Two alleles are the same architecture when they are the same repeat blocks, in
 * the same order, at the same copy number, separated in the same places. Copies
 * are rounded because an array is an integer number of units and a caller's
 * 6.97 and 7.02 are not two structures. Flanks count as a break but their length
 * does not: intervening sequence varies continuously, and letting it into the
 * key would shatter every group into singletons and rebuild the list this panel
 * exists to collapse.
 *
 * Each row draws a real allele — the median-length member — rather than a
 * synthetic average, so every block on screen is something a sample actually
 * carries and can be pinned and read. Where a group spans a range of lengths,
 * the row says so.
 *
 * Modelled on Supplementary Figure 15 of Cortese et al. (bioRxiv
 * 2025.01.06.631535), suggested on issue #13.
 */

export interface Structure {
  /** The architecture key — stable, and unique within the locus. */
  key: string;
  /** Carriers of this architecture, in the order the API returned them. */
  samples: string[];
  /** The member the row draws: median length, so the row is a real allele. */
  representative: Allele;
  minLen: number;
  maxLen: number;
}

/**
 * The architecture of one allele, as a string. Repeat blocks carry their motif
 * and rounded copy number; an internal flank carries only the fact that there
 * was a break between two arrays.
 *
 * Leading and trailing flanks are dropped. Whether an insertion begins with
 * twenty bases of unique sequence is a fact about where the breakpoint fell, not
 * about how the repeat is arranged, and keeping it splits identical
 * architectures on the alignment's ragged edges.
 */
function architecture(allele: Allele): string {
  const tokens = allele.segments.map((segment) =>
    segment.seg_type === "flank"
      ? "-"
      : `${segment.motif ?? "?"}x${Math.round(segment.units ?? 0)}`,
  );
  let first = 0;
  let last = tokens.length;
  while (first < last && tokens[first] === "-") first += 1;
  while (last > first && tokens[last - 1] === "-") last -= 1;
  return tokens.slice(first, last).join("|");
}

/**
 * Collapse carriers onto their architectures, longest allele first.
 *
 * Descending length is the order the figure this follows uses, and it is the
 * one that reads: expansions are the reason to open a locus, so they belong at
 * the top rather than buried under the common short allele.
 */
export function groupStructures(alleles: Allele[]): Structure[] {
  const groups = new Map<string, Allele[]>();
  for (const allele of alleles) {
    const key = architecture(allele);
    const members = groups.get(key);
    if (members) members.push(allele);
    else groups.set(key, [allele]);
  }

  const structures = [...groups.entries()].map(([key, members]) => {
    // `sample` breaks ties, so a group of equal-length alleles draws the same
    // member every render rather than whichever one sort happened to leave
    // there. Same convention the catalog strip uses for its representative.
    const byLength = [...members].sort(
      (a, b) => a.allele_len - b.allele_len || a.sample.localeCompare(b.sample),
    );
    return {
      key,
      samples: members.map((allele) => allele.sample),
      representative: byLength[(byLength.length - 1) >> 1],
      minLen: byLength[0].allele_len,
      maxLen: byLength[byLength.length - 1].allele_len,
    };
  });

  return structures.sort(
    (a, b) =>
      b.representative.allele_len - a.representative.allele_len ||
      b.samples.length - a.samples.length ||
      a.key.localeCompare(b.key),
  );
}

export function AlleleStructures({
  structures,
  /** Shared denominator, so a bar here and an allele row are one scale. */
  maxLen,
  colorFor,
  /** Carriers isolated elsewhere on the page; rows outside the set recede. */
  highlighted,
  onHighlight,
  onHover,
  onSelect,
  selectedKey,
}: {
  structures: Structure[];
  maxLen: number;
  colorFor: (segment: Segment) => string;
  highlighted: Set<string> | null;
  onHighlight: (samples: Set<string> | null) => void;
  onHover: (segment: Segment | null, at?: { x: number; y: number }) => void;
  onSelect: (segment: Segment) => void;
  selectedKey: string | null;
}) {
  const busiest = Math.max(...structures.map((structure) => structure.samples.length), 1);

  return (
    <ul className="space-y-1">
      {structures.map((structure) => {
        const { representative, samples, minLen, maxLen: longest } = structure;
        const n = samples.length;
        // Exactly this structure, not merely contained in the selection — so a
        // row that happens to fall inside an isolated histogram bin still
        // narrows to itself on click rather than clearing everything.
        const isolated =
          highlighted !== null &&
          highlighted.size === n &&
          samples.every((sample) => highlighted.has(sample));
        const dimmed =
          highlighted !== null && !samples.some((sample) => highlighted.has(sample));
        const spread = minLen !== longest;

        return (
          <li
            key={structure.key}
            className="grid grid-cols-[5.5rem_1fr_6rem] items-center gap-3 transition-opacity"
            style={{ opacity: dimmed ? 0.25 : 1 }}
          >
            <span
              className="tabular truncate text-right text-[11px] text-ink-muted"
              title={
                spread
                  ? `${formatBp(minLen)} – ${formatBp(longest)} across ${n} carriers; the median one is drawn`
                  : undefined
              }
            >
              {formatBp(representative.allele_len)}
              {spread && <span className="text-ink-muted/70"> ±</span>}
            </span>

            <MotifBarcode
              segments={representative.segments}
              maxLen={maxLen}
              height={20}
              ariaLabel={`${formatBp(representative.allele_len)} allele carried by ${n} sample${
                n === 1 ? "" : "s"
              }`}
              colorFor={colorFor}
              onHover={onHover}
              onSelect={onSelect}
              selectedKey={selectedKey}
            />

            {/* The count panel. A number alone would not show that two
                architectures account for most of the cohort; the bar does, and
                it is the control that isolates those carriers everywhere else. */}
            <button
              type="button"
              onClick={() => onHighlight(isolated ? null : new Set(samples))}
              aria-pressed={isolated}
              title={
                isolated
                  ? "Stop isolating these carriers"
                  : `Isolate the ${n} carrier${n === 1 ? "" : "s"} of this structure`
              }
              className="flex items-center gap-1.5 rounded-sm py-1 text-left transition-colors hover:bg-surface-raised focus-visible:outline-2 focus-visible:outline-offset-1 focus-visible:outline-[var(--motif-1)]"
            >
              <span
                aria-hidden
                className="h-2 shrink-0 rounded-sm transition-all"
                style={{
                  // Every count gets a visible mark: a 1-carrier bar rounded to
                  // nothing would read as zero.
                  width: `max(2px, ${(n / busiest) * 62}%)`,
                  background: isolated ? "var(--ink)" : "var(--known)",
                }}
              />
              <span className="tabular text-[11px] text-ink-secondary">{n}</span>
            </button>
          </li>
        );
      })}
    </ul>
  );
}
