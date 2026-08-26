"use client";

import type { ViewFilters } from "@/lib/types";
import { useView } from "@/lib/viewStore";

/**
 * Active filters as removable chips.
 *
 * Chips the agent set in its last turn are outlined, so when chat moves the view
 * it is visible *which* controls it touched — the interface stays legible rather
 * than mysteriously rearranging itself.
 */

const LABELS: Record<keyof ViewFilters, (value: unknown) => string> = {
  novel_only: () => "Novel only",
  disease_gene_only: () => "Disease genes",
  chrom: (v) => `${v}`,
  motif_class: (v) => `${v}`,
  gene: (v) => `${v}`,
  min_motif_len: (v) => `motif ≥ ${v} bp`,
  min_samples: (v) => `≥ ${v} carriers`,
  min_purity: (v) => `purity ≥ ${v}`,
  focus_locus_id: (v) => `${v}`,
};

const QUICK: { label: string; patch: ViewFilters }[] = [
  { label: "Novel only", patch: { novel_only: true } },
  { label: "VNTR", patch: { motif_class: "VNTR" } },
  { label: "Disease genes", patch: { disease_gene_only: true } },
  { label: "Shared ≥ 10", patch: { min_samples: 10 } },
];

export function FilterBar() {
  const { filters, agentTouched, patch, reset } = useView();

  const active = (Object.keys(filters) as (keyof ViewFilters)[]).filter(
    (key) => key !== "focus_locus_id",
  );

  return (
    <div className="space-y-2.5">
      <div className="flex flex-wrap gap-1.5">
        {QUICK.map((quick) => (
          <button
            key={quick.label}
            type="button"
            onClick={() => patch(quick.patch)}
            className="rounded-full border border-hairline px-2.5 py-1 text-xs text-ink-secondary transition-colors hover:border-baseline hover:text-ink"
          >
            + {quick.label}
          </button>
        ))}
      </div>

      {active.length > 0 && (
        <div className="flex flex-wrap items-center gap-1.5">
          {active.map((key) => {
            const touched = agentTouched.has(key);
            return (
              <button
                key={key}
                type="button"
                onClick={() => patch({ [key]: null } as ViewFilters)}
                title="Remove filter"
                className="group flex items-center gap-1.5 rounded-full px-2.5 py-1 text-xs transition-colors"
                style={{
                  background: "var(--surface-raised)",
                  border: `1px solid ${touched ? "var(--motif-1)" : "var(--hairline)"}`,
                  color: "var(--ink)",
                }}
              >
                {touched && (
                  <span
                    className="h-1.5 w-1.5 rounded-full"
                    style={{ background: "var(--motif-1)" }}
                    aria-label="set by assistant"
                  />
                )}
                <span className="tabular">{LABELS[key](filters[key])}</span>
                <span className="text-ink-muted transition-colors group-hover:text-ink">×</span>
              </button>
            );
          })}
          <button
            type="button"
            onClick={reset}
            className="px-1.5 text-xs text-ink-muted underline underline-offset-2 transition-colors hover:text-ink"
          >
            clear all
          </button>
        </div>
      )}
    </div>
  );
}
