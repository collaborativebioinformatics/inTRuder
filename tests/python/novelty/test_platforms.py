"""Reading a catalogue from any supported platform into the one schema."""

from __future__ import annotations

import pytest

from novelty.platforms import (
    ANNOTATION_COLUMNS,
    CATALOG_COLUMNS,
    PLATFORMS,
    ensure_table,
    get_platform,
    normalize_chrom,
    normalize_chroms,
    read_catalog,
    sniff_format,
)


def test_normalize_chrom():
    assert normalize_chrom("1") == "chr1"
    assert normalize_chrom("chr1") == "chr1"
    assert normalize_chrom("MT") == "chrM"
    assert normalize_chrom(" chrX ") == "chrX"


def test_normalize_chroms_matches_the_scalar_version():
    values = ["1", "chr1", "MT", " chrX ", "1"]
    assert list(normalize_chroms(values)) == [normalize_chrom(v) for v in values]


# --------------------------------------------------------------------------- #
# format sniffing
# --------------------------------------------------------------------------- #

def test_sniffs_a_raw_simplerepeat_dump(write_simplerepeat):
    assert sniff_format(write_simplerepeat()) == "simplerepeat"


def test_sniffs_an_hgtables_export(write_simplerepeat):
    """An hgTables download carries a `#bin ...` header instead of no header."""
    assert sniff_format(write_simplerepeat(header=True, gzipped=False)) == "simplerepeat"


def test_sniffs_a_bed_catalog(write_bed):
    assert sniff_format(write_bed()) == "bed"


def test_sniffs_a_trgt_catalog(tmp_path):
    path = tmp_path / "trgt.bed"
    path.write_text("chr1\t10000\t10108\tID=x;MOTIFS=TAACCC;STRUC=(TAACCC)n\n")
    assert sniff_format(path) == "trgt"


def test_sniffing_an_unrecognisable_file_says_so(tmp_path):
    path = tmp_path / "mystery.tsv"
    path.write_text("some\tother\tfile\n")
    with pytest.raises(ValueError, match="cannot identify"):
        sniff_format(path)


def test_gzip_is_detected_by_content_not_by_suffix(write_simplerepeat):
    """A gzipped export named `.txt` still has to read."""
    path = write_simplerepeat(gzipped=True, name="simpleRepeat.txt")
    assert sniff_format(path) == "simplerepeat"
    assert len(read_catalog(path)) == 3


# --------------------------------------------------------------------------- #
# readers
# --------------------------------------------------------------------------- #

def test_simplerepeat_reads_the_right_columns(write_simplerepeat):
    frame = read_catalog(write_simplerepeat())
    assert list(frame.columns) == list(CATALOG_COLUMNS) + list(ANNOTATION_COLUMNS)
    first = frame.iloc[0]
    assert (first.chrom, first.start, first.end) == ("chr1", 10000, 10468)
    assert first.motif == "TAACCC"
    assert first.period == 6
    assert first.copy_num == pytest.approx(77.2)
    assert first.consensus_size == 6
    assert first.per_match == 95
    assert first.per_indel == 3


def test_hgtables_export_reads_the_same_as_the_raw_dump(write_simplerepeat):
    raw = read_catalog(write_simplerepeat())
    export = read_catalog(write_simplerepeat(header=True, gzipped=False,
                                             name="export.txt"))
    assert raw.equals(export)


def test_hgtables_export_may_omit_annotation_columns(tmp_path):
    """hgTables lets you pick columns; only chrom/start/end/sequence are required."""
    path = tmp_path / "subset.txt"
    path.write_text("#chrom\tchromStart\tchromEnd\tsequence\n"
                    "chr1\t10000\t10468\tTAACCC\n")
    frame = read_catalog(path, "simplerepeat")
    assert list(frame.columns) == list(CATALOG_COLUMNS)


