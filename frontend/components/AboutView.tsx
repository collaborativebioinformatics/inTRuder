import { TEAM, fullName, initials, type Member } from "@/lib/team";

/**
 * Who made this, and what it is.
 *
 * A document rather than a workspace surface, so it gets the full-width
 * treatment in the shell — there is no cohort to summarize beside it and
 * nothing here for the assistant to query.
 *
 * The roster is imported already sorted (see lib/team). Nothing on this page
 * reorders it.
 */

/**
 * Fixed-size portrait, photo or not.
 *
 * Everyone gets the same square whether they sent a headshot or not, because
 * the alternative — an image on five rows and nothing on the rest — leaves the
 * names in two different left margins and the list stops reading as one list.
 * Without a photo the square is a quiet monogram, which is visibly a stand-in
 * rather than a picture of somebody.
 *
 * The alt text is empty on purpose: the name is the very next thing in the row,
 * so a described portrait would just say it twice.
 */
function Portrait({ member }: { member: Member }) {
  const shape = "h-14 w-14 shrink-0 rounded-full ring-1 ring-hairline";

  if (member.image) {
    return (
      <img
        src={member.image}
        alt=""
        width={256}
        height={256}
        loading="lazy"
        decoding="async"
        className={`${shape} object-cover`}
      />
    );
  }

  return (
    <span
      aria-hidden
      className={`${shape} grid place-items-center bg-surface-raised text-[13px] font-medium tracking-wide text-ink-muted`}
    >
      {initials(member)}
    </span>
  );
}

function MemberLinks({ member }: { member: Member }) {
  if (!member.links?.length) return null;

  return (
    <ul className="flex flex-wrap gap-x-3 gap-y-1 text-[12px] text-ink-muted">
      {member.links.map((link) => {
        // mailto: opens a compose window, not a page — sending it to a new tab
        // leaves the reader with a blank one to close.
        const external = link.href.startsWith("http");
        return (
          <li key={link.href}>
            <a
              href={link.href}
              target={external ? "_blank" : undefined}
              rel={external ? "noreferrer" : undefined}
              className="underline decoration-dotted underline-offset-2 hover:text-ink"
            >
              {link.label}
            </a>
          </li>
        );
      })}
    </ul>
  );
}

function TeamRow({ member }: { member: Member }) {
  const detailed = Boolean(member.bio || member.links?.length);

  return (
    <li
      // A name on its own is one line against a 3.5rem portrait, so it centres
      // against it; a bio is a paragraph, and centring that would float the
      // portrait somewhere in the middle of it. Same row, two natural baselines.
      className={`flex gap-4 py-5 ${detailed ? "items-start" : "items-center"}`}
    >
      <Portrait member={member} />
      <div className="min-w-0 flex-1 space-y-2">
        <div className="flex flex-wrap items-baseline gap-x-2">
          <h3 className="text-[15px] font-medium text-ink">{fullName(member)}</h3>
          {member.pronouns && (
            <span className="text-[12px] text-ink-muted">{member.pronouns}</span>
          )}
        </div>
        {member.bio && (
          <p className="max-w-[36rem] text-[13.5px] leading-relaxed text-ink-secondary">
            {member.bio}
          </p>
        )}
        <MemberLinks member={member} />
      </div>
    </li>
  );
}

export function AboutView() {
  return (
    <article className="mx-auto w-full max-w-[46rem] px-5 pb-20 pt-8 sm:px-6">
      <header className="space-y-3">
        <p className="text-[11px] font-medium uppercase tracking-wider text-ink-muted">
          About
        </p>
        <h1 className="text-3xl font-semibold leading-tight tracking-tight text-ink">
          inTRuder
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
            Alphabetical by surname. Bios, links and photos are each person&rsquo;s
            own, where they supplied them.
          </p>
        </div>
        {/* One name per row, hairline-separated: this is a list of people, and a
            person is the unit — a two-column layout would put a paragraph-long
            bio next to a bare name and imply they belong together. */}
        <ul className="divide-y divide-hairline border-y border-hairline">
          {TEAM.map((member) => (
            <TeamRow key={fullName(member)} member={member} />
          ))}
        </ul>
      </section>

      <section className="mt-10 space-y-3">
        <h2 className="text-xl font-semibold tracking-tight text-ink">The code</h2>
        <p className="text-[15px] leading-relaxed text-ink-secondary">
          The pipeline, the documentation and this interface all live in one
          repository:{" "}
          <a
            href="https://github.com/collaborativebioinformatics/inTRuder"
            target="_blank"
            rel="noreferrer"
            className="underline decoration-dotted underline-offset-2 hover:text-ink"
          >
            github.com/collaborativebioinformatics/inTRuder
          </a>
          .
        </p>
      </section>
    </article>
  );
}
