"""Fill the gaps in MycoBase from the extracted papers - never replace anything that is already there.

MycoBase (data/species_description.json) is the trusted reference. This script only proposes what it
does NOT contain yet:

  * a species section is matched to its ACCEPTED MycoBase record (name as printed, or its accepted
    name); only sections with target "mycobase" are used (accepted species and their synonyms).
    Records with "is accepted: No" are never filled.
  * a field from step 3 or a value from step 4 is proposed ONLY when MycoBase has no value for it -
    under any of its column names ("Colony diam, 7 d (mm)" counts as Colony diam, "Synonym" as Synonyms)
  * names are MycoBase's own columns, values are written in MycoBase's style (Molecular markers as
    {'ITS': ..., 'BenA': ...}), so no new kind of column appears
  * a species printed under an old name (Neosartorya fischeri -> Aspergillus fischeri) gives only
    descriptions, culture numbers and GenBank IDs - its MycoBank number, citation, year, type and
    nomenclature belong to the old name
  * when two papers propose different text for the same empty field, both are listed and marked
    "conflict" for a curator; nothing is chosen automatically

data/species_description.json is only READ. Results go to the output folder:

  mycobase_additions.csv    one row per proposed addition: record, column, value, paper, pages, label
  mycobase_images/          species images (plates from the papers) for accepted species that have NO
                            image in data/images yet, named "<accepted name> (<paper> fig06 p12).jpg";
                            the plate caption goes into the empty "Fig" column. Species without a plate
                            are skipped; data/images is never written to.
  mycobase_additions.json   {record: {column: value}} for the additions without conflicts
  (with --write-copy)       species_description_filled.json = MycoBase + the additions, as a NEW file

Usage:
  python src/11_fill_gaps.py --out output_sim59 --out output_vol84
"""
import argparse
import collections
import csv
import glob
import hashlib
import json
import os
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from extraction.text import canonical_label, norm_ws  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent

# step-4 values that are MycoBase backbone columns
VALUE_COLUMNS = ["MYCOBANK", "Literature", "YEAR", "TYPUS", "EX_TYPUS", "ITS GenBank ID", "BenA GenBank ID",
                 "CaM GenBank ID", "RPB2 GenBank ID", "section"]
# what a species under an old name may give to the accepted record (same organism, same strain)
SAME_ORGANISM_VALUES = {"EX_TYPUS", "ITS GenBank ID", "BenA GenBank ID", "CaM GenBank ID", "RPB2 GenBank ID"}
NAME_BOUND_FIELDS = {"Synonyms", "Basionym", "Typus", "Classification", "Etymology"}   # about the old name
SKIP_FIELDS = {"Colony diam"}            # MycoBase keeps colony diameters in several formatted columns
NOT_FIELDS = {"is accepted", "Comment", "kingdom", "phylum", "class", "order", "family", "genus", "subgenus",
              "series", "WGS_type", "Species"}
EXTRA_ALIASES = {"synonym": "Synonyms", "type": "Typus", "type specimen": "Typus"}


def field_of(column):
    """MycoBase column -> canonical field (None for backbone/admin columns)."""
    if column in VALUE_COLUMNS:
        return column
    if column in NOT_FIELDS:
        return None
    if column == "Species description":
        return "Species description"
    return canonical_label(column) or EXTRA_ALIASES.get(column.lower()) or column


