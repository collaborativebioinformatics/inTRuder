"use client";

import Link from "next/link";
import { useCallback, useEffect, useRef, useState, type ReactNode } from "react";

import { TEAM, fullName } from "@/lib/team";

/**
 * The write-up surface: what we did and what we found, in the order a reader
 * meets it rather than in the order the pipeline runs.
 *
 * This is a template. Everything result-shaped is a marked slot rather than a
 * number, because the one thing worse than an empty presentation page is one
 * carrying a figure nobody produced — the same rule the synthetic-data badge
 * follows on the catalog. Fill a slot by replacing the <Slot> with prose, a
 * chart, or a screenshot; the surrounding structure is meant to be edited.
 *
 * Topics are the tab row at the top of the document, deliberately its own
 * control rather than another row of workspace nav: those tabs move you between
 * datasets, these move you between sections of one argument.
 */

const TOPICS = [
  { id: "overview", label: "The problem" },
  { id: "approach", label: "Approach" },
  { id: "results", label: "Results" },
  { id: "validation", label: "Validation" },
  { id: "demo", label: "The interface" },
  { id: "team", label: "Team & links" },
] as const;

type TopicId = (typeof TOPICS)[number]["id"];

/* --------------------------------------------------------------------------
   Building blocks. Small on purpose: a section is prose plus slots, and the
   page should stay editable by someone who has never read this file.
   -------------------------------------------------------------------------- */

function Section({
  title,
  kicker,
  children,
}: {
  title: string;
  kicker?: string;
  children: ReactNode;
}) {
  return (
    <section className="space-y-4">
      <header className="space-y-1">
        {kicker && (
          <p className="text-[11px] font-medium uppercase tracking-wider text-ink-muted">
            {kicker}
          </p>
        )}
        <h2 className="text-xl font-semibold tracking-tight text-ink">{title}</h2>
      </header>
      {children}
    </section>
  );
}

function P({ children }: { children: ReactNode }) {
  return <p className="text-[15px] leading-relaxed text-ink-secondary">{children}</p>;
}

/** The opening sentence of a topic — one size up, and the only bold prose. */
function Lede({ children }: { children: ReactNode }) {
  return <p className="text-lg leading-relaxed text-ink">{children}</p>;
}

/**
 * A gap somebody still has to fill. Warm and dashed so it is impossible to
 * mistake for content, and it names what belongs there rather than saying TODO.
 */
function Slot({ what, children }: { what: string; children?: ReactNode }) {
  return (
    <div
      className="rounded-lg border border-dashed px-4 py-3"
      style={{ borderColor: "var(--novel)", background: "var(--novel-soft)" }}
    >
      <p
        className="text-[11px] font-medium uppercase tracking-wider"
        style={{ color: "var(--novel)" }}
      >
        Fill in · {what}
      </p>
      {children && (
        <div className="mt-1.5 text-[13px] leading-relaxed text-ink-secondary">
          {children}
        </div>
      )}
    </div>
  );
}

/** Where a chart or screenshot goes. The caption is the argument; write it first. */
function FigureSlot({ caption, hint }: { caption: string; hint?: string }) {
  return (
    <figure className="space-y-2">
      <div
        className="flex aspect-[16/9] items-center justify-center rounded-lg border border-dashed px-6 text-center"
        style={{ borderColor: "var(--baseline)", background: "var(--surface)" }}
      >
        <span className="text-[13px] leading-relaxed text-ink-muted">
          {hint ?? "Drop a figure here"}
        </span>
      </div>
      <figcaption className="text-[12px] leading-relaxed text-ink-muted">
        {caption}
      </figcaption>
    </figure>
  );
}

/**
 * A headline number. `value` left at its default draws the em dash in the
 * placeholder colour, so an unfilled tile reads as unfilled from across a room.
 */
function Stat({
  value = "—",
  label,
  note,
}: {
  value?: string;
  label: string;
  note?: string;
}) {
  const pending = value === "—";
  return (
    <div
      className="rounded-lg border border-hairline px-3 py-2.5"
      style={{ background: "var(--surface)" }}
    >
      <div
        className="tabular text-2xl leading-tight"
        style={{ color: pending ? "var(--novel)" : "var(--ink)" }}
      >
        {value}
      </div>
      <div className="mt-0.5 text-[12px] text-ink-secondary">{label}</div>
      {note && <div className="mt-0.5 text-[11px] leading-snug text-ink-muted">{note}</div>}
    </div>
  );
}

