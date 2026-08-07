"""SQLite-backed store for the meme picker web UI.

Two independent flags per meme: `starred` (a bookmark for filtering while
browsing) and `selected_seq` (non-null iff the meme is in the working set
that gets baked into the next generated font, and the order it was added).
They're deliberately separate columns rather than one — starring is a
convenience for narrowing down what you're looking at; selecting is a
distinct decision about what goes in the font, so switching a filter should
never change what's about to be generated.
"""

import sqlite3
import threading
import time
from pathlib import Path

from PIL import Image

from emojifont.fetch import IMAGE_SUFFIXES

SCHEMA = """
CREATE TABLE IF NOT EXISTS memes (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    root TEXT NOT NULL,
    rel_path TEXT NOT NULL,
    name TEXT NOT NULL,
    source TEXT NOT NULL,
    ext TEXT NOT NULL,
    width INTEGER,
    height INTEGER,
    starred INTEGER NOT NULL DEFAULT 0,
    selected_seq INTEGER,
    missing INTEGER NOT NULL DEFAULT 0,
    added_at REAL NOT NULL,
    UNIQUE(root, rel_path)
);
CREATE INDEX IF NOT EXISTS idx_memes_starred ON memes(starred);
CREATE INDEX IF NOT EXISTS idx_memes_selected_seq ON memes(selected_seq);
CREATE INDEX IF NOT EXISTS idx_memes_source ON memes(source);
"""


