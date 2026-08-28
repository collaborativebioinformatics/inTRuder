"use client";

import Link from "next/link";
import { useCallback, useEffect, useState } from "react";

import { CatalogView } from "@/components/CatalogView";
import { Chat } from "@/components/Chat";
import { ClassBreakdown } from "@/components/ClassBreakdown";
import { DatasetsView } from "@/components/DatasetsView";
import { FilterBar } from "@/components/FilterBar";
import { Funnel } from "@/components/Funnel";
import { Inspector, type Selection } from "@/components/Inspector";
import { LocusView } from "@/components/LocusView";
import { PresentationView } from "@/components/PresentationView";
import { StrchiveView } from "@/components/StrchiveView";
import { ThemeToggle } from "@/components/ThemeToggle";
import { UploadDialog } from "@/components/UploadDialog";
import {
  ApiError,
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
  UploadListing,
  ViewFilters,
} from "@/lib/types";
import { useWindowFileDrop } from "@/lib/useFileDrop";
import { fetchUploads } from "@/lib/uploads";
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

/** Left rail on the datasets surface — where the data lives and how to add more. */
function DatasetsRail({
  listing,
  health,
}: {
  listing: UploadListing | null;
  health: Health | null;
}) {
  const unavailable = health?.datasets.unavailable ?? [];
  const disabled = health?.datasets.disabled ?? [];

  return (
    <div className="space-y-6">
      <section className="space-y-2">
        <h2 className="text-sm font-medium text-ink">Where data comes from</h2>
        <p className="text-[11px] leading-relaxed text-ink-secondary">
          Every table is one YAML manifest describing a file on this machine.
          Adding data is a manifest, never a code change — and the prose in it is
          what the assistant reads when deciding whether a table can answer a
          question.
        </p>
        <p className="text-[11px] leading-relaxed text-ink-muted">
          Uploading writes both: the file into the data directory, and a manifest
          beside the hand-written ones. Nothing is sent anywhere — the backend is
          running on this machine.
        </p>
      </section>

      {unavailable.length > 0 && (
        <section className="space-y-2">
          <h2 className="text-sm font-medium text-ink">Not loaded</h2>
          <p className="text-[11px] leading-relaxed text-ink-muted">
            These manifests are committed ahead of the data they describe. A
            missing file is reported rather than crashing the backend.
          </p>
          <ul className="space-y-1.5">
            {unavailable.map((row) => (
              <li key={row.name} className="space-y-0.5">
                <span className="tabular text-[11px] text-ink-secondary">{row.name}</span>
                {/* A filesystem path has nothing to wrap on, and the rail is
                    19rem — without break-all it runs off the edge. */}
                <p className="break-all text-[11px] leading-relaxed text-ink-muted">
                  {row.error}
                </p>
              </li>
            ))}
          </ul>
        </section>
      )}

      {disabled.length > 0 && (
        <section className="space-y-2">
          <h2 className="text-sm font-medium text-ink">Switched off</h2>
          <p className="text-[11px] leading-relaxed text-ink-muted">
            No page draws these and the assistant is never told they exist. The
            demo fixtures do this to themselves once real data is driving a
            surface; every switch is yours to move, and yours alone — they live
            in this browser.
          </p>
          <ul className="space-y-0.5">
            {disabled.map((name) => (
              <li key={name} className="tabular text-[11px] text-ink-secondary">
                {name}
              </li>
            ))}
          </ul>
        </section>
      )}

      {listing && !listing.enabled && (
        <p className="text-[11px] leading-relaxed" style={{ color: "var(--novel)" }}>
          Uploads are turned off on this server (UPLOADS_ENABLED).
        </p>
      )}
    </div>
  );
}

