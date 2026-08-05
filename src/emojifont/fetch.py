"""
Browse and download meme images from public Discord/Slack emoji sources.

The point is manual selection: `list` shows you what's available (optionally as
an HTML contact sheet, since you can't judge a meme from its filename), and
`get` downloads only the ones you name and prints the --mappings string for
`emojifont`.

    emojifont-fetch packs --search pepe
    emojifont-fetch list --pack 983085-pepe --html /tmp/sheet.html
    emojifont-fetch get pepehappy pepeok --out memes/

Animated GIFs are skipped by default: SBIX holds a single still per glyph, so
an animated source would only ever show one frame.
"""

import argparse
import html
import json
import os
import sys
import time
import unicodedata
import urllib.request
from dataclasses import dataclass
from pathlib import Path

USER_AGENT = "emojifont/0.1 (+https://github.com/pj/emojifont)"
CACHE_TTL_SECONDS = 24 * 60 * 60

EMOJI_GG_INDEX = "https://emoji.gg/api/"
EMOJI_GG_PACKS = "https://emoji.gg/api/packs"
EMOJI_GG_CDN = "https://cdn3.emoji.gg/emojis"
SLACKMOJIS_INDEX = "https://slackmojis.com/emojis.json"

SOURCES = ("emoji.gg", "slackmojis")

# CJK Compatibility Ideographs. Terminals treat these as East Asian Wide, so
# they get two cells — the room a meme needs to render at full emoji size.
# See cells_for_codepoint() in inject.py.
DEFAULT_START_CODEPOINT = 0xF900
CODEPOINT_BLOCK_END = 0xFAFF

STATIC_SUFFIXES = (".png", ".jpg", ".jpeg", ".webp")


@dataclass
class Emoji:
    """One downloadable image from a source."""
    id: str          # stable, unique within a source (used to select it)
    name: str        # short human-readable name
    url: str
    source: str
    category: str = ""

    @property
    def suffix(self):
        return "." + self.url.split("?")[0].rsplit(".", 1)[-1].lower()

    @property
    def is_static(self):
        return self.suffix in STATIC_SUFFIXES


@dataclass
class Pack:
    slug: str
    name: str
    description: str
    filenames: list


# --------------------------------------------------------------------------- #
# HTTP + caching                                                               #
# --------------------------------------------------------------------------- #

def cache_dir():
    base = os.environ.get("XDG_CACHE_HOME") or (Path.home() / ".cache")
    d = Path(base) / "emojifont"
    d.mkdir(parents=True, exist_ok=True)
    return d


def http_get(url, timeout=30):
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return resp.read()


def cached_json(url, cache_name, refresh=False):
    """Fetch JSON, caching to disk. These indexes are thousands of entries and
    barely change; re-downloading between `list` and `get` would be wasteful."""
    path = cache_dir() / cache_name
    if not refresh and path.exists():
        age = time.time() - path.stat().st_mtime
        if age < CACHE_TTL_SECONDS:
            try:
                return json.loads(path.read_text())
            except (json.JSONDecodeError, OSError):
                pass  # fall through and refetch
    data = json.loads(http_get(url).decode("utf-8"))
    try:
        path.write_text(json.dumps(data))
    except OSError:
        pass  # a broken cache write shouldn't fail the command
    return data


# --------------------------------------------------------------------------- #
# Sources                                                                      #
# --------------------------------------------------------------------------- #

def fetch_index(source="emoji.gg", refresh=False):
    """All individual emoji available from a source."""
    if source == "emoji.gg":
        raw = cached_json(EMOJI_GG_INDEX, "emoji_gg_index.json", refresh)
        return [
            Emoji(
                id=str(e.get("slug") or e.get("id")),
                name=str(e.get("title") or e.get("slug") or e.get("id")),
                url=e["image"],
                source="emoji.gg",
                category=str(e.get("category", "")),
            )
            for e in raw
            if e.get("image")
        ]
    if source == "slackmojis":
        raw = cached_json(SLACKMOJIS_INDEX, "slackmojis_index.json", refresh)
        return [
            Emoji(
                id=str(e.get("name") or e.get("id")),
                name=str(e.get("name") or e.get("id")),
                url=e["image_url"],
                source="slackmojis",
                category=str((e.get("category") or {}).get("name", "")),
            )
            for e in raw
            if e.get("image_url")
        ]
    raise ValueError(f"Unknown source: {source} (expected one of {', '.join(SOURCES)})")


