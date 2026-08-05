"""Tests for emojifont.webui.db — the sqlite store behind the meme picker.

Covers the two things that would corrupt a user's picks silently: scanning
losing star/select state on existing rows, and selection ordering breaking
under deselect/reselect/reorder.
"""

from pathlib import Path

import pytest
from PIL import Image

from emojifont.webui.db import Store


def make_image(path, size=(8, 8), fmt="PNG"):
    path.parent.mkdir(parents=True, exist_ok=True)
    Image.new("RGBA", size, (255, 0, 0, 255)).save(path, fmt)
    return path


@pytest.fixture
def store(tmp_path):
    s = Store(tmp_path / "test.sqlite3")
    yield s
    s.close()


@pytest.fixture
def image_root(tmp_path):
    root = tmp_path / "images"
    make_image(root / "packA" / "pepe.png")
    make_image(root / "packA" / "shark.png")
    make_image(root / "flat.png")
    make_image(root / "dance.gif", fmt="GIF")
    return root


# ---------------------------------------------------------------------------
# scan
# ---------------------------------------------------------------------------

class TestScan:
    def test_finds_all_images(self, store, image_root):
        added, missing = store.scan([image_root])
        assert added == 4
        assert missing == 0

    def test_source_from_subdirectory(self, store, image_root):
        store.scan([image_root])
        memes, _ = store.list_memes(limit=10)
        by_name = {m["name"]: m for m in memes}
        assert by_name["pepe"]["source"] == "packA"

    def test_source_from_root_when_flat(self, store, image_root):
        store.scan([image_root])
        memes, _ = store.list_memes(limit=10)
        by_name = {m["name"]: m for m in memes}
        assert by_name["flat"]["source"] == image_root.name

    def test_gif_indexed_but_marked_non_static_ext(self, store, image_root):
        store.scan([image_root])
        memes, _ = store.list_memes(limit=10)
        by_name = {m["name"]: m for m in memes}
        assert by_name["dance"]["ext"] == ".gif"

    def test_records_dimensions(self, store, image_root):
        store.scan([image_root])
        memes, _ = store.list_memes(limit=10)
        by_name = {m["name"]: m for m in memes}
        assert by_name["pepe"]["width"] == 8
        assert by_name["pepe"]["height"] == 8

    def test_rescan_does_not_duplicate(self, store, image_root):
        store.scan([image_root])
        added2, _ = store.scan([image_root])
        assert added2 == 0
        _, total = store.list_memes(limit=100)
        assert total == 4

    def test_rescan_preserves_star_and_selection(self, store, image_root):
        """The whole point of persistence: downloading more memes and
        rescanning must not reset choices already made."""
        store.scan([image_root])
        memes, _ = store.list_memes(search="pepe", limit=1)
        meme_id = memes[0]["id"]
        store.set_starred(meme_id, True)
        store.set_selected(meme_id, True)

        store.scan([image_root])  # rescan, nothing new on disk

        m = store.get_meme(meme_id)
        assert m["starred"] == 1
        assert m["selected_seq"] is not None

    def test_removed_file_flagged_missing_not_deleted(self, store, image_root):
        store.scan([image_root])
        memes, _ = store.list_memes(search="flat", limit=1)
        meme_id = memes[0]["id"]
        store.set_starred(meme_id, True)

        (image_root / "flat.png").unlink()
        store.scan([image_root])

        m = store.get_meme(meme_id)
        assert m["missing"] == 1
        assert m["starred"] == 1  # star survives even though the file is gone

    def test_missing_file_excluded_from_default_listing(self, store, image_root):
        store.scan([image_root])
        (image_root / "flat.png").unlink()
        store.scan([image_root])
        memes, total = store.list_memes(limit=10)
        assert "flat" not in {m["name"] for m in memes}
        assert total == 3

    def test_file_that_reappears_is_unflagged(self, store, tmp_path):
        root = tmp_path / "images2"
        p = make_image(root / "a.png")
        store.scan([root])
        p.unlink()
        store.scan([root])
        assert store.get_meme(1)["missing"] == 1
        make_image(root / "a.png")
        store.scan([root])
        assert store.get_meme(1)["missing"] == 0

    def test_nonexistent_root_is_skipped_not_an_error(self, store, tmp_path):
        added, missing = store.scan([tmp_path / "does-not-exist"])
        assert added == 0
        assert missing == 0

    def test_non_image_files_ignored(self, store, tmp_path):
        root = tmp_path / "mixed"
        root.mkdir()
        make_image(root / "a.png")
        (root / "readme.txt").write_text("hello")
        added, _ = store.scan([root])
        assert added == 1


# ---------------------------------------------------------------------------
# list_memes filtering
# ---------------------------------------------------------------------------