function StatRow({ children }: { children: ReactNode }) {
  return <div className="grid grid-cols-2 gap-2 sm:grid-cols-4">{children}</div>;
}

/** Numbered stages. The number is the point, so it is drawn, not a list marker. */
function Steps({ items }: { items: { title: string; body: ReactNode }[] }) {
  return (
    <ol className="space-y-3">
      {items.map((item, i) => (
        <li key={item.title} className="flex gap-3">
          <span
            className="tabular mt-0.5 flex h-5 w-5 shrink-0 items-center justify-center rounded-full text-[11px]"
            style={{ background: "var(--surface-raised)", color: "var(--ink-muted)" }}
          >
            {i + 1}
          </span>
          <div className="min-w-0 space-y-1">
            <p className="text-sm font-medium text-ink">{item.title}</p>
            <p className="text-[13px] leading-relaxed text-ink-secondary">{item.body}</p>
          </div>
        </li>
      ))}
    </ol>
  );
}

/** A quiet aside — a caveat, a definition, the thing you say once and move on. */
function Note({ children }: { children: ReactNode }) {
  return (
    <div
      className="rounded-lg border-l-2 py-1 pl-3 text-[13px] leading-relaxed text-ink-secondary"
      style={{ borderColor: "var(--baseline)" }}
    >
      {children}
    </div>
  );
}

function Tool({ href, children }: { href: string; children: ReactNode }) {
  return (
    <a
      href={href}
      target="_blank"
      rel="noreferrer"
      className="underline decoration-dotted underline-offset-2 hover:text-ink"
    >
      {children}
    </a>
  );
}

/* --------------------------------------------------------------------------
   The topics.
   -------------------------------------------------------------------------- */

function Overview() {
  return (
    <div className="space-y-8">
      <Section kicker="The problem" title="Catalogued repeats are the only ones anyone genotypes">
        <Lede>
          Tandem repeat genotypers read from a catalog, and that catalog is built by
          annotating the reference genome — so any repeat that is individual- or
          population-specific is invisible before genotyping even starts.
        </Lede>
        <P>
          Two things can be missing, and they are not the same finding. A{" "}
          <strong className="font-medium text-ink">novel locus</strong> is present in an
          individual and absent from the reference entirely. A{" "}
          <strong className="font-medium text-ink">novel motif</strong> is a locus the
          reference does have, carrying a repeat unit it does not. Collapsing the two
          into one &ldquo;novel&rdquo; flag loses the distinction this project exists to
          draw.
        </P>
        <P>
          Finding either normally means whole-genome assembly, which is a lot of compute
          to spend on surfacing non-reference sequence. We take a cheaper route: long-read
          SV callers already report insertions accurately as a routine part of the
          workflow, and an expanded tandem repeat is, by construction, a repetitive subset
          of those insertions. Scanning the inserted sequence is enough to surface
          candidates — including ones no catalog knows about.
        </P>
      </Section>

      <Section title="What we set out to show">
        <Slot what="the claim of the talk, in one sentence">
          The single thing the audience should still believe tomorrow. Everything below
          is evidence for this sentence, so write it before filling anything else in.
        </Slot>
        <StatRow>
          <Stat value="67" label="HPRC genomes" note="Long-read cohort, joint-called" />
          <Stat label="Candidate loci" note="After purity and coverage filters" />
          <Stat label="Novel to both catalogs" note="UCSC and TRExplorer agree" />
          <Stat label="On a disease locus" note="STRchive intersect" />
        </StatRow>
        <Note>
          Leave a tile as an em dash until the number is real. An unfilled tile is a
          missing slide; an invented one is a retraction.
        </Note>
      </Section>
    </div>
  );
}

