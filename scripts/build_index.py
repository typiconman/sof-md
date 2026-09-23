#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""build_index.py — build sof-index.html from the underlined liturgical units.

The catalog marks every liturgical unit by underlining its name, which
odt2md.py carries into the Markdown as <u>…</u>.  This gathers them from the
main descriptions (original/<shelfmark>/<shelfmark>_0.md) and writes the index
in the shape it has always had: the name of a unit, and under it the
manuscripts it occurs in, each linked to its description.

The units come in the two kinds Slutsky's specification describes:

  * a unit whose first underlined word is «Молитва» has the three-part shape
    <Молитва> + <description> + <incipit in quotes>, and is indexed as
    «Молитва» plus the incipit alone, so that

        Молитва над приносимым плодом всякого овоща «Благодарим Тя…»
        -> Молитва «Благодарим Тя…»

    The incipit usually stands outside the underline, so the rest of the
    paragraph is read as well;
  * every other unit is indexed by exactly what is underlined and nothing
    else, so that an underlined «Вечерня» in «Вечерня без начала» is indexed
    as «Вечерня».

The same unit is quoted to different lengths and with different spellings
from one manuscript to the next, so near-identical entries are merged.
Merging the genuinely different is worse than leaving duplicates behind —
the first goes unnoticed, the second is visible and can be tidied by hand —
so the rules are deliberately cautious: entries merge when one is a
continuation of the other (the common case, an incipit quoted short in one
manuscript and long in another) or when they are nearly the same string.
Where several spellings meet, the entry is shown as the lowest-numbered
manuscript has it.  --report writes what was merged, and what came close to
merging but did not, so both can be reviewed by eye.

Usage:
    ./build_index.py [--catalog original] [--page sof-index.html]
                     [--similarity 0.90] [--report FILE] [-n]
