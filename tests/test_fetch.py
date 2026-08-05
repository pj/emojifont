"""Tests for emojifont.fetch — selection logic, offline.

Network access is deliberately untested here; these cover the parts that decide
*which* memes you get and *what* code points they land on, where a silent error
would put the wrong image in your font.
"""

from pathlib import Path

import pytest

from emojifont.fetch import (
    CODEPOINT_BLOCK_END,
    DEFAULT_START_CODEPOINT,
    Emoji,
    Pack,
    assign_codepoints,
    claim_filename,
    download,
    dump_group,
    find_pack,
    mappings_string,
    pack_emoji,
    resolve_names,
    search_emoji,
    write_contact_sheet,
)


def E(id, name, url="https://cdn3.emoji.gg/emojis/x.png", category=""):
    return Emoji(id=id, name=name, url=url, source="emoji.gg", category=category)


@pytest.fixture
def index():
    return [
        E("795083-pepehappy", "pepehappy"),
        E("974580-pepeok", "pepeok"),
        E("702336-kingpepe", "kingpepe"),
        E("111-shark", "shark", category="Meme"),
        E("222-dance", "dance", url="https://cdn3.emoji.gg/emojis/222-dance.gif"),
    ]


# ---------------------------------------------------------------------------
# Emoji format detection
# ---------------------------------------------------------------------------

class TestEmojiFormat:
    @pytest.mark.parametrize("url,expected", [
        ("https://x/a.png", True),
        ("https://x/a.jpg", True),
        ("https://x/a.JPEG", True),
        ("https://x/a.gif", False),
        # slackmojis appends a cache-busting query string
        ("https://emojis.slackmojis.com/emojis/images/1/lol.png?1643514041", True),
        ("https://emojis.slackmojis.com/emojis/images/1/lol.gif?1643514041", False),
    ])
    def test_is_static(self, url, expected):
        assert E("i", "n", url).is_static is expected

    def test_suffix_strips_query(self):
        assert E("i", "n", "https://x/a.png?123").suffix == ".png"


# ---------------------------------------------------------------------------
# search / resolve
# ---------------------------------------------------------------------------

class TestSearch:
    def test_substring_on_name(self, index):
        assert {e.name for e in search_emoji(index, "pepe")} == {"pepehappy", "pepeok", "kingpepe"}

    def test_case_insensitive(self, index):
        assert search_emoji(index, "PEPEHAPPY")[0].name == "pepehappy"

    def test_matches_category(self, index):
        assert [e.name for e in search_emoji(index, "meme")] == ["shark"]

    def test_no_match_is_empty(self, index):
        assert search_emoji(index, "zzzz") == []


class TestResolveNames:
    def test_exact_name(self, index):
        assert [e.id for e in resolve_names(index, ["pepeok"])] == ["974580-pepeok"]

    def test_exact_id(self, index):
        assert [e.name for e in resolve_names(index, ["795083-pepehappy"])] == ["pepehappy"]

    def test_preserves_caller_order(self, index):
        """Code points are assigned in order, so selection order must be kept."""
        got = [e.name for e in resolve_names(index, ["kingpepe", "pepeok", "shark"])]
        assert got == ["kingpepe", "pepeok", "shark"]

    def test_unique_substring_resolves(self, index):
        assert resolve_names(index, ["king"])[0].name == "kingpepe"

    def test_ambiguous_raises(self, index):
        """'pepe' hits three — better to stop than silently pick one."""
        with pytest.raises(LookupError, match="3 matches"):
            resolve_names(index, ["pepe"])

    def test_missing_raises(self, index):
        with pytest.raises(LookupError, match="no match"):
            resolve_names(index, ["nosuchmeme"])

    def test_typo_among_valid_names_still_raises(self, index):
        """A typo must not silently shorten the selection."""
        with pytest.raises(LookupError, match="nosuchmeme"):
            resolve_names(index, ["pepeok", "nosuchmeme", "kingpepe"])

    def test_exact_name_beats_substring(self):
        """'pepe' exactly names one entry, so it shouldn't be called ambiguous."""
        idx = [E("1-pepe", "pepe"), E("2-pepehappy", "pepehappy")]
        assert resolve_names(idx, ["pepe"])[0].id == "1-pepe"


# ---------------------------------------------------------------------------
# packs
# ---------------------------------------------------------------------------

