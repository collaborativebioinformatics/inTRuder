"use client";

import { SORTS, type SortDirection, type SortKey } from "@/lib/types";
import { useView } from "@/lib/viewStore";

/**
 * How the catalog list is ordered.
 *
 * Sorting is not filtering, and the interface keeps them apart: a filter says
 * which loci exist for you right now and gets a removable chip, a sort says
 * which ones you meet first and gets a control that is always visible. Clearing
 * the filters therefore leaves the order alone.
 *
 * Choosing a key resets the direction to that key's natural one — "biggest
 * first" for a magnitude, "start of the chromosome" for a position — because
 * carrying a direction across from the previous sort produces orders nobody
 * asked for, like reverse genomic.
 */

const DIRECTION_WORD: Record<SortDirection, string> = {
  desc: "Descending",
  asc: "Ascending",
};

export function SortControl({
  /** The ordering the API actually applied; differs only when a sort's table is
      missing, in which case the control says so rather than lying about it. */
  applied,
}: {
  applied?: SortKey;
}) {
  const { filters, agentTouched, patch } = useView();

  const key = filters.sort ?? "position";
  const option = SORTS.find((sort) => sort.key === key) ?? SORTS[0];
  const direction: SortDirection = filters.sort_dir ?? option.natural;
  const touched = agentTouched.has("sort") || agentTouched.has("sort_dir");
  const dropped = applied !== undefined && applied !== key;

  return (
    <div className="flex items-center gap-1.5">
      <label htmlFor="catalog-sort" className="text-xs text-ink-muted">
        Sort
      </label>

      <select
        id="catalog-sort"
        value={key}
        onChange={(event) =>
          patch({ sort: event.target.value as SortKey, sort_dir: null })
        }
        title={option.note}
        className="rounded-full px-2 py-1 text-xs text-ink transition-colors hover:border-baseline focus-visible:outline-2 focus-visible:outline-offset-1 focus-visible:outline-[var(--motif-1)]"
        style={{
          background: "var(--surface-raised)",
          border: `1px solid ${touched ? "var(--motif-1)" : "var(--hairline)"}`,
        }}
      >
        {SORTS.map((sort) => (
          <option key={sort.key} value={sort.key}>
            {sort.label}
          </option>
        ))}
      </select>

      <button
        type="button"
        onClick={() => patch({ sort_dir: direction === "desc" ? "asc" : "desc" })}
        aria-label={`${DIRECTION_WORD[direction]} — reverse the order`}
        title={`${DIRECTION_WORD[direction]} — click to reverse`}
        className="rounded-full px-1.5 py-1 text-xs leading-none text-ink-secondary transition-colors hover:text-ink focus-visible:outline-2 focus-visible:outline-offset-1 focus-visible:outline-[var(--motif-1)]"
        style={{
          background: "var(--surface-raised)",
          border: `1px solid ${touched ? "var(--motif-1)" : "var(--hairline)"}`,
        }}
      >
        {direction === "desc" ? "↓" : "↑"}
      </button>

      {dropped && (
        <span
          className="text-[11px] text-ink-muted"
          title="That sort reads the per-allele table, which is not registered here. The list is in genomic order."
        >
          not available — showing position
        </span>
      )}
    </div>
  );
}