function Approach() {
  return (
    <div className="space-y-8">
      <Section kicker="Approach" title="Five stages, each a file in and a file out">
        <Lede>
          Every stage reads a file and writes a file, so any of them can be re-run,
          swapped or checked on its own — and so the pipeline can be driven by Nextflow
          without any step reaching into another&rsquo;s internals.
        </Lede>
        <Steps
          items={[
            {
              title: "Preprocessing (upstream)",
              body: (
                <>
                  Alignment, SNV calling, haplotagging and joint SV calling — minimap2,
                  Clair3, WhatsHap and{" "}
                  <Tool href="https://github.com/fritzsedlazeck/Sniffles">Sniffles2</Tool>.
                  Assumed already done; we start from the multi-sample VCF.
                </>
              ),
            },
            {
              title: "TR detection",
              body: (
                <>
                  Find tandem repeats inside the inserted allele sequence with{" "}
                  <Tool href="https://github.com/lmdu/pytrf">pytrf</Tool>, dropping
                  homopolymers and low-purity or low-coverage calls.
                </>
              ),
            },
            {
              title: "Novelty assessment",
              body: (
                <>
                  Screen each candidate against the reference annotation independently per
                  catalog — UCSC simpleRepeat and TRExplorer — and resolve the verdict into
                  catalogued, novel motif, or novel locus.
                </>
              ),
            },
            {
              title: "Annotation",
              body: (
                <>
                  Genic and clinical context with{" "}
                  <Tool href="https://github.com/lgmgeo/AnnotSV">AnnotSV</Tool>, and a
                  comparison against{" "}
                  <Tool href="https://github.com/dashnowlab/STRchive">STRchive</Tool>, the
                  curated catalog of disease-causing repeats.
                </>
              ),
            },
            {
              title: "Validation",
              body: "Compare calls against high-quality HPRC assemblies and trio data.",
            },
          ]}
        />
      </Section>

      <Section title="The screen, in detail">
        <Slot what="the one design decision worth a slide">
          Motif equivalence and distance tolerance, or the purity filter, or the choice to
          keep the two catalogs separate rather than merging them — whichever the audience
          will ask about first.
        </Slot>
        <FigureSlot
          hint="docs/images/flowchart_05_08_2026.png, or a cleaner redraw"
          caption="Pipeline overview — stages, and the file each one hands to the next."
        />
      </Section>
    </div>
  );
}

function Results() {
  return (
    <div className="space-y-8">
      <Section kicker="Results" title="What came out of 67 genomes">
        <Slot what="the headline finding, before any chart">
          One paragraph a reader could repeat back. Chart captions carry the detail; this
          carries the claim.
        </Slot>
        <StatRow>
          <Stat label="Insertions scanned" />
          <Stat label="Repeat-containing" />
          <Stat label="Distinct loci" />
          <Stat label="Novel loci" />
        </StatRow>
      </Section>

      <Section title="Where the candidates go">
        <FigureSlot
          hint="Funnel — insertions → repeats → filtered → novel"
          caption="Each stage drops calls for a stated reason, and the reason is the interesting part."
        />
        <FigureSlot
          hint="Motif-length distribution, split by novelty verdict"
          caption="Homopolymer, STR and VNTR mix — and whether novelty concentrates anywhere in it."
        />
      </Section>

      <Section title="Novel motifs versus novel loci">
        <P>
          The two verdicts have different failure modes, so they are worth showing apart.
          A novel-motif call one edit away from a catalogued motif is a near miss, not a
          discovery; a novel-locus call in a region the reference annotates thinly is a
          different kind of claim.
        </P>
        <Slot what="the split, and how the near misses were handled" />
      </Section>

      <Section title="Clinically interesting hits">
        <P>
          Candidates that land on a STRchive locus are screened in three questions, in
          order: is it a disease locus, is the motif one catalogued there, and does the
          copy number reach the pathogenic range. Each only means anything if the previous
          answer was yes.
        </P>
        <Slot what="one or two loci worth naming, with the copy numbers seen">
          Pick examples that survive the third question, and say plainly if none did —
          &ldquo;nothing reached the pathogenic range&rdquo; is a result, and an honest one.
        </Slot>
      </Section>
    </div>
  );
}

function Validation() {
  return (
    <div className="space-y-8">
      <Section kicker="Validation" title="Reasons to believe the calls">
        <Lede>
          A candidate is a claim about sequence that is not in the reference. The check is
          whether something independent of our pipeline sees the same thing.
        </Lede>
        <Steps
          items={[
            {
              title: "Against HPRC assemblies",
              body: "The same samples have high-quality assemblies. A real insertion should be there too.",
            },
            {
              title: "Against trios",
              body: "A genuine locus segregates. A call present in a child and in neither parent is a flag on the method, not a discovery.",
            },
            {
              title: "Against the catalogs, both ways",
              body: "Screened loci that come back catalogued are the positive control: the screen has to find what is already known before its misses mean anything.",
            },
          ]}
        />
        <Slot what="what the validation actually returned" />
      </Section>

      <Section title="Known limitations">
        <Slot what="three or four honest limits">
          Say these before the audience does. Insertion-only detection misses expansions
          that align as something else; purity filtering is a threshold somebody chose;
          the cohort is 67 genomes and not a population.
        </Slot>
      </Section>
    </div>
  );
}