def empty(v):
    """No data: missing, "" or an empty list/dict ("{}" in Molecular markers)."""
    return v is None or str(v).strip() in ("", "{}", "[]", "None")


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--out", action="append", help="result folder of 06_run_steps.py (repeatable)")
    ap.add_argument("--species", default=str(ROOT / "data" / "species_description.json"))
    ap.add_argument("--save", help="folder for the results (default: first --out)")
    ap.add_argument("--images", default=str(ROOT / "data" / "images"),
                    help="MycoBase image folder (read only): '<species> Mycochat.jpg'")
    ap.add_argument("--write-copy", action="store_true",
                    help="also write species_description_filled.json (MycoBase + additions) as a new file")
    a = ap.parse_args()
    outs = a.out or [str(ROOT / "output")]
    save = Path(a.save or outs[0])

    raw = open(a.species, "rb").read()
    md5_before = hashlib.md5(raw).hexdigest()
    db = json.loads(raw.decode("utf-8"))
    by_lower = {k.lower(): k for k in db}

    # MycoBase's usual column name for each canonical field
    usual = collections.defaultdict(collections.Counter)
    for rec in db.values():
        for col in rec:
            f = field_of(col)
            if f:
                usual[f][col] += 1

    have_image = set()
    if os.path.isdir(a.images):
        for f in os.listdir(a.images):
            have_image.add(re.sub(r"\s+Mycochat$", "", os.path.splitext(f)[0]).strip().lower())
    image_rows = []                                    # species images to add
    proposals = collections.defaultdict(list)          # (record, column) -> [proposal, ...]
    for out in outs:
        for fpath in sorted(glob.glob(os.path.join(out, "*", "sections.json"))):
            paper = os.path.basename(os.path.dirname(fpath))
            with open(fpath, encoding="utf-8") as fh:
                sections = json.load(fh)
            captions, main_of = {}, {}
            fj = os.path.join(os.path.dirname(fpath), "figures.json")
            if os.path.exists(fj):
                with open(fj, encoding="utf-8") as fh:
                    figs_ = [f for f in json.load(fh) if f.get("file")]
                captions = {f["file"]: f.get("caption", "") for f in figs_}
                main_of = {f["file"]: f.get("main_species") or "" for f in figs_}
            for s in sections:
                if s["kind"] != "treatment" or s.get("target") != "mycobase":
                    continue
                # only ACCEPTED MycoBase records are filled (Visagie et al. 2025). A name printed in the
                # paper that has its own, not-accepted MycoBase record (Neosartorya fischeri) fills its
                # accepted record (Aspergillus fischeri) as a synonym.
                exact = by_lower.get(s["species"].lower())
                if exact and db[exact].get("is accepted") != "Yes":
                    exact = None
                key = exact or by_lower.get((s["name"].get("accepted_name") or "").lower())
                if not key or db[key].get("is accepted") != "Yes":
                    continue
                rec = db[key]
                filled = {field_of(c) for c, v in rec.items() if field_of(c) and not empty(v)}

                cand = []                               # (field, value, label/source)
                if exact and s.get("nomenclature"):
                    cand.append(("Species description", s["nomenclature"], "species heading"))
                for fld, txt in s.get("fields", {}).items():
                    if fld.startswith("Other: ") or fld in SKIP_FIELDS or not norm_ws(txt):
                        continue
                    if not exact and fld in NAME_BOUND_FIELDS:
                        continue
                    label = s.get("field_labels", {}).get(fld, fld)
                    if fld == "Molecular markers":
                        v = s.get("values", {})
                        ids = {g: v.get(f"{g} GenBank ID", "") for g in ("ITS", "BenA", "CaM", "RPB2")}
                        if any(ids.values()):
                            txt = str(ids)                  # MycoBase style: {'ITS': ..., 'BenA': ...}
                    cand.append((fld, norm_ws(txt), f"field '{label}'"))
                for col in VALUE_COLUMNS:
                    val = str(s.get("values", {}).get(col, "") or "").strip()
                    if val and (exact or col in SAME_ORGANISM_VALUES):
                        cand.append((col, val, "step 4 value"))

                # species images: only when MycoBase has no image for this species
                if key.lower() not in have_image:
                    for fig in s.get("figures", []):
                        src = os.path.join(os.path.dirname(fpath), fig["file"])
                        if fig["file"] in main_of and main_of[fig["file"]] not in ("", s["species"]):
                            continue                    # the caption says this plate shows another species
                        if os.path.exists(src):
                            image_rows.append({"record": key, "src": src, "paper": paper, "fig": fig,
                                               "caption": captions.get(fig["file"], ""), "species_in_paper": s["species"],
                                               "via": "" if exact else f"synonym {s['species']}"})
                    if image_rows and image_rows[-1]["record"] == key and "Fig" not in filled:
                        cap = image_rows[-1]["caption"] or ""
                        if cap:
                            cand.append(("Fig", cap, "caption of the species image"))

                for fld, val, how in cand:
                    if fld in filled:
                        continue                            # MycoBase already has it: never replace
                    empty_cols = [c for c in rec if field_of(c) == fld and empty(rec[c])]
                    col = empty_cols[0] if empty_cols else (usual[fld].most_common(1)[0][0] if usual[fld] else fld)
                    proposals[(key, col)].append({
                        "mycobase_record": key, "column": col, "value": val,
                        "slot": "empty column" if empty_cols else "column not in this record",
                        "paper": paper, "pages": f"{s['pages'][0]}-{s['pages'][1]}",
                        "species_in_paper": s["species"], "from": how,
                        "via": "" if exact else f"synonym {s['species']}"})

    rows, additions = [], collections.defaultdict(dict)
    for (key, col), props in sorted(proposals.items()):
        distinct = {re.sub(r"\s+", " ", p["value"]).lower() for p in props}
        status = "ok" if len(distinct) == 1 else "conflict"
        for p in props:
            rows.append({**p, "status": status})
        if status == "ok":
            additions[key][col] = props[0]["value"]

    save.mkdir(parents=True, exist_ok=True)
    cols = ["mycobase_record", "column", "value", "status", "slot", "paper", "pages", "species_in_paper",
            "from", "via"]
    with open(save / "mycobase_additions.csv", "w", encoding="utf-8-sig", newline="") as f:
        w = csv.DictWriter(f, fieldnames=cols)
        w.writeheader()
        w.writerows(rows)
    with open(save / "mycobase_additions.json", "w", encoding="utf-8") as f:
        json.dump(additions, f, ensure_ascii=False, indent=1)
    # copy the species images (never into data/images)
    img_dir = save / "mycobase_images"
    img_csv = []
    for r in image_rows:
        img_dir.mkdir(parents=True, exist_ok=True)
        f = r["fig"]
        name = re.sub(r'[<>:"/\\|?*]', "", f"{r['record']} ({r['paper'][:20]} fig{f['figure']:02d} p{f['page']}).jpg"
                      if isinstance(f.get("figure"), int) else f"{r['record']} ({r['paper'][:20]} p{f['page']}).jpg")
        ext = os.path.splitext(r["src"])[1]
        name = name[:-4] + ext
        with open(r["src"], "rb") as fi, open(img_dir / name, "wb") as fo:      # write in place, no deleting
            fo.write(fi.read())
        img_csv.append({"mycobase_record": r["record"], "image": f"mycobase_images/{name}", "paper": r["paper"],
                        "figure": f.get("figure"), "page": f.get("page"), "species_in_paper": r["species_in_paper"],
                        "via": r["via"], "caption": r["caption"]})
    with open(save / "mycobase_images.csv", "w", encoding="utf-8-sig", newline="") as fcsv:
        w = csv.DictWriter(fcsv, fieldnames=["mycobase_record", "image", "paper", "figure", "page",
                                             "species_in_paper", "via", "caption"])
        w.writeheader()
        w.writerows(img_csv)

    if a.write_copy:
        filled_db = json.loads(raw.decode("utf-8"))
        for key, cols_ in additions.items():
            for col, val in cols_.items():
                assert empty(filled_db[key].get(col)), (key, col)    # safety: never overwrite
                filled_db[key][col] = val
        with open(save / "species_description_filled.json", "w", encoding="utf-8") as f:
            json.dump(filled_db, f, ensure_ascii=False, indent=1)

    assert hashlib.md5(open(a.species, "rb").read()).hexdigest() == md5_before   # MycoBase not touched
    per_col = collections.Counter(r["column"] for r in rows if r["status"] == "ok")
    n_conf = len({(r["mycobase_record"], r["column"]) for r in rows if r["status"] == "conflict"})
    print(f"MycoBase records that get additions: {len(additions)}")
    print(f"additions (empty in MycoBase): {sum(len(v) for v in additions.values())}   "
          f"conflicts between papers (left for a curator): {n_conf}\n")
    for col, n in per_col.most_common():
        print(f"  {col:32s} {n:4d}")
    print(f"\nspecies images added: {len(img_csv)} for {len({r['mycobase_record'] for r in img_csv})} species "
          f"without an image in {a.images} -> {img_dir}")
    print(f"\nMycoBase file unchanged ({a.species}). Results -> {save / 'mycobase_additions.csv'}")


if __name__ == "__main__":
    main()