class TestPacks:
    @pytest.fixture
    def packs(self):
        return [
            Pack("983085-pepe", "pepe", "memepepe", ["795083-pepehappy.png", "399137-mlady.gif"]),
            Pack("232289-pepe", "PEPE", "other", ["1-a.png"]),
            Pack("498542-dnoopy", "dnoopy", "cute", ["2-b.png"]),
        ]

    def test_exact_slug_wins_over_substring(self, packs):
        """Both pepe packs match the substring; the exact slug must not be ambiguous."""
        assert find_pack(packs, "983085-pepe").name == "pepe"

    def test_unique_substring(self, packs):
        assert find_pack(packs, "noopy").slug == "498542-dnoopy"

    def test_ambiguous_lists_candidates(self, packs):
        with pytest.raises(LookupError, match="2 packs match"):
            find_pack(packs, "pepe")

    def test_missing_raises(self, packs):
        with pytest.raises(LookupError, match="No pack matching"):
            find_pack(packs, "zzz")

    def test_pack_emoji_builds_cdn_urls(self, packs):
        """Pack entries are bare filenames; /packs/ 403s, plain /emojis/ works."""
        got = pack_emoji(packs[0])
        assert got[0].url == "https://cdn3.emoji.gg/emojis/795083-pepehappy.png"

    def test_pack_emoji_strips_numeric_id_for_display(self, packs):
        got = pack_emoji(packs[0])
        assert got[0].name == "pepehappy"
        assert got[0].id == "795083-pepehappy"

    def test_pack_emoji_keeps_animated_for_filtering(self, packs):
        got = pack_emoji(packs[0])
        assert [e.is_static for e in got] == [True, False]

    def test_name_without_numeric_prefix_kept_whole(self):
        got = pack_emoji(Pack("s", "n", "d", ["party-parrot.png"]))
        assert got[0].name == "party-parrot"


# ---------------------------------------------------------------------------
# code point assignment
# ---------------------------------------------------------------------------

class TestAssignCodepoints:
    def test_consecutive_from_f900(self):
        assert assign_codepoints(3) == [0xF900, 0xF901, 0xF902]

    def test_custom_start(self):
        assert assign_codepoints(2, 0xF9F0) == [0xF9F0, 0xF9F1]

    def test_fills_block_exactly(self):
        cps = assign_codepoints(512, DEFAULT_START_CODEPOINT)
        assert cps[-1] == CODEPOINT_BLOCK_END

    def test_overflowing_block_raises(self):
        """Past U+FAFF the code points stop being East Asian Wide, so memes
        would silently drop to one cell and render half size."""
        with pytest.raises(ValueError, match="past U\\+FAFF"):
            assign_codepoints(513, DEFAULT_START_CODEPOINT)

    def test_empty_selection(self):
        assert assign_codepoints(0) == []


class TestMappingsString:
    def test_format_matches_inject_cli(self):
        got = mappings_string([(0xF900, "a.png"), (0xF901, "b.png")])
        assert got == "U+F900:a.png,U+F901:b.png"

    def test_roundtrips_through_parse_mappings(self):
        from emojifont.inject import parse_mappings
        pairs = [(0xF900, "memes/pepehappy.png"), (0xF901, "memes/pepeok.png")]
        assert parse_mappings(mappings_string(pairs)) == dict(pairs)

    def test_empty(self):
        assert mappings_string([]) == ""


# ---------------------------------------------------------------------------
# download naming
# ---------------------------------------------------------------------------

class TestDownloadNaming:
    @pytest.fixture
    def fake_http(self, monkeypatch):
        import emojifont.fetch as f
        monkeypatch.setattr(f, "http_get", lambda url, timeout=30: b"\x89PNG-data")

    def test_uses_short_name(self, tmp_path, fake_http):
        dest = download(E("795083-pepehappy", "pepehappy"), tmp_path, set())
        assert dest.name == "pepehappy.png"

    def test_rerun_overwrites_rather_than_duplicating(self, tmp_path, fake_http):
        """A repeated selection should not accumulate id-qualified copies."""
        e = E("795083-pepehappy", "pepehappy")
        download(e, tmp_path, set())
        download(e, tmp_path, set())
        assert [p.name for p in tmp_path.iterdir()] == ["pepehappy.png"]

    def test_distinct_memes_sharing_a_name_get_distinct_files(self, tmp_path, fake_http):
        taken = set()
        a = download(E("111-crying", "crying"), tmp_path, taken)
        b = download(E("222-crying", "crying"), tmp_path, taken)
        assert a.name != b.name
        assert {p.name for p in tmp_path.iterdir()} == {"crying.png", "222-crying.png"}


class TestClaimFilename:
    def test_prefers_short_name(self):
        assert claim_filename(E("795083-pepehappy", "pepehappy"), set()) == "pepehappy.png"

    def test_falls_back_to_id(self):
        taken = {"crying.png"}
        assert claim_filename(E("222-crying", "crying"), taken) == "222-crying.png"

    def test_numeric_suffix_when_id_equals_name(self):
        """slackmojis ids *are* names, so the id fallback can't disambiguate.
        Without a numeric suffix the three 'facepalm' entries collapse to one."""
        taken = set()
        got = [claim_filename(E("facepalm", "facepalm"), taken) for _ in range(3)]
        assert got == ["facepalm.png", "facepalm-2.png", "facepalm-3.png"]

    def test_claims_are_recorded(self):
        taken = set()
        claim_filename(E("a", "a"), taken)
        assert "a.png" in taken


# ---------------------------------------------------------------------------
# bulk dump
# ---------------------------------------------------------------------------

