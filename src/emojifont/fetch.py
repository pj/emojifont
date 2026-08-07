"""
Browse and download meme images from public Discord/Slack/Twitch emoji sources.

The point is manual selection: `list` shows you what's available (optionally as
an HTML contact sheet, since you can't judge a meme from its filename), and
`get` downloads only the ones you name and prints the --mappings string for
`emojifont`. `dump`/`ffz-dump` grab everything into a directory with a contact
sheet so you can cherry-pick on disk instead; `dedupe` then collapses the
exact-duplicate content that tends to accumulate across packs and sources.

    emojifont-fetch packs --search pepe
    emojifont-fetch list --pack 983085-pepe --html /tmp/sheet.html
    emojifont-fetch get pepehappy pepeok --out memes/
    emojifont-fetch ffz-dump --pages 100
    emojifont-fetch dedupe --out font_build/memes-deduped

Animated images are skipped by default: SBIX holds a single still per glyph,
so an animated source would only ever show one frame.
"""

import argparse
import hashlib
import html
import json
import os
import shutil
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
FRANKERFACEZ_API = "https://api.frankerfacez.com/v1/emoticons"

SOURCES = ("emoji.gg", "slackmojis", "frankerfacez")

# FrankerFaceZ serves images from extensionless URLs (.../emote/<id>/4), so the
# real format is only known from the response's Content-Type after a request.
CONTENT_TYPE_EXT = {
    "image/png": ".png",
    "image/gif": ".gif",
    "image/webp": ".webp",
    "image/jpeg": ".jpg",
    "image/avif": ".avif",
}

# CJK Compatibility Ideographs. Terminals treat these as East Asian Wide, so
# they get two cells — the room a meme needs to render at full emoji size.
# See cells_for_codepoint() in inject.py.
DEFAULT_START_CODEPOINT = 0xF900
CODEPOINT_BLOCK_END = 0xFAFF

STATIC_SUFFIXES = (".png", ".jpg", ".jpeg", ".webp")
# Static plus animated — the full set of "this is an image file" for browsing
# and deduping purposes, as opposed to STATIC_SUFFIXES which is what's
# actually usable in a generated SBIX font.
IMAGE_SUFFIXES = STATIC_SUFFIXES + (".gif",)


@dataclass
class Emoji:
    """One downloadable image from a source."""
    id: str          # stable, unique within a source (used to select it)
    name: str        # short human-readable name
    url: str
    source: str
    category: str = ""
    # Explicit format override for sources whose URLs carry no extension
    # (e.g. FrankerFaceZ's .../emote/<id>/4). Includes the leading dot.
    ext: str = None

    @property
    def suffix(self):
        if self.ext:
            return self.ext
        # Only the last path segment can hold a real extension — splitting the
        # whole URL would catch the dot in a domain like frankerfacez.com and
        # produce a nonsense "extension".
        last_segment = self.url.split("?")[0].rstrip("/").rsplit("/", 1)[-1]
        if "." not in last_segment:
            return ""
        return "." + last_segment.rsplit(".", 1)[-1].lower()

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