def fetch_packs(refresh=False):
    """Curated emoji.gg packs. slackmojis has categories, not packs."""
    raw = cached_json(EMOJI_GG_PACKS, "emoji_gg_packs.json", refresh)
    packs = []
    for p in raw:
        files = [f.strip() for f in (p.get("emojis") or "").split(",") if f.strip()]
        packs.append(Pack(
            slug=str(p.get("slug") or p.get("id")),
            name=str(p.get("name", "")),
            description=str(p.get("description", "")),
            filenames=files,
        ))
    return packs


def pack_emoji(pack):
    """Expand a pack's filename list into Emoji records.

    Pack entries are bare filenames like '795083-pepehappy.png'; they resolve
    under the plain /emojis/ CDN path (the /packs/ subpath returns 403).
    """
    out = []
    for fn in pack.filenames:
        stem = fn.rsplit(".", 1)[0]
        # Strip the numeric upload id to get something readable
        short = stem.split("-", 1)[1] if "-" in stem and stem.split("-", 1)[0].isdigit() else stem
        out.append(Emoji(
            id=stem,
            name=short,
            url=f"{EMOJI_GG_CDN}/{fn}",
            source="emoji.gg",
            category=pack.name,
        ))
    return out


# --------------------------------------------------------------------------- #
# Selection                                                                    #
# --------------------------------------------------------------------------- #

def _norm(s):
    return unicodedata.normalize("NFKD", str(s)).casefold()


def search_emoji(index, query):
    """Substring match on name, id and category, case-insensitive."""
    q = _norm(query)
    return [e for e in index if q in _norm(e.name) or q in _norm(e.id) or q in _norm(e.category)]


def find_pack(packs, query):
    """Exact slug match first, then substring on slug/name/description."""
    for p in packs:
        if p.slug == query:
            return p
    q = _norm(query)
    matches = [p for p in packs if q in _norm(p.slug) or q in _norm(p.name) or q in _norm(p.description)]
    if len(matches) == 1:
        return matches[0]
    if not matches:
        raise LookupError(f"No pack matching {query!r}")
    raise LookupError(
        f"{len(matches)} packs match {query!r}; be more specific:\n  "
        + "\n  ".join(f"{p.slug}  ({p.name})" for p in matches[:10])
    )


def resolve_names(index, names):
    """Map user-supplied names to Emoji records.

    Matches on exact id, then exact name, then unique substring. Raises on
    anything ambiguous or missing so a typo can't silently drop a meme from
    the selection.
    """
    by_id = {e.id: e for e in index}
    resolved, errors = [], []
    for want in names:
        if want in by_id:
            resolved.append(by_id[want])
            continue
        exact = [e for e in index if e.name == want]
        if len(exact) == 1:
            resolved.append(exact[0])
            continue
        cands = exact or search_emoji(index, want)
        if len(cands) == 1:
            resolved.append(cands[0])
        elif not cands:
            errors.append(f"  {want!r}: no match")
        else:
            preview = ", ".join(sorted({c.id for c in cands})[:6])
            errors.append(f"  {want!r}: {len(cands)} matches ({preview}...) — use an exact id")
    if errors:
        raise LookupError("Could not resolve:\n" + "\n".join(errors))
    return resolved


def assign_codepoints(count, start=DEFAULT_START_CODEPOINT):
    """Consecutive code points for the selected memes."""
    end = start + count - 1
    if end > CODEPOINT_BLOCK_END:
        raise ValueError(
            f"{count} memes starting at U+{start:04X} runs past U+{CODEPOINT_BLOCK_END:04X}, "
            f"the end of the CJK Compatibility Ideographs block. "
            f"Room for {CODEPOINT_BLOCK_END - start + 1} here."
        )
    return list(range(start, start + count))


def mappings_string(pairs):
    """Build the --mappings argument: 'U+F900:a.png,U+F901:b.png'."""
    return ",".join(f"U+{cp:04X}:{path}" for cp, path in pairs)


# --------------------------------------------------------------------------- #
# Output                                                                       #
# --------------------------------------------------------------------------- #

def claim_filename(emoji, taken):
    """Pick a filename for `emoji` not already in `taken`, and claim it.

    Falls back from the short name to the id, then to a numeric suffix. The
    last step matters for sources like slackmojis where the id *is* the name:
    without it, entries sharing a name (there are three 'facepalm's) would
    collapse onto one file and quietly disappear from the dump.

    Only in-run claims are consulted, never the filesystem, so re-running the
    same selection overwrites in place instead of accumulating copies.
    """
    if taken is None:
        return f"{emoji.name}{emoji.suffix}"
    for candidate in (f"{emoji.name}{emoji.suffix}", f"{emoji.id}{emoji.suffix}"):
        if candidate not in taken:
            taken.add(candidate)
            return candidate
    n = 2
    while f"{emoji.name}-{n}{emoji.suffix}" in taken:
        n += 1
    name = f"{emoji.name}-{n}{emoji.suffix}"
    taken.add(name)
    return name


