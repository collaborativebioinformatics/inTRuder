import { TEAM, fullName } from "@/lib/team";

/**
 * Who made this, and what it is.
 *
 * A document rather than a workspace surface, so it borrows the presentation's
 * column width and gets the same full-width treatment in the shell — there is
 * no cohort to summarize beside it and nothing here for the assistant to query.
 *
 * The roster is imported already sorted (see lib/team). Nothing on this page
 * reorders it: one list, one order, both surfaces.
 */
export function AboutView() {
  return (
    <article className="mx-auto w-full max-w-[46rem] px-5 pb-20 pt-8 sm:px-6">
      <header className="space-y-3">
        <p className="text-[11px] font-medium uppercase tracking-wider text-ink-muted">
          About
        </p>
        <h1 className="text-3xl font-semibold leading-tight tracking-tight text-ink">
          novelTRs
        </h1>
        <p className="text-[15px] leading-relaxed text-ink-secondary">
          Tandem repeats the reference genome has never seen: novel loci and novel
          motifs read out of long-read structural-variant insertion calls, without
          assembling a genome. This interface browses the candidates the pipeline
          produced and screens them against the repeats that are already catalogued.
        </p>
      </header>

      <section className="mt-10 space-y-4">
        <div className="space-y-1">
          <h2 className="text-xl font-semibold tracking-tight text-ink">Team</h2>
          <p className="text-[13px] leading-relaxed text-ink-muted">
            Alphabetical by surname.
          </p>
        </div>
        {/* Two columns once there is room, laid out with CSS columns rather than
            a grid: a grid fills row-major, which would run the alphabet across
            the page and leave each column jumping A, C, E — unreadable as the
            sorted list it is. Columns fill top-to-bottom, so the left column is
            the first half of the alphabet and the right one is the second. */}
        <ul className="columns-1 gap-x-8 sm:columns-2">
          {TEAM.map((member) => (
            <li
              key={fullName(member)}
              className="break-inside-avoid border-b border-hairline py-1.5 text-[15px] text-ink-secondary"
            >
              {fullName(member)}
            </li>
          ))}
        </ul>
      </section>

      <section className="mt-10 space-y-3">
        <h2 className="text-xl font-semibold tracking-tight text-ink">The code</h2>
        <p className="text-[15px] leading-relaxed text-ink-secondary">
          The pipeline, the documentation and this interface all live in one
          repository:{" "}
          <a
            href="https://github.com/collaborativebioinformatics/novelTRs"
            target="_blank"
            rel="noreferrer"
            className="underline decoration-dotted underline-offset-2 hover:text-ink"
          >
            github.com/collaborativebioinformatics/novelTRs
          </a>
          .
        </p>
      </section>
    </article>
  );
}
