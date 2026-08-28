"""Europe PMC search, and the ladder that decides which framing of a question to trust.

The point of a literature tool is that a citation in the chat pane is something a
reader can click rather than something the model remembered. That only holds if
the query behind it was the right query, and Europe PMC makes a wrong query hard
to notice: it answers a broken one with a large, plausible, relevance-sorted
result set rather than an error.

TWO WAYS A QUERY GOES WRONG HERE, BOTH SILENT.

*Malformed.* `GENE:` does not survive a boolean OR, in either direction, and says
nothing about it (measured against the live API, and pinned in test_literature.py):

    GENE:"RFC1" OR GENE:"XYLT1"      ->     1,260  == GENE:"XYLT1" alone;
                                                      only the last disjunct survives
    GENE:"RFC1" OR TITLE_ABS:"RFC1"  -> 5,634,780  the GENE clause degenerates to
                                                      "any gene-annotated record"
    TITLE_ABS:"RFC1" OR GENE:"RFC1"  ->     2,659  == bare `RFC1`; collapses to
                                                      unfielded free text
    FOOBAR:"RFC1"                    ->         0  unknown field, no error

So no OR built here ever spans two fields: `_or_group` takes one field for the
whole group, which makes a cross-field OR unrepresentable rather than merely
avoided, and every field name comes from `_FIELDS`.

*Well-formed but wrong.* Harder, and the reason this module is not one function.
`RFC1 AND (tandem repeat OR ...)` is a perfectly good query returning 227 papers,
of which only 30% mention RFC1 in the title or abstract -- the bare unfielded term
matches full text, so citation-sorting floats famous papers that mention the gene
once in passing. On an ambiguous symbol it is worse: `AR AND (...)` returns 3,712
papers whose top hit by citation is about JAK2 in myeloproliferative disorders.
Nothing in either hit count says so.

WHAT THIS MODULE DOES INSTEAD.

`search` composes several framings of the same question, runs them concurrently,
and scores each **against the records it actually returned**: what fraction of
them contain the terms the caller said must be present. The most specific framing
that passes wins, which is what prefers 41 on-target papers over 227 vague ones.
The full scoreboard comes back with the winner, so the transcript shows what was
tried and why one was chosen -- the same reason `app.util.vcf` reports both
readings of a record rather than asserting one.

`must_mention` is the caller's domain knowledge entering as a falsifiable test
rather than as a claim: "if these papers do not mention androgen, my query went
wrong." A self-reported confidence score would not be checkable; this is.
"""

from __future__ import annotations

import asyncio
import logging
import random
import re
import time
from dataclasses import dataclass, field
from typing import Any

import httpx

from app.config import settings

logger = logging.getLogger(__name__)

BASE_URL = "https://www.ebi.ac.uk/europepmc/webservices/rest/search"

#: Identifies us to EBI on a keyless service. The norm for their web services is
#: a contact-able User-Agent; it is what lets them mail a maintainer instead of
#: blocking an IP. Deliberately a repository URL and not anyone's address.
USER_AGENT = "noveltrs/0.1 (+https://github.com/collaborativebioinformatics/novelTRs)"

#: The only field prefixes this module will emit. An unknown field returns zero
#: hits rather than an error, so a typo would read as "no papers exist".
_FIELDS = frozenset({"TITLE_ABS", "GENE", "ABSTRACT", "AUTH", "PUB_YEAR"})

#: OR'd together on one field to say "this is a repeat paper". Same-field OR is
#: the case Europe PMC handles correctly.
REPEAT_CONTEXT_TERMS = (
    "repeat expansion",
    "tandem repeat",
    "microsatellite",
    "VNTR",
)

#: Above this, a query has degenerated rather than merely been broad. The
#: broadest *legitimate* query -- the repeat-context clause with nothing ANDed
#: onto it -- measures 75,742; the malformed cross-field OR measures 5,634,780.
#: The gap is 74x, so the threshold does not need to be precise.
HIT_CEILING = 200_000

#: Fraction of returned records that must survive `must_mention` / `reject_mention`
#: for a strategy to be citable.
MIN_COVERAGE = 0.6

