#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""add_manuscript.py — add one manuscript description to the Markdown catalogue.

odt2md.py converts the whole SOF tree at once; this script takes a single
loose ODT — the ones collected in new-odt/, which are ordinary descriptions
that simply have not been filed under SOF/<shelfmark>/ yet — and lays it out
in the catalogue the way a full run of odt2md.py would:

    new-odt/652_0.ODT  ->  original/652/652_0.md
                           original/652/README.md

The Markdown itself is produced by odt2md.py's own Converter, imported rather
than reimplemented, so the typography, the Church Slavonic decoding and the
underline of the source document come out exactly as they do for the rest of
the catalogue.  The front matter gains the two fields the catalogue now
carries on every main description, `century` and `paleography`, which no
single document can tell us on its own and so are supplied by flags.

Usage:
    ./add_manuscript.py new-odt/652_0.ODT [-o original] [--century 16]
                        [--paleography] [--force]
"""

from __future__ import annotations

import argparse
import os
import sys
from datetime import datetime

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import odt2md  # noqa: E402  (same directory; see the module docstring)


class SingleDocConverter(odt2md.Converter):
    """Converter for one ODT that is not yet under a <shelfmark>/ directory.

    odt2md.Converter derives a document's place in the output tree from its
    place in the source tree.  Here the source is a loose file, so the
    shelfmark directory it is about to be filed under is supplied instead —
    which is what any relative link inside the document is resolved against.
    """

    def __init__(self, src_root: str, out_root: str, mapping: dict[str, str],
                 shelfmark: str) -> None:
        super().__init__(src_root, out_root, mapping, front_matter=False)
        self.shelfmark = shelfmark

    def out_name(self, rel_path: str) -> str:
        stem = os.path.splitext(os.path.basename(rel_path))[0]
        return "%s/%s.md" % (self.shelfmark, stem.lower())


def shelfmark_of(path: str) -> str:
    """The catalogue directory a document belongs in: 652_0.ODT -> 652."""
    stem = os.path.splitext(os.path.basename(path))[0]
    digits = ""
    for ch in stem:
        if not ch.isdigit():
            break
        digits += ch
    return digits


def front_matter(title: str, source: str, updated: str, century: str,
                 paleography: str) -> str:
    """The front matter of odt2md.py plus the catalogue's two added fields.

    century and paleography are written bare, as the catalogue has them —
    they are read by eye and by grep, not by a YAML parser.
    """
    lines = ["---",
             "title: %s" % odt2md.yaml_scalar(title),
             "source: %s" % odt2md.yaml_scalar(source),
             "updated: %s" % odt2md.yaml_scalar(updated),
             "century: %s" % century,
             "paleography: %s" % paleography,
             "---",
             ""]
    return "\n".join(lines) + "\n"


def write_readme(directory: str, shelfmark: str, title: str, page: str) -> None:
    """The per-directory index, in the format odt2md.py's write_indexes uses."""
    lines = ["# %s" % shelfmark, "",
             "- [%s](%s)" % (title or os.path.splitext(page)[0], page), ""]
    with open(os.path.join(directory, "README.md"), "w", encoding="utf-8") as fh:
        fh.write("\n".join(lines))


def main(argv: list[str]) -> int:
    here = os.path.dirname(os.path.abspath(__file__))
    parser = argparse.ArgumentParser(
        description="Add one ODT description to the Markdown catalogue.")
    parser.add_argument("odt", help="the ODT to convert, e.g. new-odt/652_0.ODT")
    parser.add_argument("-o", "--output",
                        default=os.path.join(os.path.dirname(here), "original"),
                        help="catalogue root (default: ../original)")
    parser.add_argument("--century", default="16",
                        help="century field of the front matter (default: "
                             "%(default)s)")
    parser.add_argument("--paleography", action="store_true",
                        help="set the paleography field to yes (default: no)")
    parser.add_argument("--map", dest="mapping",
                        default=os.path.join(here, "cyrillica_bg_epigraph_mod_to_unicode.json"),
                        help="CyrillicaBgEpigraphMod → Unicode mapping (JSON)")
    parser.add_argument("--force", action="store_true",
                        help="write into the shelfmark directory even if it "
                             "already exists, overwriting what is there")
    parser.add_argument("-q", "--quiet", action="store_true")
    args = parser.parse_args(argv)

    src = os.path.abspath(args.odt)
    if not os.path.isfile(src):
        parser.error("no such file: %s" % args.odt)
    out_root = os.path.abspath(args.output)
    if not os.path.isdir(out_root):
        parser.error("no such directory: %s" % args.output)

    shelfmark = shelfmark_of(src)
    if not shelfmark:
        parser.error("cannot tell the shelfmark from the file name: %s"
                     % os.path.basename(src))

    directory = os.path.join(out_root, shelfmark)
    if os.path.isdir(directory):
        shown = os.path.relpath(directory)
        if shown.startswith(os.pardir):
            shown = directory  # outside the working directory; absolute reads better
        print("warning: %s already exists" % shown, file=sys.stderr)
        if not args.force:
            print("nothing written; pass --force to overwrite it",
                  file=sys.stderr)
            return 1

    try:
        mapping = odt2md.load_cyrillica_map(args.mapping)
    except OSError as exc:
        parser.error("cannot read font mapping: %s" % exc)

    conv = SingleDocConverter(os.path.dirname(src), out_root, mapping, shelfmark)
    page = conv.convert_file(os.path.basename(src))

    basename = os.path.basename(page["out"])
    # The catalogue names a document by where it sits under the shelfmark, so
    # the field stays right once the ODT itself is filed under SOF/<shelfmark>/.
    source = "%s/%s" % (shelfmark, os.path.basename(src))
    updated = datetime.fromtimestamp(os.path.getmtime(src)).strftime("%Y-%m-%d")

    os.makedirs(directory, exist_ok=True)
    with open(os.path.join(directory, basename), "w", encoding="utf-8") as fh:
        fh.write(front_matter(page["title"], source, updated, args.century,
                              "yes" if args.paleography else "no")
                 + page["markdown"])
    write_readme(directory, shelfmark, page["title"], basename)

    if not args.quiet:
        print("%s -> %s" % (args.odt, os.path.join(shelfmark, basename)))
        print("wrote %s" % os.path.join(shelfmark, "README.md"))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
