"""Compare the fields extracted in step 3 with the current MycoBase (data/species_description.json).

For every species treatment in <out>/*/sections.json whose name (as printed, or its accepted name)
is a MycoBase record, each description field is compared:

  same          the texts agree (similarity >= 0.95 after normalising spaces, dashes, case)
  close         similarity >= 0.80 - usually line breaks, symbols, a few words
  partial       one text is (mostly) contained in the other - one side is longer or split differently
  different     similarity < 0.80 - often MycoBase took the text from another publication
  new           extracted, but empty or missing in MycoBase -> step 3 fills a gap
  missed        in MycoBase, not extracted from this paper (the paper may simply not have it)

Backbone columns (MYCOBANK, TYPUS, EX_TYPUS, GenBank IDs, classification ...) are not compared here.

Usage:
  python src/09_compare_fields.py --out output_vol84
  python src/09_compare_fields.py --out output_sim59 --out output_vol84

Writes <first out>/fields_vs_mycobase.tsv (one row per species and field) and prints a summary.
"""
import argparse
import collections
import csv
import difflib
import glob
import json
import os
import re
import sys
import unicodedata
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from extraction.text import canonical_label, norm_ws  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
BACKBONE = {"is accepted", "Literature", "YEAR", "MYCOBANK", "TYPUS", "EX_TYPUS", "kingdom", "phylum", "class",
            "order", "family", "genus", "subgenus", "section", "series", "ITS GenBank ID", "BenA GenBank ID",
            "CaM GenBank ID", "RPB2 GenBank ID", "WGS_type", "Comment", "Species", "Species description", "Fig"}
EXTRA_ALIASES = {"synonym": "Synonyms", "type": "Typus", "type specimen": "Typus", "conidiophores": "Micromorphology",
                 "cyA 25 °c, 7 d".lower(): "Colony characters"}


def mycobase_field(column):
    """MycoBase column name -> the canonical field name used by step 3 (None = not compared)."""
    if column in BACKBONE:
        return None
    return canonical_label(column) or EXTRA_ALIASES.get(column.lower()) or column


def norm(t):
    """Compare text, not typesetting: ligatures (ﬂ), dash types, case and ALL spaces are ignored,
    because MycoBase often lost spaces when it was copied from PDFs ("deep,sulcate", "isolatedby")."""
    t = unicodedata.normalize("NFKC", str(t or ""))
    t = re.sub(r"[‐-―−]", "-", t)
    return re.sub(r"\s+", "", t).lower()


ACCESSION = re.compile(r"\b[A-Z]{1,2}_?\d{5,8}\b")


STRAIN = re.compile(r"\b[A-Z]{2,6}\s?(?:[A-Z]-?\s?)?\d[\d.\-/]*[A-Za-z]?\d*")   # CBS 589.65, IMI 86806, CBS H-22506


def accessions(t):
    return set(ACCESSION.findall(str(t or "")))


def similarity(a, b):
    a, b = norm(a), norm(b)
    if not a or not b:
        return 0.0, False
    sm = difflib.SequenceMatcher(None, a[:3000], b[:3000], autojunk=False)
    ratio = sm.ratio()
    short, long_ = (a, b) if len(a) <= len(b) else (b, a)
    covered = sum(m.size for m in difflib.SequenceMatcher(None, short[:3000], long_[:6000],
                                                          autojunk=False).get_matching_blocks())
    contained = len(short) >= 15 and covered / len(short) >= 0.9
    return ratio, contained