#: Ladder size cap. Each rung is one request, so this bounds the burst.
MAX_STRATEGIES = 8

_SORTS = {"relevance": "", "cited": "CITED desc", "recent": "P_PDATE_D desc"}

#: Characters that would let a caller's value escape its clause.
_UNSAFE = re.compile(r'["():]')


class EuropePmcError(RuntimeError):
    """Raised for a request that could not be made or a response that was not usable."""


# --------------------------------------------------------------------------- #
# Query composition
#
# Everything a caller supplies passes through `_sanitize`, and the only function
# that can emit an OR takes a single field for the whole group.
# --------------------------------------------------------------------------- #

def _sanitize(value: str) -> str:
    """A caller value reduced to something that cannot restructure the query."""
    cleaned = _UNSAFE.sub(" ", str(value)).strip()
    return re.sub(r"\s+", " ", cleaned)


def _phrase(value: str) -> str:
    return f'"{_sanitize(value)}"'


def _clause(field_name: str, value: str) -> str:
    """One fielded clause. The field must be one we know exists."""
    if field_name not in _FIELDS:
        raise EuropePmcError(f"unknown Europe PMC field {field_name!r}")
    return f"{field_name}:{_phrase(value)}"


def _or_group(field_name: str, values: tuple[str, ...] | list[str]) -> str:
    """An OR group over ONE field.

    The single-field signature is the guard: a cross-field OR cannot be
    expressed through this function, and nothing else in this module emits `OR`.
    """
    if field_name not in _FIELDS:
        raise EuropePmcError(f"unknown Europe PMC field {field_name!r}")
    parts = [_clause(field_name, value) for value in values]
    return "(" + " OR ".join(parts) + ")"


def _bare(value: str) -> str:
    """An unfielded term.

    Europe PMC's default index spans title, abstract, full text and text-mined
    annotations, and unions them correctly -- `RFC1` returns 2,659 where
    TITLE_ABS and GENE return 666 and 2,256 with a 263 overlap. It is the
    cross-field union we are forbidden from writing by hand, so it is worth a
    rung of its own; it is also the least precise rung, which is why it is
    scored rather than trusted.
    """
    clean = _sanitize(value)
    return _phrase(clean) if " " in clean else clean


@dataclass(frozen=True)
class Strategy:
    """One framing of the question, and how constrained it is."""

    name: str
    query: str

    @property
    def specificity(self) -> int:
        """Independent AND-joined constraints. More clauses, fewer and tighter hits."""
        return len(re.findall(r"\bAND\b", self.query)) + 1


def build_ladder(
    gene: str | None = None,
    motif: str | None = None,
    disease: str | None = None,
    topic: str | None = None,
    repeat_context: bool = True,
) -> list[Strategy]:
    """Framings of one question, most constrained first.

    The rungs drop one constraint at a time, so the ladder spans "everything the
    caller gave us" down to the bare anchor. Which rung is right is not decided
    here -- `score_strategy` decides it from what each one returns.
    """
    context = _or_group("TITLE_ABS", REPEAT_CONTEXT_TERMS) if repeat_context else None

    refinements: list[tuple[str, str]] = []
    if motif:
        refinements.append(("motif", _clause("TITLE_ABS", motif)))
    if disease:
        refinements.append(("disease", _clause("TITLE_ABS", disease)))
    if topic:
        refinements.append(("topic", _clause("TITLE_ABS", topic)))

    if gene:
        # Two anchor forms: the unfielded term for recall, the fielded one for
        # precision. Which wins is an empirical question per gene symbol -- it is
        # the fielded form for `AR`, the unfielded one for `RFC1`.
        anchors = [("gene", _bare(gene)), ("gene_fielded", _clause("TITLE_ABS", gene))]
    elif refinements:
        # No gene: the first refinement anchors the search and stops being a
        # refinement, so the ladder still has something to strip back to.
        label, clause = refinements.pop(0)
        anchors = [(label, clause)]
    else:
        raise EuropePmcError(
            "nothing to search for: supply at least one of gene, motif, disease or topic"
        )

    def compose(*parts: str | None) -> str:
        return " AND ".join(part for part in parts if part)

    rungs: list[Strategy] = []
    primary_label, primary = anchors[0]

    # Everything the caller gave us.
    rungs.append(Strategy("strict", compose(primary, *(c for _, c in refinements), context)))
    # One refinement at a time, when dropping one is actually a different query.
    if len(refinements) > 1:
        for label, clause in refinements:
            rungs.append(Strategy(f"{primary_label}+{label}", compose(primary, clause, context)))
    # The anchor in repeat context, then the anchor alone.
    rungs.append(Strategy(f"{primary_label}+context", compose(primary, context)))
    for label, clause in anchors[1:]:
        rungs.append(Strategy(f"{label}+context", compose(clause, context)))
    rungs.append(Strategy(primary_label, primary))

    seen: set[str] = set()
    unique = [r for r in rungs if r.query and not (r.query in seen or seen.add(r.query))]
    return unique[:MAX_STRATEGIES]


