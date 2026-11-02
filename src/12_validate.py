"""Step 5 - Validation: a confidence level for every proposed MycoBase addition.

MycoBase is the trusted reference. 11_fill_gaps.py proposes what it is missing; this script decides
how much a curator needs to look at each proposal.

Two kinds of evidence, per species record:

  identity   is this paper section really about this MycoBase species?
               + the paper's MycoBank number is the record's MYCOBANK
               + the paper's ex-type cultures share a number with the record's EX_TYPUS
               + a GenBank ID from the paper is one of the record's GenBank IDs
               - any of these present on both sides but different -> identity conflict
  quality    was the section extracted cleanly?
               unreadable characters ("�"), a field over 6000 characters or containing another
               species heading ("sp. nov.", "MycoBank MB...") -> the section may run into the next one,
               a section over 6 pages, labels not in the dictionary, fewer than 3 fields

and per addition:
               value format (GenBank ID, MycoBank number, year, culture numbers), an image caption that
               names another species, two papers proposing different text ("conflict")

Confidence:
  high     identity confirmed and no problem found  -> can be added after a spot check
  medium   no conflict, but identity not confirmed or a minor note (e.g. via a synonym)
  low      identity conflict or an extraction problem -> a curator checks it against the PDF page

Usage (after 06_run_steps.py and 11_fill_gaps.py):
  python src/12_validate.py --out output_sim59 --out output_vol84 --additions output_additions

Writes to the additions folder:
  validation_species.csv      one row per MycoBase record: confidence, identity evidence, problems
  additions_validated.csv     mycobase_additions.csv + confidence + reasons
  images_validated.csv        mycobase_images.csv + confidence + reasons
  review_queue.csv            only the medium and low rows, worst first - the curator's to-do list
MycoBase (data/species_description.json) is only read.
"""
import argparse
import collections
import csv
import glob
import json
import os
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from extraction.text import canonical_label  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
# short fields that should never contain another field (long descriptions legitimately do, e.g.
# "Description: Colony diam (7 d): CYA25 ...; Colony colour: white" in older papers)
SHORT_FIELDS = {"Typus", "Other no. of the type", "Ex-type", "Etymology", "Distribution", "Ecology and habitats",
                "Extrolites", "Pathogenicity", "Diagnosis", "Similar species", "Molecular markers", "In",
                "Classification", "Synonyms", "Synonym", "Additional materials examined", "Herb"}
INNER_LABEL = re.compile(r"(?:^|[.;]\s+|\s)((?:[A-Z][a-z]+)(?:\s[a-z]+){0,3}(?:,\s[^:;.]{1,25})?)\s*:|"
                         r"\s(Description|Morphological characteristics)\s")
GENBANK = re.compile(r"^[A-Z]{1,2}_?\d{5,8}$")
STRAIN_TOKEN = re.compile(r"^[A-Z][A-Za-z]{1,7} (?:[A-Z]{1,2}-?\s?)?[A-Za-z]{0,2}\s?\d[\w.\-/]*$")
LONG_FIELD = 6000
MAX_PAGES = 6
RANK = {"low": 0, "medium": 1, "high": 2}


def squash(t):
    t = re.sub(r"[\s.,;:()\[\]'\"]", "", str(t or "")).lower()
    return re.sub(r"(?<=[a-z-])0+(?=\d)", "", t)


def strain_set(t):
    return {squash(x) for x in re.split(r"\s*[=;]\s*", str(t or "")) if squash(x)}


def genbank_set(rec):
    return {str(rec.get(c, "")).split(".")[0].strip() for c in
            ("ITS GenBank ID", "BenA GenBank ID", "CaM GenBank ID", "RPB2 GenBank ID") if str(rec.get(c, "")).strip()}


def identity(section, rec, exact):
    """Evidence that the paper section describes this MycoBase record: (confirmed, conflicts, notes)."""
    v = section.get("values", {})
    confirmed, conflicts = [], []
    mb_paper, mb_rec = v.get("MYCOBANK", ""), str(rec.get("MYCOBANK", "")).strip()
    if exact and mb_paper and mb_rec:
        (confirmed if mb_paper == mb_rec else conflicts).append(
            f"MycoBank number {'matches' if mb_paper == mb_rec else 'differs'} (paper {mb_paper}, MycoBase {mb_rec})")
    ex_p, ex_r = strain_set(v.get("EX_TYPUS", "")), strain_set(rec.get("EX_TYPUS", ""))
    if ex_p and ex_r:
        shared = ex_p & ex_r
        (confirmed if shared else conflicts).append(
            f"ex-type cultures {'share ' + str(len(shared)) + ' number(s)' if shared else 'share no number'}")
    gb_p = {v.get(c, "") for c in ("ITS GenBank ID", "BenA GenBank ID", "CaM GenBank ID", "RPB2 GenBank ID")} - {""}
    gb_r = genbank_set(rec)
    if gb_p and gb_r:
        shared = gb_p & gb_r
        (confirmed if shared else conflicts).append(
            f"GenBank IDs {'share ' + str(len(shared)) if shared else 'share none'}")
    return confirmed, conflicts