function Demo() {
  return (
    <div className="space-y-8">
      <Section kicker="The interface" title="The results, browsable">
        <Lede>
          The same tables the pipeline writes are what this app reads — the charts and the
          assistant query one dataset registry, so nothing on screen is a separate export
          that can drift.
        </Lede>
        <P>
          Adding data is a YAML manifest pointing at a file on the machine running the
          backend. No code change, and nothing is uploaded anywhere.
        </P>
        <ul className="space-y-1.5 text-[13px] text-ink-secondary">
          <li>
            <Link href="/" className="underline decoration-dotted underline-offset-2 hover:text-ink">
              Candidate loci
            </Link>{" "}
            — the catalog, filterable, with the allele barcode for each locus.
          </li>
          <li>
            <Link
              href="/strchive"
              className="underline decoration-dotted underline-offset-2 hover:text-ink"
            >
              Disease loci
            </Link>{" "}
            — STRchive, and this cohort screened against it.
          </li>
          <li>
            <Link
              href="/datasets"
              className="underline decoration-dotted underline-offset-2 hover:text-ink"
            >
              Datasets
            </Link>{" "}
            — what is loaded, what is switched off, and what the assistant can see.
          </li>
        </ul>
      </Section>

      <Section title="Live demo">
        <Slot what="the demo script — three clicks, in order">
          Name the loci you will open and the questions you will type, so the demo works
          on a laptop that has never seen this dataset. Have a screenshot of each step
          below in case the backend is not running.
        </Slot>
        <FigureSlot
          hint="Screenshot — catalog view, filtered to novel loci"
          caption="Step 1 — the catalog, novelty as the primary encoding."
        />
        <FigureSlot
          hint="Screenshot — a single locus, alleles and reference track"
          caption="Step 2 — one locus: what every sample carries, against what the reference annotates."
        />
      </Section>
    </div>
  );
}

function Team() {
  // Shared with the About surface and imported already alphabetised, so the two
  // places this list appears can never drift or disagree about the order.
  return (
    <div className="space-y-8">
      <Section kicker="Team & links" title="Who built it">
        <ul className="flex flex-wrap gap-x-2 gap-y-1.5 text-[13px] text-ink-secondary">
          {TEAM.map((member) => (
            <li
              key={fullName(member)}
              className="rounded-full px-2.5 py-0.5"
              style={{ background: "var(--surface-raised)" }}
            >
              {fullName(member)}
            </li>
          ))}
        </ul>
      </Section>

      <Section title="Where everything lives">
        <ul className="space-y-1.5 text-[13px] text-ink-secondary">
          <li>
            <Tool href="https://github.com/collaborativebioinformatics/novelTRs">
              github.com/collaborativebioinformatics/novelTRs
            </Tool>{" "}
            — pipeline, docs and this interface.
          </li>
          <li>
            <Tool href="https://miro.com/app/board/uXjVHuDLcpE=/?share_link_id=710821883698">
              Project flowchart
            </Tool>{" "}
            — the interactive board behind the diagram above.
          </li>
        </ul>
        <Slot what="the outward-facing links">
          Preprint or paper draft, poster PDF, the Zenodo or DOI record, and the slide
          deck — whichever exist by the time this is presented.
        </Slot>
      </Section>

      <Section title="What we would do next">
        <Slot what="the next three things, in order of what you would actually do first" />
      </Section>
    </div>
  );
}

const BODIES: Record<TopicId, () => ReactNode> = {
  overview: Overview,
  approach: Approach,
  results: Results,
  validation: Validation,
  demo: Demo,
  team: Team,
};

/* --------------------------------------------------------------------------
   The surface.
   -------------------------------------------------------------------------- */

/**
 * The topic tabs. Underlined rather than pilled, so they read as sections of
 * one document instead of as a second row of workspace nav; arrow keys move
 * between them, which is what a tablist is expected to do and what you want
 * when you are presenting with one hand on a clicker.
 */
