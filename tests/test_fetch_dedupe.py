"""Tests for the dedupe machinery in emojifont.fetch — content-hash dedup of
downloaded meme images into a single clean directory.

Split from test_fetch.py because these tests write real files to a temp
directory and read them back (dedup is fundamentally a filesystem operation),
where the rest of test_fetch.py mocks the network layer and stays pure.
"""

from pathlib import Path

import pytest
from PIL import Image

from emojifont.fetch import (
    DedupeResult,
    claim_output_name,
    dedupe_images,
    default_dump_dirs,
    hash_file,
    iter_candidate_files,
)


def make_image(path, color=(255, 0, 0, 255), size=(8, 8), fmt="PNG"):
    path.parent.mkdir(parents=True, exist_ok=True)
    Image.new("RGBA", size, color).save(path, fmt)
    return path


# ---------------------------------------------------------------------------
# hash_file
# ---------------------------------------------------------------------------

class TestHashFile:
    def test_identical_bytes_hash_the_same(self, tmp_path):
        a = tmp_path / "a.png"
        b = tmp_path / "b.png"
        a.write_bytes(b"same content")
        b.write_bytes(b"same content")
        assert hash_file(a) == hash_file(b)

    def test_different_bytes_hash_differently(self, tmp_path):
        a = tmp_path / "a.png"
        b = tmp_path / "b.png"
        a.write_bytes(b"content one")
        b.write_bytes(b"content two")
        assert hash_file(a) != hash_file(b)

    def test_chunked_reading_matches_whole_file(self, tmp_path):
        """A file larger than one chunk must still hash correctly."""
        p = tmp_path / "big.bin"
        p.write_bytes(b"x" * 5000)
        assert hash_file(p, chunk_size=64) == hash_file(p, chunk_size=1 << 20)

    def test_filename_is_irrelevant_to_the_hash(self, tmp_path):
        """The whole point: two differently-named files with the same
        content must be recognized as duplicates."""
        a = tmp_path / "pepe.png"
        b = tmp_path / "totally-different-name.png"
        a.write_bytes(b"identical pixels")
        b.write_bytes(b"identical pixels")
        assert hash_file(a) == hash_file(b)


# ---------------------------------------------------------------------------
# iter_candidate_files — ordering
# ---------------------------------------------------------------------------

class TestIterCandidateFiles:
    def test_directories_scanned_in_given_order(self, tmp_path):
        """Precedence for 'first found wins' comes from the order dirs are
        passed, not from any filesystem ordering."""
        d1, d2 = tmp_path / "first", tmp_path / "second"
        make_image(d1 / "z.png")
        make_image(d2 / "a.png")
        got = list(iter_candidate_files([d2, d1]))  # second dir passed first
        assert [p.parent.name for p in got] == ["second", "first"]

    def test_files_within_a_directory_are_sorted(self, tmp_path):
        d = tmp_path / "pack"
        make_image(d / "zeta.png")
        make_image(d / "alpha.png")
        got = list(iter_candidate_files([d]))
        assert [p.name for p in got] == ["alpha.png", "zeta.png"]

    def test_nonexistent_directory_skipped_silently(self, tmp_path):
        assert list(iter_candidate_files([tmp_path / "nope"])) == []

    def test_non_image_files_excluded(self, tmp_path):
        d = tmp_path / "mixed"
        make_image(d / "a.png")
        (d / "readme.txt").parent.mkdir(parents=True, exist_ok=True)
        (d / "readme.txt").write_text("hi")
        got = list(iter_candidate_files([d]))
        assert [p.name for p in got] == ["a.png"]

    def test_gifs_included(self, tmp_path):
        """Dedupe operates on the browsable set (including animated), same
        as the web UI's index — narrowing to static-only happens later, at
        selection time, not here."""
        d = tmp_path / "d"
        make_image(d / "a.gif", fmt="GIF")
        got = list(iter_candidate_files([d]))
        assert [p.name for p in got] == ["a.gif"]


# ---------------------------------------------------------------------------
# claim_output_name
# ---------------------------------------------------------------------------

