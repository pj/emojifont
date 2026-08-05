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
    fetch_frankerfacez_pages,
    find_pack,
    frankerfacez_best_url,
    frankerfacez_emoji,
    mappings_string,
    pack_emoji,
    resolve_names,
    search_emoji,
    sniff_content_type_ext,
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

    def test_case_variants_do_not_silently_collide(self):
        """macOS APFS and Windows are case-insensitive-but-preserving: 'Pog.png'
        and 'pog.png' are the same file there, even though they're different
        Python strings. A different-case duplicate must still be detected as
        taken, or the second download silently overwrites the first on disk."""
        taken = set()
        first = claim_filename(E("1", "Pog"), taken)
        second = claim_filename(E("2", "pog"), taken)
        assert first == "Pog.png"
        assert second != first
        assert second.lower() != first.lower()

    def test_case_variant_falls_back_to_id_like_exact_duplicates(self):
        taken = set()
        claim_filename(E("111", "Pog"), taken)
        assert claim_filename(E("222", "POG"), taken) == "222.png"


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

    def test_case_variant_names_all_survive_on_disk(self, tmp_path, fake_http):
        """Regression test: on a case-insensitive-but-preserving filesystem
        (the macOS/Windows default), 'Pog.png' and 'pog.png' are literally
        the same file — writing both without case-aware collision tracking
        silently drops one and misreports a fresh directory as having
        pre-existing files. This must run against a real filesystem (not a
        fake) to actually exercise that behaviour."""
        dupes = [E("1", "Pog"), E("2", "pog"), E("3", "POG")]
        written, skipped, failures = dump_group(dupes, tmp_path, jobs=1)
        assert len(written) == 3
        assert not skipped and not failures
        on_disk = {p.name for p in tmp_path.iterdir()}
        assert len(on_disk) == 3
        assert len({n.lower() for n in on_disk}) == 3

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


# ---------------------------------------------------------------------------
# Emoji.suffix / ext override
#
# FFZ serves images from extensionless URLs like .../emote/128054/4, sitting
# under a domain (frankerfacez.com) that itself contains a dot. A naive
# "split the whole URL on its last dot" would pick up that domain dot and
# report a nonsense extension instead of "no extension" — is_static must not
# be fooled by that into a wrong answer.
# ---------------------------------------------------------------------------

class TestEmojiSuffix:
    def test_extensionless_ffz_style_url_has_no_suffix(self):
        e = Emoji(id="1", name="n", url="https://cdn.frankerfacez.com/emote/128054/4", source="frankerfacez")
        assert e.suffix == ""
        assert e.is_static is False

    def test_domain_dot_not_mistaken_for_extension(self):
        e = Emoji(id="1", name="n", url="https://cdn.example.com/emote/1/4", source="x")
        assert e.suffix == ""

    def test_normal_url_unaffected(self):
        e = Emoji(id="1", name="n", url="https://cdn3.emoji.gg/emojis/1-a.png", source="emoji.gg")
        assert e.suffix == ".png"

    def test_explicit_ext_overrides_url(self):
        e = Emoji(id="1", name="n", url="https://cdn.frankerfacez.com/emote/1/4",
                  source="frankerfacez", ext=".gif")
        assert e.suffix == ".gif"
        assert e.is_static is False

    def test_explicit_png_ext_makes_it_static(self):
        e = Emoji(id="1", name="n", url="https://cdn.frankerfacez.com/emote/1/4",
                  source="frankerfacez", ext=".png")
        assert e.is_static is True


# ---------------------------------------------------------------------------
# FrankerFaceZ
# ---------------------------------------------------------------------------

def ffz_record(id, name, urls=None, modifier=False, hidden=False, public=True, count=0):
    return {
        "id": id, "name": name, "modifier": modifier, "hidden": hidden,
        "public": public, "usage_count": count,
        "urls": urls if urls is not None else {"1": f"https://cdn.frankerfacez.com/emote/{id}/1",
                                                "2": f"https://cdn.frankerfacez.com/emote/{id}/2",
                                                "4": f"https://cdn.frankerfacez.com/emote/{id}/4"},
    }


class TestFrankerfacezBestUrl:
    def test_prefers_4x(self):
        assert frankerfacez_best_url({"1": "a", "2": "b", "4": "c"}) == "c"

    def test_falls_back_to_2x(self):
        assert frankerfacez_best_url({"1": "a", "2": "b"}) == "b"

    def test_falls_back_to_1x(self):
        assert frankerfacez_best_url({"1": "a"}) == "a"

    def test_no_urls_returns_none(self):
        assert frankerfacez_best_url({}) is None


