"""Compare the values parsed in step 4 with the MycoBase backbone columns (data/species_description.json).

Columns: MYCOBANK, YEAR, Literature, TYPUS, EX_TYPUS, ITS / BenA / CaM / RPB2 GenBank ID, section.

  same        identical after normalising spaces and punctuation
  agree       the same thing written differently: EX_TYPUS lists the same cultures plus extra ones
              (e.g. a DTO number), TYPUS the same specimen with or without "(holotype)",
              Literature 90 % alike
  different   the values disagree -> a curator should look (paper error, MycoBase error or parsing)
  new         parsed from the paper, empty in MycoBase
  missed      in MycoBase, not found in this paper

A species printed under an old name (Neosartorya fischeri -> MycoBase record Aspergillus fischeri) is
compared only on EX_TYPUS and GenBank IDs: its MycoBank number, citation and year belong to the old name.

Usage:
  python src/10_compare_values.py --out output_vol84
Writes <first out>/values_vs_mycobase.tsv and prints a table per column.
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

ROOT = Path(__file__).resolve().parent.parent
COLUMNS = ["MYCOBANK", "YEAR", "Literature", "TYPUS", "EX_TYPUS", "ITS GenBank ID", "BenA GenBank ID",
           "CaM GenBank ID", "RPB2 GenBank ID", "section"]
SAME_ORGANISM = {"EX_TYPUS", "ITS GenBank ID", "BenA GenBank ID", "CaM GenBank ID", "RPB2 GenBank ID"}


def squash(t):
    t = unicodedata.normalize("NFKC", str(t or ""))
    t = re.sub(r"[‐-―−]", "-", t)
    t = re.sub(r"[\s.,;:()\[\]'\"]", "", t).lower()
    return re.sub(r"(?<=[a-z-])0+(?=\d)", "", t)          # "IMI 074897" = "IMI 74897", "FA-0866" = "FA-866"


def strain_set(t):
    """'CBS 140611 = CGMCC 3.18197 = DTO 317-C7' -> {'cbs140611', 'cgmcc318197', 'dto317-c7'}"""
    return {squash(x) for x in re.split(r"\s*[=;]\s*", str(t or "")) if squash(x)}


def compare(col, ext, mb):
    """Return (result, note)."""
    ext, mb = str(ext or "").strip(), str(mb or "").strip()
    if not ext and not mb:
        return None, ""
    if not mb:
        return "new", ""
    if not ext:
        return "missed", ""
    if squash(ext) == squash(mb):
        return "same", ""
    if col.endswith("GenBank ID"):
        return ("same", "") if ext.split(".")[0] == mb.split(".")[0] else ("different", "")
    if col == "EX_TYPUS":
        e, m = strain_set(ext), strain_set(mb)
        if m <= e:
            return "agree", f"paper lists {len(e - m)} more culture number(s)"
        if e <= m:
            return "agree", f"MycoBase lists {len(m - e)} more culture number(s)"
        shared = len(e & m)
        return ("agree" if shared and shared >= 0.6 * min(len(e), len(m)) else "different",
                f"{shared} shared, {len(e - m)} only in paper, {len(m - e)} only in MycoBase")
    if col == "TYPUS":
        se, sm = squash(re.sub(r"\(.*?\)", "", ext)), squash(re.sub(r"\(.*?\)", "", mb))
        if se == sm:
            return "agree", "same specimen, type kind written differently"
        return "different", ""
    if col == "Literature":
        r = difflib.SequenceMatcher(None, squash(ext), squash(mb)).ratio()
        place_e = re.findall(r"\d+\s*:\s*\d+", ext)
        place_m = re.findall(r"\d+\s*:\s*\d+", mb)
        if r >= 0.9 or (place_e and place_e[-1].replace(" ", "") == (place_m[-1].replace(" ", "") if place_m else "")):
            return "agree", f"similarity {r:.2f}"
        return "different", f"similarity {r:.2f}"
    if col == "section":
        return ("same", "") if ext.lower() == mb.lower() else ("different", "")
    return "different", ""


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--out", action="append", help="result folder of 06_run_steps.py (repeatable)")
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
                if s["kind"] != "treatment" or "values" not in s or (paper, s["species"]) in seen:
                    continue
                seen.add((paper, s["species"]))
                exact = by_lower.get(s["species"].lower())
                key = exact or by_lower.get((s["name"]["accepted_name"] or "").lower())
                if not key or db[key].get("is accepted") != "Yes":
                    continue                              # only accepted records have backbone values
                for col in COLUMNS:
                    if not exact and col not in SAME_ORGANISM:
                        continue
                    res, note = compare(col, s["values"].get(col, ""), db[key].get(col, ""))
                    if res:
                        rows.append({"paper": paper, "species_in_paper": s["species"], "mycobase_record": key,
                                     "column": col, "result": res, "note": note if exact else
                                     (note + "; " if note else "") + "compared via synonym",
                                     "parsed": s["values"].get(col, ""), "mycobase": db[key].get(col, "")})
    if not rows:
        sys.exit("nothing to compare - run 06_run_steps.py first (it writes 'values' in sections.json)")
    out_file = os.path.join(outs[0], "values_vs_mycobase.tsv")
    with open(out_file, "w", encoding="utf-8-sig", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0]), delimiter="\t")
        w.writeheader()
        w.writerows(rows)

    order = ["same", "agree", "different", "new", "missed"]
    per = collections.defaultdict(collections.Counter)
    for r in rows:
        per[r["column"]][r["result"]] += 1
    print(f"{len({(r['paper'], r['species_in_paper']) for r in rows})} species compared with MycoBase records\n")
    print(f"{'column':18s}" + "".join(f"{o:>11s}" for o in order) + "   correct")
    tot = collections.Counter()
    for col in COLUMNS:
        c = per.get(col, collections.Counter())
        tot.update(c)
        both = c["same"] + c["agree"] + c["different"]
        pct = f"{100 * (c['same'] + c['agree']) / both:5.0f} %" if both else "      -"
        print(f"{col:18s}" + "".join(f"{c.get(o, 0):11d}" for o in order) + f"   {pct}")
    both = tot["same"] + tot["agree"] + tot["different"]
    print(f"{'TOTAL':18s}" + "".join(f"{tot.get(o, 0):11d}" for o in order) +
          (f"   {100 * (tot['same'] + tot['agree']) / both:5.0f} %" if both else ""))
    print(f"\n'different' rows need a look: {tot['different']}  -> {out_file}")


if __name__ == "__main__":
    main()
