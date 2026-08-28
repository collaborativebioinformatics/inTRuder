"use client";

import { FUNNEL_STEPS } from "@/lib/palette";
import type { FunnelStage, ViewFilters } from "@/lib/types";
import { useView } from "@/lib/viewStore";

/**
 * The cohort funnel — the landing view, and the argument the whole project makes.
 *
 * It is a filter chain rendered as a chart: each stage is a real query, and
 * clicking one applies exactly that filter to everything below. The point is to
 * turn "we ran a pipeline" into "we went from N raw calls to n things no
 * catalog has."
 *
 * Single-hue ordinal ramp, monotone lightness — stages are ordered, not
 * categorical, so they must not read as different kinds of thing.
 */

/**
 * The filter each stage applies, in the order the backend emits them.
 *
 * Keyed by stage index, which only works because the backend builds the funnel
 * in exactly this order — and it now builds a SHORTER one on a table with no
 * gene annotation, stopping after "absent from all catalogs" rather than showing
 * two stages of zeros. Indexing a shorter list is why `?? {}` is here: the last
 * two entries are simply never reached on such a table.
 */
const STAGE_FILTERS: ViewFilters[] = [
  {},
  { min_motif_len: 2 },
  { min_motif_len: 2, min_purity: 0.8 },
  { min_motif_len: 2, min_purity: 0.8, novel_only: true },
  { min_motif_len: 2, min_purity: 0.8, novel_only: true, genic_only: true },
  { min_motif_len: 2, min_purity: 0.8, novel_only: true, disease_gene_only: true },
];

export function Funnel({ stages }: { stages: FunnelStage[] }) {
  const { patch } = useView();
  const total = stages[0]?.count ?? 1;

  return (
    <section aria-labelledby="funnel-heading" className="space-y-3">
      <div className="flex items-baseline justify-between gap-4">
        <h2 id="funnel-heading" className="text-sm font-medium text-ink">
          Discovery funnel
        </h2>
        <p className="text-xs text-ink-muted">Click a stage to filter</p>
      </div>

      <ol className="space-y-1.5">
        {stages.map((stage, index) => {
          const share = total ? stage.count / total : 0;
          const isTerminal = index === stages.length - 1;
          return (
            <li key={stage.stage}>
              <button
                type="button"
                onClick={() => patch(STAGE_FILTERS[index] ?? {})}
                className="group grid w-full grid-cols-[1fr_auto] items-center gap-x-4 gap-y-1 rounded-md px-2 py-1.5 text-left transition-colors hover:bg-surface-raised focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-[var(--motif-1)]"
              >
                <div className="min-w-0">
                  <div className="truncate text-sm text-ink">{stage.stage}</div>
                  <div className="truncate text-xs text-ink-muted">{stage.note}</div>
                </div>

                <div className="tabular text-right">
                  <div
                    className={`text-sm ${isTerminal ? "font-semibold text-novel" : "text-ink"}`}
                  >
                    {stage.count.toLocaleString("en-US")}
                  </div>
                  <div className="text-xs text-ink-muted">
                    {(share * 100).toFixed(share < 0.1 ? 1 : 0)}%
                  </div>
                </div>

                <div
                  className="col-span-2 h-2 w-full overflow-hidden rounded-full"
                  style={{ background: "var(--hairline)" }}
                >
                  <div
                    className="h-full rounded-full transition-[width] duration-500 ease-out"
                    style={{
                      width: `${Math.max(share * 100, 0.6)}%`,
                      background: isTerminal
                        ? "var(--novel)"
                        : FUNNEL_STEPS[Math.min(index, FUNNEL_STEPS.length - 1)],
                    }}
                  />
                </div>
              </button>
            </li>
          );
        })}
      </ol>
    </section>
  );
}