def download(emoji, out_dir, taken=None):
    """Download one emoji, returning the written path."""
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    dest = out_dir / claim_filename(emoji, taken)
    dest.write_bytes(http_get(emoji.url))
    return dest


def write_contact_sheet(emojis, path, title="emojifont — pick your memes", src_map=None):
    """Write a browsable grid of thumbnails.

    Images are hotlinked by default so this stays fast for a few thousand
    entries; it needs a network connection to view. Pass src_map ({emoji id:
    src}) to point at already-downloaded local files instead.
    """
    cards = []
    for e in emojis:
        src = (src_map or {}).get(e.id, e.url)
        badge = "" if e.is_static else '<span class="anim">GIF</span>'
        cards.append(
            f'<figure><img loading="lazy" src="{html.escape(src)}" alt="">'
            f"{badge}<figcaption>{html.escape(e.name)}"
            f'<code>{html.escape(e.id)}</code></figcaption></figure>'
        )
    doc = f"""<!doctype html>
<html><head><meta charset="utf-8"><title>{html.escape(title)}</title><style>
 body {{ font: 14px/1.4 system-ui, sans-serif; margin: 2rem; background: #16161a; color: #eee; }}
 h1 {{ font-size: 1.1rem; font-weight: 600; }}
 p.hint {{ color: #9aa; }}
 .grid {{ display: grid; grid-template-columns: repeat(auto-fill, minmax(110px, 1fr)); gap: 1rem; }}
 figure {{ margin: 0; text-align: center; background: #22222a; border-radius: 8px; padding: .6rem; position: relative; }}
 img {{ width: 64px; height: 64px; object-fit: contain; }}
 figcaption {{ font-size: 11px; margin-top: .4rem; word-break: break-all; }}
 code {{ display: block; color: #8ab; font-size: 10px; margin-top: .2rem; }}
 .anim {{ position: absolute; top: .4rem; right: .4rem; background: #b34; color: #fff;
          font-size: 9px; padding: 1px 4px; border-radius: 3px; }}
</style></head><body>
<h1>{html.escape(title)} — {len(emojis)} images</h1>
<p class="hint">Pick the ones you want, then pass the <code>id</code> values (small blue text) to
<code>emojifont-fetch get</code>. Entries badged GIF are animated and are skipped by default.</p>
<div class="grid">{''.join(cards)}</div>
</body></html>"""
    Path(path).write_text(doc, encoding="utf-8")
    return path


# --------------------------------------------------------------------------- #
# CLI                                                                          #
# --------------------------------------------------------------------------- #

def _load(args):
    """Resolve the candidate emoji set implied by --pack / --search / --source."""
    if getattr(args, "pack", None):
        pack = find_pack(fetch_packs(args.refresh), args.pack)
        emojis = pack_emoji(pack)
        label = f"pack {pack.slug} ({pack.name})"
    else:
        emojis = fetch_index(args.source, args.refresh)
        label = f"source {args.source}"
    if getattr(args, "search", None):
        emojis = search_emoji(emojis, args.search)
        label += f" matching {args.search!r}"
    return emojis, label


def cmd_packs(args):
    packs = fetch_packs(args.refresh)
    if args.search:
        q = _norm(args.search)
        packs = [p for p in packs
                 if q in _norm(p.slug) or q in _norm(p.name) or q in _norm(p.description)]
    print(f"{len(packs)} pack(s)\n")
    for p in packs[:args.limit]:
        static = sum(1 for f in p.filenames if f.lower().endswith(STATIC_SUFFIXES))
        print(f"  {p.slug:<28} {p.name[:24]:<24} {len(p.filenames):>4} emoji ({static} static)")
    return 0


def cmd_list(args):
    emojis, label = _load(args)
    if not args.include_animated:
        animated = [e for e in emojis if not e.is_static]
        emojis = [e for e in emojis if e.is_static]
        if animated:
            print(f"({len(animated)} animated skipped; --include-animated to show)", file=sys.stderr)
    print(f"{len(emojis)} image(s) from {label}\n")
    for e in emojis[:args.limit]:
        flag = "" if e.is_static else "  [animated]"
        print(f"  {e.id:<34} {e.name[:22]:<22} {e.suffix:<6}{flag}")
    if len(emojis) > args.limit:
        print(f"\n  ... {len(emojis) - args.limit} more (raise --limit)")
    if args.html:
        write_contact_sheet(emojis[:args.limit], args.html, f"emojifont — {label}")
        print(f"\nContact sheet: {args.html}")
    return 0


