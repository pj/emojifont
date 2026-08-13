"""Print an --mappings string for `emojifont`: sort meme file stems
(case-sensitive) and assign U+100000, U+100001, ... in order.

commandline_thing's Meme operation computes the same index over the same
directory, so this ordering is the shared contract between the font and the
Go code — no separate manifest file. Rebuild the font whenever memes/
changes.
"""

import os
import sys

MEME_CODEPOINT_BASE = 0x100000


def build_mappings(memes_dir: str) -> str:
    files = [f for f in os.listdir(memes_dir) if os.path.isfile(os.path.join(memes_dir, f))]
    by_stem = {}
    for f in files:
        stem = os.path.splitext(f)[0]
        by_stem.setdefault(stem, f)

    parts = []
    for i, stem in enumerate(sorted(by_stem)):
        codepoint = MEME_CODEPOINT_BASE + i
        parts.append(f"U+{codepoint:06X}:{os.path.join(memes_dir, by_stem[stem])}")
    return ",".join(parts)


if __name__ == "__main__":
    print(build_mappings(sys.argv[1]))