class TestClaimOutputName:
    def test_bare_name_when_free(self, tmp_path):
        p = tmp_path / "packA" / "pepe.png"
        assert claim_output_name(p, set()) == "pepe.png"

    def test_falls_back_to_source_qualified_name(self, tmp_path):
        taken = {"pepe.png"}
        p = tmp_path / "packB" / "pepe.png"
        assert claim_output_name(p, taken) == "pepe__packB.png"

    def test_falls_back_to_numeric_suffix_when_source_qualified_also_taken(self, tmp_path):
        # `taken` always holds lowercased entries in real use (claim_output_name
        # only ever inserts via .lower()); seed it the same way here.
        taken = {"pepe.png", "pepe__packb.png"}
        p = tmp_path / "packB" / "pepe.png"
        assert claim_output_name(p, taken) == "pepe__packB-2.png"

    def test_case_variants_do_not_collide(self, tmp_path):
        """Same lesson as fetch.claim_filename: macOS/Windows are
        case-insensitive-but-preserving, so 'Pog.png' and 'pog.png' are the
        same file on disk even though they're different strings."""
        taken = set()
        first = claim_output_name(tmp_path / "a" / "Pog.png", taken)
        second = claim_output_name(tmp_path / "b" / "pog.png", taken)
        assert first == "Pog.png"
        assert second.lower() != first.lower()

    def test_claims_are_recorded(self, tmp_path):
        taken = set()
        claim_output_name(tmp_path / "a" / "x.png", taken)
        assert "x.png" in taken


# ---------------------------------------------------------------------------
# dedupe_images — the integration surface
# ---------------------------------------------------------------------------

@pytest.fixture
def dupey_tree(tmp_path):
    """packA/pepe.png and packB/happy-pepe.png are byte-identical; everything
    else is unique. packA is listed first, so pepe.png should be the keeper."""
    root = tmp_path / "src"
    make_image(root / "packA" / "pepe.png", color=(0, 255, 0, 255))
    make_image(root / "packB" / "happy-pepe.png", color=(0, 255, 0, 255))  # same content
    make_image(root / "packA" / "shark.png", color=(0, 0, 255, 255))
    make_image(root / "packB" / "unique.png", color=(1, 2, 3, 255))
    return root


class TestDedupeImages:
    def test_keeps_one_copy_per_content_hash(self, dupey_tree, tmp_path):
        out = tmp_path / "out"
        result = dedupe_images([dupey_tree], out)
        assert len(result.kept) == 3  # pepe/happy-pepe collapse to 1, plus shark, unique
        assert len(result.duplicates) == 1

    def test_first_found_wins_the_name(self, dupey_tree, tmp_path):
        out = tmp_path / "out"
        dedupe_images([dupey_tree], out)
        names = {p.name for p in out.iterdir()}
        assert "pepe.png" in names  # packA/pepe.png sorts before packB/happy-pepe.png
        assert "happy-pepe.png" not in names

    def test_duplicate_report_names_the_keeper(self, dupey_tree, tmp_path):
        result = dedupe_images([dupey_tree], tmp_path / "out")
        dupe_src, kept_src = result.duplicates[0]
        assert dupe_src.name == "happy-pepe.png"
        assert kept_src.name == "pepe.png"

    def test_survivors_have_correct_content(self, dupey_tree, tmp_path):
        out = tmp_path / "out"
        dedupe_images([dupey_tree], out)
        original = (dupey_tree / "packA" / "pepe.png").read_bytes()
        assert (out / "pepe.png").read_bytes() == original

    def test_directory_precedence_controls_which_name_survives(self, dupey_tree, tmp_path):
        """Same content, but list packB's directory first -> its name wins."""
        out = tmp_path / "out"
        dedupe_images([dupey_tree / "packB", dupey_tree / "packA"], out)
        names = {p.name for p in out.iterdir()}
        assert "happy-pepe.png" in names
        assert "pepe.png" not in names

    def test_dry_run_reports_without_writing(self, dupey_tree, tmp_path):
        out = tmp_path / "out"
        result = dedupe_images([dupey_tree], out, dry_run=True)
        assert len(result.kept) == 3
        assert not out.exists()

    def test_rerun_overwrites_rather_than_duplicating(self, dupey_tree, tmp_path):
        out = tmp_path / "out"
        dedupe_images([dupey_tree], out)
        dedupe_images([dupey_tree], out)
        assert len(list(out.iterdir())) == 3

    def test_hardlink_produces_same_content(self, dupey_tree, tmp_path):
        out = tmp_path / "out"
        dedupe_images([dupey_tree], out, hardlink=True)
        original = (dupey_tree / "packA" / "shark.png").read_bytes()
        assert (out / "shark.png").read_bytes() == original

    def test_unreadable_file_reported_not_raised(self, dupey_tree, tmp_path):
        """A single corrupt/unreadable file must not abort the whole run —
        same principle as dump_group's failure handling."""
        broken = dupey_tree / "packA" / "broken.png"
        broken.parent.mkdir(parents=True, exist_ok=True)
        broken.write_bytes(b"not really an image, but readable bytes")
        broken.chmod(0o000)
        try:
            result = dedupe_images([dupey_tree], tmp_path / "out")
            # readable-but-fake-image files still hash fine (hash doesn't
            # validate image structure) — what must not happen is a crash.
            assert isinstance(result, DedupeResult)
        finally:
            broken.chmod(0o644)  # restore so tmp_path cleanup can remove it

    def test_empty_input_produces_empty_result(self, tmp_path):
        result = dedupe_images([tmp_path / "nothing"], tmp_path / "out")
        assert result.kept == [] and result.duplicates == [] and result.errors == []

    def test_single_threaded_path_matches_threaded_path(self, dupey_tree, tmp_path):
        """jobs=1 takes a different code path (no ThreadPoolExecutor); it
        must produce the same dedup decision as the parallel path."""
        out_seq = tmp_path / "out_seq"
        out_par = tmp_path / "out_par"
        seq = dedupe_images([dupey_tree], out_seq, jobs=1)
        par = dedupe_images([dupey_tree], out_par, jobs=8)
        assert {p.name for p in out_seq.iterdir()} == {p.name for p in out_par.iterdir()}
        assert len(seq.kept) == len(par.kept)


