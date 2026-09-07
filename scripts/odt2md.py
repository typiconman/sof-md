#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""odt2md.py — convert the SOF catalogue of OpenOffice documents to Markdown.

Modelled on convert_i.pl, but the target is a browsable Markdown repository
instead of a set of server-side-included HTML pages:

  * every *.odt / *.ODT below the source tree becomes a *.md file in a mirror
    of the source directory tree (convert_i.pl exported the `_t` transcription
    files to PDF instead — here they are converted to Markdown as well);
  * links stay *relative*, so the tree can be browsed straight from the repo
    (convert_i.pl rewrote them to absolute http paths under /sof-catalog/);
  * the Russian-typography fixes of convert_i.pl are applied, emitting real
    Unicode characters (NBSP, EN DASH, EM DASH, NON-BREAKING HYPHEN) rather
    than the HTML entities the Perl script produced;
  * text set in OpenOffice's legacy `CyrillicaBgEpigraphMod` font is decoded
    to Unicode Church Slavonic via cyrillica_bg_epigraph_mod_to_unicode.json
    and wrapped in <span class="cu-text">…</span>.  convert_i.pl could not do
    this: it rendered every such run to a JPEG through oowriter + ImageMagick.

The ODF XML is read directly, so neither OpenOffice nor pandoc is needed.

Usage:
    ./odt2md.py [SRC] [-o OUTDIR] [--no-assets] [--no-index] ...
