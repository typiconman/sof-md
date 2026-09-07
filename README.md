# sof-md

Descriptions of the Sluzhebnik (Служебник) manuscripts in the Collection of
Novgorod's St Sophia Cathedral (Соф.), as a browsable Markdown repository.

## Layout

- [original/](original/) — the descriptions, one directory per shelfmark,
  each with a `.md` file and a `README.md` index. This is the tracked
  deliverable.
- [scripts/](scripts/) — the conversion tooling.
  [odt2md.py](scripts/odt2md.py) converts the legacy OpenOffice (`.odt`)
  catalogue to the Markdown in `original/`; see its docstring for details.
  [cyrillica_bg_epigraph_mod_to_unicode.json](scripts/cyrillica_bg_epigraph_mod_to_unicode.json)
  is the font-decoding table it relies on.
- `SOF/` — the legacy `.odt` source tree and the old Perl/HTML conversion
  pipeline it replaces. Kept locally only; not tracked in this repository.

## Running the converter

`odt2md.py` needs only the Python standard library (3.9+):

```sh
python3 scripts/odt2md.py SOF -o original
```

See `python3 scripts/odt2md.py --help` for the available options
(`--only`, `--no-assets`, `--clean`, etc).
