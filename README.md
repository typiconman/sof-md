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
- `SOF/` — the legacy `.odt` source tree and the old Perl/HTML conversion
  pipeline it replaces. Kept locally only; not tracked in this repository.
- `encoding.ods` — a spreadsheet that was used to make scripts/cyrillica_bg_epigraph_mod_to_unicode.json, will be deleted eventually.

## Running the converter

`odt2md.py` needs only the Python standard library (3.9+):

```sh
python3 scripts/odt2md.py SOF -o original
```

See `python3 scripts/odt2md.py --help` for the available options
(`--only`, `--no-assets`, `--clean`, etc).
