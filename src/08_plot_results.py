"""Illustrate the results of the extraction tool (steps 1-2, figures, MycoBank check) with matplotlib.

Reads the folders written by 06_run_steps_1_2.py (and 07_check_mycobank.py) and draws:

  treatments_per_paper.png   species sections per paper: to MycoBase / raw only / name-list entries
  name_status.png            how the names were resolved: accepted, synonym, not accepted, unknown
  figures_per_paper.png      figures saved per paper by kind, and treatments that got their own figure
  mycobank_check.png         MycoBank check: OK / CHECK per paper, MycoBank numbers, authors
  overview.png               the four charts on one page (for a report or a slide)
  annotated_page_<paper>_p<n>.png   (with --page) one PDF page with every line coloured by the role
                                    the tool gave it - shows how the structure of a paper is read

Usage (from the repository folder):
  python src/08_plot_results.py                                   # output/
  python src/08_plot_results.py --out output --out output_vol84   # several result folders together
  python src/08_plot_results.py --out output_vol84 --page "vol84/Vol84Art2_New-Talaromyces-species-from-indoor-environments-in-C_2016_Studies-in-Mycolo.pdf" 6

Charts are written to <first --out folder>/plots/ (change with --save).
"""
import argparse
import collections
import csv
import glob
import json
import os
import sys
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
from matplotlib.patches import Patch  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "data"

# ---------------------------------------------------------------- style (validated reference palette)
SURFACE = "#fcfcfb"
TEXT = "#0b0b0b"
TEXT_2 = "#52514e"
GRID = "#e4e3df"
BLUE, ORANGE, AQUA, YELLOW, VIOLET = "#2a78d6", "#eb6834", "#1baf7a", "#eda100", "#6250d6"
GREY = "#a9a8a2"
GOOD, WARNING = "#0ca30c", "#fab219"          # status colours: always shown with a text label

plt.rcParams.update({
    "figure.facecolor": SURFACE, "axes.facecolor": SURFACE, "savefig.facecolor": SURFACE,
    "axes.edgecolor": GRID, "axes.labelcolor": TEXT_2, "xtick.color": TEXT_2, "ytick.color": TEXT,
    "text.color": TEXT, "font.size": 10, "axes.titlesize": 12, "axes.titleweight": "bold",
    "axes.titlelocation": "left", "axes.spines.top": False, "axes.spines.right": False,
    "legend.frameon": False,
})


def short(paper, n=34):
    """'Vol84Art2_New-Talaromyces-species-from-...' -> 'Vol84Art2 New Talaromyces species ...'"""
    s = paper.replace("_", " ").replace("-", " ")
    return s if len(s) <= n else s[: n - 1].rstrip() + "…"


def style_axis(ax, axis="x"):
    ax.grid(axis=axis, color=GRID, linewidth=0.8)
    ax.set_axisbelow(True)
    ax.tick_params(length=0)
    for side in ("left", "bottom"):
        ax.spines[side].set_color(GRID)


# ---------------------------------------------------------------- read results
def load(out_dirs):
    """Return {paper: {"sections": [...], "figures": [...], "check": [...]}}; a later folder wins."""
    papers = {}
    for out in out_dirs:
        for f in sorted(glob.glob(os.path.join(out, "*", "sections.json"))):
            d = os.path.dirname(f)
            paper = os.path.basename(d)
            with open(f, encoding="utf-8") as fh:
                rec = {"sections": json.load(fh), "figures": [], "check": []}
            fj = os.path.join(d, "figures.json")
            if os.path.exists(fj):
                with open(fj, encoding="utf-8") as fh:
                    rec["figures"] = json.load(fh)
            papers[paper] = rec
        tsv = os.path.join(out, "mycobank_check.tsv")
        if os.path.exists(tsv):
            with open(tsv, encoding="utf-8-sig") as fh:
                for r in csv.DictReader(fh, delimiter="\t"):
                    if r["paper"] in papers:
                        papers[r["paper"]].setdefault("_check_new", []).append(r)
        for p in papers.values():                   # check rows of this folder replace older ones
            if "_check_new" in p:
                p["check"] = p.pop("_check_new")
    return papers


