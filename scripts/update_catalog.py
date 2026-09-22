#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""update_catalog.py — fill the manuscript lists of the catalogue front pages.

sof-catalog.html and sof-catalog-en.html group the manuscripts by century,
one <H3> section each, and colour a shelfmark by whether its description has
a palaeographic part.  Both facts now live in the front matter of every main
description (original/<shelfmark>/<shelfmark>_0.md), so the lists can be
rebuilt from the catalogue instead of being kept by hand:

    century: 16       -> the "Служебники XVI в." / "16th-Century Manuscripts"
                         section
    paleography: yes  -> class="forlink"      (the ordinary dark red link)
    paleography: no   -> class="forlink-red"  (the page's legend explains that
                         these lack a palaeographic description)

Only the run of links inside each of those five sections is rewritten; every
other element of the two pages, and their formatting, is left byte for byte
as it was.  Both pages carry the same links and differ only in the wording of
their headings, so they are driven from the one table below.

Usage:
    ./update_catalog.py [--catalogue original] [--pages .] [-n]
"""

from __future__ import annotations

import argparse
import os
import re
import sys

# The five century sections, in the order they appear on the page, with the
# heading that identifies each one in the Russian and the English page.
SECTIONS = [
    ("13", "Служебники XIII&nbsp;в.", "13th-Century Manuscripts"),
    ("14", "Служебники XIV&nbsp;в.", "14th-Century Manuscripts"),
    ("15", "Служебники XV&nbsp;в.", "15th-Century Manuscripts"),
    ("16", "Служебники XVI&nbsp;в.", "16th-Century Manuscripts"),
    ("17", "Служебники XVII&nbsp;в.", "17th-Century Manuscripts"),
]

PAGES = [("sof-catalog.html", 1), ("sof-catalog-en.html", 2)]  # file, heading column

P_OPEN = '<P class="textF" style="line-height:200%">'
P_CLOSE = "\n</P>"

LINK = ('<A class="%s" HREF="sof-catalog/%s/%s_0.html">'
        '&nbsp;%s&nbsp;</a>&nbsp;')

FM_RE = re.compile(r"\A---\n(.*?\n)---\n", re.S)


def read_front_matter(path: str) -> dict[str, str]:
    with open(path, encoding="utf-8") as fh:
        m = FM_RE.match(fh.read())
    if not m:
        return {}
    meta = {}
    for line in m.group(1).splitlines():
        key, sep, value = line.partition(":")
        if sep:
            meta[key.strip()] = value.strip()
    return meta


def collect(catalogue: str) -> tuple[dict[str, list[tuple[int, str]]], int]:
    """Group the shelfmarks by century, warning about the ones we cannot place."""
    by_century: dict[str, list[tuple[int, str]]] = {c: [] for c, _, _ in SECTIONS}
    known = {c for c, _, _ in SECTIONS}
    warnings = 0

    for name in sorted(os.listdir(catalogue)):
        directory = os.path.join(catalogue, name)
        if not os.path.isdir(directory) or not name.isdigit():
            continue
        description = os.path.join(directory, "%s_0.md" % name)
        if not os.path.isfile(description):
            print("warning: %s has no %s_0.md" % (directory, name), file=sys.stderr)
            warnings += 1
            continue

        meta = read_front_matter(description)
        century = meta.get("century", "")
        if not century:
            print("warning: %s does not define century; leaving it off the page"
                  % description, file=sys.stderr)
            warnings += 1
            continue
        if century not in known:
            print("warning: %s has century %s, which has no section on the page"
                  % (description, century), file=sys.stderr)
            warnings += 1
            continue

        paleography = meta.get("paleography", "")
        if paleography not in ("yes", "no"):
            print("warning: %s has paleography %r; treating it as no"
                  % (description, paleography), file=sys.stderr)
            warnings += 1
        css = "forlink" if paleography == "yes" else "forlink-red"
        by_century[century].append((int(name), css))

    for entries in by_century.values():
        entries.sort()
    return by_century, warnings


def render_links(entries: list[tuple[int, str]]) -> str:
    """The run of links of one section, as the pages have always spelt it."""
    return "\n\n".join(LINK % (css, shelfmark, shelfmark, shelfmark)
                       for shelfmark, css in entries)


def replace_section(text: str, heading: str, links: str, page: str) -> str:
    """Swap the links of one section, touching nothing around them."""
    anchor = "<H3>%s</H3>" % heading
    at = text.find(anchor)
    if at < 0:
        raise SystemExit("%s: no section headed %s" % (page, anchor))
    opened = text.find(P_OPEN, at)
    closed = text.find(P_CLOSE, opened) if opened >= 0 else -1
    if opened < 0 or closed < 0:
        raise SystemExit("%s: the %s section is not shaped as expected"
                         % (page, anchor))
    start = opened + len(P_OPEN)
    return text[:start] + (("\n" + links) if links else "") + text[closed:]


def main(argv: list[str]) -> int:
    here = os.path.dirname(os.path.abspath(__file__))
    root = os.path.dirname(here)
    parser = argparse.ArgumentParser(
        description="Fill in the manuscript lists of the catalogue front pages.")
    parser.add_argument("--catalogue", default=os.path.join(root, "original"),
                        help="the Markdown catalogue (default: ../original)")
    parser.add_argument("--pages", default=root,
                        help="directory holding the two pages (default: the "
                             "repository root)")
    parser.add_argument("-n", "--dry-run", action="store_true",
                        help="report what would change without writing")
    parser.add_argument("-q", "--quiet", action="store_true")
    args = parser.parse_args(argv)

    if not os.path.isdir(args.catalogue):
        parser.error("no such directory: %s" % args.catalogue)

    by_century, warnings = collect(args.catalogue)

    for filename, column in PAGES:
        path = os.path.join(args.pages, filename)
        if not os.path.isfile(path):
            parser.error("no such file: %s" % path)
        with open(path, encoding="utf-8") as fh:
            before = fh.read()

        text = before
        for section in SECTIONS:
            century, heading = section[0], section[column]
            text = replace_section(text, heading,
                                   render_links(by_century[century]), filename)

        if text == before:
            if not args.quiet:
                print("%s is already up to date" % filename)
        elif args.dry_run:
            print("%s would change" % filename)
        else:
            with open(path, "w", encoding="utf-8") as fh:
                fh.write(text)
            if not args.quiet:
                print("wrote %s" % filename)

    if not args.quiet:
        print("listed %d manuscript(s): %s"
              % (sum(len(v) for v in by_century.values()),
                 ", ".join("%s в. — %d" % (c, len(by_century[c]))
                           for c, _, _ in SECTIONS)))
    return 1 if warnings else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
