"""Check the species names found by steps 1-2 against MycoBank.

For every species section in <out>/*/sections.json this compares what the paper says with the
MycoBank export (data/cache/mycobank_index.tsv.gz, built with 06_run_steps_1_2.py --build-mycobank-index):

  name        is the name in MycoBank?  If not: close names in the same genus (spelling / misread)
  number      does the MycoBank number printed in the paper belong to this name?
  authors     are MycoBank's authors for the name found in the paper's heading?
  year        does a year in the heading match MycoBank's year?
  current     MycoBank's current name, and whether that is on the accepted list (Visagie et al. 2025)

Every section gets a verdict:  OK  or  CHECK (with the reasons), so a curator only looks at the CHECK rows.
Small differences that need no curator (year one apart: online vs print date) go to the "notes" column.

Usage (from the repository folder):
  python src/07_check_mycobank.py                 # checks output/
  
Writes <out>/mycobank_check.tsv (opens in Excel) and prints a summary per paper.
"""
import argparse
import collections
import difflib
import glob
import json
import os
import re
import sys
import unicodedata
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from extraction.names import NameIndex  # noqa: E402
from extraction.text import norm_ws  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "data"


def squash(s):
    """'A.J. Chen, Frisvad & Samson' -> 'ajchenfrisvadsamson' (no accents, spaces, dots, commas)"""
    s = unicodedata.normalize("NFKD", s or "")
    s = "".join(c for c in s if not unicodedata.combining(c))
    return re.sub(r"[^a-z]", "", s.lower())


def surnames(authors):
    """'(Thom & Raper) A.J. Chen, Frisvad & Samson' -> ['thom', 'raper', 'chen', 'frisvad', 'samson']
    One surname per author = the last word ('D. Han Kim' -> 'kim', 'Koji Yokoyama' -> 'yokoyama');
    initials, 'ex' and 'et al.' are dropped; accents removed."""
    out = []
    for author in re.split(r"[(),&]|\bex\b|\bet al\.?", authors or ""):
        words = [w for w in author.split() if not (w.endswith(".") and "-" not in w)]
        if words:
            w = squash(words[-1])
            if len(w) > 1 and w not in ("in", "emend"):
                out.append(w)
    return out


def authors_in_heading(mb_authors, heading):
    """Compare MycoBank's author surnames with the paper heading: match / partial / differ.
    Small spelling differences count as found (Sergeeva ~ Sergejeva); "et al." in the heading
    means only the first author is printed."""
    names = surnames(mb_authors)
    if not names:
        return "no authors in MycoBank"
    words = [squash(w) for w in re.split(r"[\s(),&.]+", heading) if squash(w)]
    whole = squash(heading)

    def found(n):
        return n in whole or bool(difflib.get_close_matches(n, words, n=1, cutoff=0.8))

    # the authors in brackets (basionym authors) are often left out or written differently
    outside = surnames(re.sub(r"\(.*?\)", " ", mb_authors)) or names
    if "et al" in heading.lower() and found(outside[0]):
        return "match (et al.)"
    hit = [n for n in outside if found(n)]
    if len(hit) == len(outside):
        return "match"
    if hit:
        return f"partial ({len(hit)}/{len(outside)}: missing {', '.join(n for n in outside if n not in hit)})"
    return "differ"


