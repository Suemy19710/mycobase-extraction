"""Unit tests for step 5 (12_validate.py) - no PDFs needed.
    python -m pytest tests/test_validate.py
"""
import importlib.util
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
_spec = importlib.util.spec_from_file_location("validate", ROOT / "src" / "12_validate.py")
V = importlib.util.module_from_spec(_spec)
_argv, sys.argv = sys.argv, ["12_validate.py"]
_spec.loader.exec_module(V)
sys.argv = _argv

RECORD = {"MYCOBANK": "817398", "EX_TYPUS": "CBS 140611 = CGMCC 3.18197 = DTO 317-C7",
          "ITS GenBank ID": "KU866647", "BenA GenBank ID": "KU866835"}


def section(**values):
    return {"species": "Talaromyces aerius", "nomenclature": "", "pages": [6, 6], "fields": {}, "values": values}


def test_identity_confirmed():
    ok, bad = V.identity(section(MYCOBANK="817398", EX_TYPUS="CBS 140611 = DTO 317-C7",
                                 **{"ITS GenBank ID": "KU866647"}), RECORD, exact=True)
    assert len(ok) == 3 and not bad


def test_identity_conflict():
    ok, bad = V.identity(section(MYCOBANK="809583", EX_TYPUS="CBS 121604"), RECORD, exact=True)
    assert len(bad) == 2 and not ok


def test_mycobank_number_not_compared_for_a_synonym():
    ok, bad = V.identity(section(MYCOBANK="999999"), RECORD, exact=False)
    assert not ok and not bad


def test_unreadable_characters():
    s = section()
    s["fields"] = {"Typus": "Venezuela, Morro of Garap�ata", "Etymology": "x", "Diagnosis": "y"}
    problems, _ = V.quality(s, None)
    assert any("unreadable" in p for p in problems)


def test_plate_pages_are_not_a_problem():
    s = section()
    s["pages"] = [7, 18]                      # T. cerinus: heading p7, plates p8-17, text p18
    s["fields"] = {"Etymology": "a" * 50, "Typus": "b" * 140, "Micromorphology": "c" * 220}
    problems, _ = V.quality(s, None)
    assert not problems


def test_value_formats():
    assert V.value_problem("ITS GenBank ID", "KU866647", "x y") == ""
    assert V.value_problem("ITS GenBank ID", "KU86", "x y")
    assert V.value_problem("YEAR", "2016", "x y") == ""
    assert V.value_problem("YEAR", "3016", "x y")


def test_merged_fields_detected():
    assert V.value_problem("Other no. of the type", "strain 677 Description strain Colony diam, 7 d, in mm: CYA25 27",
                           "Aspergillus calidoustus")
    assert V.value_problem("Typus", "CBS 209.92 Ehrlich reaction: violet", "Aspergillus keveii")
    assert V.value_problem("Typus", "IMI 86806. Culture ex-type: CBS 589.65 = NRRL 187", "Aspergillus nidulans") == ""


def test_caption_must_name_the_species():
    assert V.value_problem("Fig", "Fig. 5 Aspergillus campestris. A-B Colonies", "Aspergillus campestris") == ""
    assert V.value_problem("Fig", "Fig. 4. Aspergillus candidus. A-B Colonies", "Aspergillus campestris")
