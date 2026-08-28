"""What `search_literature` composes, how it scores, and how it paces itself.

Everything here runs offline against `httpx.MockTransport` and a committed
response fixture, so the suite needs no network and no credentials — the one
exception is the canary at the bottom, which is marked `network` and deselected
by default.

The tests worth reading first are the composition ones. Europe PMC answers a
malformed query with a large plausible result set rather than an error, so the
guard against that has to be structural, and these pin it.
"""

from __future__ import annotations

import asyncio
import json
import re
import time
from pathlib import Path

import httpx
import pytest

from app.util import europepmc as ep

FIXTURE = json.loads(
    (Path(__file__).parent / "fixtures" / "europepmc_rfc1_core.json").read_text()
)
RECORDS = FIXTURE["resultList"]["result"]


@pytest.fixture(autouse=True)
def _clean_cache():
    ep.clear_cache()
    yield
    ep.clear_cache()


#: Captured before any test patches the name — `_mock` must keep building real
#: clients even while `httpx.AsyncClient` is monkeypatched to return mocks.
_REAL_CLIENT = httpx.AsyncClient


def _mock(handler) -> httpx.AsyncClient:
    return _REAL_CLIENT(transport=httpx.MockTransport(handler))


# --------------------------------------------------------------------------- #
# Composition — the structural guard
# --------------------------------------------------------------------------- #

_OR_GROUP = re.compile(r"\(([^()]*\bOR\b[^()]*)\)")
_FIELDED = re.compile(r"\b([A-Z_]+):")


def _or_groups_are_single_field(query: str) -> bool:
    """Every OR group in a query mentions at most one field prefix."""
    for group in _OR_GROUP.findall(query):
        if len(set(_FIELDED.findall(group))) > 1:
            return False
    return True


def test_no_composed_query_ever_ors_across_two_fields():
    """The 5.6-million-hit bug, pinned.

    `GENE:"RFC1" OR TITLE_ABS:"RFC1"` returns 5,634,780 records — the GENE clause
    degenerates to "any gene-annotated record" — and Europe PMC reports no error
    for it. Written the other way round it silently collapses to a bare free-text
    search instead. Neither is detectable from the response, so the guard is that
    the query cannot be built.
    """
    for kwargs in (
        {"gene": "RFC1", "motif": "AAGGG", "disease": "CANVAS", "topic": "long read"},
        {"gene": "AR", "motif": "CAG"},
        {"disease": "Fragile X syndrome"},
        {"gene": "XYLT1", "repeat_context": False},
    ):
        for strategy in ep.build_ladder(**kwargs):
            assert _or_groups_are_single_field(strategy.query), strategy.query


def test_or_group_refuses_to_span_fields_by_construction():
    """`_or_group` takes one field for the whole group, so there is no call that
    produces a cross-field OR — the bug is unrepresentable, not merely avoided."""
    assert ep._or_group("TITLE_ABS", ["a", "b"]) == '(TITLE_ABS:"a" OR TITLE_ABS:"b")'
    with pytest.raises(ep.EuropePmcError):
        ep._or_group("NOT_A_FIELD", ["a"])


def test_unknown_field_names_are_refused():
    """`FOOBAR:"RFC1"` returns 0 hits rather than an error, so a typo'd field
    would read as "no papers exist". Only known fields can be emitted."""
    with pytest.raises(ep.EuropePmcError):
        ep._clause("FOOBAR", "RFC1")


def test_caller_values_cannot_restructure_the_query():
    query = ep._clause("TITLE_ABS", 'RFC1") OR (TITLE_ABS:"anything')
    assert _or_groups_are_single_field(query)
    assert query.count('"') == 2


