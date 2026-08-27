"use client";

import { useEffect, useMemo, useState } from "react";

import { CopyEstimate, CopyNumberRange } from "@/components/CopyNumberRange";
import { NoveltyBadge, PlatformAgreement } from "@/components/NoveltyBadge";
import { fetchStrchiveLoci, fetchStrchiveMatches, fetchStrchiveSummary } from "@/lib/api";
import { formatPos, shortMotif } from "@/lib/palette";
import {
  ALLELE_COLORS,
  cleanProse,
  EVIDENCE_ORDER,
  formatCopies,
  sharedCopyMax,
  splitList,
} from "@/lib/strchive";
import {
  STRCHIVE_STATUS_LABELS,
  type StrchiveLocus,
  type StrchiveLociResponse,
  type StrchiveMatchesResponse,
  type StrchiveSummary,
} from "@/lib/types";
import { useView } from "@/lib/viewStore";

/**
 * The disease-locus surface.
 *
 * Two things live here and they must not be confused with each other:
 *
 *   1. STRchive itself — 82 curated loci where a tandem repeat is known to cause
 *      human disease. Reference knowledge. Always present.
 *   2. Our cohort screened against it. A result. Absent until the pipeline's
 *      STRchive step has been run, and the page says so plainly rather than
 *      rendering an empty table that looks like a negative finding.
 *
 * The page leads with the eleven loci whose *pathogenic* motif is absent from
 * hg38, because that is this project's own argument made by an independent
 * curator: a genotyper reading a reference-derived catalog cannot see those
 * repeats at all.
 */

function Stat({
  value,
  label,
  note,
  accent,
}: {
  value: string;
  label: string;
  note?: string;
  accent?: boolean;
}) {
  return (
    <div className="min-w-0">
      <div
        className="tabular text-2xl leading-none font-semibold"
        style={{ color: accent ? "var(--novel)" : "var(--ink)" }}
      >
        {value}
      </div>
      <div className="mt-1 text-xs text-ink">{label}</div>
      {note && <div className="mt-0.5 text-[11px] leading-relaxed text-ink-muted">{note}</div>}
    </div>
  );
}

/** Motifs at a locus, grouped by what STRchive says they do. */
function MotifClasses({ locus }: { locus: StrchiveLocus }) {
  const groups = [
    { label: "Pathogenic", motifs: splitList(locus.pathogenic_motif), color: "var(--pathogenic)" },
    { label: "Reference", motifs: splitList(locus.reference_motif), color: "var(--ink-secondary)" },
    { label: "Benign", motifs: splitList(locus.benign_motif), color: "var(--benign)" },
    { label: "Unknown", motifs: splitList(locus.unknown_motif), color: "var(--allele-unknown)" },
    {
      label: "Interruption",
      motifs: splitList(locus.interruption_motif),
      color: "var(--allele-unknown)",
    },
  ].filter((group) => group.motifs.length > 0);

  return (
    <div className="flex flex-wrap gap-x-5 gap-y-2">
      {groups.map((group) => (
        <div key={group.label} className="min-w-0">
          <div className="text-[10px] uppercase tracking-wide text-ink-muted">{group.label}</div>
          <div className="mt-0.5 flex flex-wrap gap-1">
            {group.motifs.map((motif) => (
              <span
                key={motif}
                className="tabular rounded-sm px-1.5 py-0.5 text-[11px]"
                style={{ background: "var(--surface-raised)", color: group.color }}
              >
                {shortMotif(motif, 14)}
              </span>
            ))}
          </div>
        </div>
      ))}
    </div>
  );
}

/**
 * The eleven. A pathogenic motif that is not in the reference, shown as the
 * substitution it is: what hg38 has here, and what actually causes disease.
 */