const TABS: { page: PageName; href: string; label: string }[] = [
  { page: "catalog", href: "/", label: "Candidate loci" },
  { page: "strchive", href: "/strchive", label: "Disease loci" },
  // Nouns, like its neighbours: each tab names the data you are looking at.
  // Uploading is the verb, and it lives on the right as a control rather than
  // as a place you navigate to.
  { page: "datasets", href: "/datasets", label: "Datasets" },
  // Last, and the odd one out: not a view of the data but the write-up of what
  // the data showed. It sits in the same row because during a talk it is one of
  // the places you switch to, and a link somewhere else is a link nobody finds.
  { page: "presentation", href: "/presentation", label: "Hackathon Presentation" },
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
  // Kept as the Error rather than its message: a 503 the API answered and a
  // network failure need different advice, and only the object knows which.
  const [error, setError] = useState<Error | null>(null);
  // The block pinned out of a barcode. Deliberately not part of the view store:
  // it is what one person clicked, not a description of the data on screen, so
  // the agent has no business setting it and it does not belong in a URL.
  const [selection, setSelection] = useState<Selection | null>(null);

  // Uploads. `dropped` is the file that opened the dialog, and it is set to null
  // on close so dropping the same file again is a new upload rather than a
  // no-op. `registryVersion` is bumped whenever the server's data changed, which
  // is what re-runs the fetches below — a newly registered locus table changes
  // every number on the page.
  const [listing, setListing] = useState<UploadListing | null>(null);
  const [uploadOpen, setUploadOpen] = useState(false);
  const [dropped, setDropped] = useState<File | null>(null);
  const [registryVersion, setRegistryVersion] = useState(0);

  const page = filters.page ?? "catalog";

  const openUpload = useCallback((file?: File) => {
    setDropped(file ?? null);
    setUploadOpen(true);
  }, []);

  const onRegistryChanged = useCallback(() => setRegistryVersion((n) => n + 1), []);

  // Dragging a file anywhere over the window arms the upload, which is what
  // everyone tries first. The dialog opens already uploading.
  const dragging = useWindowFileDrop(openUpload, listing?.enabled ?? true);

  useEffect(() => {
    const controller = new AbortController();
    // Three independent fetches, deliberately not gathered into one Promise.all.
    // The cohort summary fails outright when no table holds `role: loci` — which
    // is a state you can reach by switching the locus tables off — and a
    // combined promise would take health down with it, freezing the very page
    // that shows you which switch to put back.
    fetchSummary(controller.signal)
      .then((s) => {
        setSummary(s);
        setError(null);
      })
      .catch((err: Error) => {
        if (err.name === "AbortError") return;
        setSummary(null);
        setError(err);
      });
    fetchHealth(controller.signal)
      .then(setHealth)
      .catch(() => undefined);
    // The disease catalog is independent of the cohort tables, so a missing
    // callset must not stop it loading — and vice versa.
    fetchStrchiveSummary(controller.signal)
      .then(setStrchive)
      .catch(() => setStrchive(null));
    return () => controller.abort();
  }, [registryVersion]);

  useEffect(() => {
    const controller = new AbortController();
    fetchUploads(controller.signal)
      .then(setListing)
      // An older backend has no /api/uploads. The rest of the page is unaffected,
      // so this stays null and the Upload control simply does not appear.
      .catch(() => setListing(null));
    return () => controller.abort();
  }, [registryVersion]);

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
        if (err.name === "AbortError") return;
        // Dropped rather than left on screen: rows fetched under different
        // filters, or from a table that has since been switched off, are not an
        // answer to the request that just failed.
        setData(null);
        setError(err);
      })
      .finally(() => setLoading(false));
    return () => controller.abort();
  }, [filters, page, registryVersion]);

  const focused = filters.focus_locus_id;

  // A block belongs to the locus it was pinned from; keeping it while the page
  // moves to another one would leave a panel of numbers about somewhere else.
  useEffect(() => setSelection(null), [focused]);

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
              title={
                summary.synthetic_tables.length === 1
                  ? `${summary.synthetic_tables[0]} is a generated fixture, not a real callset.`
                  : `${summary.synthetic_tables.join(" and ")} are generated fixtures, not a real callset.`
              }
            >
              {/* Named rather than blanket, because a real locus table drawn
                  with fixture barcodes is half of each, and a badge that
                  overclaims is one people learn to ignore. */}
              {summary.synthetic_tables.length === 1 &&
              summary.synthetic_tables[0].endsWith("segments")
                ? "Synthetic barcodes"
                : "Synthetic demo data"}
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
          {/* The only verb in this header, so it is deliberately not shaped like
              a nav pill. It is also deliberately not filled with --novel: that
              warm colour is the novelty encoding the whole catalog is read
              through, and spending it on a button would put the loudest thing on
              the page on a control rather than on a finding. */}
          {listing?.enabled !== false && (
            <button
              type="button"
              onClick={() => openUpload()}
              title="Add a callset, a locus table, or a VCF."
              className="flex items-center gap-1.5 rounded-md border border-hairline px-2.5 py-1 text-[11px] text-ink-secondary transition-colors hover:border-baseline hover:text-ink"
              style={{ background: "var(--surface-raised)" }}
            >
              <svg
                width="11"
                height="11"
                viewBox="0 0 12 12"
                fill="none"
                stroke="currentColor"
                strokeWidth="1.4"
                strokeLinecap="round"
                strokeLinejoin="round"
                aria-hidden="true"
              >
                <path d="M6 8.5V1.8M3.4 4.4 6 1.8l2.6 2.6M1.8 8.5v1.2a.5.5 0 0 0 .5.5h7.4a.5.5 0 0 0 .5-.5V8.5" />
              </svg>
              Upload
            </button>
          )}
          <ThemeToggle />
        </div>
      </header>

      {/* A 503 is the API answering, and it answers with a reason — most often
          that no table holds `role: loci`, which is a switch away from being
          fixed. Telling someone to start a server that is plainly running would
          send them looking in the wrong place, so the two cases read
          differently and the server's own sentence is the one shown. */}
      {error && page === "catalog" && (
        <div
          className="shrink-0 px-4 py-2 text-xs"
          style={{ background: "var(--novel-soft)", color: "var(--novel)" }}
        >
          {error instanceof ApiError ? (
            <>Nothing to draw — {error.message}</>
          ) : (
            <>
              Cannot reach the API — {error.message}. Start it with:{" "}
              <span className="tabular">
                cd backend &amp;&amp; uv run uvicorn app.main:app --reload
              </span>
            </>
          )}
        </div>
      )}

      {/* The presentation is a document, not a workspace surface: no cohort rail
          to orient it and nothing for the assistant to query, so it gets the whole
          width and one scroll of its own. */}
      {page === "presentation" ? (
        <main className="scroll-quiet min-h-0 flex-1 overflow-y-auto">
          <PresentationView />
        </main>
      ) : (
        <div className="grid min-h-0 flex-1 grid-cols-1 lg:grid-cols-[19rem_minmax(0,1fr)_22rem]">
          <aside className="scroll-quiet min-h-0 space-y-6 overflow-y-auto border-hairline p-4 lg:border-r">
            {/* The pinned block goes at the top of the rail, above the cohort
                context: it is the most recent thing the reader asked for, and the
                rail is the one column that never moves under them. */}
            {page === "catalog" && selection && (
              <Inspector selection={selection} onClear={() => setSelection(null)} />
            )}
            {page === "datasets" ? (
              <DatasetsRail listing={listing} health={health} />
            ) : page === "strchive" ? (
              <StrchiveRail summary={strchive} />
            ) : summary ? (
              <>
                <Funnel stages={summary.funnel} />
                <ClassBreakdown summary={summary} />
              </>
            ) : error ? (
              // The banner above already says what happened. Saying "loading"
              // under it would be the page insisting on something it has been told
              // is not true.
              <p className="text-sm text-ink-muted">No cohort to summarize.</p>
            ) : (
              <p className="text-sm text-ink-muted">Loading summary…</p>
            )}
          </aside>

          {/* Drilled into one locus, the middle column becomes a single scroll:
              the detail page is taller than the viewport and the reference band
              pins itself to the top of it (see LocusView). The catalog keeps its
              own inner scroll instead, so its header and filter row stay put
              while only the list of loci moves.

              The scrolling variant carries no top padding. Sticky offsets are
              measured from the scrollport's *content* box, so a padded column
              pins the band 16px down and leaves a gap for allele rows to show
              through as they scroll past. The padding moves inside the scroll
              content instead, where it scrolls away like everything else. */}
          <main
            className={
              page === "catalog" && focused
                ? "scroll-quiet min-h-0 overflow-y-auto px-4 pb-4"
                : "flex min-h-0 flex-col gap-3 p-4"
            }
          >
            {page === "datasets" ? (
              <DatasetsView
                listing={listing}
                onUpload={openUpload}
                onChanged={onRegistryChanged}
              />
            ) : page === "strchive" ? (
              <StrchiveView />
            ) : focused ? (
              <div className="space-y-3 pt-4">
                <FilterBar ignored={data?.ignored_filters ?? []} />
                <LocusView
                  locusId={focused}
                  selection={selection}
                  onSelect={setSelection}
                  cohortSize={summary?.cohort_size}
                />
              </div>
            ) : error instanceof ApiError && !data ? (
              // Drawing the filter row and an empty list here would read as "your
              // filters matched nothing" — the wrong diagnosis, and one that sends
              // the reader clearing controls that were never the problem. The
              // banner above carries the real reason.
              <p className="pt-4 text-sm text-ink-muted">
                Switch a locus table back on from the Datasets page, or add one.
              </p>
            ) : (
              <>
                <FilterBar ignored={data?.ignored_filters ?? []} />
                <CatalogView
                  loci={data?.loci ?? []}
                  strips={data?.strips ?? {}}
                  total={data?.total ?? 0}
                  loading={loading}
                  sort={data?.sort}
                  cohortSize={summary?.cohort_size}
                />
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
      )}

      {/* Drawn over everything while a file is in flight over the window, so the
          page says it will accept the drop before you let go. Pointer events off:
          it must not become the drop target itself, or the event would land on an
          overlay that appeared mid-drag. */}
      {dragging && !uploadOpen && (
        <div
          aria-hidden="true"
          className="pointer-events-none fixed inset-0 z-50 flex items-center justify-center"
          style={{ background: "color-mix(in srgb, var(--plane) 82%, transparent)" }}
        >
          <div
            className="rounded-xl border border-dashed px-8 py-6 text-sm text-ink"
            style={{ borderColor: "var(--baseline)", background: "var(--surface)" }}
          >
            Drop to upload
          </div>
        </div>
      )}

      <UploadDialog
        open={uploadOpen}
        onClose={() => {
          setUploadOpen(false);
          setDropped(null);
        }}
        initialFile={dropped}
        listing={listing}
        onChanged={onRegistryChanged}
      />
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
