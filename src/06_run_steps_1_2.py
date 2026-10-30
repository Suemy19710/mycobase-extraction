"""Run step 1 (layout reconstruction) and step 2 (segmentation) on one or more papers.

Examples (run from the repository folder):
  # one-time: build the MycoBank name index from data/excel/Mycobank.xlsx (~2-3 min)
  python src/06_run_steps_1_2.py --build-mycobank-index

  # one paper
  python src/06_run_steps_1_2.py --pdf "studies_in_mycology/Vol84Art2_New-Talaromyces-species-from-indoor-environments-in-C_2016_Studies-in-Mycolo.pdf"

  # a whole folder
  python src/06_run_steps_1_2.py --pdf studies_in_mycology

Output (default folder: output/):
  output/<paper>/clean_text.txt   step 1 result: clean lines, **bold**, _italic_, page/column, font size
  output/<paper>/sections.json    step 2 result: every species section with kind, name status, target,
                                  and its figures
  output/<paper>/figures/         species images: fig20_p30_Neosartorya coreana.jpg (--all-figures: every figure)
  output/<paper>/figures.json     per figure: number, page, file, caption, species attached
  output/figures_summary.tsv      one row per figure, all papers
  output/sections_summary.tsv     one row per species section, all papers
  output/run_stats.json           per paper: status, counts, seconds

  # output 
  python src/06_run_steps_1_2.py --pdf sim59 --out output_sim59
"""
import argparse
import collections
import json
import os
import re
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from extraction.figures import extract_figures, link_sections, save_species_images
from extraction.layout import clean_lines, file_fingerprint, has_text_layer, pdf_lines, write_debug_text
from extraction.names import NameIndex, build_mycobank_index
from extraction.segment import classify, find_sections
from extraction.text import join_lines, line_text

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "data"