function NovelInReference({ loci }: { loci: StrchiveLocus[] }) {
  const { focusStrchive } = useView();
  if (loci.length === 0) return null;

  return (
    <section aria-labelledby="novel-ref-heading" className="space-y-3">
      <div>
        <h3 id="novel-ref-heading" className="text-sm font-medium text-ink">
          Disease loci whose pathogenic motif is not in the reference
        </h3>
        <p className="mt-1 max-w-2xl text-xs leading-relaxed text-ink-secondary">
          STRchive curates this independently of us, and it is the same question the
          novelty screen asks. At these {loci.length} loci the repeat that causes
          disease does not exist in hg38 — so a genotyper working from a
          reference-derived catalog has no locus to genotype. Seven are the FAME
          family, where a pathogenic <span className="tabular">TTTCA</span> is
          inserted into a reference <span className="tabular">TTTTA</span> array:
          an insertion carrying a motif the reference has never seen, which is
          precisely the shape this pipeline detects.
        </p>
      </div>

      <ul className="grid gap-2 sm:grid-cols-2">
        {loci.map((locus) => {
          const reference = splitList(locus.reference_motif)[0] ?? "—";
          const pathogenic = splitList(locus.pathogenic_motif);
          return (
            <li key={locus.id}>
              <button
                type="button"
                onClick={() => focusStrchive(locus.id)}
                className="w-full rounded-lg border border-hairline bg-surface px-3 py-2.5 text-left transition-colors hover:bg-surface-raised focus-visible:outline-2 focus-visible:-outline-offset-2 focus-visible:outline-[var(--motif-1)]"
              >
                <div className="flex items-baseline justify-between gap-2">
                  <span className="truncate text-xs font-medium text-ink">{locus.gene}</span>
                  <span className="shrink-0 text-[10px] text-ink-muted">{locus.evidence}</span>
                </div>
                <div className="mt-1.5 flex flex-wrap items-center gap-1.5 text-[11px]">
                  <span
                    className="tabular rounded-sm px-1.5 py-0.5"
                    style={{ background: "var(--known-soft)", color: "var(--ink-secondary)" }}
                  >
                    {reference}
                  </span>
                  <span className="text-ink-muted">→</span>
                  {pathogenic.map((motif) => (
                    <span
                      key={motif}
                      className="tabular rounded-sm px-1.5 py-0.5 font-medium"
                      style={{ background: "var(--novel-soft)", color: "var(--novel)" }}
                    >
                      {motif}
                    </span>
                  ))}
                </div>
                <div className="mt-1 truncate text-[11px] text-ink-muted">{locus.disease}</div>
              </button>
            </li>
          );
        })}
      </ul>
    </section>
  );
}

