import json, re, sys
import pandas as pd
from pathlib import Path
import matplotlib.pyplot as plt 
DATA_DIR      = Path(__file__).resolve().parent.parent / "data"   # = mycobase/data
MYCOBANK_FILE = str(DATA_DIR / "Mycobank.xlsx")
JSON_FILE     = str(DATA_DIR / "species_description.json")
OUT_FILE      = str(DATA_DIR / "comparison_report_v2.csv")

def clean_num(x):
    """'209842', 209842.0, 'MB209842' -> '209842'"""
    if pd.isna(x): return ""
    s = re.sub(r"\D", "", str(x).split(".")[0])
    return s

def norm(s):
    return re.sub(r"\s+", " ", str(s)).replace("ﬁ", "fi").replace("ﬂ", "fl").strip().lower()
 
# 1. Load both files
if MYCOBANK_FILE.lower().endswith((".xlsx", ".xls")):
    mb = pd.read_excel(MYCOBANK_FILE, dtype=str)
else:
    mb = pd.read_csv(MYCOBANK_FILE, dtype=str)
mb["mb_num"] = mb["MycoBank #"].map(clean_num)
mb["cur_num"] = mb["Current MycoBank #"].map(clean_num)
mb["name_key"] = mb["Taxon name"].map(norm)
db = json.load(open(JSON_FILE, encoding="utf-8"))
print(f"MycoBank rows: {len(mb):,}   JSON species: {len(db):,}")
 
by_num = mb.drop_duplicates("mb_num").set_index("mb_num", drop=False)
by_name = mb.groupby("name_key")
 
rows = []
for name, rec in db.items():
    r = {"json_name": name, "json_mycobank": clean_num(rec.get("MYCOBANK", "")),
         "json_year": str(rec.get("YEAR", "")).strip(),
         "json_literature": str(rec.get("Literature", ""))[:80],
         "json_accepted": rec.get("is accepted", ""),
         "json_genus": rec.get("genus", ""), "json_family": rec.get("family", "")}
 
   # 2. Find the MycoBank row: first by MycoBank number, else by name
    hit, how = None, ""
    if r["json_mycobank"] and r["json_mycobank"] in by_num.index:
        hit, how = by_num.loc[r["json_mycobank"]], "by_number"
    elif norm(name) in by_name.groups:
        g = by_name.get_group(norm(name))
        hit, how = g.iloc[0], "by_name" + (f" ({len(g)} homonyms)" if len(g) > 1 else "")
    r["matched"] = how or "NOT_FOUND"
    if hit is None:
        rows.append(r); continue
 
    # 3. Compare field by field
    r["mb_name"] = hit["Taxon name"]
    r["mb_number"] = hit["mb_num"]
    r["mb_year"] = str(hit["Year of effective publication"]).split(".")[0]
    r["mb_authors"] = hit["Authors (abbreviated)"]
    r["mb_status"] = hit["Name status"]
    r["mb_current_name"] = hit["Current name"]
    r["same_name"] = norm(hit["Taxon name"]) == norm(name)
    r["same_number"] = r["json_mycobank"] == hit["mb_num"] if r["json_mycobank"] else ""
    r["same_year"] = r["json_year"] == r["mb_year"] if r["json_year"] else ""
    # JSON 'Literature' starts with the author citation, e.g. "Link, Mag. Ges. ..."
    a = norm(hit["Authors (abbreviated)"]).replace(" ", "")
    r["authors_in_literature"] = a[:12] in norm(r["json_literature"]).replace(" ", "") if a else ""
    is_current = hit["mb_num"] == hit["cur_num"]
    r["mb_is_current_name"] = is_current
    r["accepted_agrees"] = (r["json_accepted"] == "Yes") == (is_current and hit["Name status"] == "Legitimate")
    cls = norm(hit["Classification"])
    r["genus_in_classification"] = norm(r["json_genus"]) in cls if r["json_genus"] else ""
    r["family_in_classification"] = norm(r["json_family"]) in cls if r["json_family"] else ""
    rows.append(r)
 
rep = pd.DataFrame(rows)
rep.to_csv(OUT_FILE, index=False, encoding="utf-8-sig")

 
# 4. Summary
print("\nHow species were matched:"); 
print(rep["matched"].value_counts().to_string())
for col in ["same_name", "same_number", "same_year", "authors_in_literature",
            "mb_is_current_name", "accepted_agrees", "genus_in_classification"]:
    if col in rep:
        v = rep[col][rep[col] != ""].dropna()
        print(f"{col:26s} agree {int((v == True).sum()):5d}   disagree {int((v == False).sum()):5d}")
print(f"\nFull report: {OUT_FILE}")

# 5. Plots 
# Collect the counts
match_counts = rep["matched"].value_counts()

checks = {}
for col in ["same_name", "same_number", "same_year", "authors_in_literature",
            "mb_is_current_name", "accepted_agrees", "genus_in_classification"]:
    if col in rep:
        v = rep[col][rep[col] != ""].dropna()
        checks[col] = {"agree": int((v == True).sum()), "disagree": int((v == False).sum())}
check_df = pd.DataFrame(checks).T          # rows = checks, columns = agree / disagree

# Plot 1: how species were matched
match_counts.plot(kind="bar", color="steelblue", title="How species were matched")
plt.ylabel("Number of species")
plt.xticks(rotation=30, ha="right")
plt.tight_layout()
plt.savefig(DATA_DIR / "plot_matched.png", dpi=150)
plt.show()

# Plot 2: agree vs disagree per check
check_df.plot(kind="barh", stacked=True, color=["seagreen", "indianred"],
              title="Agreement with MycoBank per check")
plt.xlabel("Number of species")
plt.tight_layout()
plt.savefig(DATA_DIR / "plot_checks.png", dpi=150)
plt.show()