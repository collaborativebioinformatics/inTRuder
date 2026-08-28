"use client";

import { SearchBox } from "@/components/SearchBox";
import { formatRegion } from "@/lib/region";
import {
  NOVELTY_LABELS,
  SORT_LABELS,
  STRCHIVE_STATUS_LABELS,
  type NoveltyStatus,
  type SortKey,
  type StrchiveStatus,
  type ViewFilters,
} from "@/lib/types";
import { useView } from "@/lib/viewStore";

/**
 * Active filters as removable chips.
 *
 * Chips the agent set in its last turn are outlined, so when chat moves the view
 * it is visible *which* controls it touched — the interface stays legible rather
 * than mysteriously rearranging itself.
 */

const LABELS: Record<keyof ViewFilters, (value: unknown) => string> = {
  page: (v) => `${v}`,
  novel_only: () => "Novel only",
  novelty: (v) => NOVELTY_LABELS[v as NoveltyStatus] ?? `${v}`,
  platform_agreement: (v) =>
    v === "both" ? "Both catalogs agree" : `${v}`.replace("_", " "),
  disease_gene_only: () => "Disease genes",
  genic_only: () => "In a gene",
  exonic_only: () => "Exonic",
  constrained_only: () => "Constrained (pLI ≥ 0.9)",
  gene_region: (v) => `${v}`,
  chrom: (v) => `${v}`,
  region: (v) => formatRegion(`${v}`),
  motif_class: (v) => `${v}`,
  gene: (v) => `${v}`,
  gene_query: (v) => `gene contains “${v}”`,
  sample: (v) => `${v}`,
  strchive_status: (v) => STRCHIVE_STATUS_LABELS[v as StrchiveStatus] ?? `${v}`,
  strchive_novel_only: () => "Pathogenic motif not in hg38",
  min_motif_len: (v) => `motif ≥ ${v} bp`,
  min_samples: (v) => `≥ ${v} carriers`,
  min_purity: (v) => `purity ≥ ${v}`,
  min_insertion_purity: (v) => `insertion ≥ ${v} repeat`,
  sort: (v) => SORT_LABELS[v as SortKey] ?? `${v}`,
  sort_dir: (v) => `${v}`,
  focus_locus_id: (v) => `${v}`,
  focus_strchive_id: (v) => `${v}`,
};

/**
 * Keys that are navigation, ordering or drill-down rather than filters. They
 * change what you are looking at or the order you meet it in, not which subset
 * of it exists, so they do not belong in a row of removable chips — and a sort
 * has its own always-visible control, which a chip would duplicate.
 */
const NOT_A_CHIP: (keyof ViewFilters)[] = [
  "page",
  "sort",
  "sort_dir",
  "focus_locus_id",
  "focus_strchive_id",
];

const QUICK: { label: string; patch: ViewFilters; title?: string }[] = [
  {
    label: "Novel motif",
    patch: { novelty: "novel_motif" },
    title: "The reference has repeats here, but none with this motif.",
  },
  {
    label: "Novel locus",
    patch: { novelty: "novel_locus" },
    title: "The reference annotates no repeat at all near this locus.",
  },
  {
    label: "Both catalogs agree",
    patch: { platform_agreement: "both" },
    title:
      "UCSC and TRExplorer were compiled separately — where they agree, the call is a property of the data rather than of a threshold.",
  },
  { label: "VNTR", patch: { motif_class: "VNTR" } },
  {
    label: "In a gene",
    patch: { genic_only: true },
    title: "The insertion falls inside an annotated gene. Half the catalog does not.",
  },
  {
    label: "Exonic",
    patch: { exonic_only: true },
    title:
      "A breakpoint lands inside an exon — the strong claim. Not the same as the region column, where an intron between the start and stop codons reads as CDS.",
  },
  {
    label: "Disease genes",
    patch: { disease_gene_only: true },
    title:
      "The gene has an OMIM disease entry. Weaker than a STRchive locus, which is a curated repeat-expansion site.",
  },
  {
    label: "Constrained",
    patch: { constrained_only: true },
    title: "gnomAD pLI ≥ 0.9 — the gene is intolerant of loss of function.",
  },
  { label: "Shared ≥ 10", patch: { min_samples: 10 } },
];

export function FilterBar({ ignored = [] }: { ignored?: (keyof ViewFilters)[] }) {
  const { filters, agentTouched, patch, reset } = useView();

  const active = (Object.keys(filters) as (keyof ViewFilters)[]).filter(
    (key) => !NOT_A_CHIP.includes(key),
  );

  return (
    <div className="space-y-2.5">
      <SearchBox />

      <div className="flex flex-wrap gap-1.5">
        {QUICK.map((quick) => (
          <button
            key={quick.label}
            type="button"
            onClick={() => patch(quick.patch)}
            title={quick.title}
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
            // A filter the current table cannot honour is drawn as inactive: it
            // is doing nothing, and a chip that looks live implies the list
            // below was narrowed by it.
            const isIgnored = ignored.includes(key);
            return (
              <button
                key={key}
                type="button"
                onClick={() => patch({ [key]: null } as ViewFilters)}
                title={
                  isIgnored
                    ? "Not applied — this filter needs the screened callset, which is not registered yet. The list below is unfiltered by it."
                    : "Remove filter"
                }
                className="group flex items-center gap-1.5 rounded-full px-2.5 py-1 text-xs transition-colors"
                style={{
                  background: isIgnored ? "transparent" : "var(--surface-raised)",
                  border: `1px ${isIgnored ? "dashed" : "solid"} ${
                    touched && !isIgnored ? "var(--motif-1)" : "var(--hairline)"
                  }`,
                  color: isIgnored ? "var(--ink-muted)" : "var(--ink)",
                  textDecoration: isIgnored ? "line-through" : undefined,
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

      {ignored.length > 0 && (
        <p className="text-[11px] leading-relaxed text-ink-muted">
          Struck-through filters need the screened callset from the novelty screen,
          which is not registered yet — the list below is not narrowed by them.
        </p>
      )}
    </div>
  );
}