/** Our candidates that landed on a disease locus — or why there are none. */
function ScreenResults({
  matches,
  summary,
}: {
  matches: StrchiveMatchesResponse | null;
  summary: StrchiveSummary | null;
}) {
  const screen = summary?.screen;

  return (
    <section aria-labelledby="screen-heading" className="space-y-3">
      <h3 id="screen-heading" className="text-sm font-medium text-ink">
        This cohort, screened against STRchive
      </h3>

      {!matches?.available ? (
        <div className="rounded-lg border border-dashed border-hairline bg-surface p-4">
          <p className="text-xs text-ink">No screened callset registered yet.</p>
          <p className="mt-1.5 max-w-2xl text-[11px] leading-relaxed text-ink-muted">
            {matches?.note ??
              "Run the novelty screen and `strchive annotate`, then point data/web/strchive-calls.yaml at the output."}{" "}
            The manifest is already committed and the backend reports the dataset
            as unavailable rather than failing, so this section fills in on its own
            once the pipeline step lands.
          </p>
        </div>
      ) : matches.total === 0 ? (
        <div className="rounded-lg border border-hairline bg-surface p-4">
          <p className="text-xs text-ink">
            No candidate landed on a disease locus
            {screen ? (
              <>
                {" "}
                — <span className="tabular">{screen.n_rows.toLocaleString("en-US")}</span> calls
                across <span className="tabular">{screen.n_loci.toLocaleString("en-US")}</span>{" "}
                loci, all <span className="tabular">no_locus_match</span>.
              </>
            ) : (
              "."
            )}
          </p>
          <p className="mt-1.5 max-w-2xl text-[11px] leading-relaxed text-ink-muted">
            This is the expected result, not a failure: 82 disease loci in 3 Gb makes
            the base rate essentially zero. Before reading anything into it, check how
            far off the nearest call was
            {screen?.nearest_hit_bp != null && (
              <>
                {" "}
                (<span className="tabular">
                  {screen.nearest_hit_bp.toLocaleString("en-US")} bp
                </span>)
              </>
            )}
            , and check that the coordinates are the build the screen assumed — a wrong
            build shifts every locus by megabases and returns a clean, confident,
            entirely wrong set of misses.
          </p>
        </div>
      ) : (
        <ul className="space-y-2">
          {matches.matches.map((match) => (
            <li
              key={`${match.SVID}-${match.sample}-${match.strchive_id}`}
              className="rounded-lg border border-hairline bg-surface p-3"
            >
              <div className="flex flex-wrap items-center gap-2">
                <span className="tabular text-xs text-ink">
                  {formatPos(match.chrom, match.ins_coord)}
                </span>
                <NoveltyBadge status={match.novelty} />
                <PlatformAgreement
                  ucsc={match.ucsc_novelty ?? undefined}
                  trexplorer={match.trexplorer_novelty ?? undefined}
                />
                <span
                  className="rounded-sm px-1.5 py-0.5 text-[10px] font-medium"
                  style={{
                    background: "var(--novel-soft)",
                    color: "var(--novel)",
                  }}
                >
                  {STRCHIVE_STATUS_LABELS[match.strchive_status]}
                </span>
                <span className="text-[11px] text-ink-secondary">
                  {match.strchive_gene} · {match.strchive_disease}
                </span>
                <span className="tabular ml-auto text-[11px] text-ink-muted">
                  {match.strchive_distance_bp ?? "—"} bp away
                </span>
              </div>
              <div className="mt-2">
                <CopyEstimate
                  refCopies={match.strchive_ref_copies}
                  repUnits={match.rep_units}
                  estCopies={match.strchive_est_copies}
                  alleleClass={match.strchive_allele_class}
                />
              </div>
            </li>
          ))}
        </ul>
      )}
    </section>
  );
}

