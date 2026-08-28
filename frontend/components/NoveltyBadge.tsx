"use client";

import {
  NOVELTY_LABELS,
  NOVELTY_NOTES,
  PLATFORM_LABELS,
  type Locus,
  type NoveltyDisplay,
  type NoveltyStatus,
} from "@/lib/types";

/**
 * The screen's verdict, as three values rather than a boolean.
 *
 * `known → novel_motif → novel_locus` is an *ordered* scale — how much of this
 * repeat the reference already knows about — so it takes a one-hue ramp with
 * monotone lightness (recessive grey, then the finding hue soft, then solid)
 * rather than three categorical colors. The text label carries the distinction
 * unaided; the color only reinforces it.
 */

const STYLES: Record<NoveltyDisplay, { background: string; color: string }> = {
  known: { background: "var(--known-soft)", color: "var(--ink-secondary)" },
  novel_motif: { background: "var(--novel-soft)", color: "var(--novel)" },
  novel_locus: { background: "var(--novel)", color: "#ffffff" },
  novel: { background: "var(--novel-soft)", color: "var(--novel)" },
};

/**
 * What the interface can honestly say about this locus.
 *
 * Real screened data carries the three-valued `novelty`. The demo fixtures carry
 * only a boolean, and a boolean cannot be resolved into motif- versus
 * locus-novelty after the fact — so it renders as the coarse "Novel" rather than
 * silently picking one of the two and asserting something we did not compute.
 */
export function noveltyOf(locus: Pick<Locus, "novel" | "novelty">): NoveltyDisplay {
  return locus.novelty ?? (locus.novel ? "novel" : "known");
}

export function NoveltyBadge({
  status,
  size = "sm",
}: {
  status: NoveltyDisplay;
  size?: "sm" | "md";
}) {
  const style = STYLES[status];
  return (
    <span
      title={NOVELTY_NOTES[status]}
      className={`shrink-0 rounded-sm font-medium ${
        size === "md" ? "px-1.5 py-0.5 text-[11px]" : "px-1 py-px text-[10px]"
      }`}
      style={style}
    >
      {NOVELTY_LABELS[status]}
    </span>
  );
}

/**
 * Per-catalog verdicts side by side.
 *
 * UCSC and TRExplorer were compiled separately, so where they agree the call is
 * a property of the data rather than of a threshold — and where they disagree is
 * exactly where a reader should look first. That is invisible in a single
 * combined verdict, which is why it gets its own mark.
 *
 * The letter in each cell is the identity channel; color is reinforcement only.
 */
export function PlatformAgreement({
  ucsc,
  trexplorer,
  ucscEdits,
  trexplorerEdits,
}: {
  ucsc?: NoveltyStatus;
  trexplorer?: NoveltyStatus;
  ucscEdits?: number | null;
  trexplorerEdits?: number | null;
}) {
  if (!ucsc && !trexplorer) return null;

  const cells: { key: "ucsc" | "trexplorer"; letter: string; verdict?: NoveltyStatus }[] = [
    { key: "ucsc", letter: "U", verdict: ucsc },
    { key: "trexplorer", letter: "T", verdict: trexplorer },
  ];
  const disagree = ucsc && trexplorer && ucsc !== trexplorer;

  return (
    <span
      className="inline-flex items-center gap-px"
      title={cells
        .map(
          ({ key, verdict }) =>
            `${PLATFORM_LABELS[key]}: ${verdict ? NOVELTY_LABELS[verdict] : "not screened"}`,
        )
        .concat(
          disagree
            ? ["The two catalogs disagree here — a threshold effect, not a finding."]
            : [],
        )
        .join("\n")}
      style={
        disagree
          ? { outline: "1px solid var(--baseline)", outlineOffset: 1, borderRadius: 3 }
          : undefined
      }
    >
      {cells.map(({ key, letter, verdict }) => {
        const style = verdict ? STYLES[verdict] : {
          background: "var(--hairline)",
          color: "var(--ink-muted)",
        };
        return (
          <span
            key={key}
            className="tabular inline-flex h-3.5 w-3.5 items-center justify-center rounded-[2px] text-[9px] font-medium"
            style={style}
          >
            {letter}
          </span>
        );
      })}
      {/* A near miss is the routine explanation for a novel_motif call, so the
          edit distance travels with the verdict rather than hiding in a tooltip. */}
      {(ucscEdits === 1 || trexplorerEdits === 1) && (
        <span className="ml-1 text-[9px] text-ink-muted" title="One edit from a catalogued motif — likely a near miss rather than a discovery.">
          1&thinsp;edit
        </span>
      )}
    </span>
  );
}