def quality(section, label_counts_unmapped):
    """Extraction problems of one section."""
    problems, notes = [], []
    fields = section.get("fields", {})
    text = " ".join(fields.values())
    if "�" in text or "�" in section.get("nomenclature", ""):
        problems.append("unreadable characters (font without unicode map) - check the text against the PDF")
    for k, t in fields.items():
        if len(t) > LONG_FIELD:
            problems.append(f"field '{k}' is {len(t)} characters - may run into the next section")
        if k not in ("Synonyms", "Similar species", "Notes", "Distinguishing characters", "Diagnosis") and \
                re.search(r"\b(?:sp|comb)\.\s*nov\.|MycoBank\s+MB\s?\d", t):
            problems.append(f"field '{k}' contains a species heading - may include the next species")
    p0, p1 = section["pages"]
    # pages of full-page plates in between are normal (T. cerinus: heading on p7, text on p18), so a long
    # span only counts when the section also has a lot of text
    if p1 - p0 + 1 > MAX_PAGES and len(text) > 8000:
        problems.append(f"section spans {p1 - p0 + 1} pages with {len(text)} characters - may include other text")
    if section.get("unmapped_labels"):
        notes.append("labels not in the dictionary: " + ", ".join(section["unmapped_labels"]))
    if len([k for k in fields if not k.startswith("Other: ")]) < 3:
        notes.append("fewer than 3 fields")
    return problems, notes


def value_problem(column, value, species_in_paper):
    """Format check of one proposed value; returns a problem text or ''."""
    v = str(value or "").strip()
    if column.endswith("GenBank ID") and not GENBANK.match(v):
        return f"'{v}' is not a GenBank accession"
    if column == "MYCOBANK" and not re.fullmatch(r"\d{4,7}", v):
        return f"'{v}' is not a MycoBank number"
    if column == "YEAR" and not (re.fullmatch(r"\d{4}", v) and 1750 <= int(v) <= 2030):
        return f"'{v}' is not a plausible year"
    if column == "EX_TYPUS":
        bad = [t for t in re.split(r"\s*=\s*", v) if t and not STRAIN_TOKEN.match(t)]
        if bad:
            return "unusual culture number(s): " + ", ".join(bad[:3])
    if column in SHORT_FIELDS:
        for m in INNER_LABEL.finditer(v):
            lab = m.group(1) or m.group(2)
            if m.start() > 0 and canonical_label(lab):
                return f"contains another field ('{lab}') - labels in this paper may be unstyled"
    if column in ("Typus", "Other no. of the type", "Ex-type", "Herb"):
        for m in re.finditer(r"(?<=[a-z0-9)\]])[.,;]?\s+([A-Z][a-z]+(?:\s[a-z]+){0,3})\s*:", v):
            if not re.search(r"type|culture|specimen", m.group(1), re.I):
                return f"contains other text ('{m.group(1)}:') - the next field may have been merged"
    if column == "Fig":
        ep = species_in_paper.split()[-1][:5].lower()
        if ep not in v.lower():
            return "caption does not name this species"
    return ""


