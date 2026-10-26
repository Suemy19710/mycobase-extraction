"""Visualise the columns of species_description.json (matplotlib).

Left:  all columns, how many species have the column (light) vs. how many have text in it (solid),
       coloured by where the column comes from.
Right: how many different column names exist for each standard field (the duplicates to merge).

Usage:  python plot_columns.py [path/to/species_description.json] [output.png]
"""
import json, sys, collections
from pathlib import Path
import matplotlib.pyplot as plt
from matplotlib.patches import Patch

DATA_DIR      = Path(__file__).resolve().parent.parent / "data"   # = mycobase/data

JSON_FILE = str(DATA_DIR / "species_description.json")
OUT_FILE = str(DATA_DIR / "species_description_columns.png")

# ---- where each column comes from ------------------------------------------------------
BACKBONE = ["is accepted", "Literature", "YEAR", "MYCOBANK", "TYPUS", "EX_TYPUS", "kingdom", "phylum", "class",
            "order", "family", "genus", "subgenus", "section", "series", "ITS GenBank ID", "BenA GenBank ID",
            "CaM GenBank ID", "RPB2 GenBank ID", "WGS_type", "Comment"]
LAB_MANUAL = ["Macromorphology", "Morphs", "Chemical markers", "Typical cultures", "Important mycotoxins",
              "Physiology", "Biotechnological applications", "Biodeterioration and pathology", "References", "Fig",
              "Habitats and distribution"]

# ---- column name -> standard field (columns not listed map to themselves) ---------------
STANDARD = {
    "Type": "Typus", "Holotype": "Typus", "Type specimen": "Typus", "Neotype": "Typus",
    "Colony morphology": "Colony characters", "Culture characteristics": "Colony characters",
    "Conidiophores": "Micromorphology", "Morphological characteristics": "Description",
    "Synonym": "Synonyms",
    "Additional material examined": "Additional materials examined", "Cultures examined": "Additional materials examined",
    "Ecology": "Ecology and habitats",
}
def standard(col):
    if col.lower().startswith("colony diam"):
        return "Colony diam"
    if col.startswith("CYA ") and "°C" in col:
        return "Colony characters"
    return STANDARD.get(col, col)

# ---- count ------------------------------------------------------------------------------
data = json.load(open(JSON_FILE, encoding="utf-8"))
present, filled = collections.Counter(), collections.Counter()
for rec in data.values():
    for k, v in rec.items():
        present[k] += 1
        if str(v).strip():
            filled[k] += 1
cols = [k for k, _ in present.most_common()]
n_species = len(data)

def group(c):
    if c in BACKBONE: return "Backbone (accepted list)"
    if c in LAB_MANUAL: return "Lab manual"
    return "Papers (descriptions)"
COLORS = {"Backbone (accepted list)": "#2a78d6", "Papers (descriptions)": "#1baf7a", "Lab manual": "#eb6834"}
INK, INK2, GRID = "#0b0b0b", "#52514e", "#e6e5e0"

# ---- figure -----------------------------------------------------------------------------
fig, (ax, ax2) = plt.subplots(1, 2, figsize=(17, 19), gridspec_kw={"width_ratios": [1.45, 1], "wspace": 0.55})
fig.patch.set_facecolor("#fcfcfb")
fig.subplots_adjust(top=0.955)
fig.suptitle(f"species_description.json: {len(cols)} columns for {n_species:,} species",
             fontsize=18, fontweight="bold", color=INK, x=0.04, ha="left", y=0.99)

# Left panel: present (light) vs filled (solid), one row per column
y = range(len(cols))[::-1]
for yi, c in zip(y, cols):
    col = COLORS[group(c)]
    ax.barh(yi, present[c], color=col, alpha=0.25, height=0.78)
    ax.barh(yi, filled[c], color=col, height=0.78)
    ax.text(present[c] + 15, yi, f"{filled[c]:,} / {present[c]:,}", va="center", fontsize=8, color=INK2)
ax.set_yticks(list(y))
ax.set_yticklabels([c.replace(" ", " ") for c in cols], fontsize=9)
ax.set_xlim(0, n_species * 1.18)
ax.set_xlabel("number of species", color=INK2)
ax.set_title("A. Every column: species with text (solid) / species with the column (light)",
             loc="left", fontsize=12, fontweight="bold", color=INK)
ax.legend(handles=[Patch(color=v, label=k) for k, v in COLORS.items()]
          + [Patch(color="#9a9a9a", alpha=0.25, label="column present but empty")],
          loc="lower right", frameon=False, fontsize=10)

# Right panel: number of different column names per standard field (description columns only)
names_per_field = collections.defaultdict(list)
for c in cols:
    if group(c) == "Papers (descriptions)" and c not in ("Species", "Species description"):
        names_per_field[standard(c)].append(c)
fields = sorted(names_per_field, key=lambda f: (-len(names_per_field[f]), f))
y2 = range(len(fields))[::-1]
for yi, f in zip(y2, fields):
    n = len(names_per_field[f])
    ax2.barh(yi, n, color="#eb6834" if n > 1 else "#b9b8b2", height=0.7)
    if n > 1:
        ax2.text(n + 0.1, yi, ", ".join(x.replace(" ", " ") for x in names_per_field[f]),
                 va="center", fontsize=7.5, color=INK2, wrap=True)
ax2.set_yticks(list(y2))
ax2.set_yticklabels(fields, fontsize=9.5)
ax2.set_xlim(0, max(len(v) for v in names_per_field.values()) + 9)
ax2.set_xlabel("different column names", color=INK2)
total_desc = sum(len(v) for v in names_per_field.values())
ax2.set_title(f"B. Paper description columns: {total_desc} names → {len(fields)} standard fields",
              loc="left", fontsize=12, fontweight="bold", color=INK)
ax2.legend(handles=[Patch(color="#eb6834", label="several names for one field (merge)"),
                    Patch(color="#b9b8b2", label="one name only")], loc="lower right", frameon=False, fontsize=10)

for a in (ax, ax2):
    a.set_facecolor("#fcfcfb")
    for s in ("top", "right", "left"):
        a.spines[s].set_visible(False)
    a.tick_params(axis="y", length=0)
    a.grid(axis="x", color=GRID, linewidth=0.8)
    a.set_axisbelow(True)

fig.savefig(OUT_FILE, dpi=160, bbox_inches="tight")
print(f"{len(cols)} columns, {total_desc} paper-description names -> {len(fields)} standard fields; saved {OUT_FILE}")