class TestDumpGroup:
    @pytest.fixture
    def fake_http(self, monkeypatch):
        import emojifont.fetch as f
        monkeypatch.setattr(f, "http_get", lambda url, timeout=30: b"\x89PNG-data")

    def test_writes_every_entry(self, tmp_path, index, fake_http):
        static = [e for e in index if e.is_static]
        written, skipped, failures = dump_group(static, tmp_path, jobs=2)
        assert len(written) == len(static)
        assert not skipped and not failures

    def test_colliding_names_all_survive(self, tmp_path, fake_http):
        """Three same-named entries must produce three files, not one."""
        dupes = [E("facepalm", "facepalm") for _ in range(3)]
        written, _, _ = dump_group(dupes, tmp_path, jobs=2)
        assert len(written) == 3
        assert len({d for _, d in written}) == 3
        assert len(list(tmp_path.iterdir())) == 3

    def test_second_run_skips_existing(self, tmp_path, index, fake_http):
        static = [e for e in index if e.is_static]
        dump_group(static, tmp_path, jobs=2)
        written, skipped, _ = dump_group(static, tmp_path, jobs=2)
        assert not written
        assert len(skipped) == len(static)

    def test_overwrite_redownloads(self, tmp_path, index, fake_http):
        static = [e for e in index if e.is_static]
        dump_group(static, tmp_path, jobs=2)
        written, skipped, _ = dump_group(static, tmp_path, jobs=2, skip_existing=False)
        assert len(written) == len(static)
        assert not skipped

    def test_zero_byte_file_is_retried(self, tmp_path, index, fake_http):
        """A truncated download shouldn't be mistaken for a completed one."""
        static = [e for e in index if e.is_static][:1]
        dump_group(static, tmp_path, jobs=1)
        next(tmp_path.iterdir()).write_bytes(b"")
        written, skipped, _ = dump_group(static, tmp_path, jobs=1)
        assert len(written) == 1 and not skipped

    def test_failures_collected_not_raised(self, tmp_path, index, monkeypatch):
        """A few dead CDN links are normal across thousands of entries; they
        must not abort the whole dump."""
        import emojifont.fetch as f

        def flaky(url, timeout=30):
            if "kingpepe" in url:
                raise OSError("HTTP Error 403: Forbidden")
            return b"\x89PNG-data"

        monkeypatch.setattr(f, "http_get", flaky)
        idx = [E("1-a", "a"), E("2-kingpepe", "kingpepe", "https://x/kingpepe.png")]
        written, _, failures = dump_group(idx, tmp_path, jobs=2)
        assert len(written) == 1
        assert len(failures) == 1
        assert failures[0][0].name == "kingpepe"


# ---------------------------------------------------------------------------
# contact sheet
# ---------------------------------------------------------------------------

class TestContactSheet:
    def test_writes_names_and_urls(self, tmp_path, index):
        out = tmp_path / "sheet.html"
        write_contact_sheet(index, out)
        text = out.read_text()
        assert "pepehappy" in text
        assert "795083-pepehappy" in text
        assert index[0].url in text

    def test_badges_animated(self, tmp_path, index):
        out = tmp_path / "sheet.html"
        write_contact_sheet(index, out)
        assert out.read_text().count('class="anim"') == 1

    def test_src_map_points_at_local_files(self, tmp_path, index):
        """The dump's sheet must reference downloaded files, not remote URLs."""
        out = tmp_path / "sheet.html"
        write_contact_sheet(index[:1], out, src_map={index[0].id: "983085-pepe/pepehappy.png"})
        text = out.read_text()
        assert 'src="983085-pepe/pepehappy.png"' in text
        assert index[0].url not in text

    def test_escapes_markup_in_names(self, tmp_path):
        """Names are user-submitted; they must not inject markup."""
        out = tmp_path / "sheet.html"
        write_contact_sheet([E("x", '<script>alert(1)</script>')], out)
        text = out.read_text()
        assert "<script>alert(1)</script>" not in text
        assert "&lt;script&gt;" in text


# ---------------------------------------------------------------------------
# dump sheet
# ---------------------------------------------------------------------------

class TestSheetEntriesFromDisk:
    def _dump(self, root):
        (root / "packA").mkdir(parents=True)
        (root / "packB").mkdir(parents=True)
        (root / "packA" / "one.png").write_bytes(b"x")
        (root / "packA" / "two.jpg").write_bytes(b"x")
        (root / "packB" / "three.gif").write_bytes(b"x")
        (root / "index.html").write_text("<html>")

    def test_covers_every_group(self, tmp_path):
        """A second dump run must not shrink the sheet to just that run."""
        from emojifont.fetch import sheet_entries_from_disk
        self._dump(tmp_path)
        entries, srcs = sheet_entries_from_disk(tmp_path)
        assert {e.name for e in entries} == {"one", "two", "three"}
        assert srcs[str(Path("packA/one"))] == str(Path("packA/one.png"))

    def test_ignores_non_images(self, tmp_path):
        from emojifont.fetch import sheet_entries_from_disk
        self._dump(tmp_path)
        entries, _ = sheet_entries_from_disk(tmp_path)
        assert "index" not in {e.name for e in entries}

    def test_group_recorded_as_category(self, tmp_path):
        from emojifont.fetch import sheet_entries_from_disk
        self._dump(tmp_path)
        entries, _ = sheet_entries_from_disk(tmp_path)
        assert {e.category for e in entries} == {"packA", "packB"}