def test_the_ladder_runs_from_most_to_least_constrained():
    ladder = ep.build_ladder(gene="RFC1", motif="AAGGG", disease="CANVAS")
    assert ladder[0].name == "strict"
    assert ladder[0].specificity == max(s.specificity for s in ladder)
    assert ladder[-1].specificity == min(s.specificity for s in ladder)
    assert len({s.query for s in ladder}) == len(ladder), "duplicate rungs"
    assert len(ladder) <= ep.MAX_STRATEGIES


def test_a_search_with_nothing_to_search_for_is_refused():
    with pytest.raises(ep.EuropePmcError):
        ep.build_ladder()


# --------------------------------------------------------------------------- #
# Scoring — measured from the response, never declared
# --------------------------------------------------------------------------- #

def test_coverage_matches_whole_words_not_substrings():
    """The terms that most need checking are the short ambiguous ones. A
    substring test would score every paper containing "are" as an AR paper."""
    records = [{"title": "Papers are numerous", "abstractText": "nothing relevant"}]
    assert ep.coverage(records, ["AR"]) == 0.0
    assert ep.coverage([{"title": "AR expansion", "abstractText": ""}], ["AR"]) == 1.0


def test_coverage_applies_reject_terms():
    records = [
        {"title": "AR androgen receptor repeat", "abstractText": ""},
        {"title": "AR in augmented reality displays", "abstractText": "androgen"},
    ]
    assert ep.coverage(records, ["androgen"]) == 1.0
    assert ep.coverage(records, ["androgen"], ["augmented reality"]) == 0.5


def test_unverifiable_coverage_is_none_rather_than_a_silent_pass():
    assert ep.coverage(RECORDS, []) is None


@pytest.mark.parametrize(
    ("hits", "records", "must", "expected"),
    [
        (0, [], ["rfc1"], "empty"),
        (5_634_780, RECORDS, ["rfc1"], "degenerate"),
        (227, [{"title": "unrelated", "abstractText": ""}], ["rfc1"], "off_target"),
        (41, RECORDS, ["rfc1"], "pass"),
        (41, RECORDS, [], "pass"),
    ],
)
def test_verdicts(hits, records, must, expected):
    strategy = ep.Strategy("s", 'TITLE_ABS:"RFC1"')
    assert ep.score_strategy(strategy, hits, records, must).verdict == expected


def test_rank_prefers_the_constrained_query_over_the_larger_result():
    """The whole point: 41 on-target papers beat 227 vague ones."""
    tight = ep.Scored(ep.Strategy("strict", 'a AND b AND c'), hit_count=41, cover=1.0)
    loose = ep.Scored(ep.Strategy("loose", "a"), hit_count=227, cover=1.0)
    assert ep.rank([loose, tight]).strategy.name == "strict"


def test_rank_breaks_a_specificity_tie_with_the_smaller_result():
    small = ep.Scored(ep.Strategy("small", "a AND b"), hit_count=50, cover=0.9)
    big = ep.Scored(ep.Strategy("big", "a AND c"), hit_count=400, cover=0.9)
    assert ep.rank([big, small]).strategy.name == "small"


def test_rank_returns_nothing_when_every_framing_failed():
    rejected = ep.Scored(ep.Strategy("s", "a"), hit_count=0)
    rejected.verdict = "empty"
    assert ep.rank([rejected]) is None


# --------------------------------------------------------------------------- #
# Rate limiting — see the module header for why there is no official number
# --------------------------------------------------------------------------- #

def test_the_limiter_paces_requests_beyond_its_burst():
    async def run() -> float:
        limiter = ep.RateLimiter(rate_per_second=20.0, burst=2)
        start = time.monotonic()
        await asyncio.gather(*(limiter.acquire() for _ in range(6)))
        return time.monotonic() - start

    elapsed = asyncio.run(run())
    # Two free from the burst, four paced at 20/s => at least 0.2s.
    assert elapsed >= 0.18, f"limiter did not pace: {elapsed:.3f}s"