# ---------------------------------------------------------------- charts
def stacked_barh(ax, labels, series, title, xlabel):
    """Horizontal stacked bars; series = [(name, colour, values)]. Segment values written inside."""
    left = [0] * len(labels)
    y = range(len(labels))
    for name, colour, values in series:
        bars = ax.barh(y, values, left=left, color=colour, height=0.6, label=name,
                       edgecolor=SURFACE, linewidth=2)
        for b, v in zip(bars, values):
            if v and b.get_width() >= max(max(left) + max(values), 1) * 0.04:
                ax.text(b.get_x() + b.get_width() / 2, b.get_y() + b.get_height() / 2, str(v),
                        ha="center", va="center", fontsize=9, color="white", fontweight="bold")
        left = [a + b for a, b in zip(left, values)]
    for yi, total in zip(y, left):
        ax.text(total + max(left) * 0.01, yi, str(total), va="center", fontsize=9, color=TEXT_2)
    ax.set_yticks(list(y), labels)
    ax.invert_yaxis()
    ax.set_title(title, pad=26)
    ax.set_xlabel(xlabel)
    ax.set_xlim(0, max(left + [1]) * 1.12)
    style_axis(ax)
    ax.legend(loc="lower left", bbox_to_anchor=(0, 1.0), ncol=len(series), fontsize=9,
              borderaxespad=0.3, handlelength=1.2, borderpad=0, columnspacing=1.5)


def chart_treatments(ax, papers):
    names = list(papers)
    to_mb = [sum(1 for s in papers[p]["sections"] if s["kind"] == "treatment" and s["target"] == "mycobase") for p in names]
    raw = [sum(1 for s in papers[p]["sections"] if s["kind"] == "treatment" and s["target"] != "mycobase") for p in names]
    entries = [sum(1 for s in papers[p]["sections"] if s["kind"] != "treatment") for p in names]
    stacked_barh(ax, [short(p) for p in names],
                 [("treatment → MycoBase", BLUE, to_mb), ("treatment, raw output only", ORANGE, raw),
                  ("name-list entry", AQUA, entries)],
                 "Species sections per paper", "sections")


def chart_name_status(ax, papers):
    order = [("accepted", "accepted\n→ MycoBase"), ("synonym", "synonym\n→ MycoBase"),
             ("not_accepted", "not accepted\n→ raw only"), ("unknown", "unknown\n→ raw only")]
    c = collections.Counter(s["name"]["status"] for p in papers.values() for s in p["sections"])
    vals = [c.get(k, 0) for k, _ in order]
    bars = ax.bar(range(len(order)), vals, color=BLUE, width=0.6)
    for b, v in zip(bars, vals):
        ax.text(b.get_x() + b.get_width() / 2, v + max(vals + [1]) * 0.02, str(v), ha="center", fontsize=10,
                color=TEXT, fontweight="bold")
    ax.set_xticks(range(len(order)), [lab for _, lab in order])
    ax.set_title(f"Name status of all {sum(vals)} sections")
    ax.set_ylabel("sections")
    ax.set_ylim(0, max(vals + [1]) * 1.15)
    style_axis(ax, "y")
    ax.tick_params(axis="x", colors=TEXT)


def chart_figures(ax, papers):
    names = list(papers)
    kinds = [("plate", BLUE), ("phylogeny", AQUA), ("drawing", VIOLET), ("uncaptioned", GREY)]
    series = []
    for k, col in kinds:
        vals = [sum(1 for f in papers[p]["figures"] if f.get("file") and f["kind"] == k) for p in names]
        if any(vals):
            series.append((k, col, vals))
    labels = []
    for p in names:
        tr = [s for s in papers[p]["sections"] if s["kind"] == "treatment"]
        with_fig = sum(1 for s in tr if s.get("figures"))
        labels.append(f"{short(p, 28)}\n{with_fig}/{len(tr)} treatments with own figure")
    if not series:
        ax.text(0.5, 0.5, "no figures.json found\n(run 06_run_steps_1_2.py without --no-figures)",
                ha="center", va="center", color=TEXT_2, transform=ax.transAxes)
        ax.set_axis_off()
        return
    stacked_barh(ax, labels, series, "Figures saved per paper", "figures")
    ax.tick_params(axis="y", labelsize=8)


def chart_check(ax, papers):
    names = [p for p in papers if papers[p]["check"]]
    if not names:
        ax.text(0.5, 0.5, "no mycobank_check.tsv found\n(run 07_check_mycobank.py first)",
                ha="center", va="center", color=TEXT_2, transform=ax.transAxes)
        ax.set_axis_off()
        return
    ok = [sum(1 for r in papers[p]["check"] if r["verdict"] == "OK") for p in names]
    chk = [sum(1 for r in papers[p]["check"] if r["verdict"] == "CHECK") for p in names]
    stacked_barh(ax, [short(p) for p in names], [("OK", GOOD, ok), ("CHECK", WARNING, chk)],
                 f"MycoBank check: {sum(ok)} OK, {sum(chk)} CHECK", "sections")