def test_simplerepeat_without_the_required_columns_is_an_error(tmp_path):
    path = tmp_path / "wrong.txt"
    path.write_text("#chrom\tchromStart\tchromEnd\n chr1\t1\t2\n")
    with pytest.raises(ValueError, match="missing"):
        read_catalog(path, "simplerepeat")


def test_bed_reads_location_and_motif_only(write_bed):
    frame = read_catalog(write_bed())
    assert list(frame.columns) == list(CATALOG_COLUMNS)
    assert list(frame.motif) == ["TAACCC", "GC", "AAT"]
    assert list(frame.start) == [10000, 20000, 500]


def test_bed_coordinates_are_taken_verbatim(write_bed):
    """BED is already 0-based half-open, so nothing may shift on the way in."""
    frame = read_catalog(write_bed(rows=[("chr1", 10000, 10108, "TAACCC")]))
    assert (frame.start[0], frame.end[0]) == (10000, 10108)


def test_trgt_splits_a_variation_cluster_into_one_row_per_motif(tmp_path):
    path = tmp_path / "trgt.bed"
    path.write_text(
        "chr1\t10000\t10108\tID=a;MOTIFS=TAACCC;STRUC=(TAACCC)n\n"
        "chr1\t20000\t20100\tID=b;MOTIFS=GC,AT;STRUC=(GC)n(AT)n\n"
    )
    frame = read_catalog(path)
    assert list(frame.motif) == ["TAACCC", "GC", "AT"]
    assert list(frame.start) == [10000, 20000, 20000]


def test_rows_without_a_motif_are_dropped(write_bed, capsys):
    path = write_bed(rows=[("chr1", 10000, 10108, "TAACCC"), ("chr1", 1, 2, "")])
    frame = read_catalog(path)
    assert len(frame) == 1
    assert "skipped 1" in capsys.readouterr().err


def test_contigs_are_normalised_on_the_way_in(write_bed):
    frame = read_catalog(write_bed(rows=[("1", 10, 20, "AT"), ("MT", 10, 20, "GC")]))
    assert list(frame.chrom) == ["chr1", "chrM"]


def test_motifs_are_upper_cased_on_the_way_in(write_bed):
    assert read_catalog(write_bed(rows=[("chr1", 10, 20, "at")])).motif[0] == "AT"


def test_unknown_format_lists_the_known_ones(write_bed):
    with pytest.raises(ValueError, match="unknown catalogue format"):
        read_catalog(write_bed(), "vcf")


# --------------------------------------------------------------------------- #
# the registry
# --------------------------------------------------------------------------- #

def test_every_platform_declares_a_readable_format():
    from novelty.platforms import READERS
    for platform in PLATFORMS.values():
        assert platform.fmt in READERS or platform.fmt == "auto"


def test_trexplorer_only_offers_hg38():
    trexplorer = get_platform("trexplorer")
    assert "hg38" in trexplorer.url_for("hg38")
    with pytest.raises(ValueError, match="no catalogue for hg19"):
        trexplorer.url_for("hg19")


def test_ucsc_url_follows_the_assembly():
    assert "/hg19/" in get_platform("ucsc").url_for("hg19")


def test_unknown_platform_lists_the_known_ones():
    with pytest.raises(ValueError, match="unknown platform"):
        get_platform("ensembl")


def test_ensure_table_returns_an_existing_file_without_downloading(write_bed):
    path = write_bed()
    assert ensure_table("bed", "hg38", path, download=False) == path


def test_ensure_table_refuses_to_invent_a_missing_file(tmp_path):
    with pytest.raises(FileNotFoundError):
        ensure_table("ucsc", "hg38", tmp_path / "absent.txt.gz", download=False)


# --------------------------------------------------------------------------- #
# where downloaded catalogues live
# --------------------------------------------------------------------------- #

def test_default_cache_is_the_repo_data_directory():
    """Inside a checkout the catalogues belong with the rest of the data."""
    from novelty.platforms import default_cache
    cache = default_cache()
    assert cache.name == "reference"
    assert cache.parent.name == "data"