def test_the_limiter_is_process_wide():
    """Europe PMC applies its limit per IP address, and every chat session this
    backend serves shares one. A per-call limiter would be the wrong shape."""
    assert isinstance(ep._LIMITER, ep.RateLimiter)


def test_retry_after_header_is_honoured_over_the_backoff():
    response = httpx.Response(429, headers={"retry-after": "2"})
    assert ep._retry_after(response, attempt=0) == 2.0
    # An HTTP-date form is unparseable here and must fall back, not raise.
    dated = httpx.Response(429, headers={"retry-after": "Wed, 21 Oct 2026 07:28:00 GMT"})
    assert 0 < ep._retry_after(dated, attempt=0) < 5


def test_a_429_is_retried_and_then_succeeds():
    calls = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        calls["n"] += 1
        if calls["n"] == 1:
            return httpx.Response(429, headers={"retry-after": "0"})
        return httpx.Response(200, json=FIXTURE)

    async def run():
        async with _mock(handler) as client:
            return await ep.fetch_one(client, 'TITLE_ABS:"RFC1"', "relevance", 10)

    hits, records = asyncio.run(run())
    assert calls["n"] == 2
    assert hits == FIXTURE["hitCount"] and len(records) == len(RECORDS)


def test_a_persistent_failure_gives_up_rather_than_hanging_the_turn():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(503)

    async def run():
        async with _mock(handler) as client:
            await ep.fetch_one(client, "q", "relevance", 10)

    with pytest.raises(ep.EuropePmcError, match="unreachable after 3 attempts"):
        asyncio.run(run())


def test_repeated_queries_are_served_from_cache():
    """The ladder is affordable partly because rungs are shared between
    questions, and a demo asking the same thing twice costs one round of calls."""
    calls = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        calls["n"] += 1
        return httpx.Response(200, json=FIXTURE)

    async def run():
        async with _mock(handler) as client:
            await ep.fetch_one(client, "q", "relevance", 10)
            await ep.fetch_one(client, "q", "relevance", 10)

    asyncio.run(run())
    assert calls["n"] == 1


def test_a_rejected_query_returns_200_with_no_result_list_and_is_caught():
    """Europe PMC answers an invalid sort with a 200 and no resultList at all."""
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"version": "6.9", "hitCount": 0})

    async def run():
        async with _mock(handler) as client:
            await ep.fetch_one(client, "q", "relevance", 10)

    with pytest.raises(ep.EuropePmcError, match="rejected the query"):
        asyncio.run(run())


# --------------------------------------------------------------------------- #
# Normalization, against a real trimmed response
# --------------------------------------------------------------------------- #

def test_a_paper_carries_identifiers_and_a_link_that_resolves():
    entry = ep.paper(RECORDS[0])
    assert entry["pmid"] and entry["url"].startswith("https://europepmc.org/article/")
    assert entry["url"].endswith(RECORDS[0]["id"])
    assert entry["title"] and not entry["title"].endswith(".")
    assert entry["abstract_snippet"]


def test_the_journal_comes_from_the_nested_field_core_actually_populates():
    """resultType=core leaves the flat `journalTitle` null and nests the real one
    under journalInfo.journal.title. Reading the flat key gives every paper a
    blank journal, which looks like data rather than a bug."""
    assert ep.paper(RECORDS[0])["journal"]
    assert ep._journal({"journalTitle": "Fallback"}) == "Fallback"


def test_long_author_lists_are_truncated_with_a_count():
    entry = ep.paper({"authorString": "A B, C D, E F, G H, I J", "id": "1"})
    assert entry["authors"] == "A B, C D, E F (+2)"


# --------------------------------------------------------------------------- #
# The whole search
# --------------------------------------------------------------------------- #

def _ladder_handler(by_query: dict[str, tuple[int, list]]):
    """Answer each rung differently, keyed on a substring of its query."""
    def handler(request: httpx.Request) -> httpx.Response:
        query = request.url.params.get("query", "")
        for marker, (hits, records) in by_query.items():
            if marker in query:
                return httpx.Response(
                    200, json={"hitCount": hits, "resultList": {"result": records}}
                )
        return httpx.Response(200, json={"hitCount": 0, "resultList": {"result": []}})
    return handler