"""

from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import sys
import unicodedata
import urllib.parse
import zipfile
import xml.etree.ElementTree as ET
from datetime import datetime

# --------------------------------------------------------------------------
# constants
# --------------------------------------------------------------------------

NBSP = " "
NDASH = "–"
MDASH = "—"
NBHY = "‑"  # non-breaking hyphen, stands in for convert_i.pl's <nobr>

CYR_FONT_PREFIX = "cyrillicabgepigraph"  # matches …Epigraph and …EpigraphMod
CYR_SPAN_OPEN = '<span class="cu-text">'
CYR_SPAN_CLOSE = "</span>"

DOC_EXT = (".odt",)
ASSET_EXT = (".pdf", ".gif", ".jpg", ".jpeg", ".png", ".svg")
# Extensions of link targets that this script turns into Markdown pages.
LINKED_DOC_EXT = (".odt", ".html", ".htm", ".md")

# Cyrillic letters that stand in for Latin ones in a few hand-typed hrefs
# (e.g. ../530_Т3.odt, ../526_%D0%A23.odt).  convert_i.pl papered over these
# with s#_\D+(\d)#_t$1#; here the lookalikes are transliterated instead.
LOOKALIKE = str.maketrans("аАвВеЕкКмМнНоОрРсСтТуУхХ", "aABBeEkKmMHHoOpPcCtTyYxX")


# --------------------------------------------------------------------------
# Russian typography — the regex fixes of convert_i.pl, in the same order
# --------------------------------------------------------------------------

def _rule(pattern: str, repl: str):
    return re.compile(pattern), repl


TYPO_RULES = [
    _rule(r"№\s*", "№" + NBSP),
    _rule(r"([IXV])\s*в", r"\1" + NBSP + "в"),
    _rule(r"(\d)\s*г\.", r"\1" + NBSP + "г."),
    _rule(r"(\d)\s*мм", r"\1" + NBSP + "мм"),
    _rule(r"\s+(\d+)\)\s+", r" \1)" + NBSP),
    _rule(r"Соф\.\s*(\d)", "Соф." + NBSP + r"\1"),
    _rule(r"(\d)\s*л\.", r"\1" + NBSP + "л."),
    _rule(r"л\.\s*(\d)", "л." + NBSP + r"\1"),
    _rule(r"Л\.\s*(\d)", "Л." + NBSP + r"\1"),
    _rule(r"c\.\s*(\d)", "c." + NBSP + r"\1"),   # latin c
    _rule(r"с\.\s*(\d)", "с." + NBSP + r"\1"),   # cyrillic с
    _rule(r"С\.\s*(\d)", "С." + NBSP + r"\1"),
    _rule(r"вып\.\s*(\d)", "вып." + NBSP + r"\1"),
    _rule(r"Вып\.\s*(\d)", "Вып." + NBSP + r"\1"),
    _rule(r"т\.\s*([IXV\d])", "т." + NBSP + r"\1"),
    _rule(r"Т\.\s*([IXV\d])", "Т." + NBSP + r"\1"),
    _rule(r"Bd\.\s*([IXV\d])", "Bd." + NBSP + r"\1"),
    _rule(r"Vol\.\s*([IXV\d])", "Vol." + NBSP + r"\1"),
    _rule(r"p\.\s*([IXV\d])", "p." + NBSP + r"\1"),
    _rule(r"P\.\s*([IXV\d])", "P." + NBSP + r"\1"),
    _rule(r"(\d)\s*об\.", r"\1" + NBSP + "об."),
    _rule(r"(\d)\s*x\s*(\d)", r"\1" + NBSP + "x" + NBSP + r"\2"),
    _rule(r"(\d)\s*х\s*(\d)", r"\1" + NBSP + "x" + NBSP + r"\2"),  # cyrillic х
    _rule(r"(\d)\s+,\s*(\d)", r"\1, \2"),
    _rule(r"(\d)-(\d)", r"\1" + NDASH + r"\2"),
    _rule(r"(\d)—(\d)", r"\1" + NDASH + r"\2"),
    _rule(r"([IXV])-([IXV])", r"\1" + NDASH + r"\2"),
    _rule(r"([IXV])—([IXV])", r"\1" + NDASH + r"\2"),
    _rule(r"(\d)-ая", r"\1-я"),
    _rule(r"(\d)-ую", r"\1-ю"),
    _rule(r"(\d)-ое", r"\1-е"),
    _rule(r"(\d)-ый", r"\1-й"),
    _rule(r"(\d)-АЯ", r"\1-Я"),
    _rule(r"(\d)-УЮ", r"\1-Ю"),
    _rule(r"(\d)-ОЕ", r"\1-Е"),
    _rule(r"(\d)-ЫЙ", r"\1-Й"),
    _rule(r"\s+?-\s", NBSP + NDASH + " "),
    _rule(r"\s+—", NBSP + MDASH),
    _rule(r"\s+–", NBSP + NDASH),
    _rule(NDASH + r"\s+(\d)", NDASH + NBSP + r"\1"),
    # convert_i.pl wrapped these in <nobr>; a non-breaking hyphen does the
    # same job without HTML.
    _rule(r"([\s(])(\d*?)-([а-я])([\s,.:;)])", r"\1\2" + NBHY + r"\3\4"),
]


def apply_typography(text: str) -> str:
    """Apply the convert_i.pl typography rules to one already-rendered block.

    Link targets and converted Church Slavonic are masked out beforehand by
    the caller (see MaskedText), so the rules only ever see running prose.
    """
    for pattern, repl in TYPO_RULES:
        text = pattern.sub(repl, text)
    return text


class MaskedText:
    """Hides spans of text from the typography rules behind placeholders.

    Placeholders are drawn from the Unicode private-use area and framed by
    NULs, so they match none of the character classes the rules use.
    """

    def __init__(self) -> None:
        self.chunks: list[str] = []

    def mask(self, text: str) -> str:
        self.chunks.append(text)
        return "\x00" + chr(0xE000 + len(self.chunks) - 1) + "\x00"

    def unmask(self, text: str) -> str:
        def repl(m: re.Match) -> str:
            return self.chunks[ord(m.group(1)) - 0xE000]

        return re.sub("\x00([\ue000-\uf8ff])\x00", repl, text)


# --------------------------------------------------------------------------
# CyrillicaBgEpigraphMod → Unicode
# --------------------------------------------------------------------------

def load_cyrillica_map(path: str) -> dict[str, str]:
    with open(path, encoding="utf-8") as fh:
        data = json.load(fh)
    return data["mapping"] if isinstance(data, dict) and "mapping" in data else data


def cyrillica_to_unicode(text: str, mapping: dict[str, str]) -> str:
    """Decode one run of legacy-font text to Unicode Church Slavonic.

    The mapping is keyed by the *bytes* of the legacy encoding seen as
    latin-1.  Depending on how the document was produced, a byte may have
    survived in the ODF XML either as its cp1251 character (0xFF → 'я') or
    literally (0x81 → U+0081), so both are folded back to the raw byte here.
    """
    out = []
    for ch in text:
        if ord(ch) < 0x100:
            raw = ch  # already byte-transparent, i.e. latin-1
        else:
            try:
                raw = ch.encode("cp1251").decode("latin-1")
            except UnicodeEncodeError:
                raw = ch  # e.g. U+0102/U+0103, which the mapping knows about
        out.append(mapping.get(raw, raw))
    return unicodedata.normalize("NFC", "".join(out))


# --------------------------------------------------------------------------
# ODF plumbing
# --------------------------------------------------------------------------

def localname(tag: str) -> str:
    return tag.rsplit("}", 1)[-1]


def attr(elem: ET.Element, *names: str) -> str | None:
    """Fetch a namespaced attribute by local name (first match wins)."""
    for name in names:
        suffix = "}" + name
        for key, value in elem.attrib.items():
            if key.endswith(suffix) or key == name:
                return value
    return None


class StyleBook:
    """Font / bold / italic properties of named and automatic ODF styles."""

    def __init__(self) -> None:
        self.fonts: dict[str, str] = {}      # font-face name -> family
        self.styles: dict[str, dict] = {}    # style name -> props (+ parent)
        self._resolved: dict[str, dict] = {}

    def add_document(self, root: ET.Element) -> None:
        for elem in root.iter():
            name = localname(elem.tag)
            if name == "font-face":
                face = attr(elem, "name")
                family = attr(elem, "font-family") or face
                if face:
                    self.fonts[face] = (family or "").replace("'", "").strip()
            elif name == "style":
                self._add_style(elem)

    def _add_style(self, elem: ET.Element) -> None:
        name = attr(elem, "name")
        if not name:
            return
        props: dict = {"parent": attr(elem, "parent-style-name")}
        for child in elem:
            if localname(child.tag) != "text-properties":
                continue
            font = attr(child, "font-name") or attr(child, "font-family")
            if font:
                props["font"] = font
            weight = attr(child, "font-weight")
            if weight:
                props["bold"] = weight not in ("normal", "100", "200", "300", "400")
            style = attr(child, "font-style")
            if style:
                props["italic"] = style in ("italic", "oblique")
        self.styles[name] = props

    def resolve(self, name: str | None) -> dict:
        """Style properties with the parent chain folded in."""
        if not name or name not in self.styles:
            return {}
        if name in self._resolved:
            return self._resolved[name]
        self._resolved[name] = {}  # guard against cyclic parents
        props = self.styles[name]
        merged = dict(self.resolve(props.get("parent")))
        for key in ("font", "bold", "italic"):
            if key in props:
                merged[key] = props[key]
        self._resolved[name] = merged
        return merged

    def is_cyrillica(self, font: str | None) -> bool:
        if not font:
            return False
        family = self.fonts.get(font, font).replace("'", "").strip().lower()
        return family.startswith(CYR_FONT_PREFIX)


class Run:
    """One inline piece of a paragraph, carrying its formatting."""

    __slots__ = ("text", "bold", "italic", "cyr", "href", "kind")

    def __init__(self, text: str, ctx: dict, kind: str = "text",
                 href: str | None = None) -> None:
        self.text = text
        self.bold = bool(ctx.get("bold"))
        self.italic = bool(ctx.get("italic"))
        self.cyr = bool(ctx.get("cyr"))
        self.href = href if href is not None else ctx.get("href")
        self.kind = kind  # text | break | image | anchor

    def style_key(self):
        return (self.bold, self.italic, self.cyr)


# --------------------------------------------------------------------------
# document conversion
# --------------------------------------------------------------------------

class Converter:
    def __init__(self, src_root: str, out_root: str, mapping: dict[str, str],
                 anchors: dict[str, set[str]] | None = None,
                 front_matter: bool = True) -> None:
        self.src_root = os.path.abspath(src_root)
        self.out_root = os.path.abspath(out_root)
        self.mapping = mapping
        self.anchors = anchors or {}
        self.front_matter = front_matter
        self.assets_needed: set[str] = set()
        # per-document state, filled in by convert_file()
        self.styles = StyleBook()
        self.pictures: list[str] = []
        self.picture_index = 0
        self.picture_stem = ""
        self.cur_rel_dir = ""
        self.wanted_anchors: set[str] = set()
        self.src_zip = ""

    # -- paths ------------------------------------------------------------

    def out_name(self, rel_path: str) -> str:
        """Repo-relative Markdown path for a source document (lower-cased,
        as normalize_names.pl did for the web tree)."""
        directory, base = os.path.split(rel_path)
        stem = os.path.splitext(base)[0]
        return os.path.join(directory, stem.lower() + ".md")

    def resolve_target(self, href: str, cur_rel_dir: str) -> tuple[str, str]:
        """Map an ODF hyperlink to a repo-relative path plus fragment.

        This is the Markdown counterpart of convert_i.pl's &coraddr: the
        catalogue's hrefs are a mix of stale relative paths, absolute Windows
        paths and hand-typed Cyrillic lookalikes, but every target is named
        <number>_<something>, so the number alone locates it.
        """
        href, _, fragment = href.partition("#")
        href = urllib.parse.unquote(href)
        if re.match(r"^[a-zA-Z][a-zA-Z0-9+.-]*:", href) and not href.lower().startswith("file:"):
            return href, fragment  # http(s):, mailto:, … — leave alone
        if not href:
            return "", fragment

        base = re.split(r"[\\/]", href)[-1]
        stem, ext = os.path.splitext(base)
        stem = stem.translate(LOOKALIKE)
        ext = ext.lower()
        if ext in LINKED_DOC_EXT:
            ext = ".md"

        low = stem.lower()
        if "literatur" in low:
            target = "literature.md"
        elif low == "head":
            target = "README.md"
        elif re.fullmatch(r"comment\d*", low):
            target = low + ".md"
        else:
            m = re.match(r"(\d+)_(.+)", stem)
            if m:
                target = "%s/%s_%s" % (m.group(1), m.group(1), m.group(2).lower() + ext)
            else:
                # Nothing recognisable: keep the original relative path,
                # normalised against the current directory.
                target = os.path.normpath(os.path.join(cur_rel_dir, os.path.dirname(href),
                                                       low + ext))
        return target.replace(os.sep, "/"), fragment

    def link(self, href: str, cur_rel_dir: str) -> str:
        target, fragment = self.resolve_target(href, cur_rel_dir)
        if not target:
            return "#" + fragment if fragment else "#"
        if re.match(r"^[a-zA-Z][a-zA-Z0-9+.-]*:", target):
            return target + (("#" + fragment) if fragment else "")
        if os.path.splitext(target)[1].lower() in ASSET_EXT:
            self.assets_needed.add(target)
        rel = os.path.relpath(target, cur_rel_dir or ".").replace(os.sep, "/")
        if fragment:
            rel += "#" + fragment
        return urllib.parse.quote(rel, safe="/#._-~()!$&'*+,;=:@%")

    # -- ODF walking ------------------------------------------------------

    def convert_file(self, rel_path: str) -> dict:
        src = os.path.join(self.src_root, rel_path)
        self.src_zip = src
        with zipfile.ZipFile(src) as zf:
            content = ET.fromstring(zf.read("content.xml"))
            styles = StyleBook()
            try:
                styles.add_document(ET.fromstring(zf.read("styles.xml")))
            except KeyError:
                pass
            styles.add_document(content)
            pictures = self.picture_names(rel_path)

        self.styles = styles
        self.pictures = pictures
        self.picture_index = 0
        self.cur_rel_dir = os.path.dirname(self.out_name(rel_path))
        self.wanted_anchors = self.anchors.get(self.out_name(rel_path), set())

        body = content.find(".//{*}body")
        blocks: list[tuple[str, str]] = []  # (kind, markdown)
        self.walk_blocks(body if body is not None else content, {}, blocks)

        title, lines = self.assemble(blocks)
        text = "\n".join(lines).rstrip() + "\n"
        if self.front_matter:
            text = self.make_front_matter(rel_path, title) + text
        return {"markdown": text, "title": title, "out": self.out_name(rel_path)}

    def picture_names(self, rel_path: str) -> list[str]:
        """Web-ready images for this document, in document order.

        convert_i.pl renamed the GIFs of OpenOffice's HTML export to
        <prefix>_ris<N>.gif; those files are still next to the ODT, so they
        are reused here rather than re-rendered.  Documents without them fall
        back to the pictures embedded in the ODT (see next_picture).
        """
        directory, base = os.path.split(rel_path)
        self.picture_stem = os.path.splitext(base)[0].lower()
        prefix = self.picture_stem.split("_")[0]
        src_dir = os.path.join(self.src_root, directory)
        gifs = []
        if os.path.isdir(src_dir):
            for name in os.listdir(src_dir):
                if re.fullmatch(prefix + r"_ris\d+\.gif", name.lower()):
                    gifs.append(name)
        gifs.sort(key=natural_key)
        return [os.path.join(directory, g).replace(os.sep, "/") for g in gifs]

    def walk_blocks(self, elem: ET.Element, ctx: dict,
                    blocks: list[tuple[str, str]]) -> None:
        for child in elem:
            name = localname(child.tag)
            if name in ("p", "h"):
                runs: list[Run] = []
                self.walk_inline(child, self.push(ctx, child), runs)
                blocks.append(self.render_block(runs, forced_heading=(name == "h")))
            elif name in ("frame", "text-box"):
                runs = []
                self.walk_inline(child, self.push(ctx, child), runs)
                blocks.append(self.render_block(runs))
            elif name in ("list", "list-item", "list-header", "section",
                          "text", "table", "table-row", "table-cell",
                          "note-body"):
                self.walk_blocks(child, ctx, blocks)

    def push(self, ctx: dict, elem: ET.Element) -> dict:
        """Extend a formatting context with the style of one element."""
        props = self.styles.resolve(attr(elem, "style-name"))
        if not props:
            return ctx
        new = dict(ctx)
        if "bold" in props:
            new["bold"] = props["bold"]
        if "italic" in props:
            new["italic"] = props["italic"]
        if "font" in props:
            new["cyr"] = self.styles.is_cyrillica(props["font"])
        return new

    def walk_inline(self, elem: ET.Element, ctx: dict, runs: list[Run]) -> None:
        if elem.text:
            runs.append(Run(elem.text, ctx))
        for child in elem:
            name = localname(child.tag)
            if name == "span":
                self.walk_inline(child, self.push(ctx, child), runs)
            elif name == "a":
                inner = dict(self.push(ctx, child))
                inner["href"] = attr(child, "href") or ""
                self.walk_inline(child, inner, runs)
            elif name == "s":
                count = attr(child, "c")
                runs.append(Run(" " * (int(count) if count and count.isdigit() else 1), ctx))
            elif name == "tab":
                runs.append(Run(" ", ctx))
            elif name == "line-break":
                runs.append(Run("", ctx, kind="break"))
            elif name in ("bookmark", "bookmark-start"):
                bookmark = attr(child, "name")
                if bookmark and bookmark in self.wanted_anchors:
                    runs.append(Run(bookmark, ctx, kind="anchor"))
            elif name in ("frame", "text-box"):
                self.walk_inline(child, self.push(ctx, child), runs)
            elif name == "image":
                runs.append(Run(self.next_picture(attr(child, "href")), ctx,
                                kind="image"))
            elif name in ("note", "annotation"):
                continue  # footnotes/comments are editorial, as in convert_i.pl
            else:
                self.walk_inline(child, ctx, runs)
            if child.tail:
                runs.append(Run(child.tail, ctx))

    def next_picture(self, href: str | None) -> str:
        """Path (relative to the current page) of the next image, or "".

        Falls back to unpacking the picture stored inside the ODT when no
        pre-rendered GIF is available; OpenOffice metafiles (.svm), which no
        browser can display, are reported and skipped.
        """
        index = self.picture_index
        self.picture_index += 1
        if index < len(self.pictures):
            target = self.pictures[index]
            self.assets_needed.add(target)
        elif href and os.path.splitext(href)[1].lower() in ASSET_EXT:
            target = os.path.join(self.cur_rel_dir,
                                  "%s_img%d%s" % (self.picture_stem, index + 1,
                                                  os.path.splitext(href)[1].lower()))
            target = target.replace(os.sep, "/")
            dest = os.path.join(self.out_root, target)
            os.makedirs(os.path.dirname(dest) or ".", exist_ok=True)
            try:
                with zipfile.ZipFile(self.src_zip) as zf, open(dest, "wb") as fh:
                    fh.write(zf.read(href))
            except (KeyError, OSError) as exc:
                print("cannot unpack %s from %s: %s" % (href, self.src_zip, exc),
                      file=sys.stderr)
                return ""
        else:
            print("no web-ready image for %s picture %d (%s)"
                  % (self.src_zip, index + 1, href or "?"), file=sys.stderr)
            return ""
        return os.path.relpath(target, self.cur_rel_dir or ".").replace(os.sep, "/")

    # -- inline rendering -------------------------------------------------

    def render_block(self, runs: list[Run], forced_heading: bool = False) -> tuple[str, str]:
        runs = [r for r in runs if r.kind != "text" or r.text]
        if not runs:
            return ("blank", "")

        text_runs = [r for r in runs if r.kind == "text" and r.text.strip()]
        is_heading = forced_heading or (
            bool(text_runs) and all(r.bold and not r.href for r in text_runs)
        )

        masker = MaskedText()
        body = self.render_runs(runs, masker, suppress_bold=is_heading)
        body = re.sub(r"[ \t]+", " ", body).strip()
        if not body:
            return ("blank", "")
        body = masker.unmask(apply_typography(body))
        body = escape_block_start(body)

        plain = strip_markup(body)
        if is_heading and len(plain) <= 5:
            # convert_i.pl dropped <H3> around such fragments as well.
            is_heading = False
        return ("heading" if is_heading else "para", body)

    def render_runs(self, runs: list[Run], masker: MaskedText,
                    suppress_bold: bool = False) -> str:
        """Render a paragraph's runs: emphasis first, then the link wrapping.

        Emphasis is done before links so that a chunk always knows the text
        on either side of it, which decides whether `*`/`**` can be used at
        all (see emphasize).
        """
        chunks = []
        for key, group in group_by(runs, lambda r: (r.href,) + r.style_key()):
            href, bold, italic, cyr = key
            chunks.append({"href": href,
                           "bold": bold and not suppress_bold,
                           "italic": italic,
                           "text": self.render_plain(group, masker, cyr)})

        for index, chunk in enumerate(chunks):
            before = chunks[index - 1]["text"] if index else ""
            after = chunks[index + 1]["text"] if index + 1 < len(chunks) else ""
            chunk["text"] = emphasize(chunk["text"], chunk["bold"],
                                      chunk["italic"], before, after)

        out: list[str] = []
        for href, group in group_by(chunks, lambda c: c["href"]):
            inner = "".join(c["text"] for c in group)
            lead, core, trail = split_ws(inner)
            if not href or not core:
                out.append(inner)
                continue
            # convert_i.pl moved whitespace out of </A>; the same here, so the
            # link text never starts or ends with a space.
            target = masker.mask(self.link(href, self.cur_rel_dir))
            out.append("%s[%s](%s)%s" % (lead, core, target, trail))
        return merge_cyr_spans("".join(out), masker)

    def render_plain(self, runs: list[Run], masker: MaskedText, cyr: bool) -> str:
        out: list[str] = []
        for run in runs:
            if run.kind == "break":
                out.append(masker.mask("<br>"))
            elif run.kind == "anchor":
                out.append(masker.mask('<a id="%s"></a>' % run.text))
            elif run.kind == "image":
                out.append(masker.mask("![](%s)" % run.text) if run.text else "")
            elif cyr:
                # Whitespace stays outside the span, as convert_i.pl kept it
                # outside <CYR>…</CYR>.
                lead, core, trail = split_ws(run.text)
                if core:
                    converted = cyrillica_to_unicode(core, self.mapping)
                    out.append(lead + masker.mask(CYR_SPAN_OPEN + converted +
                                                  CYR_SPAN_CLOSE) + trail)
                else:
                    out.append(run.text)
            else:
                out.append(escape_md(run.text))
        return "".join(out)

    # -- assembly ---------------------------------------------------------

    def assemble(self, blocks: list[tuple[str, str]]) -> tuple[str, list[str]]:
        title = ""
        lines: list[str] = []
        seen_heading = False
        for kind, body in blocks:
            if kind == "blank":
                continue
            if kind == "heading":
                level = "#" if not seen_heading else "##"
                if not seen_heading:
                    title = clean_title(strip_markup(body))
                seen_heading = True
                lines.extend([level + " " + body, ""])
            else:
                if not title:
                    title = clean_title(strip_markup(body))
                lines.extend([body, ""])
        return title, lines

    def make_front_matter(self, rel_path: str, title: str) -> str:
        src = os.path.join(self.src_root, rel_path)
        updated = datetime.fromtimestamp(os.path.getmtime(src)).strftime("%Y-%m-%d")
        fields = [
            ("title", title),
            ("source", rel_path.replace(os.sep, "/")),
            ("updated", updated),
        ]
        out = ["---"]
        out += ["%s: %s" % (k, yaml_scalar(v)) for k, v in fields]
        out += ["---", ""]
        return "\n".join(out) + "\n"


# --------------------------------------------------------------------------
# small helpers
# --------------------------------------------------------------------------

_MD_ESCAPE = re.compile(r"([\\`*_\[\]<>])")
_WS_SPLIT = re.compile(r"^(\s*)(.*?)(\s*)$", re.S)
_MARKUP = re.compile(r"</?[a-zA-Z][^>]*>|[*`\\]|!?\[|\]\([^)]*\)")


def escape_md(text: str) -> str:
    return _MD_ESCAPE.sub(r"\\\1", text)


def escape_block_start(text: str) -> str:
    """Keep a paragraph from being read as a list, heading or quote."""
    return re.sub(r"^(#{1,6}\s|[-+]\s|>\s|\d+[.)]\s)",
                  lambda m: "\\" + m.group(1) if m.group(1)[0] in "#-+>"
                  else m.group(1)[:-2] + "\\" + m.group(1)[-2:], text)


def split_ws(text: str) -> tuple[str, str, str]:
    m = _WS_SPLIT.match(text)
    return m.group(1), m.group(2), m.group(3)


def strip_markup(text: str) -> str:
    return re.sub(r"\s+", " ", _MARKUP.sub("", text)).strip()


def clean_title(text: str) -> str:
    # convert_i.pl: $title=~s#\.(\d)#. $1#
    return re.sub(r"\.(\d)", r". \1", text).strip()


# Characters next to which a Markdown emphasis marker still parses as one.
OPEN_OK = "([{«“‘\u2039<\u2014\u2013-\u2011/"
CLOSE_OK = ")]}»”’\u203a>.,;:!?…\u2014\u2013-\u2011/"


def emphasize(text: str, bold: bool, italic: bool, before: str, after: str) -> str:
    """Wrap one chunk in bold/italic markup.

    `*`/`**` are used where they parse reliably — that is, where the marker
    touches whitespace, the block edge or bracketing punctuation.  Inside a
    word (the catalogue is full of restorations like «подоба[ет Тебе]», where
    the brackets are italic and their contents are not) CommonMark would
    mis-pair the asterisks, so <em>/<strong> are emitted instead.
    """
    if (not bold and not italic) or not text.strip():
        return text
    lead, core, trail = split_ws(text)
    left = lead[-1:] or before[-1:]
    right = trail[:1] or after[:1]
    plain_ok = (not left or left.isspace() or left in OPEN_OK) and \
               (not right or right.isspace() or right in CLOSE_OK)
    if plain_ok:
        marker = ("**" if bold else "") + ("*" if italic else "")
        return lead + marker + core + marker[::-1] + trail
    tags = (["strong"] if bold else []) + (["em"] if italic else [])
    open_tags = "".join("<%s>" % t for t in tags)
    close_tags = "".join("</%s>" % t for t in reversed(tags))
    return lead + open_tags + core + close_tags + trail


_TWO_MASKS = re.compile("\x00([\ue000-\uf8ff])\x00([ \t]*)\x00([\ue000-\uf8ff])\x00")


def merge_cyr_spans(text: str, masker: MaskedText) -> str:
    """Fuse Church Slavonic spans that ended up side by side.

    The runs of one word are often split across several ODF spans that differ
    only in some irrelevant attribute; convert_i.pl glued them back together
    with s#</CYR><CYR>##, and so does this — here also across the whitespace
    that convert_i.pl had shifted out of the run, which keeps a transcribed
    paragraph down to a single span.
    """
    def repl(m: re.Match) -> str:
        left = masker.chunks[ord(m.group(1)) - 0xE000]
        right = masker.chunks[ord(m.group(3)) - 0xE000]
        if left.endswith(CYR_SPAN_CLOSE) and right.startswith(CYR_SPAN_OPEN):
            return masker.mask(left[: -len(CYR_SPAN_CLOSE)] + m.group(2) +
                               right[len(CYR_SPAN_OPEN):])
        return m.group(0)

    while True:
        merged = _TWO_MASKS.sub(repl, text)
        if merged == text:
            return text
        text = merged


def group_by(items, key):
    """Yield (key, [items…]) for maximal runs of equal key."""
    group: list = []
    current = object()
    for item in items:
        k = key(item)
        if group and k != current:
            yield current, group
            group = []
        current = k
        group.append(item)
    if group:
        yield current, group


def natural_key(text: str):
    return [int(part) if part.isdigit() else part.lower()
            for part in re.split(r"(\d+)", text)]


def yaml_scalar(value: str) -> str:
    return '"%s"' % value.replace("\\", "\\\\").replace('"', '\\"')


# --------------------------------------------------------------------------
# driver
# --------------------------------------------------------------------------

def find_documents(src_root: str) -> list[str]:
    docs = []
    for dirpath, dirnames, filenames in os.walk(src_root):
        dirnames[:] = [d for d in dirnames if not d.startswith(".")]
        for name in filenames:
            if os.path.splitext(name)[1].lower() in DOC_EXT:
                docs.append(os.path.relpath(os.path.join(dirpath, name), src_root))
    docs.sort(key=natural_key)
    return docs


def collect_anchors(src_root: str, docs: list[str], conv: Converter) -> dict[str, set[str]]:
    """Bookmarks that some link actually points at, per target page.

    Only these become <a id="…"></a>; the thousands of DDE_LINK/OLE_LINK
    bookmarks Word left behind are dropped, exactly as convert_i.pl dropped
    <A NAME="DDE_LINK…"> and <A NAME="OLE_LINK…">.
    """
    wanted: dict[str, set[str]] = {}
    href_re = re.compile(r'xlink:href="([^"]*)"')
    for rel_path in docs:
        cur_dir = os.path.dirname(conv.out_name(rel_path))
        try:
            with zipfile.ZipFile(os.path.join(src_root, rel_path)) as zf:
                xml = zf.read("content.xml").decode("utf-8", "replace")
        except (zipfile.BadZipFile, KeyError, OSError):
            continue
        for href in href_re.findall(xml):
            if "#" not in href:
                continue
            target, fragment = conv.resolve_target(href, cur_dir)
            if fragment and target.endswith(".md"):
                wanted.setdefault(target, set()).add(fragment)
    return wanted


def copy_assets(src_root: str, out_root: str, wanted: set[str] | None) -> int:
    """Copy PDFs and images alongside the Markdown so links resolve locally."""
    copied = 0
    for dirpath, dirnames, filenames in os.walk(src_root):
        dirnames[:] = [d for d in dirnames if not d.startswith(".")]
        for name in filenames:
            if os.path.splitext(name)[1].lower() not in ASSET_EXT:
                continue
            rel = os.path.relpath(os.path.join(dirpath, name), src_root)
            directory, base = os.path.split(rel)
            target = os.path.join(directory, base.lower()).replace(os.sep, "/")
            if wanted is not None and target not in wanted:
                continue
            dest = os.path.join(out_root, target)
            os.makedirs(os.path.dirname(dest) or ".", exist_ok=True)
            src = os.path.join(dirpath, name)
            if not (os.path.exists(dest)
                    and os.path.getmtime(dest) >= os.path.getmtime(src)
                    and os.path.getsize(dest) == os.path.getsize(src)):
                shutil.copy2(src, dest)
            copied += 1
    return copied


def write_indexes(out_root: str, pages: list[dict]) -> None:
    """README.md per directory plus a root index — the browsable counterpart
    of the nav.shtml drop-down convert_i.pl generated."""
    by_dir: dict[str, list[dict]] = {}
    for page in pages:
        by_dir.setdefault(os.path.dirname(page["out"]), []).append(page)

    for directory, entries in by_dir.items():
        if not directory:
            continue
        entries.sort(key=lambda p: natural_key(p["out"]))
        lines = ["# %s" % (directory or "."), ""]
        for entry in entries:
            base = os.path.basename(entry["out"])
            label = entry["title"] or os.path.splitext(base)[0]
            lines.append("- [%s](%s)" % (label, base))
        lines.append("")
        with open(os.path.join(out_root, directory, "README.md"), "w",
                  encoding="utf-8") as fh:
            fh.write("\n".join(lines))

    lines = ["# Каталог", ""]
    for directory in sorted((d for d in by_dir if d), key=natural_key):
        entries = sorted(by_dir[directory], key=lambda p: natural_key(p["out"]))
        label = entries[0]["title"] or directory
        lines.append("- [%s](%s/README.md) — %s" % (directory, directory, label))
    root_entries = sorted(by_dir.get("", []), key=lambda p: natural_key(p["out"]))
    if root_entries:
        lines += ["", "## Общие материалы", ""]
        for entry in root_entries:
            label = entry["title"] or os.path.splitext(entry["out"])[0]
            lines.append("- [%s](%s)" % (label, entry["out"]))
    lines.append("")
    with open(os.path.join(out_root, "README.md"), "w", encoding="utf-8") as fh:
        fh.write("\n".join(lines))


def main(argv: list[str]) -> int:
    here = os.path.dirname(os.path.abspath(__file__))
    parser = argparse.ArgumentParser(
        description="Convert the SOF ODT catalogue to a browsable Markdown repo.")
    parser.add_argument("src", nargs="?", default=".", help="source tree (default: .)")
    parser.add_argument("-o", "--output", help="output tree (default: <src>-md)")
    parser.add_argument("--map", dest="mapping",
                        default=os.path.join(here, "cyrillica_bg_epigraph_mod_to_unicode.json"),
                        help="CyrillicaBgEpigraphMod → Unicode mapping (JSON)")
    parser.add_argument("--only", metavar="REGEX",
                        help="convert only documents whose path matches REGEX")
    parser.add_argument("--no-assets", action="store_true",
                        help="do not copy PDFs and images into the output tree")
    parser.add_argument("--linked-assets-only", action="store_true",
                        help="copy only the PDFs and images that are linked to")
    parser.add_argument("--no-index", action="store_true",
                        help="do not generate README.md index pages")
    parser.add_argument("--no-front-matter", action="store_true",
                        help="do not emit YAML front matter")
    parser.add_argument("--clean", action="store_true",
                        help="delete the output tree first (convert_i.pl did this)")
    parser.add_argument("-q", "--quiet", action="store_true")
    args = parser.parse_args(argv)

    src_root = os.path.abspath(args.src)
    if not os.path.isdir(src_root):
        parser.error("no such directory: %s" % src_root)
    out_root = os.path.abspath(args.output or (src_root.rstrip(os.sep) + "-md"))
    if out_root == src_root or src_root.startswith(out_root + os.sep):
        parser.error("the output tree must not contain the source tree")

    try:
        mapping = load_cyrillica_map(args.mapping)
    except OSError as exc:
        parser.error("cannot read font mapping: %s" % exc)

    if args.clean and os.path.isdir(out_root):
        shutil.rmtree(out_root)
    os.makedirs(out_root, exist_ok=True)

    docs = find_documents(src_root)
    if args.only:
        pattern = re.compile(args.only)
        docs = [d for d in docs if pattern.search(d)]
    if not docs:
        print("no .odt documents found under %s" % src_root, file=sys.stderr)
        return 1

    conv = Converter(src_root, out_root, mapping,
                     front_matter=not args.no_front_matter)
    conv.anchors = collect_anchors(src_root, docs, conv)

    pages: list[dict] = []
    failures = 0
    for rel_path in docs:
        try:
            page = conv.convert_file(rel_path)
        except Exception as exc:  # a damaged ODT must not stop the run
            print("FAILED %s: %s: %s" % (rel_path, type(exc).__name__, exc),
                  file=sys.stderr)
            failures += 1
            continue
        dest = os.path.join(out_root, page["out"])
        os.makedirs(os.path.dirname(dest) or ".", exist_ok=True)
        with open(dest, "w", encoding="utf-8") as fh:
            fh.write(page["markdown"])
        pages.append(page)
        if not args.quiet:
            print("%s -> %s" % (rel_path, page["out"]))

    if not args.no_assets:
        wanted = conv.assets_needed if args.linked_assets_only else None
        copied = copy_assets(src_root, out_root, wanted)
        if not args.quiet:
            print("copied %d asset(s)" % copied)

    if not args.no_index:
        write_indexes(out_root, pages)

    if not args.quiet:
        print("converted %d document(s) into %s%s"
              % (len(pages), out_root,
                 "" if not failures else " (%d failed)" % failures))
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
