"""What `describe_vcf` reports, checked against both dialects in the repository.

These run against the committed VCFs under `data/sv_output`, so they need no
credentials and no external data. The two files are the point: one single-sample
Sniffles callset and one SURVIVOR merge of 69 of them. A reader that reports the
same thing about both is not reporting anything.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from app.config import settings
from app.tools.vcf import describe_vcf
from app.util.vcf import VcfScanError, list_vcfs, resolve_vcf_path, scan_vcf

DATA = settings.vcf_root
MERGED = DATA / "sv_output/survivor_multi_sample_vcf/first_500_INS.vcf"
SINGLE = DATA / "sv_output/sniffles/filtered/HG00290.merged.sniffles.vcf"

pytestmark = pytest.mark.skipif(
    not (MERGED.exists() and SINGLE.exists()),
    reason="the committed SV callsets are not present",
)


@pytest.fixture(scope="module")
def merged() -> dict:
    return scan_vcf(MERGED, root=DATA)


@pytest.fixture(scope="module")
def single() -> dict:
    return scan_vcf(SINGLE, max_records=300, root=DATA)


# --------------------------------------------------------------------------- #
# What the file is
# --------------------------------------------------------------------------- #

def test_the_merge_is_reported_as_multi_sample_and_the_caller_vcf_as_single(
    merged, single
):
    assert merged["samples"]["layout"] == "multi-sample"
    assert merged["samples"]["n"] == 69
    assert single["samples"]["layout"] == "single-sample"
    assert single["samples"]["names"] == ["HG00290"]


def test_the_callers_are_named_from_the_header_and_from_the_ids(merged, single):
    """`##source` alone under-reports a merge: it names the merger, not the
    caller whose calls were merged. The per-sample IDs carry the rest."""
    assert merged["provenance"]["source_lines"] == ["SURVIVOR"]
    assert "SURVIVOR1.0.7" in merged["provenance"]["svmethod"]
    assert "Sniffles2" in merged["provenance"]["callers_named_by_per_sample_ids"]

    assert single["provenance"]["source_lines"] == ["Sniffles2_2.7.5"]
    assert "sniffles" in single["provenance"]["command_lines"][0]


def test_the_assembly_is_a_guess_that_carries_its_evidence(merged):
    reference = merged["reference"]
    assert reference["assembly_guess"] == "GRCh38/hg38"
    assert "248,956,422" in reference["evidence"]


def test_symbolic_alt_records_are_counted_apart_from_the_ones_with_sequence(merged):
    """A `<INS>` record has no sequence to extract, so it cannot be counted with
    the records that do."""
    representation = merged["records"]["alt_representation"]
    assert representation["literal_sequence"] == 481
    assert representation["symbolic"] == 19
    assert merged["records"]["symbolic_alleles"] == {"<INS>": 19}


# --------------------------------------------------------------------------- #
# Where the sequence lives
# --------------------------------------------------------------------------- #

def test_the_merged_file_keeps_its_per_sample_sequence_in_the_format_fields(merged):
    roles = merged["fields"]["roles"]
    assert roles["sequence_alt"] == "AAL"
    assert roles["sequence_ref_anchor"] == "RAL"
    assert roles["breakpoint"] == "CO"
    assert roles["length"] == "LN"
    assert roles["source_id"] == "ID"


def test_the_single_sample_file_has_no_sequence_field_and_says_so(single):
    """The other half of the contract. Reporting `AAL` here would be a
    hallucinated dialect; the sequence really is only in ALT."""
    assert single["fields"]["roles"]["sequence_alt"] is None
    assert single["fields"]["roles"]["breakpoint"] is None
    assert any("only representation" in note for note in single["notes"])
    assert "merge" not in single


def test_every_detected_role_carries_the_evidence_that_chose_it(merged):
    evidence = merged["fields"]["role_evidence"]
    assert set(evidence) >= {"sequence", "coordinate", "length"}
    assert "alternate allele" in evidence["sequence"]
    # The coordinate role is decided by looking at values, not by the name.
    assert "292/292" in evidence["coordinate"]


def test_the_not_called_marker_is_not_mistaken_for_a_sequence(merged):
    """SURVIVOR writes `NAN` into its string FORMAT fields, and `NAN` is a
    nucleotide string as far as a regex is concerned. If it were counted as one,
    all 69 samples would look like carriers at every record."""
    aal = next(f for f in merged["fields"]["format"] if f["key"] == "AAL")
    assert aal["observed"]["not_called"] > 0
    assert aal["observed"]["nucleotide_like"] < aal["observed"]["values_seen"]
    first = merged["examples"][0]
    assert first["per_sample"]["n_called"] == 37


# --------------------------------------------------------------------------- #
# The two readings, and where they disagree
# --------------------------------------------------------------------------- #

def test_each_example_is_extracted_both_ways(merged, single):
    for report in (merged, single):
        assert len(report["examples"]) == 5
        for example in report["examples"]:
            assert example["record_level"]["method"]
            assert example["per_sample"]["method"]


def test_the_merged_record_alt_is_shown_to_be_one_allele_among_many(merged):
    """The finding this tool exists for: on a merged record the ALT column is a
    representative, not the truth for any particular sample."""
    comparison = merged["merge"]["per_sample_vs_record"]
    assert comparison["records_compared"] == 481
    assert comparison["records_with_more_than_one_distinct_allele"] == 324
    assert comparison["most_distinct_alleles_at_one_record"] == 68

    first = merged["examples"][0]
    assert first["per_sample"]["carriers_with_sequence"] == 37
    assert first["per_sample"]["distinct_inserted_sequences"] == 35
    assert any("one representative" in d for d in first["disagreements"])


def test_the_breakpoint_disagreement_is_measured_rather_than_asserted(merged):
    breakpoint = merged["merge"]["breakpoint"]
    assert breakpoint["records_where_a_carrier_sits_off_the_record_POS"] == 290
    assert breakpoint["median_offset_bp_where_shifted"] == 34
    assert breakpoint["max_offset_bp"] > 100
    assert any("FORMAT/CO" in note and "median 34 bp" in note for note in merged["notes"])


def test_a_carrier_entry_holding_two_calls_is_not_read_as_one(merged):
    """`chr1_10712-chr1_10712` is the start and end of one call; a comma joins
    two. Confusing the separators either invents a second breakpoint or loses
    one, and both change the offset the report leads with."""
    breakpoint = merged["merge"]["breakpoint"]
    entries = breakpoint["carrier_entries_compared"]
    assert 0 < breakpoint["carrier_entries_holding_several_coordinates"] < entries


def test_the_single_sample_file_reports_no_disagreements(single):
    assert all(example["disagreements"] == [] for example in single["examples"])


def test_a_partial_scan_says_it_is_partial(single):
    assert single["scan"]["records_scanned"] == 300
    assert single["scan"]["complete"] is False
    assert any("not of the file" in note for note in single["notes"])


def test_a_scan_that_reached_the_end_says_so(merged):
    assert merged["scan"]["complete"] is True
    assert merged["scan"]["records_scanned"] == 500


# --------------------------------------------------------------------------- #
# Which files may be opened at all
# --------------------------------------------------------------------------- #

@pytest.mark.parametrize(
    "path",
    ["/etc/hosts", "../../../etc/passwd", "/etc/passwd.vcf"],
)
def test_a_path_outside_the_data_root_is_refused(path):
    with pytest.raises(VcfScanError):
        resolve_vcf_path(path, DATA)


def test_a_symlink_pointing_out_of_the_data_root_is_refused(tmp_path):
    """resolve() before the containment check, so a link cannot smuggle a path
    past it."""
    root = tmp_path / "data"
    root.mkdir()
    outside = tmp_path / "secret.vcf"
    outside.write_text("##fileformat=VCFv4.2\n")
    (root / "link.vcf").symlink_to(outside)
    with pytest.raises(VcfScanError):
        resolve_vcf_path("link.vcf", root)


def test_a_non_vcf_inside_the_root_is_refused(tmp_path):
    (tmp_path / "notes.txt").write_text("hello")
    with pytest.raises(VcfScanError, match="not a VCF"):
        resolve_vcf_path("notes.txt", tmp_path)


def test_bcf_is_refused_with_the_conversion_to_run(tmp_path):
    (tmp_path / "calls.bcf").write_bytes(b"BCF\x02")
    with pytest.raises(VcfScanError, match="bcftools"):
        resolve_vcf_path("calls.bcf", tmp_path)


def test_a_relative_path_is_read_against_the_data_root():
    resolved = resolve_vcf_path(
        "sv_output/sniffles/filtered/HG00290.merged.sniffles.vcf", DATA
    )
    assert resolved == SINGLE.resolve()


def test_the_available_files_are_listed_from_the_root():
    listed = {entry["path"] for entry in list_vcfs(DATA)}
    assert str(SINGLE.relative_to(DATA)) in listed
    assert all(entry["size_bytes"] > 0 for entry in list_vcfs(DATA))


def test_gzipped_input_is_read_by_its_magic_bytes_not_its_name(tmp_path):
    import gzip

    packed = tmp_path / "small.vcf.gz"
    with gzip.open(packed, "wt") as handle:
        handle.write(SINGLE.read_text()[:200_000])
    report = scan_vcf(packed, max_records=5, root=tmp_path)
    assert report["file"]["compressed"] is True
    assert report["samples"]["names"] == ["HG00290"]


# --------------------------------------------------------------------------- #
# The tool wrapper
# --------------------------------------------------------------------------- #

def test_the_tool_returns_json_for_a_path_under_the_data_root():
    payload = json.loads(
        describe_vcf.invoke(
            {"path": "sv_output/survivor_multi_sample_vcf/first_500_INS.vcf"}
        )
    )
    assert payload["samples"]["n"] == 69
    assert payload["fields"]["roles"]["sequence_alt"] == "AAL"


def test_the_tool_with_no_path_lists_what_it_can_read():
    payload = json.loads(describe_vcf.invoke({}))
    assert payload["vcfs"]
    assert all(not Path(entry["path"]).is_absolute() for entry in payload["vcfs"])


def test_a_bad_path_comes_back_with_the_readable_ones_rather_than_an_error_alone():
    """A dead end is where the model gives up or invents a path; the recovery has
    to be in the same response."""
    payload = json.loads(describe_vcf.invoke({"path": "/etc/hosts"}))
    assert "error" in payload
    assert payload["available"]
