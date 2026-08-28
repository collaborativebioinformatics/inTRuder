"use client";

import { useCallback, useEffect, useRef, useState } from "react";

import { formatSpan, parseLocusQuery } from "@/lib/region";
import type { ViewFilters } from "@/lib/types";
import { useView } from "@/lib/viewStore";

/**
 * One box for "where in the genome" and "which gene".
 *
 * Genome browsers have taught everyone who works with these coordinates that
 * there is a single box you type `chr3:1,000-50,000` into, and that a gene name
 * goes in the same one. Splitting it into two inputs would be more explicit and
 * less usable: you would have to decide which field your text belongs in before
 * typing it. Instead the box reads what you typed and says so — inline while you
 * type, and afterwards as a chip in the row below, which is also how you remove
 * it. Nothing is applied invisibly.
 *
 * The box owns three filters and never more: `region`, `chrom` and `gene_query`.
 * It remembers which one it last set so that typing a gene clears a range it put
 * there, without touching a chromosome the assistant or another control chose.
 */

/** The filters this box is allowed to write. */
type OwnedKey = "region" | "chrom" | "gene_query";

const OWNED: OwnedKey[] = ["region", "chrom", "gene_query"];

interface Applied {
  key: OwnedKey;
  value: string;
}

/** What a parsed line of text becomes in the view — or nothing, when empty. */
function targetOf(text: string): Applied | null {
  const parsed = parseLocusQuery(text);
  switch (parsed.kind) {
    case "region":
      return { key: "region", value: parsed.region };
    case "chrom":
      return { key: "chrom", value: parsed.chrom };
    case "gene":
      return { key: "gene_query", value: parsed.text };
    default:
      return null;
  }
}

/** The running commentary beside the box: what this text is about to do. */
function Interpretation({ text }: { text: string }) {
  const parsed = parseLocusQuery(text);

  if (parsed.kind === "region") {
    // Only the span, not the range read back: the chip below already carries
    // the range in full, and three copies of the same coordinates on one screen
    // is noise. How wide the window is, is the part you cannot see by looking.
    return <span className="truncate text-ink-secondary">{formatSpan(parsed.region)} window</span>;
  }

  if (parsed.kind === "chrom") {
    return <span className="truncate text-ink-secondary">all of {parsed.chrom}</span>;
  }

  if (parsed.kind === "gene") {
    // A range with a typo in it — `chr3:1000-` — parses as a gene name, which
    // would then match nothing for a reason the reader cannot see. Say what
    // happened instead of letting an empty list be the explanation.
    const meantARange = parsed.text.includes(":") && /^(?:chr)?[\dxym]/i.test(parsed.text);
    return meantARange ? (
      <span className="truncate text-ink-muted">
        not a range — searching gene names for “{parsed.text}”
      </span>
    ) : (
      <span className="truncate text-ink-secondary">
        genes containing “{parsed.text}”
      </span>
    );
  }

  return null;
}

export function SearchBox() {
  const { filters, patch } = useView();
  const [text, setText] = useState("");
  // What this box last wrote into the view, so it can tell its own filters
  // apart from ones a chip, the assistant, or "clear all" moved.
  const applied = useRef<Applied | null>(null);

  const commit = useCallback(
    (raw: string) => {
      const target = targetOf(raw);
      const previous = applied.current;
      if (target?.key === previous?.key && target?.value === previous?.value) return;

      const next: ViewFilters = {};
      // Clear only what this box put there. A chromosome someone else chose is
      // not ours to drop just because a gene was typed here.
      if (previous && previous.key !== target?.key) next[previous.key] = null;
      if (target) next[target.key] = target.value;
      applied.current = target;
      patch(next);
    },
    [patch],
  );

  // Typing is a filter change like any other, so it goes through the view store
  // — but one patch per keystroke would refetch the catalog on every letter.
  useEffect(() => {
    const timer = setTimeout(() => commit(text), 250);
    return () => clearTimeout(timer);
  }, [text, commit]);

  // The other direction: removing the chip, clearing all filters, or the
  // assistant setting a region must empty or refill the box it came from.
  useEffect(() => {
    const current = applied.current;
    if (current && filters[current.key] === current.value) return;
    const key = OWNED.find((owned) => filters[owned]);
    const next = key ? { key, value: String(filters[key]) } : null;
    applied.current = next;
    // The canonical range goes back into the box rather than the prettified
    // one, so what is on screen always parses back to what is in the view.
    setText(next ? next.value : "");
  }, [filters]);

  return (
    <div className="flex items-center gap-2">
      <div className="relative">
        <svg
          viewBox="0 0 16 16"
          aria-hidden="true"
          className="pointer-events-none absolute left-2.5 top-1/2 h-3.5 w-3.5 -translate-y-1/2 text-ink-muted"
          fill="none"
          stroke="currentColor"
          strokeWidth="1.5"
        >
          <circle cx="7" cy="7" r="4.25" />
          <path d="M10.2 10.2 14 14" strokeLinecap="round" />
        </svg>
        <input
          type="search"
          value={text}
          onChange={(event) => setText(event.target.value)}
          onKeyDown={(event) => {
            // Enter is impatience, not a different action — skip the debounce.
            if (event.key === "Enter") commit(text);
            if (event.key === "Escape") setText("");
          }}
          placeholder="chr3:1,000-50,000 or a gene"
          aria-label="Filter by genomic range or gene name"
          spellCheck={false}
          className="tabular w-64 rounded-full border border-hairline bg-surface py-1 pl-8 pr-3 text-xs text-ink placeholder:text-ink-muted focus:border-baseline focus:outline-none"
        />
      </div>
      <p className="min-w-0 flex-1 text-[11px] leading-none">
        <Interpretation text={text} />
      </p>
    </div>
  );
}