def test_search_picks_the_on_target_framing_over_the_bigger_one(monkeypatch):
    off_target = [{"title": "The DNA-damage response", "abstractText": "no mention"}] * 5
    handler = _ladder_handler({
        '"AAGGG"': (41, RECORDS),          # every rung carrying the motif is on target
        "RFC1 AND": (227, off_target),     # the bare-anchor rung is not
    })
    monkeypatch.setattr(httpx, "AsyncClient", lambda **kw: _mock(handler))

    report = asyncio.run(ep.search(gene="RFC1", motif="AAGGG", must_mention=["RFC1"]))
    assert report["chosen_strategy"] == "strict"
    assert report["hit_count"] == 41
    assert report["term_coverage"] == 1.0
    assert any(row["verdict"] == "off_target" for row in report["strategies_tried"])
    assert report["results"]


def test_search_reports_every_framing_it_tried(monkeypatch):
    """The scoreboard is the evidence that a framing was chosen, not assumed."""
    handler = _ladder_handler({"RFC1": (41, RECORDS)})
    monkeypatch.setattr(httpx, "AsyncClient", lambda **kw: _mock(handler))

    report = asyncio.run(ep.search(gene="RFC1", motif="AAGGG"))
    rows = report["strategies_tried"]
    assert len(rows) == len(ep.build_ladder(gene="RFC1", motif="AAGGG"))
    assert all({"strategy", "query", "hits", "verdict"} <= set(row) for row in rows)


def test_finding_nothing_says_so_instead_of_returning_papers(monkeypatch):
    handler = _ladder_handler({})  # every rung comes back empty
    monkeypatch.setattr(httpx, "AsyncClient", lambda **kw: _mock(handler))

    report = asyncio.run(ep.search(gene="ZZZZ9", must_mention=["ZZZZ9"]))
    assert report["results"] == []
    assert "do not cite from memory" in report["note"]
    assert "chosen_strategy" not in report


def test_the_result_cap_is_the_settings_ceiling_not_the_caller(monkeypatch):
    handler = _ladder_handler({"RFC1": (41, RECORDS * 20)})
    monkeypatch.setattr(httpx, "AsyncClient", lambda **kw: _mock(handler))

    report = asyncio.run(ep.search(gene="RFC1", limit=500))
    assert report["returned"] <= ep.settings.literature_max_results


# --------------------------------------------------------------------------- #
# Canary
# --------------------------------------------------------------------------- #

@pytest.mark.network
def test_the_cross_field_or_bug_still_exists_upstream():
    """If Europe PMC ever fixes its parser, this fails and tells us the
    workaround is obsolete — rather than leaving it fossilized in the module."""
    import httpx as _httpx

    def hits(query: str) -> int:
        response = _httpx.get(
            ep.BASE_URL,
            params={"query": query, "format": "json", "pageSize": 1},
            headers={"User-Agent": ep.USER_AGENT},
            timeout=30,
        )
        return int(response.json().get("hitCount", 0))

    assert hits('TITLE_ABS:"RFC1"') < 5_000
    assert hits('GENE:"RFC1" OR TITLE_ABS:"RFC1"') > ep.HIT_CEILING


@pytest.mark.network
def test_the_composed_query_still_finds_the_landmark_rfc1_paper():
    report = asyncio.run(
        ep.search(gene="RFC1", motif="AAGGG", disease="CANVAS", sort="cited", limit=5)
    )
    assert report["results"], report.get("note")
    assert 0 < report["hit_count"] <= ep.HIT_CEILING
    assert report["term_coverage"] >= ep.MIN_COVERAGE
    assert any("30926972" == p["pmid"] for p in report["results"])