class Checker:
    def __init__(self, names):
        self.n = names
        self.epithets_by_genus = collections.defaultdict(list)
        for key, rows in names.by_name.items():
            if rows[0]["rank"] in ("sp.", "species") or len(key.split()) == 2:
                g, _, e = key.partition(" ")
                if e and " " not in e:
                    self.epithets_by_genus[g].append(e)

    def close_names(self, name, k=3):
        g, _, e = name.lower().partition(" ")
        cands = difflib.get_close_matches(e, self.epithets_by_genus.get(g, []), n=k, cutoff=0.8)
        return [self.n.by_name[f"{g} {c}"][0]["name"] for c in cands]

    def check(self, s):
        name = s["species"]
        head = s["nomenclature"]
        mb_paper = s["mycobank_in_paper"]
        rows = self.n.by_name.get(norm_ws(name).lower(), [])
        res = s["name"]
        out = {"name_in_mycobank": "yes" if rows else "no", "close_names": "", "mycobank_numbers": "",
               "number_check": "", "number_belongs_to": "", "authors_mycobank": "", "authors_check": "",
               "year_mycobank": "", "year_check": "", "mycobank_status": res["mycobank_status"],
               "current_name": res["mycobank_current_name"], "accepted_status": res["status"],
               "accepted_name": res["accepted_name"]}
        reasons, notes = [], []        # reasons -> CHECK; notes are shown but do not need a curator

        if not rows:
            out["close_names"] = "; ".join(self.close_names(name))
            reasons.append("name not in MycoBank" + (f" (close: {out['close_names']})" if out["close_names"] else ""))

        # the MycoBank record this section is about: the one with the paper's number, else the best one
        row = next((r for r in rows if r["mb"] == mb_paper), None) if mb_paper else None
        if row is None and rows:
            row = next((r for r in rows if r["mb"] == res["mycobank_number"]), rows[0])
        out["mycobank_numbers"] = "; ".join(r["mb"] for r in rows)

        if not mb_paper:
            out["number_check"] = "no number in paper"
        elif any(r["mb"] == mb_paper for r in rows):
            out["number_check"] = "match"
        else:
            other = self.n.by_num.get(mb_paper)
            if other is None:
                out["number_check"] = "number not in MycoBank"
                reasons.append(f"MB{mb_paper} not in MycoBank")
            else:
                out["number_belongs_to"] = other["name"]
                cur = self.n._current(other)
                if norm_ws(cur).lower() == norm_ws(name).lower():
                    out["number_check"] = "number of a synonym/basionym"
                else:
                    out["number_check"] = "number of another name"
                    reasons.append(f"MB{mb_paper} is {other['name']} in MycoBank")

        if row:
            out["authors_mycobank"] = row["authors"]
            out["authors_check"] = authors_in_heading(row["authors"], head)
            if out["authors_check"].startswith(("differ", "partial")):
                reasons.append(f"authors differ (MycoBank: {row['authors']})")
            y = re.sub(r"\D", "", row["year"] or "")[:4]
            out["year_mycobank"] = y
            years = re.findall(r"\b(1[7-9]\d\d|20\d\d)\b", head)
            if not years:
                out["year_check"] = "no year in heading"
            elif y in years:
                out["year_check"] = "match"
            elif y and any(abs(int(y) - int(x)) == 1 for x in years):
                out["year_check"] = f"1 year apart (heading: {', '.join(years)})"
                notes.append(f"year {y} in MycoBank, {', '.join(years)} in paper (online vs print date?)")
            else:
                out["year_check"] = f"differ (heading: {', '.join(years)})"
                reasons.append(f"year differs (MycoBank {y}, paper {', '.join(years)})")
            st = (row["status"] or "").lower()
            if st and not st.startswith("legitimate"):
                reasons.append(f"MycoBank status: {row['status']}")

        if res["status"] == "synonym":
            reasons.append(f"synonym of {res['accepted_name']}")
        out["verdict"] = "CHECK" if reasons else "OK"
        out["reasons"] = "; ".join(reasons)
        out["notes"] = "; ".join(notes)
        return out


COLUMNS = ["paper", "species_in_paper", "kind", "pages", "mycobank_in_paper", "verdict", "reasons", "notes",
           "name_in_mycobank", "close_names", "mycobank_numbers", "number_check", "number_belongs_to",
           "authors_mycobank", "authors_check", "year_mycobank", "year_check", "mycobank_status",
           "current_name", "accepted_status", "accepted_name", "nomenclature"]


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--out", default=str(ROOT / "output"), help="folder written by 06_run_steps_1_2.py")
    ap.add_argument("--species", default=str(DATA / "species_description.json"))
    ap.add_argument("--mycobank-cache", default=str(DATA / "cache" / "mycobank_index.tsv.gz"))
    ap.add_argument("--treatments-only", action="store_true", help="skip name-list entries")
    a = ap.parse_args()

    names = NameIndex(a.species, a.mycobank_cache)
    if not names.has_mycobank:
        sys.exit("MycoBank index not found: run  python src/06_run_steps_1_2.py --build-mycobank-index")
    checker = Checker(names)

    files = sorted(glob.glob(os.path.join(a.out, "*", "sections.json")))
    if not files:
        sys.exit(f"no sections.json under {a.out}: run 06_run_steps_1_2.py first")
    rows = []
    for f in files:
        paper = os.path.basename(os.path.dirname(f))
        with open(f, encoding="utf-8") as fh:
            sections = json.load(fh)
        counts = collections.Counter()
        for s in sections:
            if a.treatments_only and s["kind"] != "treatment":
                continue
            c = checker.check(s)
            counts[c["verdict"]] += 1
            counts["in MycoBank" if c["name_in_mycobank"] == "yes" else "not in MycoBank"] += 1
            counts["number " + c["number_check"]] += 1
            rows.append({"paper": paper, "species_in_paper": s["species"], "kind": s["kind"],
                         "pages": f"{s['pages'][0]}-{s['pages'][1]}", "mycobank_in_paper": s["mycobank_in_paper"],
                         "nomenclature": s["nomenclature"][:300], **c})
        print(f"\n{paper[:70]}")
        print(f"  {counts['OK']} OK, {counts['CHECK']} CHECK   |  name in MycoBank: {counts['in MycoBank']}, "
              f"not: {counts['not in MycoBank']}")
        print("  MycoBank number: " + ", ".join(f"{k[7:]} {v}" for k, v in counts.items() if k.startswith("number ")))
        for r in rows:
            if r["paper"] == paper and r["verdict"] == "CHECK":
                print(f"    CHECK  {r['species_in_paper']:32s} {r['reasons']}")

    out_file = os.path.join(a.out, "mycobank_check.tsv")
    with open(out_file, "w", encoding="utf-8-sig") as f:
        f.write("\t".join(COLUMNS) + "\n")
        for r in rows:
            f.write("\t".join(str(r.get(c, "")).replace("\t", " ").replace("\n", " ") for c in COLUMNS) + "\n")
    v = collections.Counter(r["verdict"] for r in rows)
    print(f"\n{len(rows)} sections checked: {v['OK']} OK, {v['CHECK']} CHECK -> {out_file}")


if __name__ == "__main__":
    main()
