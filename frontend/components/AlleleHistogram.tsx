"use client";

import { useMemo, useState } from "react";
import {
  Bar,
  BarChart,
  CartesianGrid,
  ReferenceLine,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";

import { MOTIF_OTHER, MOTIF_SLOTS, formatBp, shortMotif } from "@/lib/palette";
import type { Allele } from "@/lib/types";

/**
 * How one locus looks across the whole cohort.
 *
 * The barcodes below this show one allele each, which answers "what is in this
 * insertion" but never "is this length normal here". A distribution answers the
 * second question directly: a tight unimodal pile is a stable repeat, a long
 * right tail is a locus where somebody carries an expansion, and a gap between
 * two modes is the signature of a common structural difference rather than
 * ordinary copy-number jitter.
 *
 * Bars are stacked by motif rather than pooled, because a compound locus can put
 * two motifs in one allele and the interesting question is usually which motif
 * the tail belongs to. Colours are the same three categorical slots the barcodes
 * use, assigned by the same rank order, so a block in the strip and a bar in the
 * histogram that share a colour are the same motif — the whole page is one
 * legend. Motifs past the top three fold into a neutral Other; a fourth hue
 * would not survive the all-pairs colourblind check that palette is built on.
 *
 * Median markers are per motif, matching how STRchive-style locus plots read: the
 * median is the number people quote, and its position against the pile is the
 * fastest way to see skew.
 */

type MetricKey = "allele_len" | "copies" | "motif_bp";

const METRICS: {
  key: MetricKey;
  label: string;
  note: string;
  unit: string;
  /** The x-axis caption. Spelled out rather than composed from label + unit,
      which produces "Motif copies (MC) (copies)". */
  axis: string;
  /** What one count on the y axis is. Not always a carrier: under the per-motif
      metrics a compound allele contributes one observation per motif. */
  counted: string;
}[] = [
  {
    key: "allele_len",
    label: "Allele length",
    note: "Total inserted sequence per carrier, coloured by the motif that accounts for most of it. One allele, one observation.",
    unit: "bp",
    axis: "Allele length (bp)",
    counted: "carriers",
  },
  {
    key: "copies",
    label: "Motif copies (MC)",
    note: "Copies of each motif in the allele. A compound allele contributes one observation per motif it carries.",
    unit: "copies",
    axis: "Motif copies (MC)",
    counted: "alleles",
  },
  {
    key: "motif_bp",
    label: "Motif length",
    note: "How much sequence each motif accounts for within the allele. Separates a long array from a long allele.",
    unit: "bp",
    axis: "Motif length (bp)",
    counted: "alleles",
  },
];

/** One value on the x axis, tagged with the motif series it belongs to. */
interface Observation {
  sample: string;
  series: string;
  value: number;
}

/** A per-motif median, drawn as a dashed rule across the distribution. */
interface MedianMark {
  series: string;
  value: number | null;
  n: number;
}

interface Bin {
  x0: number;
  x1: number;
  mid: number;
  total: number;
  /** Carriers in this bin, for the tooltip and for click-to-highlight. */
  samples: string[];
  /** One count per motif series; keys are motif strings or OTHER. */
  [series: string]: number | string[] | number[];
}

const OTHER = "Other";

/**
 * A round number near `range / target`. Histograms are read by their shape, and
 * a bin edge at 37.4 makes the reader do arithmetic to check the shape is real.
 */
function niceStep(range: number, target: number, integral: boolean): number {
  const raw = Math.max(range, 1) / target;
  const magnitude = 10 ** Math.floor(Math.log10(raw));
  const step =
    [1, 2, 2.5, 5, 10].map((m) => m * magnitude).find((c) => c >= raw) ?? magnitude * 10;
  return integral ? Math.max(1, Math.round(step)) : step;
}

function median(values: number[]): number | null {
  if (!values.length) return null;
  const sorted = [...values].sort((a, b) => a - b);
  const middle = Math.floor(sorted.length / 2);
  return sorted.length % 2 ? sorted[middle] : (sorted[middle - 1] + sorted[middle]) / 2;
}

/**
 * Rank motifs by the sequence they account for across the cohort and give the
 * top three the categorical slots, in that fixed order. Deliberately the same
 * rule as `buildMotifScale`, applied to the same segments, so the histogram and
 * the strips below it cannot disagree about which motif is blue.
 */
function motifSeries(alleles: Allele[]): { order: string[]; color: Map<string, string> } {
  const span = new Map<string, number>();
  for (const allele of alleles) {
    for (const segment of allele.segments) {
      if (segment.seg_type !== "repeat" || !segment.motif) continue;
      span.set(segment.motif, (span.get(segment.motif) ?? 0) + (segment.end - segment.start));
    }
  }
  const ranked = [...span.entries()]
    .sort((a, b) => b[1] - a[1] || a[0].localeCompare(b[0]))
    .map(([motif]) => motif);

  const color = new Map<string, string>();
  const order: string[] = [];
  ranked.forEach((motif, index) => {
    if (index < MOTIF_SLOTS.length) {
      color.set(motif, MOTIF_SLOTS[index]);
      order.push(motif);
    } else {
      color.set(motif, MOTIF_OTHER);
    }
  });
  if (ranked.length > MOTIF_SLOTS.length) {
    color.set(OTHER, MOTIF_OTHER);
    order.push(OTHER);
  }
  return { order, color };
}

function observe(alleles: Allele[], metric: MetricKey, top: Set<string>): Observation[] {
  const out: Observation[] = [];

  for (const allele of alleles) {
    // Per-motif totals within this one allele.
    const byMotif = new Map<string, { copies: number; bp: number }>();
    for (const segment of allele.segments) {
      if (segment.seg_type !== "repeat" || !segment.motif) continue;
      const entry = byMotif.get(segment.motif) ?? { copies: 0, bp: 0 };
      entry.copies += segment.units ?? 0;
      entry.bp += segment.end - segment.start;
      byMotif.set(segment.motif, entry);
    }

    const label = (motif: string) => (top.has(motif) ? motif : OTHER);

    if (metric === "allele_len") {
      // One observation per carrier. Its colour is the motif accounting for the
      // most sequence in that allele — the allele's own headline, not the
      // locus's, so a carrier whose insertion is mostly the minority motif shows
      // up as such.
      let dominant: string | null = null;
      let best = -1;
      for (const [motif, totals] of byMotif) {
        if (totals.bp > best) {
          best = totals.bp;
          dominant = motif;
        }
      }
      out.push({
        sample: allele.sample,
        series: dominant ? label(dominant) : OTHER,
        value: allele.allele_len,
      });
      continue;
    }

    for (const [motif, totals] of byMotif) {
      const value = metric === "copies" ? totals.copies : totals.bp;
      if (value <= 0) continue;
      out.push({ sample: allele.sample, series: label(motif), value });
    }
  }

  return out;
}

export function AlleleHistogram({
  alleles,
  /** Carriers currently isolated by a click, so the control can say so. */
  highlighted,
  onHighlight,
}: {
  alleles: Allele[];
  highlighted: Set<string> | null;
  onHighlight: (samples: Set<string> | null) => void;
}) {
  const [metric, setMetric] = useState<MetricKey>("allele_len");
  const [hidden, setHidden] = useState<Set<string>>(new Set());

  const spec = METRICS.find((m) => m.key === metric) ?? METRICS[0];
  const { order, color } = useMemo(() => motifSeries(alleles), [alleles]);
  const top = useMemo(() => new Set(order.filter((s) => s !== OTHER)), [order]);

  const { bins, medians, empty } = useMemo(() => {
    const observations = observe(alleles, metric, top);
    if (!observations.length) {
      return { bins: [] as Bin[], medians: [] as MedianMark[], empty: true };
    }

    const values = observations.map((o) => o.value);
    const low = Math.min(...values);
    const high = Math.max(...values);
    const integral = metric === "copies";
    const step = niceStep(high - low, 18, integral);
    const start = Math.floor(low / step) * step;
    const count = Math.max(1, Math.ceil((high - start) / step) + 1);

    const built: Bin[] = Array.from({ length: count }, (_, index) => {
      const x0 = start + index * step;
      const bin: Bin = { x0, x1: x0 + step, mid: x0 + step / 2, total: 0, samples: [] };
      for (const series of order) bin[series] = 0;
      return bin;
    });

    for (const observation of observations) {
      const index = Math.min(count - 1, Math.floor((observation.value - start) / step));
      const bin = built[index];
      bin[observation.series] = ((bin[observation.series] as number) ?? 0) + 1;
      bin.total += 1;
      if (!bin.samples.includes(observation.sample)) bin.samples.push(observation.sample);
    }

    const perSeries = order.map((series) => {
      const values = observations.filter((o) => o.series === series).map((o) => o.value);
      return { series, value: median(values), n: values.length };
    });

    return { bins: built, medians: perSeries, empty: false };
  }, [alleles, metric, order, top]);

  if (empty) return null;

  const visible = order.filter((series) => !hidden.has(series));

  // Axis ticks are compact — a tick reading "1.1 kb" is enough to place a bar.
  const tick = (value: number) =>
    spec.unit === "bp" ? formatBp(Math.round(value)) : `×${value.toFixed(0)}`;

  // Bin edges and medians are exact. Rounded to the nearest 0.1 kb a 50 bp bin
  // prints as "1.1 kb – 1.1 kb", which reads as a bug in the chart.
  const exact = (value: number) =>
    spec.unit === "bp"
      ? `${Math.round(value).toLocaleString("en-US")} bp`
      : `×${value.toFixed(0)}`;

  return (
    <section aria-labelledby="distribution-heading" className="space-y-2">
      <div className="flex flex-wrap items-center justify-between gap-x-4 gap-y-2">
        <div>
          <h3 id="distribution-heading" className="text-sm font-medium text-ink">
            Across the cohort
          </h3>
          <p className="tabular text-[11px] text-ink-muted">
            {alleles.length} carriers · {alleles.length} alleles
          </p>
        </div>

        <div className="flex items-center gap-1.5">
          <label htmlFor="histogram-metric" className="text-xs text-ink-muted">
            Metric
          </label>
          <select
            id="histogram-metric"
            value={metric}
            onChange={(event) => {
              setMetric(event.target.value as MetricKey);
              onHighlight(null);
            }}
            className="rounded-full px-2 py-1 text-xs text-ink focus-visible:outline-2 focus-visible:outline-offset-1 focus-visible:outline-[var(--motif-1)]"
            style={{
              background: "var(--surface-raised)",
              border: "1px solid var(--hairline)",
            }}
          >
            {METRICS.map((option) => (
              <option key={option.key} value={option.key}>
                {option.label}
              </option>
            ))}
          </select>
        </div>
      </div>

      <p className="max-w-2xl text-[11px] leading-relaxed text-ink-muted">{spec.note}</p>

      {/* Identity never rides on colour alone: every series is named here, and
          the legend doubles as the filter. */}
      <div className="flex flex-wrap items-center gap-x-3 gap-y-1.5 text-xs">
        {order.map((series) => {
          const off = hidden.has(series);
          return (
            <button
              key={series}
              type="button"
              onClick={() => {
                const next = new Set(hidden);
                if (off) next.delete(series);
                else if (visible.length > 1) next.add(series);
                setHidden(next);
              }}
              aria-pressed={!off}
              title={off ? `Show ${series}` : `Hide ${series}`}
              className="flex items-center gap-1.5 transition-opacity"
              style={{ opacity: off ? 0.4 : 1 }}
            >
              <span
                className="inline-block h-2.5 w-2.5 rounded-sm"
                style={{ background: color.get(series) ?? MOTIF_OTHER }}
              />
              <span className="tabular text-ink-secondary">
                {series.length > 12 ? `${series.slice(0, 11)}…` : series}
              </span>
            </button>
          );
        })}
        {highlighted && (
          <button
            type="button"
            onClick={() => onHighlight(null)}
            className="text-[11px] text-ink-muted underline underline-offset-2 transition-colors hover:text-ink"
          >
            {/* Not "clear bin": the isolated set can also have come from a row
                in the structure list below. */}
            clear ({highlighted.size} carriers)
          </button>
        )}
      </div>

      {/* Recharts gives its bar layers a tabIndex for keyboard navigation, and
          the browser then rings the whole plot on an ordinary mouse click. The
          ring is right for keyboard focus and noise for a click. */}
      <div className="h-56 w-full rounded-lg border border-hairline bg-surface p-2 [&_*:focus:not(:focus-visible)]:outline-none">
        <ResponsiveContainer width="100%" height="100%">
          <BarChart
            data={bins}
            margin={{ top: 22, right: 10, bottom: 14, left: 0 }}
            barCategoryGap={0}
          >
            <CartesianGrid
              vertical={false}
              stroke="var(--hairline)"
              strokeDasharray="2 3"
            />
            <XAxis
              dataKey="mid"
              type="number"
              domain={[bins[0].x0, bins[bins.length - 1].x1]}
              tickFormatter={(value: number) => tick(value)}
              tick={{ fill: "var(--ink-muted)", fontSize: 10 }}
              tickLine={false}
              axisLine={{ stroke: "var(--hairline)" }}
              label={{
                value: spec.axis,
                position: "insideBottom",
                offset: -12,
                fill: "var(--ink-muted)",
                fontSize: 10,
              }}
            />
            <YAxis
              allowDecimals={false}
              width={34}
              tick={{ fill: "var(--ink-muted)", fontSize: 10 }}
              tickLine={false}
              axisLine={false}
              label={{
                value: spec.counted.replace(/^./, (c) => c.toUpperCase()),
                angle: -90,
                position: "insideLeft",
                fill: "var(--ink-muted)",
                fontSize: 10,
              }}
            />
            <Tooltip
              cursor={{ fill: "var(--surface-raised)" }}
              content={({ active, payload }) => {
                if (!active || !payload?.length) return null;
                const bin = payload[0].payload as Bin;
                return (
                  <div className="max-w-xs rounded-md border border-hairline bg-surface-raised px-2.5 py-1.5 text-xs shadow-lg">
                    <div className="tabular font-medium text-ink">
                      {exact(bin.x0)} – {exact(bin.x1)}
                    </div>
                    {payload
                      .filter((entry) => (entry.value as number) > 0)
                      .map((entry) => (
                        <div
                          key={entry.name as string}
                          className="tabular flex items-center gap-1.5 text-ink-secondary"
                        >
                          <span
                            className="inline-block h-2 w-2 shrink-0 rounded-sm"
                            style={{ background: entry.color }}
                          />
                          {/* Elided: a VNTR motif runs to ninety bases and would
                              make the tooltip wider than the chart. */}
                          {shortMotif(entry.name as string, 14)} · {entry.value as number}
                        </div>
                      ))}
                    <div className="mt-0.5 text-ink-muted">
                      {bin.samples.length} carrier{bin.samples.length === 1 ? "" : "s"} —
                      click to isolate
                    </div>
                  </div>
                );
              }}
            />

            {visible.map((series, index) => (
              <Bar
                key={series}
                dataKey={series}
                stackId="alleles"
                fill={color.get(series) ?? MOTIF_OTHER}
                // A 1px surface stroke on each side of a boundary is the 2px
                // gap the mark spec asks for between stacked fills.
                stroke="var(--surface)"
                strokeWidth={1}
                radius={index === visible.length - 1 ? [2, 2, 0, 0] : undefined}
                isAnimationActive={false}
                onClick={(entry: unknown) => {
                  const bin = (entry as { payload?: Bin })?.payload;
                  if (!bin) return;
                  const samples = new Set(bin.samples);
                  const same =
                    highlighted?.size === samples.size &&
                    [...samples].every((s) => highlighted.has(s));
                  onHighlight(same ? null : samples);
                }}
                className="cursor-pointer"
              />
            ))}

            {/* The median is the number people quote for a locus; its position
                against the pile is the fastest read of skew. */}
            {medians
              .filter((m) => m.value != null && m.n >= 3 && !hidden.has(m.series))
              .map(({ series, value }, index) => (
                <ReferenceLine
                  key={series}
                  x={value as number}
                  stroke={color.get(series) ?? MOTIF_OTHER}
                  strokeDasharray="4 3"
                  label={{
                    value: exact(value as number),
                    position: "top",
                    // Staggered: two motifs with similar medians would otherwise
                    // print their labels on top of one another.
                    offset: 2 + (index % 2) * 10,
                    fill: color.get(series) ?? MOTIF_OTHER,
                    fontSize: 9,
                  }}
                />
              ))}
          </BarChart>
        </ResponsiveContainer>
      </div>
    </section>
  );
}