def chart_check_detail(fig, papers):
    rows = [r for p in papers.values() for r in p["check"]]
    if not rows:
        return False
    gs = fig.add_gridspec(2, 2, height_ratios=[1.15, 1], hspace=0.55, wspace=0.45)
    chart_check(fig.add_subplot(gs[0, :]), papers)

    def counts(ax, key, title, order):
        c = collections.Counter(r[key].split(" (")[0] for r in rows)
        keys = [k for k in order if c.get(k)] + sorted(k for k in c if k not in order)
        vals = [c[k] for k in keys]
        bars = ax.barh(range(len(keys)), vals, color=BLUE, height=0.5)
        for b, v in zip(bars, vals):
            ax.text(v + max(vals) * 0.02, b.get_y() + b.get_height() / 2, str(v), va="center", fontsize=9)
        ax.set_yticks(range(len(keys)), keys)
        ax.invert_yaxis()
        ax.set_xlim(0, max(vals) * 1.18)
        ax.set_title(title)
        style_axis(ax)

    counts(fig.add_subplot(gs[1, 0]), "number_check", "MycoBank number printed in the paper",
           ["match", "no number in paper", "number of a synonym/basionym", "number of another name",
            "number not in MycoBank"])
    counts(fig.add_subplot(gs[1, 1]), "authors_check", "Authors in the heading vs MycoBank",
           ["match", "partial", "differ", "no authors in MycoBank"])
    return True


# ---------------------------------------------------------------- annotated page
ROLE_COLOURS = {"heading": "#e34948", "citation": "#eda100", "label": "#008300", "body": BLUE,
                "removed": "#7a7974", "figure": VIOLET}
ROLE_TEXT = {"heading": "species heading", "citation": "heading citation (MycoBank number, Fig.)",
             "label": "field label (Etymology:, Typus: …)", "body": "body text (kept, reading order)",
             "removed": "removed: header, page number, caption, small print", "figure": "figure saved as image"}


def annotated_page(pdf, page_no, save_dir, species_json, mycobank_cache):
    """Draw page `page_no` (1-based) of `pdf` with each line coloured by its role in steps 1-2."""
    import io

    import pymupdf
    from PIL import Image

    sys.path.insert(0, str(Path(__file__).resolve().parent))
    from extraction.figures import extract_figures
    from extraction.layout import clean_lines, pdf_lines
    from extraction.names import NameIndex
    from extraction.segment import find_sections
    from extraction.text import starts_with_label

    names = NameIndex(species_json, mycobank_cache)
    lines = pdf_lines(pdf)
    clean, body = clean_lines(lines)
    sections = find_sections(clean, body, names)
    key = lambda r: (r["p"], r["x0"], r["y0"])  # noqa: E731
    role = {}
    for s in sections:
        for i, r in enumerate(s["head"]):
            role[key(r)] = "heading" if i == 0 else "citation"
        for r in s["body"]:
            role[key(r)] = "label" if starts_with_label(r) else "body"
    clean_keys = {key(r) for r in clean}
    pno = page_no - 1

    def line_role(r):
        if key(r) in role:
            return role[key(r)]
        # pieces of a justified line were merged into the line that starts on the same baseline
        for c in clean:
            if (c["p"] == r["p"] and abs(c["y0"] - r["y0"]) < 2.5 and c["x0"] <= r["x0"] <= c["x1"] + 5
                    and (c["x0"] < c["W"] * 0.47) == (r["x0"] < r["W"] * 0.47)):
                return role.get(key(c), "body")
        return "body" if key(r) in clean_keys else "removed"

    doc = pymupdf.open(pdf)
    if not 0 <= pno < len(doc):
        sys.exit(f"--page {page_no}: the PDF has {len(doc)} pages")
    page = doc[pno]
    used = set()
    for r in (x for x in lines if x["p"] == pno):
        k = line_role(r)
        used.add(k)
        col = tuple(int(ROLE_COLOURS[k][i:i + 2], 16) / 255 for i in (1, 3, 5))
        rect = pymupdf.Rect(r["x0"] - 1, r["y0"] - 0.5, r["x1"] + 1, r["y1"] + 0.5)
        if k == "removed":
            page.draw_rect(rect, color=col, width=0.9, dashes="[2] 1")
        else:
            page.draw_rect(rect, color=col, fill=col, fill_opacity=0.15, width=0.8)
    # figure areas (found again here, images written to a temporary folder)
    import tempfile
    with tempfile.TemporaryDirectory() as tmp:
        figs = extract_figures(pdf, lines, clean, Path(tmp), names, {s["name"] for s in sections}, dpi=30)
    for f in figs:
        if f["page"] == page_no and f["bbox"]:
            b = f["bbox"]
            col = tuple(int(VIOLET[i:i + 2], 16) / 255 for i in (1, 3, 5))
            page.draw_rect(pymupdf.Rect(b[0] - 3, b[1] - 3, b[2] + 3, b[3] + 3), color=col, width=2)
            used.add("figure")
    img = Image.open(io.BytesIO(page.get_pixmap(dpi=130).tobytes("png")))

    fig = plt.figure(figsize=(12, 11))
    ax = fig.add_axes([0.0, 0.0, 0.62, 1.0])
    ax.imshow(img)
    ax.set_axis_off()
    order = ["heading", "citation", "label", "body", "removed", "figure"]
    handles = [Patch(facecolor="none" if k == "removed" else ROLE_COLOURS[k] + "40", edgecolor=ROLE_COLOURS[k],
                     linestyle="--" if k == "removed" else "-", linewidth=2, label=ROLE_TEXT[k])
               for k in order if k in used]
    lax = fig.add_axes([0.64, 0.25, 0.35, 0.6])
    lax.set_axis_off()
    lax.text(0, 1.0, "How the tool reads this page", fontsize=14, fontweight="bold", va="top")
    lax.text(0, 0.93, f"{os.path.basename(pdf)[:60]}\npage {page_no}", fontsize=9, color=TEXT_2, va="top")
    lax.legend(handles=handles, loc="upper left", bbox_to_anchor=(0, 0.82), fontsize=11, handlelength=2.2,
               handleheight=1.4, labelspacing=1.1)
    here = [s["name"] for s in sections if s["pages"][0] <= pno <= s["pages"][1]]
    if here:
        lax.text(0, 0.18, "Species sections on this page:\n" + "\n".join(f"  • {n}" for n in here[:8]),
                 fontsize=10, va="top")
    stem = Path(pdf).stem[:40].replace(" ", "_")
    out = save_dir / f"annotated_page_{stem}_p{page_no}.png"
    write_png(fig, out, dpi=130)
    return out


