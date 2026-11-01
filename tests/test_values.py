"""Unit tests for step 4 (value parsing) on real text from the papers - no PDFs needed.
    python -m pytest -q tests
"""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))
from extraction.values import (clean_strain, parse_barcodes, parse_colony_diam, parse_values,  # noqa: E402
                               strains)

STUD_MYCOL_84 = {"journal": "Stud. Mycol.", "volume": "84", "first_page": 119, "year": "2016", "page_offset": 118}
STUD_MYCOL_59 = {"journal": "Stud. Mycol.", "volume": "59", "first_page": 147, "year": "2007", "page_offset": 146}


def values(species, nomenclature, fields=None, cit=STUD_MYCOL_84, page=6):
    return parse_values({"species": species, "nomenclature": nomenclature, "pages": [page, page],
                         "fields": fields or {}}, cit)


def test_new_species_gets_the_papers_citation():
    v = values("Talaromyces aerius", "Talaromyces aerius A.J. Chen, Frisvad & Samson, sp. nov. MycoBank MB817398. Fig. 6.")
    assert v["MYCOBANK"] == "817398"
    assert v["status"] == "sp. nov."
    assert v["Literature"] == "A.J. Chen, Frisvad & Samson, Stud. Mycol. 84: 124. 2016."   # PDF page 6 = page 124
    assert v["YEAR"] == "2016"


def test_old_name_keeps_its_own_citation():
    v = values("Aspergillus nidulans", "Aspergillus nidulans (Eidam) G. Winter, Rabenh. Krypt.-Fl., ed. 2, 1: 62. 1884. "
               "MycoBank MB182069. Figs 36, 37.")
    assert v["Literature"] == "(Eidam) G. Winter, Rabenh. Krypt.-Fl., ed. 2, 1: 62. 1884."
    assert v["YEAR"] == "1884" and v["MYCOBANK"] == "182069"


def test_anamorph_bracket_skipped():
    v = values("Neosartorya fischeri", "Neosartorya fischeri (Wehmer) Malloch & Cain [anamorph: A. fischerianus "
               "Samson & W. Gams], Canad. J. Bot. 50: 2621. 1972. Fig. 24.", cit=STUD_MYCOL_59)
    assert v["Literature"] == "(Wehmer) Malloch & Cain, Canad. J. Bot. 50: 2621. 1972."


def test_comb_nov_status_removed_from_citation():
    v = values("Aspergillus latus", "Aspergillus latus (Thom & Raper) A.J. Chen, Frisvad & Samson, comb. nov. "
               "MycoBank MB816100. Fig. 31.")
    assert v["status"] == "comb. nov."
    assert v["Literature"] == "(Thom & Raper) A.J. Chen, Frisvad & Samson, Stud. Mycol. 84: 124. 2016."


def test_holotype_and_ex_type():
    v = values("Talaromyces aerius", "x", {"Typus": "China, Beijing, indoor air, May 2014, isolated by B.D. Sun "
               "(holotype CBS H-22506, culture ex-type CBS 140611 = CGMCC3. 18197 = DTO 317-C7)."})
    assert v["TYPUS"] == "CBS H-22506 (holotype)"
    assert v["EX_TYPUS"] == "CBS 140611 = CGMCC 3.18197 = DTO 317-C7"


def test_type_specimen_then_culture_list():
    v = values("Aspergillus nidulans", "x", {"Typus": "IMI 86806. Culture ex-type: CBS 589.65 = NRRL 187 = "
               "ATCC 10074 = IHEM 3563 = IMI 126691 = IMI 86806 = QM 1985 = Thom 4640.5 = WB 187 = DTO 047-H9."})
    assert v["TYPUS"] == "IMI 86806"
    assert v["EX_TYPUS"].startswith("CBS 589.65 = NRRL 187 = ATCC 10074")
    assert "Thom 4640.5" in v["EX_TYPUS"] and v["EX_TYPUS"].endswith("DTO 047-H9")


def test_older_type_and_other_numbers():
    v = values("Neosartorya fischeri", "x", {"Typus": "CBS 544.65, from canned apples, Wehmer",
               "Other no. of the type": "ATCC 1020; DSM 3700; IMI 211391; NRRL 181; QM 1983; Thom 4651.2, WB 181"},
               cit=STUD_MYCOL_59)
    assert v["TYPUS"] == "CBS 544.65"
    assert v["EX_TYPUS"].startswith("CBS 544.65 = ATCC 1020 = DSM 3700 = IMI 211391 = NRRL 181")


def test_holotype_here_designated():
    v = values("Neosartorya warcupii", "x", {"Typus": "Holotype of Neosartorya warcupii, here designated as "
               "NRRL 35723T (dried culture), isolated from soil"}, cit=STUD_MYCOL_59)
    assert v["TYPUS"] == "NRRL 35723 (holotype)"
    assert v["EX_TYPUS"] == ""                       # a dried culture is not an ex-type culture


def test_barcodes():
    bc = parse_barcodes("KU866647. (Alternative markers: BenA = KU866835; CaM = KU866731; RPB2 = KU866991).")
    assert bc == {"ITS": "KU866647", "BenA": "KU866835", "CaM": "KU866731", "RPB2": "KU866991"}


def test_colony_diam():
    d = parse_colony_diam("CYA 17–18; CYA 30 °C 20–22; CYA 37 °C No growth; MEA 32–33; DG18 11–12")
    assert d == {"CYA": "17–18", "CYA 30 °C": "20–22", "CYA 37 °C": "No growth", "MEA": "32–33", "DG18": "11–12"}


def test_section():
    assert values("x y", "x", {"Classification": "Talaromyces section Trachyspermi"})["section"] == "Trachyspermi"


def test_strain_cleaning():
    assert clean_strain("CGMCC3. 18197") == "CGMCC 3.18197"
    assert clean_strain("CBS140611.") == "CBS 140611"
    assert strains("CBS 261.93 = NRRL A-1673 = IMI 61455ii.") == ["CBS 261.93", "NRRL A-1673", "IMI 61455ii"]


def test_citation_without_volume_keeps_its_year():
    # "Gen. Aspergillus: 506. 1965." has no volume number; it must not get this paper's citation
    v = values("Aspergillus fruticulosus", "Aspergillus fruticulosus Raper & Fennell, Gen. Aspergillus: 506. 1965. "
               "MycoBank MB326635. Fig. 25.")
    assert v["Literature"] == "Raper & Fennell, Gen. Aspergillus: 506. 1965."
    assert v["YEAR"] == "1965"


def test_isotype_is_not_the_type():
    v = values("Aspergillus pluriseminatus", "x", {"Typus": "FMR 5588; isotype IMI 370867. Culture ex-type: "
               "CBS 100523 = FMR 5588 = IMI 370867 = DTO 011-H1."})
    assert v["TYPUS"] == "FMR 5588"
    assert v["EX_TYPUS"] == "CBS 100523 = FMR 5588 = IMI 370867 = DTO 011-H1"


def test_media_are_not_cultures():
    assert strains("CBS 121604 = CYA 25 = MEA 25 = YES 36") == ["CBS 121604"]