def run_paper(pdf, names, out_dir, find_tables=False, figures=True, dpi=150, all_figures=False):
    t0 = time.time()
    stem = re.sub(r"\.pdf$", "", os.path.basename(pdf), flags=re.I)
    lines = pdf_lines(pdf, find_tables=find_tables)
    if not has_text_layer(lines):
        return [], [], {"paper": stem, "status": "no_text_layer (needs OCR)", "seconds": round(time.time() - t0, 2)}
    clean, body = clean_lines(lines)
    paper_dir = out_dir / stem
    paper_dir.mkdir(parents=True, exist_ok=True)
    write_debug_text(clean, body, paper_dir / "clean_text.txt")
    sections = []
    for s in find_sections(clean, body, names):
        rec = classify(s, names)
        rec["body_text"] = join_lines([line_text(r) for r in s["body"]])
        rec["source"] = os.path.basename(pdf)
        sections.append(rec)
    figs = []
    if figures:
        figs = extract_figures(pdf, lines, clean, names, {s["species"] for s in sections})
        save_species_images(pdf, figs, sections, paper_dir / "figures", dpi=dpi, all_figures=all_figures)
        link_sections(sections, figs)
        for f in figs:
            f["source"] = os.path.basename(pdf)
        with open(paper_dir / "figures.json", "w", encoding="utf-8") as f:
            json.dump(figs, f, ensure_ascii=False, indent=1)
    with open(paper_dir / "sections.json", "w", encoding="utf-8") as f:
        json.dump(sections, f, ensure_ascii=False, indent=1)
    kinds = collections.Counter(s["kind"] for s in sections)
    targets = collections.Counter(s["target"] for s in sections if s["kind"] == "treatment")
    return sections, figs, {"paper": stem, "status": "ok", "body_font": body, "lines": len(lines),
                      "clean_lines": len(clean), "sections": len(sections),
                      "treatments": kinds["treatment"], "name_entries": kinds["name_entry"],
                      "treatments_for_mycobase": targets["mycobase"], "treatments_raw_only": targets["raw_only"],
                      "figures_saved": sum(1 for f in figs if f["file"]),
                      "treatments_with_figure": sum(1 for s in sections if s["kind"] == "treatment" and s.get("figures")),
                      "seconds": round(time.time() - t0, 2)}


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--pdf", action="append", help="PDF file or folder (repeatable)")
    ap.add_argument("--out", default=str(ROOT / "output"))
    ap.add_argument("--species", default=str(DATA / "species_description.json"),
                    help="MycoBase file; its 'is accepted: Yes' records = accepted list (Visagie et al. 2025)")
    ap.add_argument("--mycobank-xlsx", default=str(DATA / "excel" / "Mycobank.xlsx"))
    ap.add_argument("--mycobank-cache", default=str(DATA / "cache" / "mycobank_index.tsv.gz"))
    ap.add_argument("--build-mycobank-index", action="store_true", help="(re)build the MycoBank name index")
    ap.add_argument("--tables", action="store_true", help="also remove ruled tables (slower)")
    ap.add_argument("--no-figures", action="store_true", help="do not save figure images")
    ap.add_argument("--all-figures", action="store_true",
                    help="save every figure (trees, comparison plates ...), not only the species images")
    ap.add_argument("--fig-dpi", type=int, default=150, help="resolution of saved figures (default 150)")
    a = ap.parse_args()

    if a.build_mycobank_index:
        build_mycobank_index(a.mycobank_xlsx, a.mycobank_cache)
        if not a.pdf:
            return
    if not a.pdf:
        ap.error("give --pdf (file or folder), or --build-mycobank-index")

    names = NameIndex(a.species, a.mycobank_cache)
    print(f"accepted species: {len(names.accepted):,}   MycoBank index: "
          f"{'loaded, ' + format(len(names.by_num), ',') + ' names' if names.has_mycobank else 'not found (run --build-mycobank-index)'}")

    pdfs = []
    for p in a.pdf:
        if os.path.isdir(p):
            pdfs += sorted(os.path.join(p, f) for f in os.listdir(p) if f.lower().endswith(".pdf"))
        else:
            pdfs.append(p)

    out_dir = Path(a.out)
    out_dir.mkdir(parents=True, exist_ok=True)
    stats, rows, fig_rows, seen = [], [], [], {}
    for pdf in pdfs:
        fp = file_fingerprint(pdf)
        if fp in seen:
            stats.append({"paper": os.path.basename(pdf), "status": "duplicate", "duplicate_of": seen[fp]})
            print(f"{os.path.basename(pdf)[:60]:60s} duplicate of {seen[fp]}")
            continue
        seen[fp] = os.path.basename(pdf)
        try:
            sections, figs, st = run_paper(pdf, names, out_dir, a.tables, not a.no_figures, a.fig_dpi,
                                              a.all_figures)
        except Exception as e:                      # one broken PDF must not stop a batch
            st, sections, figs = {"paper": os.path.basename(pdf), "status": f"error: {e}"}, [], []
        stats.append(st)
        if st["status"] != "ok":
            print(f"{st['paper'][:60]:60s} {st['status']}")
            continue
        print(f"{st['paper'][:60]:60s} treatments={st['treatments']:4d} "
              f"(MycoBase {st['treatments_for_mycobase']}, raw only {st['treatments_raw_only']})  "
              f"name entries={st['name_entries']}  species images={st['figures_saved']} "
              f"(treatments with a figure {st['treatments_with_figure']})  {st['seconds']}s")
        for f in figs:
            fig_rows.append([f["source"], f["figure"], f["part"], f["page"], f["kind"], f["file"] or "",
                             f["main_species"] or "",
                             "; ".join(x["name"] for x in f["species_in_caption"]),
                             "; ".join(sorted({x["accepted_name"] for x in f["species_in_caption"] if x["accepted_name"]})),
                             len(f["species_in_labels"]), f["caption"][:150]])
        for s in sections:
            rows.append([s["source"], s["species"], s["kind"], s["name"]["status"], s["name"]["accepted_name"],
                         s["target"], f"{s['pages'][0]}-{s['pages'][1]}", s["mycobank_in_paper"],
                         s["name"]["mycobank_number"], len(s["labels_found"]), s["nomenclature"][:150]])

    with open(out_dir / "run_stats.json", "w", encoding="utf-8") as f:
        json.dump(stats, f, ensure_ascii=False, indent=1)
    with open(out_dir / "sections_summary.tsv", "w", encoding="utf-8") as f:
        f.write("source\tspecies_in_paper\tkind\tname_status\taccepted_name\ttarget\tpages\t"
                "mycobank_in_paper\tmycobank_in_index\tn_labels\tnomenclature\n")
        for r in rows:
            f.write("\t".join(str(x).replace("\t", " ") for x in r) + "\n")
    with open(out_dir / "figures_summary.tsv", "w", encoding="utf-8") as f:
        f.write("source\tfigure\tpart\tpage\tkind\tfile\tmain_species\tspecies_in_caption\t"
                "accepted_names\tn_species_in_labels\tcaption\n")
        for r in fig_rows:
            f.write("\t".join(str(x).replace("\t", " ") for x in r) + "\n")
    print(f"\n{len(rows)} sections from {sum(1 for s in stats if s['status'] == 'ok')} papers -> {out_dir}")


if __name__ == "__main__":
    main()