def test_the_cache_env_var_wins(monkeypatch, tmp_path):
    from novelty.platforms import CACHE_ENV, default_cache
    monkeypatch.setenv(CACHE_ENV, str(tmp_path))
    assert default_cache() == tmp_path


def test_default_cache_falls_back_when_there_is_no_repo(monkeypatch, tmp_path):
    """Installed outside a checkout there is no data/ to write into."""
    from novelty import platforms

    monkeypatch.delenv(platforms.CACHE_ENV, raising=False)
    monkeypatch.setenv("XDG_CACHE_HOME", str(tmp_path))
    monkeypatch.setattr(platforms, "__file__", str(tmp_path / "a/b/c/platforms.py"))
    assert platforms.default_cache() == tmp_path / "novelty"


def test_platform_paths_follow_the_cache_directory(tmp_path):
    from novelty.platforms import get_platform
    path = get_platform("ucsc").default_path("hg38", tmp_path)
    assert path == tmp_path / "ucsc" / "hg38.simpleRepeat.txt.gz"


def test_ensure_table_looks_in_the_given_cache_directory(tmp_path):
    target = tmp_path / "ucsc" / "hg38.simpleRepeat.txt.gz"
    target.parent.mkdir(parents=True)
    target.write_text("")
    assert ensure_table("ucsc", "hg38", cache_dir=tmp_path, download=False) == target


# --------------------------------------------------------------------------- #
# bundled catalogues
# --------------------------------------------------------------------------- #

def test_the_pathogenic_catalogue_is_kept_in_the_repo():
    """It is 5KB of known disease loci, so keeping it in data/novelty/ means the
    tool works offline and pins the exact version results were produced against."""
    platform = get_platform("pathogenic")
    assert platform.annotation_only
    path = platform.bundled_path("hg38")
    assert path is not None and path.exists()

    frame = read_catalog(path, platform.fmt)
    assert len(frame) == 83
    assert set(frame.columns) >= {"chrom", "start", "end", "motif"}
    # the ABCD3 GCC locus, cross-checked against the ExpansionHunter JSON that
    # ships beside it upstream, whose ReferenceRegion is chr1:94418421-94418442
    abcd3 = frame[(frame.chrom == "chr1") & (frame.start == 94418421)]
    assert list(abcd3.end) == [94418442]
    assert list(abcd3.motif) == ["GCC"]


def test_ensure_table_prefers_the_bundled_copy_without_downloading(tmp_path):
    path = ensure_table("pathogenic", "hg38", download=False, cache_dir=tmp_path)
    assert path == get_platform("pathogenic").bundled_path("hg38")
    assert not list(tmp_path.iterdir())      # nothing was cached or fetched


def test_a_bundled_platform_still_honours_an_explicit_path(tmp_path, write_bed):
    override = write_bed()
    assert ensure_table("pathogenic", "hg38", override, download=False) == override


def test_the_bundled_path_is_under_data_novelty():
    path = get_platform("pathogenic").bundled_path("hg38")
    assert path is not None
    assert path.parent.name == "novelty" and path.parent.parent.name == "data"


def test_only_hg38_is_bundled():
    """Upstream ships GRCh37 as ExpansionHunter JSON only, which this tool cannot
    read, so asking for it must not silently hand back the hg38 file."""
    assert get_platform("pathogenic").bundled_path("hg19") is None


# --------------------------------------------------------------------------- #
# IUPAC in a catalogue
# --------------------------------------------------------------------------- #

def test_sniff_accepts_a_bed_whose_motifs_carry_ambiguity_codes(tmp_path):
    """TRExplorer v2 has 11 rows with an N in the motif; a catalogue is entitled
    to write any IUPAC base in a consensus."""
    path = tmp_path / "iupac.bed"
    path.write_text("chr1\t100\t200\tGCN\nchr1\t300\t400\tACRYT\n")
    assert sniff_format(path) == "bed"
    frame = read_catalog(path)
    assert list(frame.motif) == ["GCN", "ACRYT"]
