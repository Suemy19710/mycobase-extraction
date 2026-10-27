"""Name lists: the accepted species list and the MycoBank export.

Rule from the mentor: MycoBase contains only species accepted in
  Visagie et al. 2025, "From chaos to tranquillity..." (Studies in Mycology 112).
That list is the backbone of data/species_description.json (records with "is accepted": "Yes").

So every species name found in a paper is resolved like this:
  accepted       the name itself is on the accepted list
  synonym        MycoBank says its current name is an accepted species -> use that name
  not_accepted   MycoBank knows the name, but it does not lead to an accepted species
  unknown        not on the accepted list and not in MycoBank (new, misread or out of scope)
Only "accepted" and "synonym" go on to MycoBase; everything is kept in the raw output.

The MycoBank Excel file has ~545,000 rows and takes minutes to read, so the first run builds a
small cached index (data/cache/mycobank_index.tsv.gz) and later runs read only that.
"""
import csv
import gzip
import json
import os
import re
import time
import zipfile
from xml.etree.ElementTree import iterparse

from .text import norm_ws

_NS = "{http://schemas.openxmlformats.org/spreadsheetml/2006/main}"
# columns of the MycoBank export we keep (Excel letter -> our name)
_KEEP = {"B": "name", "D": "authors", "E": "rank", "F": "year", "G": "status",
         "H": "mb", "K": "current_mb", "L": "current_name"}


def _num(x):
    """'209842', '209842.0', 'MB209842' -> '209842'"""
    return re.sub(r"\D", "", str(x or "").split(".")[0])


def build_mycobank_index(xlsx_path, cache_path):
    """Read the MycoBank .xlsx once (streaming, ~2 min) and write a compact gzipped TSV."""
    t0 = time.time()
    z = zipfile.ZipFile(xlsx_path)
    shared = []
    for _, el in iterparse(z.open("xl/sharedStrings.xml")):
        if el.tag == _NS + "si":
            shared.append("".join(x.text or "" for x in el.iter(_NS + "t")))
            el.clear()
    os.makedirs(os.path.dirname(cache_path), exist_ok=True)
    n = 0
    with gzip.open(cache_path, "wt", encoding="utf-8", newline="") as out:
        w = csv.writer(out, delimiter="\t")
        w.writerow(list(_KEEP.values()))
        row = {}
        first = True
        for _, el in iterparse(z.open("xl/worksheets/sheet1.xml")):
            if el.tag == _NS + "c":
                col = re.match(r"[A-Z]+", el.get("r")).group(0)
                if col in _KEEP:
                    v = el.find(_NS + "v")
                    if el.get("t") == "s" and v is not None:
                        row[col] = shared[int(v.text)]
                    elif el.get("t") == "inlineStr":
                        row[col] = "".join(x.text or "" for x in el.iter(_NS + "t"))
                    else:
                        row[col] = v.text if v is not None else ""
            elif el.tag == _NS + "row":
                if not first:                   # first row = header
                    w.writerow([row.get(c, "") for c in _KEEP])
                    n += 1
                first = False
                row = {}
                el.clear()
    print(f"MycoBank index: {n:,} names -> {cache_path} ({time.time() - t0:.0f} s)")
    return n


class NameIndex:
    """Look up species names against the accepted list and (optionally) MycoBank."""

    def __init__(self, species_json, mycobank_cache=None):
        with open(species_json, encoding="utf-8") as f:
            db = json.load(f)
        self.accepted = {norm_ws(k): k for k, v in db.items() if v.get("is accepted") == "Yes"}
        self.mycobase_names = set(db)
        self.by_name, self.by_num = {}, {}
        self.genera = {k.split()[0] for k in self.accepted}
        self.has_mycobank = False
        if mycobank_cache and os.path.exists(mycobank_cache):
            with gzip.open(mycobank_cache, "rt", encoding="utf-8") as f:
                for r in csv.DictReader(f, delimiter="\t"):
                    r["mb"], r["current_mb"] = _num(r["mb"]), _num(r["current_mb"])
                    key = norm_ws(r["name"]).lower()
                    self.by_name.setdefault(key, []).append(r)
                    if r["mb"]:
                        self.by_num[r["mb"]] = r
                    if r["rank"] == "gen.":
                        self.genera.add(norm_ws(r["name"]))
            self.has_mycobank = True

    def is_genus(self, genus):
        return genus in self.genera

    def _current(self, row):
        """Follow 'Current MycoBank #' to the current name (at most 5 steps)."""
        seen = set()
        while row and row["current_mb"] and row["current_mb"] != row["mb"] and row["mb"] not in seen:
            seen.add(row["mb"])
            nxt = self.by_num.get(row["current_mb"])
            if nxt is None:
                return row["current_name"]
            row = nxt
            if len(seen) > 5:
                break
        return row["name"] if row else ""

    def resolve(self, name):
        """Return how a name from a paper relates to the accepted list."""
        name = norm_ws(name)
        res = {"name_in_paper": name, "status": "unknown", "accepted_name": "",
               "mycobank_number": "", "mycobank_current_name": "", "mycobank_status": ""}
        rows = self.by_name.get(name.lower(), [])
        if rows:
            # prefer the record whose current name is accepted (homonyms exist)
            rows = sorted(rows, key=lambda r: norm_ws(self._current(r)) not in self.accepted)
            r = rows[0]
            res.update(mycobank_number=r["mb"], mycobank_current_name=self._current(r),
                       mycobank_status=r["status"])
        if name in self.accepted:
            res.update(status="accepted", accepted_name=self.accepted[name])
        elif rows and norm_ws(res["mycobank_current_name"]) in self.accepted:
            res.update(status="synonym", accepted_name=self.accepted[norm_ws(res["mycobank_current_name"])])
        elif rows:
            res["status"] = "not_accepted"
        return res