# --------------------------------------------------------------------------- #
# Scoring: measured against what came back, never declared in advance
# --------------------------------------------------------------------------- #

def _mentions(blob: str, term: str) -> bool:
    """Whole-word containment.

    Word boundaries rather than substring because the terms that most need
    checking are the short ambiguous ones -- `AR` must not match "are".
    """
    return re.search(rf"\b{re.escape(term)}\b", blob, re.IGNORECASE) is not None


def coverage(
    results: list[dict[str, Any]],
    must_mention: list[str],
    reject_mention: list[str] | None = None,
) -> float | None:
    """Fraction of returned records that carry every required term and no rejected one.

    None when there is nothing to check against, which is reported as unverified
    rather than silently scored as a pass.
    """
    if not must_mention and not reject_mention:
        return None
    if not results:
        return 0.0
    good = 0
    for record in results:
        blob = f"{record.get('title') or ''} {record.get('abstractText') or ''}"
        if all(_mentions(blob, t) for t in must_mention) and not any(
            _mentions(blob, t) for t in (reject_mention or [])
        ):
            good += 1
    return good / len(results)


@dataclass
class Scored:
    """One rung of the ladder, and what its results turned out to be."""

    strategy: Strategy
    hit_count: int = 0
    results: list[dict[str, Any]] = field(default_factory=list)
    cover: float | None = None
    verdict: str = "pass"

    @property
    def ok(self) -> bool:
        return self.verdict == "pass"

    def row(self) -> dict[str, Any]:
        """The scoreboard entry, which ships with the answer."""
        return {
            "strategy": self.strategy.name,
            "query": self.strategy.query,
            "hits": self.hit_count,
            "specificity": self.strategy.specificity,
            "term_coverage": None if self.cover is None else round(self.cover, 2),
            "verdict": self.verdict,
        }


def score_strategy(
    strategy: Strategy,
    hit_count: int,
    results: list[dict[str, Any]],
    must_mention: list[str],
    reject_mention: list[str] | None = None,
) -> Scored:
    """Judge one rung from its response alone."""
    scored = Scored(strategy=strategy, hit_count=hit_count, results=results)
    scored.cover = coverage(results, must_mention, reject_mention)

    if hit_count == 0:
        scored.verdict = "empty"
    elif hit_count > HIT_CEILING:
        # Not merely broad. See HIT_CEILING.
        scored.verdict = "degenerate"
    elif scored.cover is not None and scored.cover < MIN_COVERAGE:
        scored.verdict = "off_target"
    return scored


def rank(scoreboard: list[Scored]) -> Scored | None:
    """The most specific rung that passed; fewest hits breaks a tie.

    Specificity first rather than size first, because "smallest result set" on
    its own would reward a query that is precise about the wrong thing. More
    clauses means fewer hits anyway, so preferring the constrained query prefers
    the small one without having to say so.
    """
    passing = [s for s in scoreboard if s.ok]
    if not passing:
        return None
    return min(passing, key=lambda s: (-s.strategy.specificity, s.hit_count))