class TestListMemes:
    @pytest.fixture(autouse=True)
    def seeded(self, store, image_root):
        store.scan([image_root])
        self.ids = {m["name"]: m["id"] for m in store.list_memes(limit=10)[0]}

    def test_search_is_case_insensitive_substring(self, store):
        memes, _ = store.list_memes(search="PEP", limit=10)
        assert [m["name"] for m in memes] == ["pepe"]

    def test_search_escapes_sql_wildcards(self, store, tmp_path):
        """A literal '%' or '_' in a search term must not act as a wildcard."""
        weird_root = tmp_path / "weird"
        make_image(weird_root / "100%_real.png")
        store.scan([weird_root])
        memes, _ = store.list_memes(search="100%_real", limit=10)
        assert len(memes) == 1
        memes_wrong, _ = store.list_memes(search="100Xreal", limit=10)
        assert len(memes_wrong) == 0

    def test_filter_by_source(self, store):
        memes, _ = store.list_memes(source="packA", limit=10)
        assert {m["name"] for m in memes} == {"pepe", "shark"}

    def test_filter_starred(self, store):
        store.set_starred(self.ids["pepe"], True)
        memes, _ = store.list_memes(starred=True, limit=10)
        assert [m["name"] for m in memes] == ["pepe"]
        memes, _ = store.list_memes(starred=False, limit=10)
        assert "pepe" not in {m["name"] for m in memes}

    def test_filter_selected(self, store):
        store.set_selected(self.ids["shark"], True)
        memes, _ = store.list_memes(selected=True, limit=10)
        assert [m["name"] for m in memes] == ["shark"]

    def test_starred_and_selected_are_independent(self, store):
        """Starring something must not select it, and vice versa."""
        store.set_starred(self.ids["pepe"], True)
        m = store.get_meme(self.ids["pepe"])
        assert m["selected_seq"] is None
        store.set_selected(self.ids["shark"], True)
        m = store.get_meme(self.ids["shark"])
        assert m["starred"] == 0

    def test_pagination(self, store):
        page1, total = store.list_memes(limit=2, offset=0)
        page2, _ = store.list_memes(limit=2, offset=2)
        assert total == 4
        assert len(page1) == 2
        assert len(page2) == 2
        assert {m["id"] for m in page1}.isdisjoint({m["id"] for m in page2})


# ---------------------------------------------------------------------------
# selection ordering
# ---------------------------------------------------------------------------

class TestSelection:
    @pytest.fixture(autouse=True)
    def seeded(self, store, image_root):
        store.scan([image_root])
        self.ids = {m["name"]: m["id"] for m in store.list_memes(limit=10)[0]}

    def test_selection_order_matches_selection_calls(self, store):
        store.set_selected(self.ids["shark"], True)
        store.set_selected(self.ids["pepe"], True)
        ordered = store.selected_ordered()
        assert [m["name"] for m in ordered] == ["shark", "pepe"]

    def test_deselect_then_reselect_goes_to_the_end(self, store):
        """Sequence numbers must never be reused: this is what fixes code
        point assignment order, so a deselect+reselect changing the order
        would silently reassign every meme after it to a new code point."""
        store.set_selected(self.ids["shark"], True)
        store.set_selected(self.ids["pepe"], True)
        store.set_selected(self.ids["shark"], False)
        store.set_selected(self.ids["shark"], True)
        ordered = store.selected_ordered()
        assert [m["name"] for m in ordered] == ["pepe", "shark"]

    def test_unselected_items_excluded(self, store):
        store.set_selected(self.ids["shark"], True)
        ordered = store.selected_ordered()
        assert [m["name"] for m in ordered] == ["shark"]

    def test_reorder_up(self, store):
        store.set_selected(self.ids["shark"], True)
        store.set_selected(self.ids["pepe"], True)
        store.reorder_selected(self.ids["pepe"], -1)
        ordered = store.selected_ordered()
        assert [m["name"] for m in ordered] == ["pepe", "shark"]

    def test_reorder_down(self, store):
        store.set_selected(self.ids["shark"], True)
        store.set_selected(self.ids["pepe"], True)
        store.reorder_selected(self.ids["shark"], 1)
        ordered = store.selected_ordered()
        assert [m["name"] for m in ordered] == ["pepe", "shark"]

    def test_reorder_past_the_end_is_a_noop(self, store):
        store.set_selected(self.ids["shark"], True)
        ok = store.reorder_selected(self.ids["shark"], 1)
        assert ok is False
        assert [m["name"] for m in store.selected_ordered()] == ["shark"]

    def test_reorder_unselected_item_fails(self, store):
        store.set_selected(self.ids["shark"], True)
        ok = store.reorder_selected(self.ids["pepe"], -1)
        assert ok is False

    def test_reorder_preserves_relative_order_of_others(self, store):
        """Swapping two adjacent items must not disturb a third."""
        store.set_selected(self.ids["shark"], True)
        store.set_selected(self.ids["pepe"], True)
        store.set_selected(self.ids["flat"], True)
        store.reorder_selected(self.ids["pepe"], -1)  # shark,pepe,flat -> pepe,shark,flat
        assert [m["name"] for m in store.selected_ordered()] == ["pepe", "shark", "flat"]

    def test_clear_selection(self, store):
        store.set_selected(self.ids["shark"], True)
        store.set_selected(self.ids["pepe"], True)
        n = store.clear_selection()
        assert n == 2
        assert store.selected_ordered() == []

    def test_selecting_unknown_id_returns_false(self, store):
        assert store.set_selected(999999, True) is False

    def test_starring_unknown_id_returns_false(self, store):
        assert store.set_starred(999999, True) is False


# ---------------------------------------------------------------------------
# sources
# ---------------------------------------------------------------------------

class TestSources:
    def test_groups_and_counts(self, store, image_root):
        store.scan([image_root])
        sources = {s["source"]: s["n"] for s in store.sources()}
        assert sources["packA"] == 2

    def test_missing_files_excluded_from_counts(self, store, tmp_path):
        root = tmp_path / "solo"
        make_image(root / "only.png")
        store.scan([root])
        (root / "only.png").unlink()
        store.scan([root])
        sources = {s["source"]: s["n"] for s in store.sources()}
        assert root.name not in sources