def dump_group(emojis, out_dir, jobs=8, skip_existing=True, on_done=None):
    """Download a batch of emoji into out_dir, in parallel.

    Returns (written, skipped, failures). Individual failures are collected
    rather than raised: across thousands of user-submitted entries a few dead
    CDN links are normal, and they shouldn't abort the whole dump.
    """
    from concurrent.futures import ThreadPoolExecutor

    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    # Claim filenames up front, single-threaded, so collision handling is
    # deterministic rather than dependent on which thread finishes first.
    taken, planned = set(), []
    for e in emojis:
        planned.append((e, out_dir / claim_filename(e, taken)))

    written, skipped, failures = [], [], []

    def one(item):
        e, dest = item
        if skip_existing and dest.exists() and dest.stat().st_size > 0:
            return ("skip", e, dest, None)
        try:
            dest.write_bytes(http_get(e.url))
            return ("ok", e, dest, None)
        except Exception as exc:  # noqa: BLE001 - report and keep going
            return ("fail", e, dest, exc)

    with ThreadPoolExecutor(max_workers=jobs) as pool:
        for status, e, dest, exc in pool.map(one, planned):
            if status == "ok":
                written.append((e, dest))
            elif status == "skip":
                skipped.append((e, dest))
            else:
                failures.append((e, exc))
            if on_done:
                on_done(status, e)
    return written, skipped, failures


def sheet_entries_from_disk(out_root):
    """Build contact-sheet entries from everything already in the dump.

    Scanning the directory rather than just the current run's groups means
    index.html always covers the whole dump; otherwise dumping a second source
    would rewrite the sheet to show only that source.
    """
    out_root = Path(out_root)
    entries, srcs = [], {}
    for path in sorted(out_root.rglob("*")):
        if not path.is_file() or path.suffix.lower() not in STATIC_SUFFIXES + (".gif",):
            continue
        rel = path.relative_to(out_root)
        group = rel.parent.name if rel.parent != Path(".") else ""
        entries.append(Emoji(id=str(rel.with_suffix("")), name=path.stem,
                             url=str(rel), source="disk", category=group))
        srcs[str(rel.with_suffix(""))] = str(rel)
    return entries, srcs


def cmd_dump(args):
    """Bulk-download everything so you can cherry-pick in a file browser."""
    out_root = Path(args.out)
    groups = []

    if args.pack:
        pack = find_pack(fetch_packs(args.refresh), args.pack)
        groups.append((pack.slug, pack_emoji(pack)))
    elif args.source == "emoji.gg" and not args.no_packs:
        packs = fetch_packs(args.refresh)
        if args.search:
            q = _norm(args.search)
            packs = [p for p in packs if q in _norm(p.slug) or q in _norm(p.name)
                     or q in _norm(p.description)]
        groups = [(p.slug, pack_emoji(p)) for p in packs]
    else:
        emojis = fetch_index(args.source, args.refresh)
        if args.search:
            emojis = search_emoji(emojis, args.search)
        groups.append((args.source.replace(".", "_"), emojis))

    if not args.include_animated:
        groups = [(n, [e for e in g if e.is_static]) for n, g in groups]
    groups = [(n, g) for n, g in groups if g]

    total = sum(len(g) for _, g in groups)
    if args.max_images and total > args.max_images:
        raise SystemExit(
            f"{total} images exceeds --max-images {args.max_images}. "
            f"Narrow with --pack/--search, or raise the cap."
        )
    print(f"Dumping {total} image(s) across {len(groups)} group(s) -> {out_root}\n")

    all_written = all_skipped = 0
    all_failures = []
    for name, emojis in groups:
        target = out_root if args.flat else out_root / name
        written, skipped, failures = dump_group(
            emojis, target, jobs=args.jobs, skip_existing=not args.overwrite
        )
        all_written += len(written)
        all_skipped += len(skipped)
        all_failures += failures
        note = f" ({len(failures)} failed)" if failures else ""
        print(f"  {name:<30} {len(written):>4} new, {len(skipped):>4} present{note}")

    sheet = out_root / "index.html"
    entries, srcs = sheet_entries_from_disk(out_root)
    write_contact_sheet(entries, sheet, f"emojifont — dump of {out_root.name}", src_map=srcs)

    print(f"\n{all_written} downloaded, {all_skipped} already present, "
          f"{len(all_failures)} failed; {len(entries)} image(s) in the dump")
    if all_failures:
        print("\nfailures:")
        for e, exc in all_failures[:15]:
            print(f"  {e.id}: {exc}")
        if len(all_failures) > 15:
            print(f"  ... {len(all_failures) - 15} more")
    print(f"\nBrowse: {sheet}")
    print(f"Then copy the ones you want into your memes directory.")
    return 0


