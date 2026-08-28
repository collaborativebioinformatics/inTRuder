"""Insertion purity and the filters built on it."""

from __future__ import annotations

import pandas as pd
import pytest

from intruder.pipeline.novelty.insertions import (
    PASS,
    add_insertion_purity,
    filter_reasons,
    parse_sizes,
    union_length,
)


@pytest.mark.parametrize("raw,expected", [
    ("415", 415),
    ("[415]", 415),          # sv_trfcaller writes the VCF LEN field through
    ("[-415]", 415),         # a deletion length is still a length
    (415, 415),
])
def test_parse_sizes(raw, expected):
    assert parse_sizes([raw])[0] == expected


def test_parse_sizes_leaves_nonsense_missing():
    assert parse_sizes(["", "nope"]).isna().all()


def _frame(intervals, key="a"):
    return pd.DataFrame({
        "svid": [key] * len(intervals),
        "rep_start": [s for s, _ in intervals],
        "rep_end": [e for _, e in intervals],
    })


@pytest.mark.parametrize("intervals,expected", [
    ([(0, 10)], 10),
    ([(0, 10), (20, 30)], 20),          # disjoint
    ([(0, 10), (10, 20)], 20),          # abutting, half-open so no double count
    ([(0, 10), (5, 15)], 15),           # overlapping
    ([(0, 100), (10, 20)], 100),        # nested
    ([(0, 100), (0, 100)], 100),        # duplicated
    ([(10, 20), (0, 100), (5, 7)], 100),  # out of order
])
def test_union_length(intervals, expected):
    got = union_length(_frame(intervals), ["svid"], "rep_start", "rep_end")
    assert set(got) == {expected}


def test_union_length_keeps_groups_apart():
    frame = pd.concat([_frame([(0, 10), (5, 15)], "a"), _frame([(0, 10)], "b")],
                      ignore_index=True)
    got = union_length(frame, ["svid"], "rep_start", "rep_end")
    assert list(got) == [15, 15, 10]


def test_union_length_returns_values_in_the_input_order():
    """The sweep sorts internally; the result must line up with the caller's rows."""
    frame = pd.DataFrame({
        "svid": ["b", "a", "b"],
        "rep_start": [0, 0, 100],
        "rep_end": [10, 50, 130],
    })
    assert list(union_length(frame, ["svid"], "rep_start", "rep_end")) == [40, 50, 40]


def test_insertion_purity_is_repeat_bases_over_insert_size():
    frame = pd.DataFrame({
        "svid": ["a", "a", "b"],
        "rep_start": [0, 5, 0],
        "rep_end": [10, 15, 10],
        "insert_size": ["[30]", "[30]", "[100]"],
    })
    out = add_insertion_purity(frame, keys=["svid"])
    assert list(out.insertion_repeat_bases) == [15, 15, 10]
    assert list(out.insertion_purity) == [0.5, 0.5, 0.1]


def test_insertion_purity_never_exceeds_one():
    """TRF can call a repeat running past the reported insert size."""
    frame = pd.DataFrame({"svid": ["a"], "rep_start": [0], "rep_end": [200],
                          "insert_size": ["[100]"]})
    assert add_insertion_purity(frame, keys=["svid"]).insertion_purity[0] == 1.0


def test_insertion_purity_says_which_column_is_missing():
    frame = pd.DataFrame({"svid": ["a"], "rep_start": [0], "rep_end": [1]})
    with pytest.raises(KeyError, match="insert_size"):
        add_insertion_purity(frame, keys=["svid"])


# --------------------------------------------------------------------------- #
# filters
# --------------------------------------------------------------------------- #

def test_filter_reasons_accumulate():
    frame = pd.DataFrame({"purity": [0.9, 0.5, 0.9, 0.5],
                          "insertion_purity": [0.9, 0.9, 0.5, 0.5]})
    got = filter_reasons(frame, [("purity", "low_purity", 0.8),
                                 ("insertion_purity", "low_insertion_purity", 0.8)])
    assert list(got) == [PASS, "low_purity", "low_insertion_purity",
                         "low_purity,low_insertion_purity"]


def test_a_threshold_of_none_is_no_filter_at_all():
    frame = pd.DataFrame({"purity": [0.1]})
    assert list(filter_reasons(frame, [("purity", "low_purity", None)])) == [PASS]


def test_a_missing_value_is_not_evidence_of_failure():
    frame = pd.DataFrame({"purity": [None, 0.5]})
    got = filter_reasons(frame, [("purity", "low_purity", 0.8)])
    assert list(got) == [PASS, "low_purity"]


def test_the_threshold_is_inclusive():
    frame = pd.DataFrame({"purity": [0.8]})
    assert list(filter_reasons(frame, [("purity", "low_purity", 0.8)])) == [PASS]


def test_filtering_on_a_column_that_is_not_there_says_so():
    with pytest.raises(KeyError, match="purity"):
        filter_reasons(pd.DataFrame({"a": [1]}), [("purity", "low_purity", 0.8)])