# ---------------------------------------------------------------- main
def write_png(fig, path, dpi=160):
    """Save a figure; writes the bytes in place (some synced folders do not allow deleting a file)."""
    import io
    buf = io.BytesIO()
    fig.savefig(buf, format="png", dpi=dpi, bbox_inches="tight")
    plt.close(fig)
    with open(path, "wb") as f:
        f.write(buf.getvalue())
    print("saved", path)


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--out", action="append", help="result folder of 06_run_steps_1_2.py (repeatable; default output/)")
    ap.add_argument("--save", help="folder for the charts (default: <first --out>/plots)")
    ap.add_argument("--page", nargs=2, metavar=("PDF", "PAGE"), help="also draw one annotated page of a paper")
    ap.add_argument("--species", default=str(DATA / "species_description.json"))
    ap.add_argument("--mycobank-cache", default=str(DATA / "cache" / "mycobank_index.tsv.gz"))
    a = ap.parse_args()
    outs = a.out or [str(ROOT / "output")]
    save = Path(a.save or os.path.join(outs[0], "plots"))
    save.mkdir(parents=True, exist_ok=True)

    papers = load(outs)
    if papers:
        n = len(papers)
        h = max(3.0, 0.55 * n + 1.6)
        fig, ax = plt.subplots(figsize=(10, h))
        chart_treatments(ax, papers)
        write_png(fig, save / "treatments_per_paper.png")

        fig, ax = plt.subplots(figsize=(8, 4.5))
        chart_name_status(ax, papers)
        write_png(fig, save / "name_status.png")

        fig, ax = plt.subplots(figsize=(10, max(3.0, 0.75 * n + 1.6)))
        chart_figures(ax, papers)
        write_png(fig, save / "figures_per_paper.png")

        fig = plt.figure(figsize=(11, h + 3.6))
        if chart_check_detail(fig, papers):
            write_png(fig, save / "mycobank_check.png")
        else:
            plt.close(fig)
            print("no mycobank_check.tsv in", ", ".join(outs), "- run 07_check_mycobank.py for the MycoBank chart")

        fig, axs = plt.subplots(2, 2, figsize=(18, max(9.0, 1.1 * n + 5)))
        chart_treatments(axs[0, 0], papers)
        chart_name_status(axs[0, 1], papers)
        chart_figures(axs[1, 0], papers)
        chart_check(axs[1, 1], papers)
        fig.suptitle(f"MycoBase extraction: {n} papers, "
                     f"{sum(1 for p in papers.values() for s in p['sections'] if s['kind'] == 'treatment')} species treatments",
                     x=0.01, ha="left", fontsize=15, fontweight="bold")
        fig.tight_layout(h_pad=3, w_pad=4)
        write_png(fig, save / "overview.png")
    else:
        print("no sections.json found in", ", ".join(outs), "- run 06_run_steps_1_2.py first")

    if a.page:
        annotated_page(a.page[0], int(a.page[1]), save, a.species, a.mycobank_cache)


if __name__ == "__main__":
    main()