/** One disease locus, opened. */
function LocusDetail({ locus, onBack }: { locus: StrchiveLocus; onBack: () => void }) {
  const tags = splitList(locus.locus_tags);
  const omim = splitList(locus.omim);

  return (
    <section aria-labelledby="strchive-locus-heading" className="space-y-4">
      <button
        type="button"
        onClick={onBack}
        className="text-xs text-ink-secondary transition-colors hover:text-ink"
      >
        ← All disease loci
      </button>

      <header className="space-y-2">
        <div className="flex flex-wrap items-center gap-2">
          <h3 id="strchive-locus-heading" className="text-base font-medium text-ink">
            {locus.gene}
          </h3>
          <span className="tabular text-xs text-ink-muted">
            {formatPos(locus.chrom, locus.start_hg38 ?? 0)}–
            {(locus.stop_hg38 ?? 0).toLocaleString("en-US")} (hg38)
          </span>
          {locus.novel_in_reference && (
            <span
              className="rounded-sm px-1.5 py-0.5 text-[11px] font-medium"
              style={{ background: "var(--novel-soft)", color: "var(--novel)" }}
              title="STRchive records the pathogenic motif as absent from hg38."
            >
              Pathogenic motif not in hg38
            </span>
          )}
        </div>
        <p className="text-sm text-ink">{locus.disease}</p>
        {locus.disease_description && (
          <p className="max-w-2xl text-xs leading-relaxed text-ink-secondary">
            {cleanProse(locus.disease_description)}
          </p>
        )}
      </header>

      <dl className="grid grid-cols-2 gap-x-6 gap-y-2 sm:grid-cols-4">
        {[
          ["Evidence", locus.evidence || "—"],
          ["Inheritance", splitList(locus.inheritance).join(", ") || "—"],
          ["In gene", locus.location_in_gene || "—"],
          ["Motif length", locus.motif_len != null ? `${locus.motif_len} bp` : "—"],
        ].map(([label, value]) => (
          <div key={label} className="min-w-0">
            <dt className="text-[11px] uppercase tracking-wide text-ink-muted">{label}</dt>
            <dd className="truncate text-sm text-ink">{value}</dd>
          </div>
        ))}
      </dl>

      <div className="rounded-lg border border-hairline bg-surface p-4">
        <h4 className="text-xs font-medium text-ink">Allele size ranges</h4>
        <p className="mt-1 mb-6 text-[11px] text-ink-muted">
          Copy number, log scale. This is the axis a candidate insertion is placed on.
        </p>
        <CopyNumberRange locus={locus} />
      </div>

      <div className="rounded-lg border border-hairline bg-surface p-4">
        <h4 className="mb-3 text-xs font-medium text-ink">Motifs recorded here</h4>
        <MotifClasses locus={locus} />
        {locus.novel_in_reference && (
          <p className="mt-3 max-w-2xl text-[11px] leading-relaxed text-ink-muted">
            The pathogenic and reference motifs differ, and STRchive records the
            pathogenic one as absent from hg38 — which is why this locus is invisible
            to a reference-catalog genotyper and why an insertion-derived call can see
            it.
          </p>
        )}
      </div>

      {(tags.length > 0 || locus.age_onset || locus.mechanism) && (
        <div className="rounded-lg border border-hairline bg-surface p-4 space-y-3">
          {locus.mechanism && (
            <div>
              <div className="text-[10px] uppercase tracking-wide text-ink-muted">Mechanism</div>
              <p className="text-xs text-ink-secondary">{cleanProse(locus.mechanism)}</p>
            </div>
          )}
          {locus.age_onset && (
            <div>
              <div className="text-[10px] uppercase tracking-wide text-ink-muted">
                Age of onset
              </div>
              <p className="text-xs text-ink-secondary">{cleanProse(locus.age_onset)}</p>
            </div>
          )}
          {tags.length > 0 && (
            <div>
              <div className="mb-1 text-[10px] uppercase tracking-wide text-ink-muted">
                Locus behaviour
              </div>
              <div className="flex flex-wrap gap-1">
                {tags.map((tag) => (
                  <span
                    key={tag}
                    className="rounded-full px-2 py-0.5 text-[10px] text-ink-secondary"
                    style={{ background: "var(--surface-raised)" }}
                  >
                    {tag.replace(/_/g, " ")}
                  </span>
                ))}
              </div>
            </div>
          )}
        </div>
      )}

      <div className="flex flex-wrap items-center gap-x-4 gap-y-1 text-[11px]">
        <a
          href={`https://strchive.org/loci/${locus.id}`}
          target="_blank"
          rel="noreferrer noopener"
          className="text-ink-secondary underline underline-offset-2 hover:text-ink"
        >
          STRchive
        </a>
        {omim.map((id) => (
          <a
            key={id}
            href={`https://omim.org/entry/${id}`}
            target="_blank"
            rel="noreferrer noopener"
            className="text-ink-secondary underline underline-offset-2 hover:text-ink"
          >
            OMIM {id}
          </a>
        ))}
        <span className="tabular text-ink-muted">{locus.catalog_version}</span>
      </div>
    </section>
  );
}