"""

from __future__ import annotations

import argparse
import difflib
import html
import os
import re
import sys
from datetime import datetime

PRAYER = "Молитва"

# Entries merge when one continues the other and they already agree for this
# many words; short names (one or two words) are never merged on that rule.
MIN_PREFIX_WORDS = 4
# An incipit runs long and is copied by ear, so the same prayer can differ in
# spelling from end to end and still plainly be the same prayer; it is held to
# a slightly easier standard than the short name of a unit, where a single
# word carries the whole distinction — «праздничные триодного цикла» against
# «праздничные минейного цикла» are two different things.
PRAYER_SLACK = 0.05
# Pairs at least this similar are reported as worth a look even when they are
# left apart.
NEAR_MISS = 0.75

FM_RE = re.compile(r"\A---\n.*?\n---\n", re.S)
U_RE = re.compile(r"<u>(.*?)</u>", re.S)
# Underline broken across several runs by a difference the index does not
# care about — an italic word, the quotation marks — is one unit.
GLUE_RE = re.compile(r"</u>((?:\s|«|»|,|:|\.{3}|…)*)<u>")
LINK_RE = re.compile(r"!?\[((?:[^\[\]\\]|\\.)*)\]\([^)]*\)")
TAG_RE = re.compile(r"</?(?:em|strong|br|span)\b[^>]*>")
QUOTE_RE = re.compile(r"«\s*(.+?)\s*»", re.S)
# The folio reference that closes a line: « — л. 27 – л. 27 об.»
FOLIO_RE = re.compile(r"[\s ]*[—–-][\s ]*л\.")

NBSP = " "


def clean(text: str) -> str:
    """Strip the Markdown around a line, keeping the <u> tags and the words."""
    text = LINK_RE.sub(r"\1", text)
    text = TAG_RE.sub("", text)
    text = text.replace("*", "")
    text = re.sub(r"\\(.)", r"\1", text)
    return text


def tidy(text: str) -> str:
    """One line of display text: no stray markup, ordinary spaces.

    A bracket left hanging by an underline that stops mid-phrase — the
    catalog has «…праздничные (» around a word that was not underlined — is
    dropped, since the index shows the name and not the punctuation.
    """
    text = re.sub(r"</?u>", "", text)
    text = re.sub(r"[\s ]+", " ", text).strip(" \t.,;:")
    if text.count("(") != text.count(")"):
        text = text.strip("()").strip(" ,;:")
    return text


# Latin letters typed for their Cyrillic lookalikes, which the catalog has
# here and there ("Cинаксарь" with a Latin C).  Folded for comparison only.
LOOKALIKE = str.maketrans("ACEHIKMOPTXBacehikmoptxy",
                          "АСЕНІКМОРТХВасеhікмортху")


def key_of(text: str) -> str:
    """The form two entries are compared in: letters, lowercase, spaced out."""
    text = text.translate(LOOKALIKE).lower().replace("ё", "е")
    text = re.sub(r"[«»\"“”„'‘’(),.;:!?\[\]…\-–—‑ ]", " ", text)
    return re.sub(r"\s+", " ", text).strip()


def has_letters(text: str) -> bool:
    """Underline that caught only punctuation is not a liturgical unit."""
    return bool(re.search(r"[а-яА-ЯёЁ]", text))


def unit_name(span: str, tail: str) -> tuple[str, bool]:
    """The index entry for one underlined span; True if it wanted an incipit.

    A «Молитва» is indexed by its incipit, which may stand inside the
    underline or, far more often, just after it.  When it has none the
    description is kept instead, so that prayers that differ only there do
    not all collapse into a bare «Молитва».
    """
    span, tail = tidy(span), tidy(tail)
    words = span.split()
    if not words or words[0].strip(".,:;«»").lower() != PRAYER.lower():
        return span, False
    # The incipit belongs to this unit, so look no further than the folio
    # reference that closes the line.
    described = FOLIO_RE.split(tail)[0].strip(" ,;:")
    quoted = QUOTE_RE.search(span) or QUOTE_RE.search(described)
    if quoted:
        return "%s «%s»" % (PRAYER, quoted.group(1)), True
    return (("%s %s" % (PRAYER, described)).strip(), True)


def extract(catalog: str, quiet: bool) -> list[dict]:
    """Every underlined unit of every main description, in shelfmark order."""
    found: list[dict] = []
    for name in sorted(os.listdir(catalog), key=lambda n: (not n.isdigit(), n)):
        directory = os.path.join(catalog, name)
        description = os.path.join(directory, "%s_0.md" % name)
        if not name.isdigit() or not os.path.isfile(description):
            continue
        with open(description, encoding="utf-8") as fh:
            body = FM_RE.sub("", fh.read())
        for line in body.splitlines():
            if "<u>" not in line:
                continue
            line = GLUE_RE.sub(r"\1", clean(line))
            for match in U_RE.finditer(line):
                if not match.group(1).strip():
                    continue
                label, wanted_incipit = unit_name(match.group(1),
                                                  line[match.end():])
                if not has_letters(label):
                    continue
                found.append({"label": label,
                              "shelfmark": int(name),
                              "prayer": wanted_incipit,
                              "key": key_of(label)})
    if not quiet:
        print("read %d underlined unit(s) from %s" % (len(found), catalog))
    return found


def ratio_at_least(a: str, b: str, floor: float) -> float:
    """How alike two entries read, or 0.0 once that is known to be below floor.

    difflib's two cheap bounds are tried first; on this many pairs of long
    incipits the full comparison is far too slow to reach for every time.
    """
    matcher = difflib.SequenceMatcher(None, a, b)
    if matcher.real_quick_ratio() < floor or matcher.quick_ratio() < floor:
        return 0.0
    ratio = matcher.ratio()
    return ratio if ratio >= floor else 0.0


def mergeable(a: str, b: str, similarity: float, prefix_words: int) -> bool:
    """Is one of these entries the same unit as the other?

    Either one carries on where the other stops — an incipit quoted short in
    one manuscript and at length in another — or the two read almost alike.
    """
    first, second = a.split(), b.split()
    shared = min(len(first), len(second))
    if shared >= prefix_words and first[:shared] == second[:shared]:
        return True
    return ratio_at_least(a, b, similarity) > 0.0


def cluster(found: list[dict], similarity: float,
            prefix_words: int) -> tuple[list[dict], list]:
    """Gather the entries that name the same unit.

    Identical entries are gathered first, so that the comparisons are made
    between distinct wordings only; a wording joins the first group it can be
    merged with, and prayers are never merged with anything else.
    """
    groups: dict[tuple[bool, str], dict] = {}
    order: list[tuple[bool, str]] = []
    for item in found:
        ident = (item["prayer"], item["key"])
        if ident not in groups:
            groups[ident] = {"key": item["key"], "prayer": item["prayer"],
                             "wordings": [], "shelfmarks": set()}
            order.append(ident)
        groups[ident]["wordings"].append((item["shelfmark"], item["label"]))
        groups[ident]["shelfmarks"].add(item["shelfmark"])

    clusters: list[dict] = []
    near: list[tuple[float, str, str]] = []
    buckets: dict[tuple[bool, str], list[dict]] = {}
    for ident in order:
        group = groups[ident]
        # Only entries that begin alike can merge, which keeps the comparison
        # count sane without changing the outcome.
        bucket = (group["prayer"], group["key"][:3])
        threshold = similarity - PRAYER_SLACK if group["prayer"] else similarity
        home = None
        for candidate in buckets.setdefault(bucket, []):
            if mergeable(candidate["key"], group["key"], threshold,
                         prefix_words):
                home = candidate
                break
            ratio = ratio_at_least(candidate["key"], group["key"], NEAR_MISS)
            if ratio:
                near.append((ratio, candidate["wordings"][0][1],
                             group["wordings"][0][1]))
        if home is None:
            group["merged"] = []
            clusters.append(group)
            buckets[bucket].append(group)
        else:
            home["merged"].append(group)
            home["wordings"].extend(group["wordings"])
            home["shelfmarks"] |= group["shelfmarks"]

    for group in clusters:
        # Rule 7: show the unit as the first manuscript of the list has it.
        group["label"] = min(group["wordings"], key=lambda w: w[0])[1]
    clusters.sort(key=lambda g: (key_of(g["label"]), g["label"]))
    near.sort(reverse=True)
    return clusters, near


def render(clusters: list[dict]) -> str:
    """The body of the index, in the markup the page has always used."""
    blocks = []
    for group in clusters:
        links = ", \n".join(
            '<A href="/sof-catalog/%d/%d_0.html">%d</A>' % (s, s, s)
            for s in sorted(group["shelfmarks"]))
        blocks.append('<div class="item">%s \n<div class="links">\n\n%s\n'
                      "</div>\n</div>\n" % (html.escape(group["label"]), links))
    return "\n".join(blocks)


def rebuild(page: str, body: str) -> str:
    """Put the new entries into the page, keeping its head and its foot."""
    with open(page, encoding="utf-8") as fh:
        text = fh.read()
    head = text.find("</H3>")
    foot = text.find("<HR>")
    if head < 0 or foot < 0:
        raise SystemExit("%s: cannot find the heading and the footer" % page)
    head += len("</H3>")
    stamped = re.sub(r"(Последнее обновление данного документа: )\d{2}\.\d{2}\.\d{4}",
                     r"\g<1>%s" % datetime.now().strftime("%d.%m.%Y"),
                     text[foot:], count=1)
    return text[:head] + "\n\n\n" + body + "\n" + stamped


def write_report(path: str, clusters: list[dict], near: list) -> None:
    lines = ["Отчет указателя — %s" % datetime.now().strftime("%d.%m.%Y"), ""]
    joined = [g for g in clusters
              if len({w[1] for w in g["wordings"]}) > 1]
    lines += ["ОБЪЕДИНЕНО (%d) — проверить, что это действительно одно и то же:"
              % len(joined), ""]
    for group in joined:
        lines.append("  %s" % group["label"])
        for shelfmark, wording in sorted(set(group["wordings"])):
            if wording != group["label"]:
                lines.append("      %-5d %s" % (shelfmark, wording))
        lines.append("")
    lines += ["", "НЕ ОБЪЕДИНЕНО, НО ПОХОЖЕ (%d) — возможно, стоит свести "
              "вручную:" % len(near), ""]
    for ratio, first, second in near:
        lines += ["  %.2f  %s" % (ratio, first), "        %s" % second, ""]
    with open(path, "w", encoding="utf-8") as fh:
        fh.write("\n".join(lines) + "\n")


def main(argv: list[str]) -> int:
    here = os.path.dirname(os.path.abspath(__file__))
    root = os.path.dirname(here)
    parser = argparse.ArgumentParser(
        description="Build sof-index.html from the underlined liturgical units.")
    parser.add_argument("--catalog", default=os.path.join(root, "original"),
                        help="the Markdown catalog (default: ../original)")
    parser.add_argument("--page", default=os.path.join(root, "sof-index.html"),
                        help="the index page to rewrite (default: "
                             "../sof-index.html)")
    parser.add_argument("--similarity", type=float, default=0.90,
                        help="how alike two entries must read before they are "
                             "merged, 0..1 (default: %(default)s; lower merges "
                             "more, at the risk of merging what differs)")
    parser.add_argument("--prefix-words", type=int, default=MIN_PREFIX_WORDS,
                        help="how many opening words two entries must share "
                             "before one counts as a continuation of the "
                             "other (default: %(default)s; fewer merges more, "
                             "and prayers that open alike — «Господи Боже "
                             "наш…» — start to run together)")
    parser.add_argument("--report", help="write a file listing what was merged "
                                         "and what nearly was")
    parser.add_argument("-n", "--dry-run", action="store_true",
                        help="report what would change without writing")
    parser.add_argument("-q", "--quiet", action="store_true")
    args = parser.parse_args(argv)

    if not os.path.isdir(args.catalog):
        parser.error("no such directory: %s" % args.catalog)
    if not os.path.isfile(args.page):
        parser.error("no such file: %s" % args.page)

    found = extract(args.catalog, args.quiet)
    if not found:
        print("no underlined units found under %s" % args.catalog,
              file=sys.stderr)
        return 1
    clusters, near = cluster(found, args.similarity, args.prefix_words)

    with open(args.page, encoding="utf-8") as fh:
        before = fh.read()
    text = rebuild(args.page, render(clusters))
    if args.dry_run:
        print("%s would %s" % (os.path.basename(args.page),
                               "change" if text != before else "stay as it is"))
    else:
        with open(args.page, "w", encoding="utf-8") as fh:
            fh.write(text)
        if not args.quiet:
            print("wrote %s" % os.path.basename(args.page))

    if args.report:
        write_report(args.report, clusters, near)
        if not args.quiet:
            print("wrote %s" % args.report)

    if not args.quiet:
        prayers = sum(1 for g in clusters if g["prayer"])
        print("%d entries (%d prayers, %d other); %d near-miss pair(s) to review"
              % (len(clusters), prayers, len(clusters) - prayers, len(near)))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