def cmd_get(args):
    emojis, _ = _load(args)
    chosen = resolve_names(emojis, args.names)

    animated = [e for e in chosen if not e.is_static]
    if animated and not args.include_animated:
        raise SystemExit(
            "Refusing to download animated images (SBIX shows one still frame only):\n  "
            + "\n  ".join(e.id for e in animated)
            + "\nPass --include-animated to override."
        )

    codepoints = assign_codepoints(len(chosen), args.start_codepoint)
    pairs, taken = [], set()
    for cp, e in zip(codepoints, chosen):
        dest = download(e, args.out, taken)
        print(f"  U+{cp:04X}  {e.name:<22} -> {dest}")
        pairs.append((cp, dest))

    print(f"\n{len(pairs)} image(s) in {args.out}\n")
    print("--mappings argument:\n")
    print(f"  {mappings_string(pairs)}\n")
    return 0


def _hex_codepoint(s):
    return int(s.removeprefix("U+").removeprefix("u+"), 16)


def main(argv=None):
    parser = argparse.ArgumentParser(
        prog="emojifont-fetch",
        description="Browse and download meme images for emojifont.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""examples:
  emojifont-fetch packs --search pepe
  emojifont-fetch list --pack 983085-pepe --html /tmp/sheet.html
  emojifont-fetch list --search shark --source slackmojis
  emojifont-fetch get pepehappy pepeok --out memes/

Images are user-submitted with mostly unmarked licensing — fine for personal
use, check before redistributing.""",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    def common(p, with_pack=True):
        p.add_argument("--source", choices=SOURCES, default="emoji.gg",
                       help="where to pull from (default: emoji.gg)")
        if with_pack:
            p.add_argument("--pack", help="restrict to an emoji.gg pack (slug or name)")
        p.add_argument("--search", help="filter by substring on name/id/category")
        p.add_argument("--refresh", action="store_true", help="bypass the cached index")
        p.add_argument("--include-animated", action="store_true",
                       help="include GIFs (SBIX renders one still frame only)")

    p_packs = sub.add_parser("packs", help="list curated emoji.gg packs")
    p_packs.add_argument("--search", help="filter packs by substring")
    p_packs.add_argument("--limit", type=int, default=60)
    p_packs.add_argument("--refresh", action="store_true")
    p_packs.set_defaults(func=cmd_packs)

    p_list = sub.add_parser("list", help="list individual images so you can pick")
    common(p_list)
    p_list.add_argument("--limit", type=int, default=200)
    p_list.add_argument("--html", help="also write an HTML contact sheet here")
    p_list.set_defaults(func=cmd_list)

    p_dump = sub.add_parser("dump", help="bulk-download so you can cherry-pick on disk")
    common(p_dump)
    p_dump.add_argument("--out", default="font_build/meme-dump", help="output directory")
    p_dump.add_argument("--flat", action="store_true",
                        help="one directory instead of a subdirectory per pack")
    p_dump.add_argument("--no-packs", action="store_true",
                        help="dump the whole source index rather than curated packs")
    p_dump.add_argument("--overwrite", action="store_true",
                        help="re-download files that are already present")
    p_dump.add_argument("--jobs", type=int, default=8, help="parallel downloads (default 8)")
    p_dump.add_argument("--max-images", type=int, default=6000,
                        help="refuse to start above this many images (default 6000)")
    p_dump.set_defaults(func=cmd_dump)

    p_get = sub.add_parser("get", help="download the images you name")
    p_get.add_argument("names", nargs="+", help="ids or names from `list`")
    common(p_get)
    p_get.add_argument("--out", default="memes", help="output directory (default: memes)")
    p_get.add_argument("--start-codepoint", type=_hex_codepoint, default=DEFAULT_START_CODEPOINT,
                       help="first code point to assign (default: F900)")
    p_get.set_defaults(func=cmd_get)

    args = parser.parse_args(argv)
    try:
        return args.func(args)
    except (LookupError, ValueError) as e:
        print(f"error: {e}", file=sys.stderr)
        return 1
    except urllib.error.URLError as e:
        print(f"error: network request failed: {e}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