export function StrchiveView() {
  const { filters, focusStrchive, patch } = useView();
  const [summary, setSummary] = useState<StrchiveSummary | null>(null);
  const [data, setData] = useState<StrchiveLociResponse | null>(null);
  const [matches, setMatches] = useState<StrchiveMatchesResponse | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [query, setQuery] = useState("");

  const novelOnly = Boolean(filters.strchive_novel_only);

  useEffect(() => {
    const controller = new AbortController();
    Promise.all([
      fetchStrchiveSummary(controller.signal),
      fetchStrchiveMatches(controller.signal),
    ])
      .then(([s, m]) => {
        setSummary(s);
        setMatches(m);
        setError(null);
      })
      .catch((err: Error) => {
        if (err.name !== "AbortError") setError(err.message);
      });
    return () => controller.abort();
  }, []);

  useEffect(() => {
    const controller = new AbortController();
    fetchStrchiveLoci({ novel_in_reference: novelOnly, q: query || undefined }, controller.signal)
      .then((response) => {
        setData(response);
        setError(null);
      })
      .catch((err: Error) => {
        if (err.name !== "AbortError") setError(err.message);
      });
    return () => controller.abort();
  }, [novelOnly, query]);

  const focused = useMemo(
    () => data?.loci.find((locus) => locus.id === filters.focus_strchive_id) ?? null,
    [data, filters.focus_strchive_id],
  );
  const novelLoci = useMemo(
    () => (data?.loci ?? []).filter((locus) => locus.novel_in_reference),
    [data],
  );
  // One domain for every row in the list — see sharedCopyMax.
  const listMax = useMemo(() => sharedCopyMax(data?.loci ?? []), [data]);

  if (error) {
    return (
      <div className="rounded-lg border border-hairline bg-surface p-6">
        <p className="text-sm text-ink">The disease-locus catalog is not loaded.</p>
        <p className="mt-1 text-xs text-ink-muted">{error}</p>
        <p className="tabular mt-3 text-xs text-ink-secondary">
          cd backend &amp;&amp; uv run python scripts/fetch_strchive.py
        </p>
      </div>
    );
  }

  if (!summary || !data) {
    return (
      <div className="rounded-lg border border-hairline bg-surface p-6 text-sm text-ink-muted">
        Loading the disease-locus catalog…
      </div>
    );
  }

  if (focused) {
    return (
      <div className="min-h-0 flex-1 overflow-y-auto pr-1">
        <LocusDetail locus={focused} onBack={() => focusStrchive(null)} />
      </div>
    );
  }

  return (
    <div className="min-h-0 flex-1 space-y-7 overflow-y-auto pr-1">
      <header className="space-y-3">
        <div>
          <h2 className="text-sm font-medium text-ink">Known repeat-expansion disease loci</h2>
          <p className="mt-1 max-w-2xl text-xs leading-relaxed text-ink-secondary">
            Curated by STRchive. This is reference knowledge, not a result from this
            cohort — the table our candidates are compared against.
          </p>
        </div>
        <div className="grid grid-cols-2 gap-6 sm:grid-cols-4">
          <Stat value={String(summary.n_loci)} label="Disease loci" note="Curated, hg38" />
          <Stat
            value={String(summary.n_novel_in_reference)}
            label="Pathogenic motif not in hg38"
            note="Invisible to a reference-catalog genotyper"
            accent
          />
          <Stat
            value={String(summary.n_without_ref_copies)}
            label="No reference copy count"
            note="No copy-number estimate is possible"
          />
          <Stat
            value={summary.by_evidence.find((row) => row.evidence === "Definitive")?.n.toString() ?? "—"}
            label="Definitive evidence"
            note="Weight conclusions by tier"
          />
        </div>
      </header>

      <NovelInReference loci={novelLoci} />

      <ScreenResults matches={matches} summary={summary} />

      <section aria-labelledby="all-loci-heading" className="space-y-3">
        <div className="flex flex-wrap items-center justify-between gap-3">
          <h3 id="all-loci-heading" className="text-sm font-medium text-ink">
            All loci{" "}
            <span className="tabular font-normal text-ink-muted">
              {data.returned} of {data.total}
            </span>
          </h3>
          <div className="flex items-center gap-2">
            <input
              type="search"
              value={query}
              onChange={(event) => setQuery(event.target.value)}
              placeholder="Gene or disease…"
              aria-label="Search disease loci"
              className="rounded-full border border-hairline bg-surface px-3 py-1 text-xs text-ink placeholder:text-ink-muted focus:border-baseline focus:outline-none"
            />
            <button
              type="button"
              onClick={() => patch({ strchive_novel_only: !novelOnly })}
              className="rounded-full border px-2.5 py-1 text-xs transition-colors"
              style={{
                borderColor: novelOnly ? "var(--novel)" : "var(--hairline)",
                color: novelOnly ? "var(--novel)" : "var(--ink-secondary)",
              }}
            >
              Not in reference
            </button>
          </div>
        </div>

        <div className="overflow-hidden rounded-lg border border-hairline bg-surface">
          {data.loci.length === 0 ? (
            <p className="p-6 text-sm text-ink-muted">No loci match.</p>
          ) : (
            <ul className="divide-y divide-hairline">
              {data.loci.map((locus) => (
                <li key={locus.id}>
                  <button
                    type="button"
                    onClick={() => focusStrchive(locus.id)}
                    className="grid w-full grid-cols-[minmax(7rem,1fr)_minmax(0,1.4fr)_minmax(8rem,1fr)_auto] items-center gap-4 px-3 py-2 text-left transition-colors hover:bg-surface-raised focus-visible:outline-2 focus-visible:-outline-offset-2 focus-visible:outline-[var(--motif-1)]"
                  >
                    <div className="min-w-0">
                      <div className="flex items-center gap-1.5">
                        <span className="truncate text-xs text-ink">{locus.gene}</span>
                        {locus.novel_in_reference && (
                          <span
                            className="h-1.5 w-1.5 shrink-0 rounded-full"
                            style={{ background: "var(--novel)" }}
                            title="Pathogenic motif absent from hg38"
                          />
                        )}
                      </div>
                      <div className="tabular truncate text-[11px] text-ink-muted">
                        {splitList(locus.pathogenic_motif)[0] ??
                          splitList(locus.reference_motif)[0] ??
                          "—"}{" "}
                        · {locus.motif_len ?? "?"} bp
                      </div>
                    </div>

                    <div className="min-w-0">
                      <div className="truncate text-[11px] text-ink-secondary">
                        {locus.disease}
                      </div>
                      <div className="truncate text-[10px] text-ink-muted">
                        {locus.evidence} · {splitList(locus.inheritance).join(", ")}
                      </div>
                    </div>

                    <div className="min-w-0">
                      <CopyNumberRange locus={locus} dense height={10} scaleMax={listMax} />
                    </div>

                    <div className="tabular text-right text-[11px] text-ink-muted">
                      {locus.pathogenic_min != null ? (
                        <>
                          <span style={{ color: "var(--pathogenic)" }}>
                            ≥{formatCopies(locus.pathogenic_min)}
                          </span>
                          <div className="text-ink-muted">copies</div>
                        </>
                      ) : (
                        "—"
                      )}
                    </div>
                  </button>
                </li>
              ))}
            </ul>
          )}
        </div>

        <div className="flex flex-wrap items-center gap-x-4 gap-y-1 text-[11px] text-ink-secondary">
          <span className="text-ink-muted">Allele class:</span>
          {(["benign", "intermediate", "pathogenic"] as const).map((key) => (
            <span key={key} className="flex items-center gap-1.5">
              <span
                className="inline-block h-2.5 w-2.5 rounded-sm"
                style={{ background: ALLELE_COLORS[key] }}
              />
              {key}
            </span>
          ))}
          <span className="text-ink-muted">
            shared log axis, 0–{listMax.toLocaleString("en-US")} copies
          </span>
          <span className="tabular ml-auto text-ink-muted">{summary.catalog_version}</span>
        </div>
      </section>

      <section aria-labelledby="evidence-heading" className="space-y-2 pb-4">
        <h3 id="evidence-heading" className="text-sm font-medium text-ink">
          Curation confidence
        </h3>
        <p className="max-w-2xl text-xs leading-relaxed text-ink-secondary">
          Not every locus is equally established. Three are disputed and one is refuted;
          a hit at a Limited-evidence locus is a lead, not a diagnosis.
        </p>
        <ul className="space-y-1.5">
          {EVIDENCE_ORDER.filter((tier) =>
            summary.by_evidence.some((row) => row.evidence === tier),
          ).map((tier) => {
            const row = summary.by_evidence.find((entry) => entry.evidence === tier)!;
            const max = Math.max(...summary.by_evidence.map((entry) => entry.n), 1);
            return (
              <li key={tier} className="space-y-1">
                <div className="flex items-baseline justify-between gap-2 text-xs">
                  <span className="text-ink-secondary">{tier}</span>
                  <span className="tabular text-ink-muted">
                    {row.novel > 0 && (
                      <span style={{ color: "var(--novel)" }}>{row.novel} not in ref · </span>
                    )}
                    {row.n}
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
            );
          })}
        </ul>
      </section>
    </div>
  );
}
