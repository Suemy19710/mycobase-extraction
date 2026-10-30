"""Regression tests for step 1 (layout) and step 2 (segmentation).

They run on real papers in studies_in_mycology/ (not in git); a test is skipped when its PDF
is missing. Run from the repository folder:   python -m pytest -q tests
"""
import sys
from functools import lru_cache
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))
import tempfile  # noqa: E402

from extraction.figures import extract_figures, figure_numbers, link_sections, save_species_images  # noqa: E402
from extraction.layout import clean_lines, pdf_lines  # noqa: E402
from extraction.names import NameIndex  # noqa: E402
from extraction.segment import classify, find_sections  # noqa: E402
from extraction.text import join_lines, line_text  # noqa: E402

PAPERS = ROOT / "studies_in_mycology"
CHEN_2017 = "Vol88Art2_Polyphasic-taxonomy-of-Aspergillus-section-Aspergillus--forme_2017_Studies-i.pdf"
TALAROMYCES_2016 = "Vol84Art2_New-Talaromyces-species-from-indoor-environments-in-C_2016_Studies-in-Mycolo.pdf"
SAMSON_2007 = "Samson et al 2007 Stud Mycol 59 147-203.pdf"
VISAGIE_2014 = "sim78Art1.pdf"


@lru_cache(maxsize=1)
def names():
    return NameIndex(ROOT / "data" / "species_description.json",
                     ROOT / "data" / "cache" / "mycobank_index.tsv.gz")


@lru_cache(maxsize=None)
def run(paper):
    path = PAPERS / paper
    if not path.exists():
        pytest.skip(f"{paper} not in studies_in_mycology/")
    clean, body = clean_lines(pdf_lines(str(path)))
    text = "\n".join(line_text(r) for r in clean)
    sections = [dict(classify(s, names()), body_text=join_lines([line_text(r) for r in s["body"]]))
                for s in find_sections(clean, body, names())]
    return text, sections


def by_species(sections):
    return {s["species"]: s for s in sections}


# ---------------------------------------------------------------- step 1: layout
def test_running_headers_removed():
    text, _ = run(CHEN_2017)
    assert "www.studiesinmycology.org" not in text
    assert "REVISION OF ASPERGILLUS SECTION ASPERGILLUS" not in text.upper().replace("A SPERGILLUS", "ASPERGILLUS")


def test_numbers_inside_text_are_kept():
    # a digits-only fragment of justified text was once removed as if it were a page number
    _, sections = run(CHEN_2017)
    assert "IRAN 16110 F" in by_species(sections)["Aspergillus osmophilus"]["body_text"]

def test_sentence_comes_out_whole():
    _, sections = run(CHEN_2017)
    assert "isolated from air treatment system" in by_species(sections)["Aspergillus aerius"]["body_text"]


def test_hyphenation_undone():
    _, sections = run(CHEN_2017)
    body = by_species(sections)["Aspergillus aurantiacoflavus"]["body_text"]
    assert "sporulation absent to sparse" in body          # "ab-" + "sent" in the PDF


# ---------------------------------------------------------------- step 2: segmentation
def test_talaromyces_species_found():
    _, sections = run(TALAROMYCES_2016)
    found = {s["species"] for s in sections if s["kind"] == "treatment"}
    assert found == {"Talaromyces aerius", "Talaromyces adpressus", "Talaromyces beijingensis",
                     "Talaromyces cerinus", "Talaromyces chlamydosporus", "Talaromyces diversiformis",
                     "Talaromyces fusiformis", "Talaromyces neorugulosus", "Talaromyces reverso-olivaceus"}


def test_mycobank_number_on_second_heading_line():
    # "Talaromyces aerius A.J. Chen, Frisvad & Samson, sp. nov." / "MycoBank MB817398. Fig. 6."
    _, sections = run(TALAROMYCES_2016)
    s = by_species(sections)["Talaromyces aerius"]
    assert s["mycobank_in_paper"] == "817398"
    assert "MycoBank MB817398" in s["nomenclature"]


def test_methods_subheadings_are_not_species():
    _, sections = run(TALAROMYCES_2016)
    assert not any(s["species"].startswith(("Phylogenetic", "Morphological", "Extrolites")) for s in sections)


def test_heading_sharing_a_block_with_small_print_synonyms():
    # N. spinosa's heading is in one block with 8 pt synonym lines; it was once lost
    _, sections = run(SAMSON_2007)
    assert "Neosartorya spinosa" in by_species(sections)


def test_old_name_resolved_to_accepted_name():
    _, sections = run(SAMSON_2007)
    res = by_species(sections)["Neosartorya fischeri"]["name"]
    if not names().has_mycobank:
        pytest.skip("MycoBank index not built")
    assert res["status"] in ("synonym", "not_accepted")      # MycoBank may still list the old name
    assert res["name_in_paper"] == "Neosartorya fischeri"


