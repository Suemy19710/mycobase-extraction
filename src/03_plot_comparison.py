"""Plot the MycoBank vs species_description.json comparison (comparison_report.csv)."""
import sys
import pandas as pd
import matplotlib.pyplot as plt
from pathlib import Path

DATA_DIR      = Path(__file__).resolve().parent.parent / "data"   # = mycobase/data

CSV     = str(DATA_DIR / "comparison_report.csv")
OUT = str(DATA_DIR / "comparison_mycobank_vs_json.png")

r = pd.read_csv(CSV, dtype=str).fillna("")

# palette (validated reference palette): blue = agree / matched, orange = disagree, grey = neutral
BLUE, ORANGE, AQUA, YELLOW, GREY = "#2a78d6", "#eb6834", "#1baf7a", "#eda100", "#b9b8b2"
INK, INK2, SURF = "#0b0b0b", "#52514e", "#fcfcfb"
plt.rcParams.update({"font.family": "DejaVu Sans", "font.size": 10, "axes.edgecolor": "#d6d5d0",
                     "axes.labelcolor": INK2, "xtick.color": INK2, "ytick.color": INK,
                     "axes.facecolor": SURF, "figure.facecolor": SURF})

def clean(ax):
    for s in ("top", "right", "left"):
        ax.spines[s].set_visible(False)
    ax.tick_params(axis="y", length=0)
    ax.grid(axis="x", color="#ecebe7", linewidth=0.8)
    ax.set_axisbelow(True)

fig, axes = plt.subplots(2, 2, figsize=(15, 9.5), gridspec_kw={"hspace": 0.45, "wspace": 0.55})
fig.suptitle(f"MycoBank export ({544942:,} names) vs MycoBase species_description.json ({len(r):,} species)",
             fontsize=15, fontweight="bold", color=INK, x=0.02, ha="left")

# ---- A: how species were matched ------------------------------------------------------
ax = axes[0, 0]
m = r["matched"]
nf = r[m == "NOT_FOUND"]
bad_key = nf["json_name"].str.contains(r"[,:()]|\d", regex=True)
cats = [("Matched by MycoBank number", (m == "by_number").sum(), BLUE),
        ("Matched by name only", (m == "by_name").sum(), BLUE),
        ("Matched by name (homonyms)", m.str.contains("homonym").sum(), YELLOW),
        ("Not found: newer than export", (~bad_key).sum(), GREY),
        ("Not found: broken JSON key", bad_key.sum(), ORANGE)]
labels, vals, cols = zip(*cats)
y = range(len(cats))[::-1]
ax.barh(list(y), vals, color=cols, height=0.62)
for yi, v in zip(y, vals):
    ax.text(v + 15, yi, f"{v:,}", va="center", color=INK, fontsize=10)
ax.set_yticks(list(y)); ax.set_yticklabels(labels)
ax.set_xlim(0, max(vals) * 1.15)
ax.set_title("A. Can each JSON species be found in MycoBank?", loc="left", fontweight="bold", color=INK)
ax.set_xlabel("species"); clean(ax)

# ---- B: agreement per check (100% stacked) --------------------------------------------
ax = axes[0, 1]
checks = [("Same name", "same_name"), ("Same MycoBank #", "same_number"), ("Same year", "same_year"),
          ("Author found in citation", "authors_in_literature"), ("MycoBank: name is current", "mb_is_current_name"),
          ("Accepted status agrees", "accepted_agrees"), ("Genus in classification", "genus_in_classification")]
y = list(range(len(checks)))[::-1]
for yi, (lab, col) in zip(y, checks):
    v = r[col][r[col].isin(["True", "False"])]
    a, d = (v == "True").sum(), (v == "False").sum()
    n = a + d
    ax.barh(yi, a / n * 100, color=BLUE, height=0.62)
    ax.barh(yi, d / n * 100, left=a / n * 100, color=ORANGE, height=0.62, edgecolor=SURF, linewidth=1.5)
    ax.text(101.5, yi, f"{a:,} / {n:,}  ({(f"{a / n * 100:.1f}" if d else "100")}%)", va="center", fontsize=9.5, color=INK)
