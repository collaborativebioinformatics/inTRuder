"use client";

import Link from "next/link";
import { useEffect, useState } from "react";

import { CatalogView } from "@/components/CatalogView";
import { Chat } from "@/components/Chat";
import { FilterBar } from "@/components/FilterBar";
import { Funnel } from "@/components/Funnel";
import { LocusView } from "@/components/LocusView";
import { StrchiveView } from "@/components/StrchiveView";
import { ThemeToggle } from "@/components/ThemeToggle";
import {
  fetchHealth,
  fetchLoci,
  fetchStrchiveSummary,
  fetchSummary,
  type Health,
} from "@/lib/api";
import type {
  LociResponse,
  PageName,
  StrchiveSummary,
  Summary,
  ViewFilters,
} from "@/lib/types";
import { ViewProvider, useView } from "@/lib/viewStore";

/**
 * The shell both surfaces share: header and nav, a left rail of context, the
 * main view, and the assistant.
 *
 * Which surface is showing lives in the view store rather than in the route, so
 * the agent's `set_view(page=…)` moves between them the same way a click does —
 * the whole premise of this interface is that chat and the controls edit one
 * object. The routes exist so the surfaces are linkable and bookmarkable; they
 * seed that object and then get out of the way.
 */

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

/** Left rail on the disease-locus surface — orientation, not cohort stats. */
function StrchiveRail({ summary }: { summary: StrchiveSummary | null }) {
  if (!summary) return <p className="text-sm text-ink-muted">Loading catalog…</p>;
  const max = Math.max(...summary.by_inheritance.map((row) => row.n), 1);

  return (
    <div className="space-y-6">
      <section className="space-y-2">
        <h2 className="text-sm font-medium text-ink">What this is</h2>
        <p className="text-[11px] leading-relaxed text-ink-secondary">
          STRchive curates the tandem repeats known to cause human disease, with
          the motifs seen at each locus and the copy numbers separating a benign
          allele from a pathogenic one.
        </p>
        <p className="text-[11px] leading-relaxed text-ink-muted">
          The screen asks three questions in order: does a call land on a disease
          locus, is its motif one catalogued there, and does the copy number reach
          the pathogenic range. Each only means something if the previous one was
          yes.
        </p>
      </section>

      <section className="space-y-2">
        <h2 className="text-sm font-medium text-ink">Inheritance</h2>
        <ul className="space-y-1.5">
          {summary.by_inheritance.map((row) => (
            <li key={row.inheritance} className="space-y-1">
              <div className="flex items-baseline justify-between gap-2 text-xs">
                <span className="text-ink-secondary">{row.inheritance}</span>
                <span className="tabular text-ink-muted">{row.n}</span>
              </div>
              <div
                className="h-1.5 overflow-hidden rounded-full"
                style={{ background: "var(--hairline)" }}
              >
                <div
                  className="h-full rounded-full"
                  style={{ width: `${(row.n / max) * 100}%`, background: "var(--known)" }}
                />
              </div>
            </li>
          ))}
        </ul>
      </section>
    </div>
  );
}

const TABS: { page: PageName; href: string; label: string }[] = [
  { page: "catalog", href: "/", label: "Candidate loci" },
  { page: "strchive", href: "/strchive", label: "Disease loci" },
];

function Nav() {
  const { filters, patch } = useView();
  const current = filters.page ?? "catalog";

  return (
    <nav className="flex items-center gap-1" aria-label="Surfaces">
      {TABS.map((tab) => {
        const active = current === tab.page;
        return (
          <Link
            key={tab.page}
            href={tab.href}
            onClick={() => patch({ page: tab.page })}
            aria-current={active ? "page" : undefined}
            className="rounded-full px-2.5 py-1 text-xs transition-colors"
            style={{
              background: active ? "var(--surface-raised)" : "transparent",
              color: active ? "var(--ink)" : "var(--ink-muted)",
              border: `1px solid ${active ? "var(--hairline)" : "transparent"}`,
            }}
          >
            {tab.label}
          </Link>
        );
      })}
    </nav>
  );
}

function WorkspaceInner() {
  const { filters } = useView();
  const [summary, setSummary] = useState<Summary | null>(null);
  const [strchive, setStrchive] = useState<StrchiveSummary | null>(null);
  const [health, setHealth] = useState<Health | null>(null);
  const [data, setData] = useState<LociResponse | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const page = filters.page ?? "catalog";

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
    // The disease catalog is independent of the cohort tables, so a missing
    // callset must not stop it loading — and vice versa.
    fetchStrchiveSummary(controller.signal)
      .then(setStrchive)
      .catch(() => setStrchive(null));
    return () => controller.abort();
  }, []);

  useEffect(() => {
    if (page !== "catalog") return;
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
  }, [filters, page]);

  const focused = filters.focus_locus_id;

  return (
    <div className="flex h-full flex-col">
      <header className="flex shrink-0 flex-wrap items-center justify-between gap-3 border-b border-hairline px-4 py-2.5">
        <div className="flex items-center gap-4">
          <h1 className="text-sm font-semibold tracking-tight text-ink">novelTRs</h1>
          <Nav />
        </div>
        <div className="flex items-center gap-2">
          {page === "catalog" && summary?.synthetic && (
            <span
              className="rounded-full px-2 py-0.5 text-[11px] font-medium"
              style={{ background: "var(--novel-soft)", color: "var(--novel)" }}
              title="Every number on screen comes from a generated fixture, not a real callset."
            >
              Synthetic demo data
            </span>
          )}
          {page === "strchive" && strchive && (
            <span
              className="tabular rounded-full px-2 py-0.5 text-[11px] text-ink-muted"
              style={{ background: "var(--surface-raised)" }}
              title="Curated reference data, pinned to a release."
            >
              {strchive.catalog_version}
            </span>
          )}
          <ThemeToggle />
        </div>
      </header>

      {error && page === "catalog" && (
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
          {page === "strchive" ? (
            <StrchiveRail summary={strchive} />
          ) : summary ? (
            <>
              <Funnel stages={summary.funnel} />
              <ClassBreakdown summary={summary} />
            </>
          ) : (
            <p className="text-sm text-ink-muted">Loading summary…</p>
          )}
        </aside>

        <main className="flex min-h-0 flex-col gap-3 p-4">
          {page === "strchive" ? (
            <StrchiveView />
          ) : (
            <>
              <FilterBar ignored={data?.ignored_filters ?? []} />
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
            </>
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

export function Workspace({ initial }: { initial?: ViewFilters }) {
  return (
    <ViewProvider initial={initial}>
      <WorkspaceInner />
    </ViewProvider>
  );
}