# species treatments (full descriptions) per paper; name-list entries are counted separately
EXPECTED_TREATMENTS = {CHEN_2017: 31, TALAROMYCES_2016: 9, SAMSON_2007: 33, VISAGIE_2014: 27}
EXPECTED_NAME_ENTRIES = {CHEN_2017: 5, TALAROMYCES_2016: 0, SAMSON_2007: 0, VISAGIE_2014: 0}


def test_species_counts():
    for paper, n in EXPECTED_TREATMENTS.items():
        _, sections = run(paper)
        kinds = [s["kind"] for s in sections]
        assert kinds.count("treatment") == n, f"{paper}: {kinds.count('treatment')} treatments, expected {n}"
        m = EXPECTED_NAME_ENTRIES[paper]
        assert kinds.count("name_entry") == m, f"{paper}: {kinds.count('name_entry')} name entries, expected {m}"


# ---------------------------------------------------------------- figures
FIG_DIR = Path(tempfile.mkdtemp(prefix="mycobase_figs_"))


@lru_cache(maxsize=None)
def figs(paper):
    path = PAPERS / paper
    if not path.exists():
        pytest.skip(f"{paper} not in studies_in_mycology/")
    lines = pdf_lines(str(path))
    clean, body = clean_lines(lines)
    sections = [classify(s, names()) for s in find_sections(clean, body, names())]
    out = FIG_DIR / path.stem
    figures = extract_figures(str(path), lines, clean, names(), {s["species"] for s in sections})
    save_species_images(str(path), figures, sections, out / "figures", dpi=60)
    link_sections(sections, figures)
    return out, figures, sections


def test_figure_numbers():
    assert figure_numbers("MycoBank MB817398. Fig. 6.") == [6]
    assert figure_numbers("sp. nov. Figs 6, 7.") == [6, 7]
    assert figure_numbers("Figs 6–8") == [6, 7, 8]
    assert figure_numbers("Fig. 6A–C") == [6]


def test_plate_saved_and_attached_to_species():
    out, figures, sections = figs(TALAROMYCES_2016)
    s = by_species(sections)["Talaromyces aerius"]
    assert [f["figure"] for f in s["figures"]] == [6]
    assert (out / s["figures"][0]["file"]).exists()
    f6 = next(f for f in figures if f["figure"] == 6)
    assert f6["main_species"] == "Talaromyces aerius" and f6["kind"] == "plate"


def test_every_treatment_has_its_plate():
    for paper in (TALAROMYCES_2016, SAMSON_2007, VISAGIE_2014, CHEN_2017):
        _, _, sections = figs(paper)
        missing = [s["species"] for s in sections if s["kind"] == "treatment" and not s["figures"]]
        assert not missing, f"{paper}: no figure for {missing}"


def test_tree_titles_are_not_captions():
    # "Fig. 2. cmd" printed inside the Samson 2007 trees is a title, not a caption
    _, figures, _ = figs(SAMSON_2007)
    trees = [f for f in figures if f["figure"] in (1, 2, 3, 4)]
    assert sorted(f["figure"] for f in trees) == [1, 2, 3, 4]
    assert all(f["bbox"] and f["kind"] == "phylogeny" for f in trees)


def test_tables_are_not_figures():
    _, figures, _ = figs(CHEN_2017)
    assert not [f for f in figures if f["uncaptioned"]]       # Tables 5-6 (p21-23) were saved once


def test_text_pages_are_not_figures():
    # Samson 2007 p44/p55 draw some letters as vector shapes; they are text, not figures
    _, figures, _ = figs(SAMSON_2007)
    assert not [f for f in figures if f["uncaptioned"]]


def test_continued_figure_inherits_kind():
    _, figures, _ = figs(CHEN_2017)
    parts = [f for f in figures if f["figure"] == 1]
    assert len(parts) == 2 and all(f["kind"] == "phylogeny" for f in parts)


def test_caption_on_next_page_joined_to_tree():
    # Talaromyces Fig. 3: tree on page 8, caption at the bottom of page 9
    _, figures, _ = figs(TALAROMYCES_2016)
    f3 = [f for f in figures if f["figure"] == 3]
    assert len(f3) == 1 and f3[0]["page"] == 8 and f3[0]["caption"].startswith("Fig. 3")


def test_only_species_images_are_saved():
    # trees, "(Continued)" tree pages and comparison plates are listed but not saved
    out, figures, _ = figs(CHEN_2017)
    saved = [f for f in figures if f["file"]]
    assert saved and all(f["kind"] == "plate" and f["main_species"] for f in saved)
    assert not any(f["file"] for f in figures if f["kind"] == "phylogeny")
    f6 = next(f for f in figures if f["figure"] == 6)            # ascospores of several species
    assert f6["file"] is None and "several species" in f6["skipped"]


def test_image_named_after_species_in_paper():
    out, figures, _ = figs(SAMSON_2007)
    f20 = next(f for f in figures if f["figure"] == 20)
    assert f20["file"] == "figures/fig20_p30_Neosartorya coreana.jpg"
    assert (out / f20["file"]).exists()