ax.set_yticks(y); ax.set_yticklabels([c[0] for c in checks])
ax.set_xlim(0, 100); ax.set_xlabel("% of compared species")
ax.set_title("B. Field-by-field agreement (matched species only)", loc="left", fontweight="bold", color=INK)
ax.legend(handles=[plt.Rectangle((0, 0), 1, 1, color=BLUE), plt.Rectangle((0, 0), 1, 1, color=ORANGE)],
          labels=["agree", "disagree"], loc="lower left", bbox_to_anchor=(0, -0.28), ncol=2, frameon=False)
clean(ax)

# ---- C: why accepted status disagrees ------------------------------------------------
ax = axes[1, 0]
mm = r[r["matched"] != "NOT_FOUND"]
ac = mm[mm["accepted_agrees"] == "False"]
c1 = ((ac.json_accepted == "No")).sum()
c2 = ((ac.json_accepted == "Yes") & (ac.mb_is_current_name == "False")).sum()
c3 = ((ac.json_accepted == "Yes") & (ac.mb_is_current_name == "True")).sum()
causes = [("JSON 'No' = not in Visagie 2025 list\n(MycoBank: current & legitimate)", c1, GREY),
          ("JSON 'Yes', MycoBank points to\nanother current name (synonymy)", c2, ORANGE),
          ("JSON 'Yes', but MycoBank name is\nInvalid / Illegitimate", c3, ORANGE)]
y = [2, 1, 0]
ax.barh(y, [c[1] for c in causes], color=[c[2] for c in causes], height=0.6)
for yi, (_, v, _) in zip(y, causes):
    ax.text(v + 1.2, yi, str(v), va="center", fontsize=10, color=INK)
ax.set_yticks(y); ax.set_yticklabels([c[0] for c in causes])
ax.set_xlim(0, max(c1, c2, c3) * 1.18); ax.set_xlabel("species")
ax.set_title(f"C. Accepted status: {len(ac)} disagreements by cause", loc="left", fontweight="bold", color=INK)
ax.text(0, -0.32, "Orange = worth a curator's review; grey = difference in what the field means",
        transform=ax.transAxes, fontsize=9, color=INK2)
clean(ax)

# ---- D: year differences -----------------------------------------------------------------
ax = axes[1, 1]
yy = r[r["same_year"] == "False"].copy()
yy["d"] = pd.to_numeric(yy["json_year"], errors="coerce") - pd.to_numeric(yy["mb_year"], errors="coerce")
yy = yy.dropna(subset=["d"])
bins = {"−1 yr": (yy.d == -1).sum(), "+1 yr": (yy.d == 1).sum(),
        "±2–4 yr": ((yy.d.abs() >= 2) & (yy.d.abs() <= 4)).sum(), "≥10 yr": (yy.d.abs() >= 10).sum()}
x = range(len(bins))
colsD = [GREY, GREY, ORANGE, ORANGE]
ax.bar(list(x), list(bins.values()), color=colsD, width=0.6)
for xi, v in zip(x, bins.values()):
    ax.text(xi, v + 0.8, str(v), ha="center", fontsize=10, color=INK)
ax.set_xticks(list(x)); ax.set_xticklabels(list(bins)); ax.set_xlabel("year in JSON − year in MycoBank")
ax.set_ylim(0, max(bins.values()) * 1.15)
for s in ("top", "right"):
    ax.spines[s].set_visible(False)
ax.grid(axis="y", color="#ecebe7", linewidth=0.8); ax.set_axisbelow(True)
ax.set_ylabel("species")
ax.set_title(f"D. Publication year: {len(yy)} differences", loc="left", fontweight="bold", color=INK)
ax.text(0, -0.32, "±1 year = online vs printed publication date (grey); larger gaps need checking (orange)",
        transform=ax.transAxes, fontsize=9, color=INK2)

fig.savefig(OUT, dpi=180, bbox_inches="tight")
print("saved", OUT)