function TopicTabs({
  current,
  onSelect,
}: {
  current: TopicId;
  onSelect: (id: TopicId) => void;
}) {
  const refs = useRef<(HTMLButtonElement | null)[]>([]);

  const onKeyDown = (event: React.KeyboardEvent) => {
    const delta = event.key === "ArrowRight" ? 1 : event.key === "ArrowLeft" ? -1 : 0;
    if (!delta) return;
    event.preventDefault();
    const index = TOPICS.findIndex((topic) => topic.id === current);
    const next = (index + delta + TOPICS.length) % TOPICS.length;
    onSelect(TOPICS[next].id);
    refs.current[next]?.focus();
  };

  return (
    <div
      role="tablist"
      aria-label="Presentation topics"
      onKeyDown={onKeyDown}
      className="scroll-quiet flex gap-1 overflow-x-auto"
    >
      {TOPICS.map((topic, i) => {
        const active = topic.id === current;
        return (
          <button
            key={topic.id}
            ref={(node) => {
              refs.current[i] = node;
            }}
            type="button"
            role="tab"
            id={`topic-tab-${topic.id}`}
            aria-selected={active}
            aria-controls={`topic-panel-${topic.id}`}
            tabIndex={active ? 0 : -1}
            onClick={() => onSelect(topic.id)}
            className="shrink-0 whitespace-nowrap px-2.5 py-2 text-[13px] transition-colors"
            style={{
              color: active ? "var(--ink)" : "var(--ink-muted)",
              boxShadow: active ? "inset 0 -2px 0 0 var(--novel)" : "none",
            }}
          >
            {topic.label}
          </button>
        );
      })}
    </div>
  );
}

export function PresentationView() {
  const [topic, setTopic] = useState<TopicId>(TOPICS[0].id);
  const panelRef = useRef<HTMLDivElement | null>(null);

  // The hash is how a topic gets linked or reloaded into — worth the ten lines,
  // because during a talk the thing you want is a URL that opens on the slide
  // you are talking about. Read on mount, and again on hashchange: pasting a
  // topic link while already on this page changes only the fragment, which is a
  // same-document navigation and never remounts anything.
  useEffect(() => {
    const apply = () => {
      const fromHash = window.location.hash.slice(1);
      if (TOPICS.some((t) => t.id === fromHash)) setTopic(fromHash as TopicId);
    };
    apply();
    window.addEventListener("hashchange", apply);
    return () => window.removeEventListener("hashchange", apply);
  }, []);

  const select = useCallback((id: TopicId) => {
    setTopic(id);
    // replaceState, not a route push: moving between sections of one page is
    // not navigation, and it must not fill the back button with topics.
    window.history.replaceState(null, "", `#${id}`);
    // Deep in one topic, switching to another would otherwise leave you at the
    // old scroll offset — halfway down a section you have not started reading.
    // Nothing moves when the panel is already in view, so a click near the top
    // of the page does not jump.
    panelRef.current?.scrollIntoView({ block: "start" });
  }, []);

  const Body = BODIES[topic];

  return (
    <article className="mx-auto w-full max-w-[46rem] px-5 pb-20 pt-8 sm:px-6">
      <header className="space-y-3">
        <p className="text-[11px] font-medium uppercase tracking-wider text-ink-muted">
          Hackathon presentation
        </p>
        <h1 className="text-3xl font-semibold leading-tight tracking-tight text-ink">
          inTRuder — tandem repeats the reference has never seen
        </h1>
        <p className="text-[15px] leading-relaxed text-ink-secondary">
          Surfacing novel tandem repeat loci and motifs from long-read structural-variant
          insertion calls, without assembling a genome.
        </p>
        <Slot what="venue, date and presenters">
          Replace this line with the event and who is speaking, then delete the slot.
        </Slot>
      </header>

      <div
        className="sticky top-0 z-10 -mx-5 mt-6 border-b border-hairline px-5 sm:-mx-6 sm:px-6"
        style={{ background: "var(--plane)" }}
      >
        <TopicTabs current={topic} onSelect={select} />
      </div>

      <div
        ref={panelRef}
        role="tabpanel"
        id={`topic-panel-${topic}`}
        aria-labelledby={`topic-tab-${topic}`}
        // scroll-mt clears the sticky tab row, which would otherwise cover the
        // first lines of whatever was just scrolled to.
        className="scroll-mt-12 pt-8"
      >
        <Body />
      </div>
    </article>
  );
}
