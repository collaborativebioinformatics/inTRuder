"use client";

import { Bar, BarChart, Cell, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";

import type { MotifClass, Summary } from "@/lib/types";
import { useView } from "@/lib/viewStore";

/**
 * Where the novel fraction actually lives, by motif class.
 *
 * The claim this project makes is that existing catalogs thin out as motifs get
 * longer, so the bar that matters is not the count but the *share* that is
 * novel — which is why the two measures are stacked into one bar per class
 * rather than drawn as a grouped pair. A grouped pair invites reading the
 * heights against each other; a stack makes the fraction the shape.
 *
 * Two series, so the encoding is novel-versus-catalogued rather than motif
 * identity: this uses the figure/ground pair, not the categorical slots. Clicking
 * a bar filters the catalog to that class, which is the only reason to look at
 * this chart in the first place.
 */

const ORDER: MotifClass[] = ["homopolymer", "STR", "VNTR"];

const PERIOD: Record<MotifClass, string> = {
  homopolymer: "1 bp",
  STR: "2–6 bp",
  VNTR: "≥7 bp",
};

export function ClassBreakdown({ summary }: { summary: Summary }) {
  const { filters, patch } = useView();

  // Sorted by motif length rather than by count: the argument is a trend across
  // period, and re-ordering the axis by magnitude would hide it.
  const data = ORDER.map((motif_class) => {
    const row = summary.by_class.find((entry) => entry.motif_class === motif_class);
    const n = row?.n ?? 0;
    const novel = row?.novel ?? 0;
    return { motif_class, n, novel, known: n - novel, share: n ? novel / n : 0 };
  }).filter((row) => row.n > 0);

  const selected = filters.motif_class;

  return (
    <section aria-labelledby="class-heading" className="space-y-2">
      <h2 id="class-heading" className="text-sm font-medium text-ink">
        Novel fraction by motif class
      </h2>

      {/* Legend and affordance share a line; the heading is long enough that a
          hint beside it wraps the column. */}
      <div className="flex items-center justify-between gap-2 text-[11px]">
        <span className="flex items-center gap-3 text-ink-secondary">
          <span className="flex items-center gap-1.5">
            <span
              className="inline-block h-2.5 w-2.5 rounded-sm"
              style={{ background: "var(--novel)" }}
            />
            Novel
          </span>
          <span className="flex items-center gap-1.5">
            <span
              className="inline-block h-2.5 w-2.5 rounded-sm"
              style={{ background: "var(--known)" }}
            />
            Catalogued
          </span>
        </span>
        <span className="text-ink-muted">Click to filter</span>
      </div>

      <div className="h-36 w-full [&_*:focus:not(:focus-visible)]:outline-none">
        <ResponsiveContainer width="100%" height="100%">
          <BarChart
            layout="vertical"
            data={data}
            margin={{ top: 0, right: 8, bottom: 0, left: 0 }}
            barCategoryGap={6}
          >
            <XAxis type="number" hide />
            <YAxis
              type="category"
              dataKey="motif_class"
              width={78}
              tick={{ fill: "var(--ink-secondary)", fontSize: 11 }}
              tickLine={false}
              axisLine={false}
            />
            <Tooltip
              cursor={{ fill: "var(--surface-raised)" }}
              content={({ active, payload }) => {
                if (!active || !payload?.length) return null;
                const row = payload[0].payload as (typeof data)[number];
                return (
                  <div className="rounded-md border border-hairline bg-surface-raised px-2.5 py-1.5 text-xs shadow-lg">
                    <div className="font-medium text-ink">
                      {row.motif_class}{" "}
                      <span className="tabular font-normal text-ink-muted">
                        {PERIOD[row.motif_class]}
                      </span>
                    </div>
                    <div className="tabular text-ink-secondary">
                      <span style={{ color: "var(--novel)" }}>{row.novel}</span> novel of{" "}
                      {row.n} loci · {(row.share * 100).toFixed(0)}%
                    </div>
                  </div>
                );
              }}
            />
            {/* Stacked, with a 1px surface stroke either side of the boundary —
                the 2px gap the mark spec asks for between adjacent fills. */}
            <Bar
              dataKey="novel"
              stackId="loci"
              fill="var(--novel)"
              stroke="var(--plane)"
              strokeWidth={1}
              isAnimationActive={false}
              onClick={(entry: unknown) => {
                const row = (entry as { payload?: (typeof data)[number] })?.payload;
                if (!row) return;
                patch({ motif_class: selected === row.motif_class ? null : row.motif_class });
              }}
              className="cursor-pointer"
            >
              {data.map((row) => (
                <Cell
                  key={row.motif_class}
                  // The class you have filtered to stays solid; the rest recede,
                  // so the chart shows the current view rather than ignoring it.
                  opacity={!selected || selected === row.motif_class ? 1 : 0.35}
                />
              ))}
            </Bar>
            <Bar
              dataKey="known"
              stackId="loci"
              fill="var(--known)"
              stroke="var(--plane)"
              strokeWidth={1}
              radius={[0, 2, 2, 0]}
              isAnimationActive={false}
              onClick={(entry: unknown) => {
                const row = (entry as { payload?: (typeof data)[number] })?.payload;
                if (!row) return;
                patch({ motif_class: selected === row.motif_class ? null : row.motif_class });
              }}
              className="cursor-pointer"
            >
              {data.map((row) => (
                <Cell
                  key={row.motif_class}
                  opacity={!selected || selected === row.motif_class ? 1 : 0.35}
                />
              ))}
            </Bar>
          </BarChart>
        </ResponsiveContainer>
      </div>

      <p className="text-[11px] leading-relaxed text-ink-muted">
        Existing catalogs are built from reference-anchored short-read panels, so
        coverage falls off as motifs get longer. The gap is what this pipeline is for.
      </p>
    </section>
  );
}