class TestFrankerfacezEmoji:
    @pytest.fixture
    def fake_sniff(self, monkeypatch):
        """Every sniffed emote comes back PNG unless the test overrides it."""
        import emojifont.fetch as f
        monkeypatch.setattr(f, "sniff_content_type_ext", lambda url, **kw: ".png")

    def test_drops_modifiers(self, fake_sniff):
        raw = [ffz_record(1, "flip", modifier=True), ffz_record(2, "OMEGALUL")]
        got = frankerfacez_emoji(raw)
        assert [e.name for e in got] == ["OMEGALUL"]

    def test_drops_hidden(self, fake_sniff):
        raw = [ffz_record(1, "banned", hidden=True), ffz_record(2, "OMEGALUL")]
        got = frankerfacez_emoji(raw)
        assert [e.name for e in got] == ["OMEGALUL"]

    def test_drops_non_public(self, fake_sniff):
        raw = [ffz_record(1, "private", public=False), ffz_record(2, "OMEGALUL")]
        got = frankerfacez_emoji(raw)
        assert [e.name for e in got] == ["OMEGALUL"]

    def test_skips_entries_with_no_urls(self, fake_sniff):
        raw = [ffz_record(1, "broken", urls={}), ffz_record(2, "OMEGALUL")]
        got = frankerfacez_emoji(raw)
        assert [e.name for e in got] == ["OMEGALUL"]

    def test_preserves_order(self, fake_sniff):
        raw = [ffz_record(1, "OMEGALUL"), ffz_record(2, "Pog"), ffz_record(3, "KEKW")]
        got = frankerfacez_emoji(raw)
        assert [e.name for e in got] == ["OMEGALUL", "Pog", "KEKW"]

    def test_uses_best_url(self, fake_sniff):
        raw = [ffz_record(1, "OMEGALUL", urls={"1": "low"})]
        got = frankerfacez_emoji(raw)
        assert got[0].url == "low"

    def test_ext_from_sniff_drives_is_static(self, monkeypatch):
        import emojifont.fetch as f
        monkeypatch.setattr(f, "sniff_content_type_ext",
                            lambda url, **kw: ".gif" if "999" in url else ".png")
        raw = [ffz_record(999, "animatedOne"), ffz_record(2, "staticOne")]
        got = {e.name: e for e in frankerfacez_emoji(raw)}
        assert got["animatedOne"].is_static is False
        assert got["staticOne"].is_static is True

    def test_empty_input(self, fake_sniff):
        assert frankerfacez_emoji([]) == []

    def test_id_is_stringified(self, fake_sniff):
        got = frankerfacez_emoji([ffz_record(128054, "OMEGALUL")])
        assert got[0].id == "128054"


class TestSniffContentTypeExt:
    def test_maps_known_content_type(self, monkeypatch):
        import emojifont.fetch as f
        monkeypatch.setattr(f, "http_content_type", lambda url, **kw: "image/gif")
        assert sniff_content_type_ext("https://x/y") == ".gif"

    def test_unknown_content_type_falls_back_to_default(self, monkeypatch):
        import emojifont.fetch as f
        monkeypatch.setattr(f, "http_content_type", lambda url, **kw: "text/html")
        assert sniff_content_type_ext("https://x/y") == ".png"

    def test_failed_head_falls_back_rather_than_raising(self, monkeypatch):
        """A single dead link during a 5000-item dump must not blow up the run."""
        import emojifont.fetch as f
        def boom(url, **kw):
            raise OSError("connection reset")
        monkeypatch.setattr(f, "http_content_type", boom)
        assert sniff_content_type_ext("https://x/y") == ".png"

    def test_custom_default_honoured(self, monkeypatch):
        import emojifont.fetch as f
        monkeypatch.setattr(f, "http_content_type", lambda url, **kw: "text/html")
        assert sniff_content_type_ext("https://x/y", default=".webp") == ".webp"


class TestFetchFrankerfacezPages:
    def test_orders_by_page_then_position(self, monkeypatch):
        """Pages are fetched in parallel; results must still come back in
        request order regardless of which page's HTTP call finished first."""
        import emojifont.fetch as f
        import json as jsonlib

        def fake_get(url, timeout=30):
            page = int(url.split("page=")[1].split("&")[0])
            # Reverse arrival order to prove sorting isn't accidental
            import time as t
            t.sleep(0.02 * (3 - page))
            return jsonlib.dumps({
                "emoticons": [{"id": page * 10 + i, "name": f"p{page}e{i}"} for i in range(2)]
            }).encode()

        monkeypatch.setattr(f, "http_get", fake_get)
        got = fetch_frankerfacez_pages(pages=3, per_page=2, jobs=3)
        assert [e["name"] for e in got] == ["p1e0", "p1e1", "p2e0", "p2e1", "p3e0", "p3e1"]

    def test_builds_expected_url(self, monkeypatch):
        import emojifont.fetch as f
        seen = []

        def fake_get(url, timeout=30):
            seen.append(url)
            return b'{"emoticons": []}'

        monkeypatch.setattr(f, "http_get", fake_get)
        fetch_frankerfacez_pages(pages=1, per_page=50, sort="count-desc")
        assert "page=1" in seen[0] and "per_page=50" in seen[0] and "sort=count-desc" in seen[0]


class TestFrankerfacezDumpIntegration:
    """The point of sniffing ext up front is that FFZ Emoji objects then need
    no special handling in the existing download/collision/sheet machinery."""

    def test_ffz_emoji_flows_through_dump_group(self, tmp_path, monkeypatch):
        import emojifont.fetch as f
        monkeypatch.setattr(f, "http_get", lambda url, timeout=30: b"\x89PNG-data")
        emojis = [
            Emoji(id="1", name="OMEGALUL", url="https://cdn.frankerfacez.com/emote/1/4",
                 source="frankerfacez", ext=".png"),
            Emoji(id="2", name="Pog", url="https://cdn.frankerfacez.com/emote/2/4",
                 source="frankerfacez", ext=".png"),
        ]
        written, skipped, failures = dump_group(emojis, tmp_path, jobs=2)
        assert len(written) == 2
        assert not failures
        assert {p.name for p in tmp_path.iterdir()} == {"OMEGALUL.png", "Pog.png"}