def worst(a, b):
    return a if RANK[a] <= RANK[b] else b


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--out", action="append", help="result folder(s) of 06_run_steps.py, as given to 11_fill_gaps.py")
    ap.add_argument("--additions", default=str(ROOT / "output_additions"), help="folder written by 11_fill_gaps.py")
    ap.add_argument("--species", default=str(ROOT / "data" / "species_description.json"))
    a = ap.parse_args()
    outs = a.out or [str(ROOT / "output")]
    add_dir = Path(a.additions)

    with open(a.species, encoding="utf-8") as f:
        db = json.load(f)
    sections = {}
    for out in outs:
        for fpath in glob.glob(os.path.join(out, "*", "sections.json")):
            paper = os.path.basename(os.path.dirname(fpath))
            with open(fpath, encoding="utf-8") as fh:
                for s in json.load(fh):
                    sections[(paper, s["species"])] = s

    def read(name):
        p = add_dir / name
        if not p.exists():
            sys.exit(f"{p} not found - run 11_fill_gaps.py first")
        with open(p, encoding="utf-8-sig") as fh:
            return list(csv.DictReader(fh))
    additions, images = read("mycobase_additions.csv"), read("mycobase_images.csv")

    # ---- per record (paper section -> MycoBase record)
    per_record = {}
    for r in additions + images:
        key = (r["mycobase_record"], r["paper"], r["species_in_paper"])
        if key in per_record:
            continue
        s = sections.get((r["paper"], r["species_in_paper"]))
        rec = db.get(r["mycobase_record"], {})
        if s is None:
            per_record[key] = {"confidence": "low", "confirmed": [], "conflicts": [], "problems":
                               ["section not found in the given --out folders"], "notes": []}
            continue
        exact = s["species"].lower() == r["mycobase_record"].lower()
        confirmed, conflicts = identity(s, rec, exact)
        problems, notes = quality(s, None)
        if not exact:
            notes.append(f"via synonym {s['species']}")
        if conflicts or problems:
            conf = "low"
        elif confirmed and not notes:
            conf = "high"
        elif confirmed:
            conf = "high" if all(n.startswith("via synonym") for n in notes) else "medium"
        else:
            conf = "medium"
            notes.append("identity not confirmed (no MycoBank number, culture or GenBank ID to compare)")
        per_record[key] = {"confidence": conf, "confirmed": confirmed, "conflicts": conflicts,
                           "problems": problems, "notes": notes}

    def judge(r, column, value):
        rv = per_record[(r["mycobase_record"], r["paper"], r["species_in_paper"])]
        conf, reasons = rv["confidence"], rv["conflicts"] + rv["problems"] + rv["notes"]
        p = value_problem(column, value, r["species_in_paper"])
        if p:
            conf, reasons = "low", [p] + reasons
        if r.get("status") == "conflict":
            conf, reasons = "low", ["papers disagree on this value"] + reasons
        return conf, reasons

    out_rows = []
    for r in additions:
        conf, reasons = judge(r, r["column"], r["value"])
        out_rows.append({**r, "confidence": conf, "reasons": "; ".join(reasons)})
    img_rows = []
    for r in images:
        conf, reasons = judge(r, "Fig", r["caption"])
        img_rows.append({**r, "confidence": conf, "reasons": "; ".join(reasons)})

    def write(name, rows, fields=None):
        with open(add_dir / name, "w", encoding="utf-8-sig", newline="") as fh:
            w = csv.DictWriter(fh, fieldnames=fields or list(rows[0]))
            w.writeheader()
            w.writerows([r for r in rows if r])

    sp_rows = [{"mycobase_record": k[0], "paper": k[1], "species_in_paper": k[2], "confidence": v["confidence"],
                "identity_confirmed": "; ".join(v["confirmed"]), "identity_conflicts": "; ".join(v["conflicts"]),
                "problems": "; ".join(v["problems"]), "notes": "; ".join(v["notes"])}
               for k, v in sorted(per_record.items(), key=lambda x: (RANK[x[1]["confidence"]], x[0]))]
    write("validation_species.csv", sp_rows or [{}], ["mycobase_record", "paper", "species_in_paper", "confidence",
                                                    "identity_confirmed", "identity_conflicts", "problems", "notes"])
    if out_rows:
        write("additions_validated.csv", out_rows)
    if img_rows:
        write("images_validated.csv", img_rows)
    queue = [{"kind": "value", "mycobase_record": r["mycobase_record"], "column": r["column"],
              "value": r["value"][:300], "paper": r["paper"], "pages": r["pages"], "confidence": r["confidence"],
              "reasons": r["reasons"]} for r in out_rows if r["confidence"] != "high"]
    queue += [{"kind": "image", "mycobase_record": r["mycobase_record"], "column": "(image)", "value": r["image"],
               "paper": r["paper"], "pages": r["page"], "confidence": r["confidence"], "reasons": r["reasons"]}
              for r in img_rows if r["confidence"] != "high"]
    queue.sort(key=lambda r: (RANK[r["confidence"]], r["mycobase_record"], r["column"]))
    write("review_queue.csv", queue or [{}], ["kind", "mycobase_record", "column", "value", "paper", "pages",
                                         "confidence", "reasons"])

    c_sp = collections.Counter(v["confidence"] for v in per_record.values())
    c_add = collections.Counter(r["confidence"] for r in out_rows)
    c_img = collections.Counter(r["confidence"] for r in img_rows)
    print(f"{'':22s}{'high':>8s}{'medium':>8s}{'low':>8s}")
    for name, c in (("species (paper x record)", c_sp), ("text/value additions", c_add), ("images", c_img)):
        print(f"{name:22s}{c['high']:8d}{c['medium']:8d}{c['low']:8d}")
    print("\nmost common reasons (medium/low):")
    reasons = collections.Counter()
    for v in per_record.values():
        if v["confidence"] != "high":
            for t in v["conflicts"] + v["problems"] + v["notes"]:
                reasons[re.sub(r"\(.*?\)|'.*?'|\d+", "…", t)] += 1
    for t, n in reasons.most_common(8):
        print(f"  {n:4d}  {t}")
    print(f"\ncurator's to-do list: {len(queue)} rows -> {add_dir / 'review_queue.csv'}")


if __name__ == "__main__":
    main()