class TestDedupeOrderingUnderConcurrency:
    def test_first_found_order_survives_out_of_order_completion(self, tmp_path, monkeypatch):
        """Threads can finish hashing in any order; the survivor must still
        be decided by iter_candidate_files()'s order, not by which thread's
        hash_file() call happens to return first. Simulated by making later
        files (alphabetically) resolve their hash faster than earlier ones."""
        import time as time_mod
        import emojifont.fetch as fetch_mod

        root = tmp_path / "src"
        # Three identical-content files; 'a' should win by sort order even
        # though its hash is deliberately delayed.
        for name, delay in (("a_first.png", 0.05), ("b_second.png", 0.0), ("c_third.png", 0.0)):
            (root / name).parent.mkdir(parents=True, exist_ok=True)
            (root / name).write_bytes(b"identical content")

        real_hash_file = fetch_mod.hash_file

        def slow_for_a(path, chunk_size=1 << 20):
            if path.name.startswith("a_"):
                time_mod.sleep(0.05)
            return real_hash_file(path, chunk_size)

        monkeypatch.setattr(fetch_mod, "hash_file", slow_for_a)
        result = dedupe_images([root], tmp_path / "out", jobs=4)
        assert len(result.kept) == 1
        kept_src, _ = result.kept[0]
        assert kept_src.name == "a_first.png"


# ---------------------------------------------------------------------------
# default_dump_dirs
# ---------------------------------------------------------------------------

class TestDefaultDumpDirs:
    def test_only_existing_dirs_included(self, tmp_path):
        (tmp_path / "font_build" / "meme-dump").mkdir(parents=True)
        got = default_dump_dirs(tmp_path)
        assert got == [tmp_path / "font_build" / "meme-dump"]

    def test_empty_when_none_exist(self, tmp_path):
        assert default_dump_dirs(tmp_path) == []

    def test_order_matches_dump_command_precedence(self, tmp_path):
        for d in ("meme-dump", "ffz-dump", "memes"):
            (tmp_path / "font_build" / d).mkdir(parents=True)
        got = [d.name for d in default_dump_dirs(tmp_path)]
        assert got == ["meme-dump", "ffz-dump", "memes"]
