"use client";

import { useEffect, useState } from "react";

import { CatalogView } from "@/components/CatalogView";
import { Chat } from "@/components/Chat";
import { FilterBar } from "@/components/FilterBar";
import { Funnel } from "@/components/Funnel";
import { LocusView } from "@/components/LocusView";
import { ThemeToggle } from "@/components/ThemeToggle";
import { fetchHealth, fetchLoci, fetchSummary, type Health } from "@/lib/api";
import type { LociResponse, Summary } from "@/lib/types";
import { ViewProvider, useView } from "@/lib/viewStore";

function ClassBreakdown({ summary }: { summary: Summary }) {
  const max = Math.max(...summary.by_class.map((row) => row.n), 1);
  return (
    <section aria-labelledby="class-heading" className="space-y-2">
      <h2 id="class-heading" className="text-sm font-medium text-ink">
        Novel fraction by motif class
      </h2>
      <ul className="space-y-1.5">
        {summary.by_class.map((row) => (
          <li key={row.motif_class} className="space-y-1">
            <div className="flex items-baseline justify-between gap-2 text-xs">
              <span className="text-ink-secondary">{row.motif_class}</span>
              <span className="tabular text-ink-muted">
                <span style={{ color: "var(--novel)" }}>{row.novel}</span> / {row.n}
              </span>
            </div>
            <div
              className="relative h-1.5 overflow-hidden rounded-full"
              style={{ background: "var(--hairline)" }}
            >
              <div
                className="absolute inset-y-0 left-0 rounded-full"
                style={{ width: `${(row.n / max) * 100}%`, background: "var(--known)" }}
              />
              <div
                className="absolute inset-y-0 left-0 rounded-full"
                style={{ width: `${(row.novel / max) * 100}%`, background: "var(--novel)" }}
              />
            </div>
          </li>
        ))}
      </ul>
      <p className="text-[11px] leading-relaxed text-ink-muted">
        Existing catalogs are built from reference-anchored short-read panels, so
        coverage falls off as motifs get longer. The gap is what this pipeline is for.
      </p>
    </section>
  );
}

function Workspace() {
  const { filters } = useView();
  const [summary, setSummary] = useState<Summary | null>(null);
  const [health, setHealth] = useState<Health | null>(null);
  const [data, setData] = useState<LociResponse | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    const controller = new AbortController();
    Promise.all([fetchSummary(controller.signal), fetchHealth(controller.signal)])
      .then(([s, h]) => {
        setSummary(s);
        setHealth(h);
      })
      .catch((err: Error) => {
        if (err.name !== "AbortError") setError(err.message);
      });
    return () => controller.abort();
  }, []);

  useEffect(() => {
    const controller = new AbortController();
    setLoading(true);
    fetchLoci(filters, 400, controller.signal)
      .then((response) => {
        setData(response);
        setError(null);
      })
      .catch((err: Error) => {
        if (err.name !== "AbortError") setError(err.message);
      })
      .finally(() => setLoading(false));
    return () => controller.abort();
  }, [filters]);

  const focused = filters.focus_locus_id;

  return (
    <div className="flex h-full flex-col">
      <header className="flex shrink-0 flex-wrap items-center justify-between gap-3 border-b border-hairline px-4 py-2.5">
        <div className="flex items-baseline gap-3">
          <h1 className="text-sm font-semibold tracking-tight text-ink">novelTRs</h1>
          <p className="hidden text-xs text-ink-muted sm:block">
            Tandem repeats absent from the reference, discovered from SV insertions
          </p>
        </div>
        <div className="flex items-center gap-2">
          {summary?.synthetic && (
            <span
              className="rounded-full px-2 py-0.5 text-[11px] font-medium"
              style={{ background: "var(--novel-soft)", color: "var(--novel)" }}
              title="Every number on screen comes from a generated fixture, not a real callset."
            >
              Synthetic demo data
            </span>
          )}
          <ThemeToggle />
        </div>
      </header>

      {error && (
        <div
          className="shrink-0 px-4 py-2 text-xs"
          style={{ background: "var(--novel-soft)", color: "var(--novel)" }}
        >
          Cannot reach the API — {error}. Start it with:{" "}
          <span className="tabular">cd backend &amp;&amp; uv run uvicorn app.main:app --reload</span>
        </div>
      )}

      <div className="grid min-h-0 flex-1 grid-cols-1 lg:grid-cols-[19rem_minmax(0,1fr)_22rem]">
        <aside className="min-h-0 space-y-6 overflow-y-auto border-hairline p-4 lg:border-r">
          {summary ? (
            <>
              <Funnel stages={summary.funnel} />
              <ClassBreakdown summary={summary} />
            </>
          ) : (
            <p className="text-sm text-ink-muted">Loading summary…</p>
          )}
        </aside>

        <main className="flex min-h-0 flex-col gap-3 p-4">
          <FilterBar />
          {focused ? (
            <LocusView locusId={focused} />
          ) : (
            <CatalogView
              loci={data?.loci ?? []}
              strips={data?.strips ?? {}}
              total={data?.total ?? 0}
              loading={loading}
            />
          )}
        </main>

        <aside className="flex min-h-0 flex-col border-hairline lg:border-l">
          <div className="shrink-0 border-b border-hairline px-3 py-2.5">
            <h2 className="text-sm font-medium text-ink">Assistant</h2>
            <p className="text-[11px] text-ink-muted">
              {health?.llm.provider ?? "…"}
              {health?.agent_enabled === false && " · not configured"}
            </p>
          </div>
          <Chat agentEnabled={health?.agent_enabled ?? false} />
        </aside>
      </div>
    </div>
  );
}

export default function Page() {
  return (
    <ViewProvider>
      <Workspace />
    </ViewProvider>
  );
}