class Store:
    """Thread-safe wrapper around one sqlite connection.

    SQLite serializes writes regardless of how many connections you open;
    using a single connection plus an explicit lock makes that serialization
    visible in the code instead of surfacing as sporadic "database is locked"
    errors under the ThreadingHTTPServer's concurrent requests.
    """

    def __init__(self, db_path):
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()
        self._conn = sqlite3.connect(str(self.db_path), check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        with self._lock:
            self._conn.executescript(SCHEMA)
            self._conn.commit()

    def close(self):
        self._conn.close()

    # -- scanning ---------------------------------------------------------

    def scan(self, roots):
        """Walk each root for image files and add any not already indexed.

        Existing rows (matched on root+rel_path) are left untouched — a
        rescan after downloading more memes must not reset stars or the
        selection you already built. Files that vanish are flagged `missing`
        rather than deleted, so a star/select survives a renamed folder or a
        temporarily unmounted drive instead of silently dropping the meme
        out of your selection.

        Returns (added, missing) counts.
        """
        found = set()
        added = 0
        with self._lock:
            resolved_roots = []
            for root in roots:
                root = Path(root).resolve()
                if not root.is_dir():
                    continue
                resolved_roots.append(str(root))
                for path in sorted(root.rglob("*")):
                    if not path.is_file() or path.suffix.lower() not in IMAGE_SUFFIXES:
                        continue
                    rel = str(path.relative_to(root))
                    found.add((str(root), rel))
                    row = self._conn.execute(
                        "SELECT id FROM memes WHERE root = ? AND rel_path = ?",
                        (str(root), rel),
                    ).fetchone()
                    if row:
                        self._conn.execute("UPDATE memes SET missing = 0 WHERE id = ?", (row["id"],))
                        continue
                    width = height = None
                    try:
                        with Image.open(path) as im:
                            width, height = im.size
                    except Exception:
                        pass  # not a real/decodable image; keep the row but without dimensions
                    parts = Path(rel).parts
                    source = parts[0] if len(parts) > 1 else root.name
                    self._conn.execute(
                        "INSERT INTO memes (root, rel_path, name, source, ext, width, height, added_at)"
                        " VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                        (str(root), rel, path.stem, source, path.suffix.lower(),
                         width, height, time.time()),
                    )
                    added += 1

            missing = 0
            if resolved_roots:
                placeholders = ",".join("?" * len(resolved_roots))
                rows = self._conn.execute(
                    f"SELECT id, root, rel_path, missing FROM memes WHERE root IN ({placeholders})",
                    resolved_roots,
                ).fetchall()
                for r in rows:
                    is_found = (r["root"], r["rel_path"]) in found
                    if not is_found and not r["missing"]:
                        self._conn.execute("UPDATE memes SET missing = 1 WHERE id = ?", (r["id"],))
                        missing += 1
            self._conn.commit()
        return added, missing

    # -- queries ------------------------------------------------------------

    def list_memes(self, search=None, source=None, starred=None, selected=None,
                   limit=300, offset=0, include_missing=False):
        where = ["1=1"]
        args = []
        if not include_missing:
            where.append("missing = 0")
        if search:
            where.append("name LIKE ? ESCAPE '\\'")
            escaped = search.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
            args.append(f"%{escaped}%")
        if source:
            where.append("source = ?")
            args.append(source)
        if starred is not None:
            where.append("starred = ?")
            args.append(1 if starred else 0)
        if selected is not None:
            where.append("selected_seq IS " + ("NOT NULL" if selected else "NULL"))
        clause = " AND ".join(where)

        with self._lock:
            total = self._conn.execute(
                f"SELECT COUNT(*) FROM memes WHERE {clause}", args
            ).fetchone()[0]
            rows = self._conn.execute(
                f"SELECT * FROM memes WHERE {clause}"
                " ORDER BY selected_seq IS NULL, selected_seq, name COLLATE NOCASE"
                " LIMIT ? OFFSET ?",
                [*args, limit, offset],
            ).fetchall()
        return [dict(r) for r in rows], total

    def get_meme(self, meme_id):
        with self._lock:
            row = self._conn.execute("SELECT * FROM memes WHERE id = ?", (meme_id,)).fetchone()
        return dict(row) if row else None

    def sources(self):
        with self._lock:
            rows = self._conn.execute(
                "SELECT source, COUNT(*) AS n FROM memes WHERE missing = 0"
                " GROUP BY source ORDER BY source COLLATE NOCASE"
            ).fetchall()
        return [dict(r) for r in rows]

    def selected_ordered(self):
        with self._lock:
            rows = self._conn.execute(
                "SELECT * FROM memes WHERE selected_seq IS NOT NULL AND missing = 0"
                " ORDER BY selected_seq"
            ).fetchall()
        return [dict(r) for r in rows]

    # -- mutations ------------------------------------------------------------

    def set_starred(self, meme_id, starred):
        with self._lock:
            cur = self._conn.execute(
                "UPDATE memes SET starred = ? WHERE id = ?", (1 if starred else 0, meme_id)
            )
            self._conn.commit()
            return cur.rowcount > 0

    def set_selected(self, meme_id, selected):
        """Toggle selection, assigning the next sequence number when turning on.

        The sequence is a monotonic counter, never reused: deselecting then
        reselecting a meme puts it at the end of the order rather than back
        in its old spot. That order is what fixes code point order at
        generation time, so it needs to mean "when did you decide this
        belongs in the font", not "where did it used to be".
        """
        with self._lock:
            if selected:
                next_seq = self._conn.execute(
                    "SELECT COALESCE(MAX(selected_seq), 0) + 1 FROM memes"
                ).fetchone()[0]
                cur = self._conn.execute(
                    "UPDATE memes SET selected_seq = ? WHERE id = ?", (next_seq, meme_id)
                )
            else:
                cur = self._conn.execute(
                    "UPDATE memes SET selected_seq = NULL WHERE id = ?", (meme_id,)
                )
            self._conn.commit()
            return cur.rowcount > 0

    def reorder_selected(self, meme_id, direction):
        """Swap a selected meme with its neighbor. direction: -1 (up) or +1 (down).

        Swapping the two rows' seq values (rather than renumbering the whole
        list) keeps every other meme's position untouched even though the
        sequence has gaps from past deselections.
        """
        with self._lock:
            rows = self._conn.execute(
                "SELECT id, selected_seq FROM memes WHERE selected_seq IS NOT NULL"
                " ORDER BY selected_seq"
            ).fetchall()
            ids = [r["id"] for r in rows]
            if meme_id not in ids:
                return False
            i = ids.index(meme_id)
            j = i + direction
            if j < 0 or j >= len(ids):
                return False
            a, b = rows[i], rows[j]
            self._conn.execute("UPDATE memes SET selected_seq = ? WHERE id = ?",
                              (b["selected_seq"], a["id"]))
            self._conn.execute("UPDATE memes SET selected_seq = ? WHERE id = ?",
                              (a["selected_seq"], b["id"]))
            self._conn.commit()
            return True

    def clear_selection(self):
        with self._lock:
            cur = self._conn.execute("UPDATE memes SET selected_seq = NULL WHERE selected_seq IS NOT NULL")
            self._conn.commit()
            return cur.rowcount