def http_content_type(url, timeout=15):
    """HEAD a URL and return its Content-Type, or "" if unavailable.

    Used for FrankerFaceZ, whose image URLs carry no file extension — the
    format has to be discovered from the response rather than the URL.
    """
    req = urllib.request.Request(url, method="HEAD", headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return resp.headers.get("Content-Type", "").split(";")[0].strip().lower()


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
    if source == "frankerfacez":
        # Unlike the other two sources this isn't a flat index — it's ranked
        # and paginated. `list`/`search` just need enough to browse, so this
        # covers the top few pages by popularity; `ffz-dump` walks as many
        # pages as asked for.
        return frankerfacez_emoji(fetch_frankerfacez_pages(pages=4, per_page=50))
    raise ValueError(f"Unknown source: {source} (expected one of {', '.join(SOURCES)})")


def sniff_content_type_ext(url, timeout=15, default=".png"):
    """Extension implied by a URL's Content-Type, falling back to `default`.

    FFZ overwhelmingly serves PNG (including animated ones as APNG, same
    content-type), so defaulting to .png on a failed/unknown HEAD is the safe
    choice rather than dropping the image.
    """
    try:
        ct = http_content_type(url, timeout=timeout)
    except Exception:  # noqa: BLE001 - a failed HEAD shouldn't drop the image
        return default
    return CONTENT_TYPE_EXT.get(ct, default)


def frankerfacez_best_url(urls):
    """Highest-resolution image FFZ has for an emote: prefer 4x, then 2x, then 1x.

    Not every emote has all sizes — smaller/older ones often lack 4x and 2x.
    """
    for size in ("4", "2", "1"):
        if urls.get(size):
            return urls[size]
    return None


def fetch_frankerfacez_pages(pages, per_page=50, sort="count-desc", jobs=8, timeout=20):
    """Fetch raw FrankerFaceZ emoticon records across `pages` API pages.

    Pages are fetched in parallel (they're independent, offset-only requests)
    but the results are handed back sorted by (page, position) so callers see
    the requested ranking order regardless of which page finished first.
    """
    from concurrent.futures import ThreadPoolExecutor

    def fetch_one(page):
        url = f"{FRANKERFACEZ_API}?page={page}&per_page={per_page}&sort={sort}"
        data = json.loads(http_get(url, timeout=timeout).decode("utf-8"))
        return page, data.get("emoticons", [])

    results = {}
    with ThreadPoolExecutor(max_workers=jobs) as pool:
        for page, emoticons in pool.map(fetch_one, range(1, pages + 1)):
            results[page] = emoticons

    out = []
    for page in range(1, pages + 1):
        out.extend(results.get(page, []))
    return out


def frankerfacez_emoji(raw_records, sniff_ext=True, jobs=8):
    """Convert raw FrankerFaceZ API records to Emoji, in the given order.

    Modifier emotes (tiny overlay icons like "flip") and hidden/removed ones
    are dropped — they aren't the kind of image anyone means by "meme", and
    mixing them in would bury the real emotes in the contact sheet.

    FFZ's URLs carry no file extension, so `is_static`/`suffix` are useless
    without knowing the real format. When sniff_ext is set (the default), a
    HEAD request per emote fills in Emoji.ext from Content-Type — the same
    animated-GIF filtering used for the other sources then works here too.
    Skip it (sniff_ext=False) for cheap, format-agnostic listing.
    """
    from concurrent.futures import ThreadPoolExecutor

    candidates = []
    for e in raw_records:
        if e.get("modifier") or e.get("hidden") or e.get("public") is False:
            continue
        url = frankerfacez_best_url(e.get("urls") or {})
        if not url:
            continue
        candidates.append((str(e["id"]), str(e["name"]), url, str(e.get("usage_count", ""))))

    if not candidates:
        return []

    exts = [None] * len(candidates)
    if sniff_ext:
        with ThreadPoolExecutor(max_workers=jobs) as pool:
            exts = list(pool.map(lambda c: sniff_content_type_ext(c[2]), candidates))

    return [
        Emoji(id=id_, name=name, url=url, source="frankerfacez", category=cat, ext=ext)
        for (id_, name, url, cat), ext in zip(candidates, exts)
    ]


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

    Collisions are checked case-insensitively even though the returned name
    keeps its original case: the usual target filesystems (macOS APFS,
    Windows) are case-insensitive-but-preserving, so "Pog.png" and "pog.png"
    are the *same file* there even though they're different Python strings —
    treating them as distinct would silently overwrite one with the other
    without either name ever hitting the "already taken" branch below.

    Only in-run claims are consulted, never the filesystem, so re-running the
    same selection overwrites in place instead of accumulating copies.
    """
    if taken is None:
        return f"{emoji.name}{emoji.suffix}"
    for candidate in (f"{emoji.name}{emoji.suffix}", f"{emoji.id}{emoji.suffix}"):
        if candidate.lower() not in taken:
            taken.add(candidate.lower())
            return candidate
    n = 2
    while f"{emoji.name}-{n}{emoji.suffix}".lower() in taken:
        n += 1
    name = f"{emoji.name}-{n}{emoji.suffix}"
    taken.add(name.lower())
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
# Dedupe                                                                       #
#                                                                              #
# The dump commands produce a lot of exact-duplicate content: the same meme   #
# gets uploaded to multiple packs, or independently to both emoji.gg and      #
# FrankerFaceZ. That's a different problem from claim_filename()'s: this      #
# dedupes by *file content* across everything already on disk, not by *name*  #
# among files about to be written in one run.                                #
# --------------------------------------------------------------------------- #

def default_dump_dirs(project_root):
    """The directories the dump/ffz-dump commands write to, plus the curated
    memes/ directory — the default place to look for duplicates."""
    candidates = [
        Path(project_root) / "font_build" / "meme-dump",
        Path(project_root) / "font_build" / "ffz-dump",
        Path(project_root) / "font_build" / "memes",
    ]
    return [d for d in candidates if d.is_dir()]


def iter_candidate_files(dirs):
    """Yield image files from `dirs` in stable "first found wins" order:
    directories in the order given, files within each directory sorted.

    That order is what makes "the id of the meme is the name of the first
    one found" well-defined — callers should list directories in the
    precedence they want ties broken.
    """
    for d in dirs:
        d = Path(d)
        if not d.is_dir():
            continue
        for path in sorted(d.rglob("*")):
            if path.is_file() and path.suffix.lower() in IMAGE_SUFFIXES:
                yield path


def hash_file(path, chunk_size=1 << 20):
    """SHA-256 of a file's contents, read in chunks so file size doesn't matter."""
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(chunk_size), b""):
            h.update(chunk)
    return h.hexdigest()


def _hash_or_error(path):
    try:
        return path, hash_file(path), None
    except OSError as exc:
        return path, None, exc


def claim_output_name(path, taken):
    """Pick a collision-free destination filename for a deduped survivor.

    Two *different* memes can share a filename across source directories
    (e.g. two unrelated images both called "pepe.png" in different packs).
    This only has to break ties among survivors of content-dedup, so it's
    rare — but silently letting one overwrite the other on copy would be
    worse than an ugly name. Escalates bare name -> source-qualified name ->
    numeric suffix, the same ladder claim_filename() uses in the dump
    commands, including tracking claims case-insensitively: macOS (APFS) and
    Windows treat "Pog.png" and "pog.png" as the same file even though
    they're different Python strings, so a case-only difference must still
    count as taken or one file quietly clobbers the other on disk.
    """
    stem, suffix = path.stem, path.suffix.lower()
    source_label = path.parent.name
    for candidate in (f"{stem}{suffix}", f"{stem}__{source_label}{suffix}"):
        if candidate.lower() not in taken:
            taken.add(candidate.lower())
            return candidate
    n = 2
    while f"{stem}__{source_label}-{n}{suffix}".lower() in taken:
        n += 1
    name = f"{stem}__{source_label}-{n}{suffix}"
    taken.add(name.lower())
    return name


@dataclass
class DedupeResult:
    kept: list        # [(source_path, dest_path)] — one dest_path per unique content hash
    duplicates: list  # [(source_path, kept_source_path)] — files that were skipped, and why
    errors: list       # [(source_path, exception)] — files that couldn't be hashed


def dedupe_images(dirs, out_dir, jobs=8, hardlink=False, dry_run=False):
    """Copy exactly one file per distinct content hash from `dirs` into `out_dir`.

    Hashing happens in a thread pool (I/O-bound: thousands of small file
    reads), but ThreadPoolExecutor.map() yields results in the same order the
    inputs were submitted regardless of which thread finishes first — the
    same ordering guarantee fetch_frankerfacez_pages() relies on — so "first
    found wins" is still decided by iter_candidate_files()'s order, not by
    hashing speed.
    """
    from concurrent.futures import ThreadPoolExecutor

    files = list(iter_candidate_files(dirs))

    if jobs > 1 and len(files) > 1:
        with ThreadPoolExecutor(max_workers=jobs) as pool:
            hashed = list(pool.map(_hash_or_error, files))
    else:
        hashed = [_hash_or_error(p) for p in files]

    seen, kept_paths, duplicates, errors = {}, [], [], []
    for path, digest, exc in hashed:
        if exc is not None:
            errors.append((path, exc))
        elif digest in seen:
            duplicates.append((path, seen[digest]))
        else:
            seen[digest] = path
            kept_paths.append(path)

    out_dir = Path(out_dir)
    if not dry_run:
        out_dir.mkdir(parents=True, exist_ok=True)

    taken, kept = set(), []
    for path in kept_paths:
        dest = out_dir / claim_output_name(path, taken)
        if not dry_run:
            if hardlink:
                if dest.exists():
                    dest.unlink()
                try:
                    os.link(path, dest)
                except OSError:
                    shutil.copy2(path, dest)  # e.g. cross-filesystem; fall back to a real copy
            else:
                shutil.copy2(path, dest)
        kept.append((path, dest))

    return DedupeResult(kept=kept, duplicates=duplicates, errors=errors)


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
        if not path.is_file() or path.suffix.lower() not in IMAGE_SUFFIXES:
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


def cmd_ffz_dump(args):
    """Page through FrankerFaceZ by popularity and bulk-download the results."""
    print(f"Fetching {args.pages} page(s) of {args.per_page} (~{args.pages * args.per_page} "
          f"emotes, sort={args.sort})...")
    raw = fetch_frankerfacez_pages(args.pages, per_page=args.per_page, sort=args.sort, jobs=args.jobs)

    print("Checking image formats (HEAD per emote, this is the slow part)...")
    emojis = frankerfacez_emoji(raw, sniff_ext=True, jobs=args.jobs)

    skipped_animated = 0
    if not args.include_animated:
        before = len(emojis)
        emojis = [e for e in emojis if e.is_static]
        skipped_animated = before - len(emojis)

    if not emojis:
        print("Nothing to download.")
        return 0

    if args.max_images and len(emojis) > args.max_images:
        raise SystemExit(
            f"{len(emojis)} images exceeds --max-images {args.max_images}. "
            f"Lower --pages/--per-page, or raise the cap."
        )

    out_root = Path(args.out)
    print(f"Downloading {len(emojis)} image(s) -> {out_root}\n")
    written, skipped, failures = dump_group(
        emojis, out_root, jobs=args.jobs, skip_existing=not args.overwrite
    )

    sheet = out_root / "index.html"
    entries, srcs = sheet_entries_from_disk(out_root)
    write_contact_sheet(
        entries, sheet, f"emojifont — FrankerFaceZ, top {args.pages} page(s)", src_map=srcs
    )

    note = f", {skipped_animated} animated skipped" if skipped_animated else ""
    print(f"\n{len(written)} downloaded, {len(skipped)} already present, "
          f"{len(failures)} failed{note}; {len(entries)} image(s) in the dump")
    if failures:
        print("\nfailures:")
        for e, exc in failures[:15]:
            print(f"  {e.id} ({e.name}): {exc}")
        if len(failures) > 15:
            print(f"  ... {len(failures) - 15} more")
    print(f"\nBrowse: {sheet}")
    print("Then copy the ones you want into your memes directory.")
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


def cmd_dedupe(args):
    """Collapse exact-duplicate images across one or more directories."""
    dirs = [Path(d) for d in args.dirs] if args.dirs else default_dump_dirs(Path.cwd())
    dirs = [d for d in dirs if d.is_dir()]
    if not dirs:
        raise SystemExit(
            "No input directories found. Pass one or more directories, or run "
            "emojifont-fetch dump / ffz-dump first (this defaults to their output)."
        )
    print(f"Scanning {len(dirs)} director(y/ies), in this precedence order:")
    for d in dirs:
        print(f"  {d}")

    result = dedupe_images(dirs, args.out, jobs=args.jobs, hardlink=args.hardlink,
                           dry_run=args.dry_run)

    verb = "Would keep" if args.dry_run else "Kept"
    note = f", {len(result.errors)} unreadable" if result.errors else ""
    print(f"\n{verb} {len(result.kept)} unique image(s), "
          f"skipped {len(result.duplicates)} duplicate(s){note}")
    if not args.dry_run:
        print(f"-> {args.out}")

    if args.show_duplicates and result.duplicates:
        print("\nduplicates (skipped -> kept as):")
        for dupe_path, kept_path in result.duplicates[:50]:
            print(f"  {dupe_path}  ==  {kept_path}")
        if len(result.duplicates) > 50:
            print(f"  ... {len(result.duplicates) - 50} more (use --show-duplicates with a "
                  f"narrower --dir to see the rest)")

    if result.errors:
        print("\nunreadable, skipped:")
        for path, exc in result.errors[:20]:
            print(f"  {path}: {exc}")
        if len(result.errors) > 20:
            print(f"  ... {len(result.errors) - 20} more")
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
  emojifont-fetch dump --out font_build/meme-dump
  emojifont-fetch ffz-dump --pages 100 --out font_build/ffz-dump
  emojifont-fetch dedupe --out font_build/memes-deduped

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

    p_ffz = sub.add_parser("ffz-dump", help="bulk-download FrankerFaceZ emotes by popularity")
    p_ffz.add_argument("--pages", type=int, default=100, help="API pages to walk (default 100)")
    p_ffz.add_argument("--per-page", type=int, default=50, help="emotes per page (default 50)")
    p_ffz.add_argument("--sort", default="count-desc",
                       help="FFZ sort order (default count-desc, i.e. most-used first)")
    p_ffz.add_argument("--out", default="font_build/ffz-dump", help="output directory")
    p_ffz.add_argument("--jobs", type=int, default=8, help="parallel requests (default 8)")
    p_ffz.add_argument("--overwrite", action="store_true",
                       help="re-download files that are already present")
    p_ffz.add_argument("--include-animated", action="store_true",
                       help="include animated emotes (SBIX renders one still frame only)")
    p_ffz.add_argument("--max-images", type=int, default=6000,
                       help="refuse to start above this many images (default 6000)")
    p_ffz.set_defaults(func=cmd_ffz_dump)

    p_get = sub.add_parser("get", help="download the images you name")
    p_get.add_argument("names", nargs="+", help="ids or names from `list`")
    common(p_get)
    p_get.add_argument("--out", default="memes", help="output directory (default: memes)")
    p_get.add_argument("--start-codepoint", type=_hex_codepoint, default=DEFAULT_START_CODEPOINT,
                       help="first code point to assign (default: F900)")
    p_get.set_defaults(func=cmd_get)

    p_dedupe = sub.add_parser(
        "dedupe", help="collapse exact-duplicate images across dump directories",
        description="Hash every image under the given directories and keep only one "
                    "copy per distinct content hash, named after the first file found "
                    "with that content. Directories are scanned in the order given "
                    "(files within a directory alphabetically) — that order decides "
                    "which of several identical files is 'the first one'.",
    )
    p_dedupe.add_argument("dirs", nargs="*",
                          help="directories to scan (default: font_build/meme-dump, "
                               "font_build/ffz-dump, font_build/memes — whichever exist)")
    p_dedupe.add_argument("--out", default="font_build/memes-deduped", help="output directory")
    p_dedupe.add_argument("--jobs", type=int, default=8, help="parallel hashing (default 8)")
    p_dedupe.add_argument("--hardlink", action="store_true",
                          help="hardlink instead of copy (saves disk; falls back to a copy "
                               "if the output is on a different filesystem)")
    p_dedupe.add_argument("--dry-run", action="store_true",
                          help="report what would happen without writing anything")
    p_dedupe.add_argument("--show-duplicates", action="store_true",
                          help="list which files were skipped as duplicates of which")
    p_dedupe.set_defaults(func=cmd_dedupe)

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