def verdict(ratio, contained):
    if ratio >= 0.95:
        return "same"
    if ratio >= 0.80:
        return "close"
    if contained:
        return "partial"
    return "different"


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--out", action="append", help="result folder of 06_run_steps_1_2.py (repeatable)")
    ap.add_argument("--species", default=str(ROOT / "data" / "species_description.json"))
    a = ap.parse_args()
    outs = a.out or [str(ROOT / "output")]

    with open(a.species, encoding="utf-8") as f:
        db = json.load(f)
    by_lower = {k.lower(): k for k in db}

    rows, seen = [], set()
    for out in outs:
        for fpath in sorted(glob.glob(os.path.join(out, "*", "sections.json"))):
            paper = os.path.basename(os.path.dirname(fpath))
            with open(fpath, encoding="utf-8") as fh:
                sections = json.load(fh)
            for s in sections:
                if s["kind"] != "treatment" or (paper, s["species"]) in seen:
                    continue
                seen.add((paper, s["species"]))
                key = by_lower.get(s["species"].lower()) or by_lower.get((s["name"]["accepted_name"] or "").lower())
                if not key:
                    continue
                rec = db[key]
                mb = collections.defaultdict(list)
                for col, val in rec.items():
                    fld = mycobase_field(col)
                    if fld and str(val).strip():
                        mb[fld].append(str(val))
                ext = {k: v for k, v in s["fields"].items() if not k.startswith("Other: ") and v.strip()}
                for fld in sorted(set(mb) | set(ext)):
                    e, m = ext.get(fld, ""), " ".join(mb.get(fld, []))
                    note = ""
                    if fld in ("Ex-type", "Herb") and not e and m and ext.get("Typus"):
                        e, note = ext["Typus"], "compared with extracted Typus (split in step 4)"
                    if fld == "Molecular markers" and e and m and accessions(m):
                        a_e, a_m = accessions(e), accessions(m)       # MycoBase keeps a dict of IDs
                        ratio = len(a_e & a_m) / len(a_e | a_m)
                        v = "same" if a_m <= a_e else ("partial" if a_e & a_m else "different")
                        note = f"GenBank IDs: {len(a_e & a_m)} shared, {len(a_m - a_e)} only in MycoBase"
                    elif note.startswith("compared with extracted Typus"):
                        nums = [norm(x).rstrip(".-/") for x in STRAIN.findall(m) if not ACCESSION.fullmatch(x.strip(". "))]   # not GenBank IDs
                        found = [x for x in nums if x in norm(e)]
                        ratio = len(found) / len(nums) if nums else 0.0
                        v = "partial" if nums and ratio >= 0.8 else "different"
                        note += f"; {len(found)}/{len(nums)} culture/herbarium numbers found"
                    elif e and m:
                        ratio, contained = similarity(e, m)
                        v = verdict(ratio, contained)
                    else:
                        ratio, v = 0.0, ("new" if e else "missed")
                    rows.append({"paper": paper, "species_in_paper": s["species"], "mycobase_record": key,
                                 "field": fld, "result": v, "similarity": f"{ratio:.2f}", "note": note,
                                 "extracted": norm_ws(e)[:400], "mycobase": norm_ws(m)[:400]})

    if not rows:
        sys.exit("no extracted species found in MycoBase - run 06_run_steps_1_2.py first (step 3 needs it)")
    out_file = os.path.join(outs[0], "fields_vs_mycobase.tsv")
    with open(out_file, "w", encoding="utf-8-sig", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0]), delimiter="\t")
        w.writeheader()
        w.writerows(rows)

    species = {(r["paper"], r["species_in_paper"]) for r in rows}
    with_desc = {(r["paper"], r["species_in_paper"]) for r in rows if r["result"] not in ("new",)}
    order = ["same", "close", "partial", "different", "new", "missed"]
    tot = collections.Counter(r["result"] for r in rows)
    print(f"{len(species)} extracted species are MycoBase records; "
          f"{len(with_desc)} of them already have description fields in MycoBase\n")
    print(f"{'field':32s}" + "".join(f"{o:>10s}" for o in order))
    per = collections.defaultdict(collections.Counter)
    for r in rows:
        per[r["field"]][r["result"]] += 1
    for fld, c in sorted(per.items(), key=lambda x: -sum(x[1].values())):
        print(f"{fld[:32]:32s}" + "".join(f"{c.get(o, 0):10d}" for o in order))
    print(f"{'TOTAL':32s}" + "".join(f"{tot.get(o, 0):10d}" for o in order))
    compared = sum(tot[o] for o in ("same", "close", "partial", "different"))
    if compared:
        agree = tot["same"] + tot["close"] + tot["partial"]
        print(f"\nfields in both: {compared}; agree (same/close/partial): {agree} ({100 * agree / compared:.0f} %)")
    print(f"fields step 3 adds where MycoBase is empty: {tot['new']}")
    print(f"-> {out_file}")


if __name__ == "__main__":
    main()