# --------------------------------------------------------------------------- #
# Rate limiting
#
# Europe PMC publishes no quota. The "10 requests per second" figure in
# circulation comes from a forum poster, not from the maintainers; asked
# directly, Europe PMC confirmed only that "the API limit is applied per IP
# address" and gave no number (epmc-webservices, Dec 2024). Responses carry no
# RateLimit-* or Retry-After headers, so there is nothing to read the budget
# from at runtime either.
#
# Two consequences, and they are the whole design:
#
# 1. Per IP means per *process*, not per chat session. Every conversation this
#    backend serves shares one address, so the limiter is a module-level
#    singleton and concurrent turns queue behind each other rather than each
#    getting its own allowance.
# 2. With no verifiable ceiling, the safe posture is to stay far under the
#    unofficial one and to handle rejection properly, rather than to pace up to
#    a number nobody has confirmed. The default of 5 rps is half the folklore
#    figure and roughly 30x what one chat turn actually needs -- a ladder is
#    ~6 requests, cached, once per question.
#
# The stated policy that does exist -- no automated bulk downloading -- is
# respected by never paginating: one page, capped at LITERATURE_MAX_RESULTS.
# --------------------------------------------------------------------------- #

class RateLimiter:
    """Token bucket over a monotonic clock, shared by every caller in the process."""

    def __init__(self, rate_per_second: float, burst: int) -> None:
        self._rate = max(rate_per_second, 0.1)
        self._capacity = float(max(burst, 1))
        self._tokens = self._capacity
        self._updated = time.monotonic()
        self._lock = asyncio.Lock()

    async def acquire(self) -> None:
        """Block until this caller may make one request."""
        while True:
            async with self._lock:
                now = time.monotonic()
                self._tokens = min(
                    self._capacity, self._tokens + (now - self._updated) * self._rate
                )
                self._updated = now
                if self._tokens >= 1.0:
                    self._tokens -= 1.0
                    return
                wait = (1.0 - self._tokens) / self._rate
            # Slept outside the lock: holding it would serialize the waiting
            # itself, so N waiters would each pay N delays instead of one.
            await asyncio.sleep(wait)


#: Process-wide, because the limit Europe PMC confirmed is per IP address.
_LIMITER = RateLimiter(settings.europepmc_rate_limit_rps, settings.europepmc_burst)
#: Separate from the rate: caps how many sockets one ladder opens at once.
_GATE = asyncio.Semaphore(settings.europepmc_max_concurrency)

_RETRY_STATUS = frozenset({429, 500, 502, 503, 504})


def _retry_after(response: httpx.Response, attempt: int) -> float:
    """How long to wait before retrying, preferring the server's own answer.

    Europe PMC has not been observed to send Retry-After, but a proxy in front
    of it may, and honouring it is strictly better than guessing. The fallback
    is exponential with jitter, so a burst of ladder requests that all get 429
    does not retry in lockstep.
    """
    header = response.headers.get("retry-after")
    if header:
        try:
            return min(float(header), 10.0)
        except ValueError:
            pass  # HTTP-date form; fall through to the backoff below
    return min(0.5 * (2**attempt), 4.0) + random.uniform(0, 0.25)


# --------------------------------------------------------------------------- #
# Response cache
#
# Keyed on the exact request, so overlapping ladders share rungs and a demo that
# asks the same question twice costs nothing. Also the main reason the ladder is
# affordable: the second question about a gene reuses most of the first ladder.
# --------------------------------------------------------------------------- #

_CACHE: dict[tuple[str, str, int], tuple[float, tuple[int, list[dict[str, Any]]]]] = {}
_CACHE_MAX = 256


def _cache_get(key: tuple[str, str, int]) -> tuple[int, list[dict[str, Any]]] | None:
    entry = _CACHE.get(key)
    if entry is None:
        return None
    expires, payload = entry
    if time.monotonic() > expires:
        _CACHE.pop(key, None)
        return None
    return payload


def _cache_put(key: tuple[str, str, int], payload: tuple[int, list[dict[str, Any]]]) -> None:
    if len(_CACHE) >= _CACHE_MAX:
        # Cheapest sufficient eviction: drop whatever is most stale.
        oldest = min(_CACHE, key=lambda k: _CACHE[k][0])
        _CACHE.pop(oldest, None)
    _CACHE[key] = (time.monotonic() + settings.europepmc_cache_ttl_s, payload)


