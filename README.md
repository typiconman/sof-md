# sof-md

Descriptions of the Sluzhebnik (Служебник) manuscripts in the Collection of
Novgorod's St Sophia Cathedral (Соф.) at the National Library of Russia, as a browsable Markdown repository. This repository is used as the source code for the [HTML website](https://byzantinorossica.ponomar.net/sof-catalog.html).

## Layout

- [original/](original/) — the descriptions, one directory per shelfmark,
  each with a `.md` file and a `README.md` index. This is the tracked
  deliverable.
- [scripts/](scripts/) — the conversion tooling.
  [odt2md.py](scripts/odt2md.py) converts the legacy OpenOffice (`.odt`)
  catalog to the Markdown in `original/`; see its docstring for details.
  [cyrillica_bg_epigraph_mod_to_unicode.json](scripts/cyrillica_bg_epigraph_mod_to_unicode.json)
  is the font-decoding table it relies on, based on the obsolete CyrillicaBgEpigraphMod font.
  [md2html.py](scripts/md2html.py) builds the HTML website from `original/`,
  taking over from the legacy `SOF/convert_i.pl`.
- `SOF/` — the legacy `.odt` source tree and the old Perl/HTML conversion
  pipeline it replaces. Kept locally only; not tracked in this repository.
- `encoding.ods` — a spreadsheet that was used to make scripts/cyrillica_bg_epigraph_mod_to_unicode.json, will be deleted eventually.

## Running the tools

Both scripts need only the Python standard library (3.9+).

Convert the legacy ODT catalog to Markdown:

```sh
python3 scripts/odt2md.py SOF -o original
```

Build the website from the Markdown:

```sh
python3 scripts/md2html.py original -o original-html
```

See `--help` for the available options (`--only`, `--no-assets`, `--clean`,
etc). `md2html.py` reproduces the look of the pages the old `convert_i.pl`
generated, rewrites `.md` links to `.html`, and puts every
`<span class="cu-text">` run — the Church Slavonic that `odt2md.py` decoded
from the obsolete CyrillicaBgEpigraphMod font — into the
[Shafarik](https://sci.ponomar.net/) webfont, where the old pipeline could
only render it to a JPEG. The output tree is a build artifact and is not
tracked.

## License and authorship

The `LICENSE` file (MIT) covers the code in `scripts/` only. The manuscript
descriptions in `original/` are copyrighted by their authors and are not
covered by that license.

The cataloguing project was supported by grant N 06-01-12102v of the
Russian Foundation for the Humanities. Project team: T.I. Afanasyeva,
E.V. Krushelnitskaya, O.V. Motygin, A.S. Slutsky (director).
