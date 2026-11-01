# MycoBase extraction: steps 1 and 2

Extract species descriptions from taxonomic papers (Studies in Mycology) into MycoBase.
This part covers **step 1 (layout reconstruction)** and **step 2 (segmentation)**.

**Rule (mentor):** MycoBase contains only species accepted in Visagie et al. 2025,
*From chaos to tranquillity* (Studies in Mycology 112). The tool extracts everything into the
raw output, then marks which sections can go to MycoBase:

| name status | meaning | target |
|---|---|---|
| `accepted` | name is on the accepted list | `mycobase` |
| `synonym` | MycoBank's current name for it is an accepted species | `mycobase` (under the accepted name) |
| `not_accepted` | in MycoBank, but not leading to an accepted species | `raw_only` |
| `unknown` | not in MycoBank (new, misread or out of scope) | `raw_only` |

## Layout

```
config/label_dictionary.json   paper headings -> MycoBase fields (edit here, no code change)
src/extraction/
    text.py                    text + style helpers, label detection
    layout.py                  step 1: PDF -> clean lines in reading order
    names.py                   accepted list + MycoBank name index, name resolution
    segment.py                 step 2: species sections, kind, name status, target
src/06_run_steps.py        command line for steps 1-2
tests/test_steps_1_2.py        regression tests on real papers
```

Not in git (see `.gitignore`): `studies_in_mycology/` (PDFs), `data/excel/Mycobank.xlsx`,
`data/cache/` (MycoBank index), `output/`.

## Run

```
pip install -r requirements.txt

# one time (about 2-3 minutes): build the MycoBank name index from data/excel/Mycobank.xlsx
python src/06_run_steps.py --build-mycobank-index

# one paper, or a whole folder
python src/06_run_steps.py --pdf "studies_in_mycology/Vol84Art2_New-Talaromyces-species-from-indoor-environments-in-C_2016_Studies-in-Mycolo.pdf"
python src/06_run_steps.py --pdf studies_in_mycology

# tests
python -m pytest -q tests
```

## Output (`output/`)

| file | what to look at |
|---|---|
| `<paper>/clean_text.txt` | Step 1. Every clean line as `p<page> c<column> <size>pt \| text`, with `**bold**` and `_italic_`. Check that headers, captions and tables are gone and the column order is right. |
| `<paper>/sections.json` | Step 2. One entry per species section: name in paper, accepted name, kind, target, pages, MycoBank number, labels found, body text. |
| `<paper>/figures/` | Every figure as an image: `fig06_p12.jpg` = Fig. 6 on page 12 (JPEG for photo plates, PNG for trees and drawings). |
| `<paper>/figures.json` | Per figure: number, page, file, kind (plate / phylogeny / drawing), caption, `main_species`, species named in the caption and in tree labels, each resolved to the accepted name. |
| `figures_summary.tsv` | All figures of all papers in one table. |
| `sections_summary.tsv` | All sections of all papers in one table (opens in Excel). |
| `run_stats.json` | Per paper: ok / duplicate / needs OCR, counts, time. |

## How it works

**Step 1** reads each text line with font size, bold and italic (PyMuPDF), finds the body font size,
removes running headers/footers and page numbers (only in the page margins), captions, small-print
tables and rotated tables, orders two-column pages and merges the pieces of justified lines.

**Step 2** starts a species section at a line that begins with a bold *Genus epithet* and is either
in a larger font or followed by a citation cue (MycoBank, MB number, sp. nov., Fig. n). Lines up to
the first field label that carry the citation (e.g. `MycoBank MB817398. Fig. 6.`) belong to the
heading. A section ends at the next species heading or at DISCUSSION / REFERENCES. Each section is
classified as `treatment` (has description labels) or `name_entry` (name list), and its name is
resolved against the accepted list and MycoBank.

**Figures** (`src/extraction/figures.py`). Captions ("Fig. 6. ...") are kept out of the text, but the
figure is saved: the graphics between the caption and the paragraph above it are rendered to an image.
Species are attached from three places: the caption ("Morphological characters of *Talaromyces aerius*"),
the species heading that cites the figure ("MycoBank MB817398. Fig. 6."), and tree labels. In
`sections.json` every species gets `figures` (its plates) and `in_trees` (trees that show it).
Tables are not saved as figures. Use `--no-figures` to skip this, `--fig-dpi` to change the resolution.

**Step 3** (`src/extraction/fields.py`) splits every section at its field labels: a bold/italic label
with a colon ("Etymology:"), a short bold line ("Description"), or a dictionary label in plain text at
the start of a paragraph ("In: Talaromyces section ..."). Labels not in the dictionary count only when
they recur in at least a quarter of the paper's treatments. Labels are mapped to MycoBase columns
with `config/label_dictionary.json`; unknown ones are kept as `Other: <label>` and listed first in
`labels_report.tsv`, so the dictionary can be extended without changing code. Small-print synonym
lines ("≡ Emericella desertorum ...") become `Synonyms`; unlabelled text under the heading becomes
`Description`. A genus treatment ("Ovatospora ..., gen. nov.") ends the species section before it.

## Known limits

* Scanned PDFs (no text layer, e.g. volume 45) are reported as `needs OCR` and skipped.
* Species mentioned only in a Notes section, without a bold heading, are not sections.
* Labels of a tree pasted in as a picture (e.g. Talaromyces 2016) cannot be read without OCR, so such
  trees get species only from their caption.
* Comparison plates without names in the caption ("Growth comparison of ... species") get no species.
* MycoBank still lists some old names (e.g. *Neosartorya*) as current; those come out as
  `not_accepted` and need a curator (or a rule) to map them to the *Aspergillus* name.