def clear_cache() -> None:
    """Drop every cached response. For tests."""
    _CACHE.clear()


# --------------------------------------------------------------------------- #
# Transport
# --------------------------------------------------------------------------- #

async def fetch_one(
    client: httpx.AsyncClient, query: str, sort: str, page_size: int
) -> tuple[int, list[dict[str, Any]]]:
    """One search request, rate limited, retried, and cached.

    Returns the hit count and the page of records. Raises `EuropePmcError` for
    anything that leaves us without a usable answer -- the caller turns that into
    a scoreboard row rather than a failed turn.
    """
    key = (query, sort, page_size)
    cached = _cache_get(key)
    if cached is not None:
        return cached

    params = {
        "query": query,
        "format": "json",
        "resultType": "core",  # carries abstractText, which the coverage check needs
        "pageSize": page_size,
        **({"sort": _SORTS[sort]} if _SORTS.get(sort) else {}),
    }

    last_error = "no attempt made"
    for attempt in range(3):
        async with _GATE:
            await _LIMITER.acquire()
            try:
                response = await client.get(BASE_URL, params=params)
            except httpx.RequestError as exc:
                last_error = f"{type(exc).__name__}: {exc}"
                logger.warning("europepmc request failed: %s", last_error)
                response = None

        if response is not None:
            if response.status_code not in _RETRY_STATUS:
                if response.status_code != 200:
                    raise EuropePmcError(
                        f"Europe PMC returned HTTP {response.status_code} for {query!r}"
                    )
                try:
                    body = response.json()
                except ValueError as exc:
                    raise EuropePmcError(f"Europe PMC returned unreadable JSON: {exc}") from exc
                # A rejected query comes back 200 with no resultList at all, so
                # this is a real branch rather than defensive padding.
                if "resultList" not in body:
                    raise EuropePmcError(
                        f"Europe PMC rejected the query {query!r} "
                        f"(no result list in the response)"
                    )
                payload = (
                    int(body.get("hitCount") or 0),
                    body["resultList"].get("result") or [],
                )
                _cache_put(key, payload)
                return payload
            last_error = f"HTTP {response.status_code}"

        if attempt < 2:
            await asyncio.sleep(
                _retry_after(response, attempt) if response is not None else 0.5 * (2**attempt)
            )

    raise EuropePmcError(f"Europe PMC unreachable after 3 attempts ({last_error})")


# --------------------------------------------------------------------------- #
# Normalization
# --------------------------------------------------------------------------- #

def _authors(record: dict[str, Any]) -> str:
    """First three authors and a count, rather than a wall of names."""
    raw = (record.get("authorString") or "").strip().rstrip(".")
    if not raw:
        return ""
    names = [n.strip() for n in raw.split(",") if n.strip()]
    if len(names) <= 3:
        return ", ".join(names)
    return f"{', '.join(names[:3])} (+{len(names) - 3})"


def _journal(record: dict[str, Any]) -> str:
    """resultType=core nests the journal and leaves the flat key null."""
    info = record.get("journalInfo") or {}
    journal = info.get("journal") or {}
    return journal.get("title") or record.get("journalTitle") or ""


