import json
from collections import Counter
from pathlib import Path
import pandas as pd

DATA_DIR  = Path(__file__).resolve().parent.parent / "data"      # = mycobase/data
JSON_FILE = DATA_DIR / "species_description.json"
CSV_FILE  = DATA_DIR / "species_description.csv"

with open(JSON_FILE, encoding="utf-8") as f:
    data = json.load(f)                      # { "Aspergillus flavus": {field: value, ...}, ... }

rows = []
for name, fields in data.items():
    row = {"species_key": name}              # the JSON key becomes the first column
    for k, v in fields.items():
        # a few values are dicts/lists (e.g. Molecular markers) -> keep them as JSON text
        row[k] = json.dumps(v, ensure_ascii=False) if isinstance(v, (dict, list)) else v
    rows.append(row)

# column order: key first, then fields from most to least common
counts = Counter(k for r in rows for k in r if k != "species_key")
columns = ["species_key"] + [k for k, _ in counts.most_common()]

df = pd.DataFrame(rows, columns=columns)
df.to_csv(CSV_FILE, index=False, encoding="utf-8-sig")   # utf-8-sig: Excel shows accents correctly

print(f"{len(df):,} species x {len(columns)} columns -> {CSV_FILE}")