def _snippet(record: dict[str, Any], limit: int = 320) -> str:
    """Abstract head, cut at a sentence boundary where there is one nearby."""
    text = re.sub(r"\s+", " ", (record.get("abstractText") or "")).strip()
    if len(text) <= limit:
        return text
    cut = text[:limit]
    stop = cut.rfind(". ")
    return (cut[: stop + 1] if stop > limit // 2 else cut.rstrip() + "…")


def paper(record: dict[str, Any]) -> dict[str, Any]:
    """One record as the model should cite it: identifiers, and a link that resolves."""
    source = record.get("source") or "MED"
    ident = record.get("id") or record.get("pmid") or ""
    return {
        "title": (record.get("title") or "").strip().rstrip("."),
        "authors": _authors(record),
        "journal": _journal(record),
        "year": record.get("pubYear"),
        "pmid": record.get("pmid"),
        "pmcid": record.get("pmcid"),
        "doi": record.get("doi"),
        "citations": record.get("citedByCount"),
        "open_access": (record.get("isOpenAccess") or "N") == "Y",
        "url": f"https://europepmc.org/article/{source}/{ident}" if ident else None,
        "abstract_snippet": _snippet(record),
    }


# --------------------------------------------------------------------------- #
# The search itself
# --------------------------------------------------------------------------- #

async def search(
    gene: str | None = None,
    motif: str | None = None,
    disease: str | None = None,
    topic: str | None = None,
    must_mention: list[str] | None = None,
    reject_mention: list[str] | None = None,
    repeat_context: bool = True,
    sort: str = "relevance",
    limit: int = 8,
) -> dict[str, Any]:
    """Run the ladder and return the winning rung's papers plus the scoreboard.

    Every rung is one request and they go out together, so the ladder costs one
    round trip of latency rather than one per rung.
    """
    limit = max(1, min(limit, settings.literature_max_results))
    sort = sort if sort in _SORTS else "relevance"
    ladder = build_ladder(gene, motif, disease, topic, repeat_context)

    # Nothing to check against means nothing to reject on, and a coverage of 0
    # would fail every rung. Falling back to the gene symbol keeps the gate live
    # for the common call; with no gene either, coverage reports as unmeasured.
    required = list(must_mention) if must_mention else ([gene] if gene else [])
    rejected = list(reject_mention or [])

    # Scored on a full page even when the caller wants fewer: coverage over three
    # records is noise, and the extra rows cost nothing on a request already made.
    page_size = max(limit, 10)

    async with httpx.AsyncClient(
        timeout=settings.europepmc_timeout_s, headers={"User-Agent": USER_AGENT}
    ) as client:
        responses = await asyncio.gather(
            *(fetch_one(client, s.query, sort, page_size) for s in ladder),
            return_exceptions=True,
        )

    scoreboard: list[Scored] = []
    failures: list[str] = []
    for strategy, response in zip(ladder, responses):
        if isinstance(response, Exception):
            failures.append(str(response))
            failed = Scored(strategy=strategy)
            failed.verdict = "unreachable"
            scoreboard.append(failed)
            continue
        hit_count, records = response
        scoreboard.append(
            score_strategy(strategy, hit_count, records, required, rejected)
        )

    winner = rank(scoreboard)
    payload: dict[str, Any] = {
        "source": "Europe PMC",
        "searched_for": {
            k: v
            for k, v in {
                "gene": gene, "motif": motif, "disease": disease, "topic": topic,
            }.items()
            if v
        },
        "must_mention": required,
        "reject_mention": rejected,
        "sort": sort,
        # The scoreboard ships whether or not anything won: it is the evidence
        # that the chosen framing was chosen rather than assumed.
        "strategies_tried": [s.row() for s in scoreboard],
    }

    if winner is None:
        if failures and all(s.verdict == "unreachable" for s in scoreboard):
            payload["error"] = f"Europe PMC could not be reached: {failures[0]}"
            return payload
        payload["results"] = []
        payload["note"] = (
            "No query framing produced citable papers: every candidate returned "
            "nothing, returned an implausibly large result set, or returned "
            "records that do not mention "
            f"{required or 'the requested terms'}. Say that no papers were found "
            "and do not cite from memory."
        )
        return payload

    payload["chosen_strategy"] = winner.strategy.name
    payload["query"] = winner.strategy.query
    payload["hit_count"] = winner.hit_count
    payload["term_coverage"] = None if winner.cover is None else round(winner.cover, 2)
    if winner.cover is None:
        payload["coverage_note"] = (
            "Relevance was not verified: no must_mention terms were supplied and "
            "no gene symbol was available to fall back on."
        )
    papers = [paper(record) for record in winner.results[:limit]]
    payload["returned"] = len(papers)
    payload["results"] = papers
    if failures:
        payload["partial"] = f"{len(failures)} of {len(ladder)} candidate queries failed"
    return payload
