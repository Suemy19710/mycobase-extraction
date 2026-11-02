"""Figures: save every figure of a paper as an image and attach species names to it.

Step 1 removes figure captions and figure text (tree labels, table cells) from the clean text.
This module keeps the figures themselves:

    figs = extract_figures(pdf, lines, clean, names, section_species)   # find every figure
    save_species_images(pdf, figs, sections, out_dir / "figures")       # save the species plates
    link_sections(sections, figs)          # each species section gets its figures

Only species images are saved: plates about one species, named after the species as printed in
the paper, e.g.  fig20_p30_Neosartorya coreana.jpg . Phylogenetic trees, maps, comparison plates of
many species and uncaptioned graphics are listed in figures.json (with the reason) but not saved,
unless save_species_images(..., all_figures=True) / --all-figures is used.

How a figure is found
  * a caption is a text block starting with "Fig. 6." / "Figs 3" / "Figure 2" / "FIG. 1"
  * the figure is the graphics (embedded images and vector drawings, e.g. phylogenetic trees)
    and small label text between the caption and the nearest prose paragraph above it
    (or below it, when nothing is above - captions on top)
  * the area is rendered from the page to an image (JPEG for photo plates, PNG for drawings),
    so vector trees are kept too
  * graphics with no caption on the page (a tree continued from the previous page) are saved
    as "uncaptioned" and pointed at the nearest caption

How species are attached
  caption   binomials in the caption ("Fig. 6. Morphological characters of Talaromyces aerius")
  heading   the species heading cites the figure ("... sp. nov. MycoBank MB817398. Fig. 6.")
  label     tree labels inside the figure that name a species of this paper ("T. aerius CBS 140611T");
            only when the labels are text (a tree pasted in as a picture needs OCR)
Tables are not saved here: pages with a "Table n" caption are left to step 3.
Every name is resolved with names.NameIndex, like the species sections.
"""
import collections
import re

from .text import fix_chars, line_size, line_text, norm_ws

CAPTION_RE = re.compile(r"^(?:Figs?\.?|Figure|FIG\.?|FIGURE)\s*(\d+)\s*([A-Z](?![a-z]))?")
TABLE_RE = re.compile(r"^(?:Table|TABLE)\s*\d+")
CONTINUED_RE = re.compile(r"\(\s*[Cc]ontinued\s*\)|\(\s*[Cc]ont\.?\s*\)")
PHYLO_RE = re.compile(r"phylogen|tree|cladogram|maximum likelihood|bayesian|neighbou?r.joining|"
                      r"parsimony|concatenated", re.I)
BINOMIAL_ANY = re.compile(r"\b([A-Z][a-z]{2,}|[A-Z]\.)\s?([a-z][a-z\-]{2,})\b")
NOT_EPITHET = {"section", "sect", "subgenus", "series", "species", "and", "the", "sequences", "sequence",
               "strains", "strain", "isolates", "isolate", "colonies", "from", "with", "data", "based",
               "showing", "phylogeny", "tree", "clade", "complex", "group", "spp", "sp", "nov", "comb",
               "conidiophores", "conidia", "ascospores", "ascomata", "cleistothecia", "sclerotia", "after",
               "incubated", "grown", "were", "are", "was", "for", "of", "in", "on", "at", "obverse", "reverse"}
TOP, BOTTOM = 45, 30          # page margins (points) ignored when collecting graphics
PAD = 4                       # points of white space kept around a figure


# ------------------------------------------------------------------ page geometry helpers
def _area(b):
    return max(0.0, b[2] - b[0]) * max(0.0, b[3] - b[1])


def _union(boxes):
    return (min(b[0] for b in boxes), min(b[1] for b in boxes), max(b[2] for b in boxes), max(b[3] for b in boxes))


def _overlap_x(a, b):
    return min(a[2], b[2]) - max(a[0], b[0]) > 0


def _graphics(page):
    """Image and drawing boxes on a page (no page background, no margin logos)."""
    W, H = page.rect.width, page.rect.height
    out = []
    for im in page.get_image_info():
        b = tuple(im["bbox"])
        if b[2] - b[0] < 15 or b[3] - b[1] < 15 or b[1] > H - BOTTOM - 10 or b[3] < TOP:
            continue
        out.append(("img", b))
    for d in page.get_drawings():
        b = tuple(d["rect"])
        if _area(b) > 0.5 * W * H or b[1] > H - BOTTOM or b[3] < TOP:
            continue
        out.append(("drw", b))
    return out


# ------------------------------------------------------------------ species names in figure text
def _species_in(text, names, paper_species, require_known=True):
    """Binomials in text, abbreviations ("T. aerius") expanded; kept if known to the paper or MycoBank."""
    text = norm_ws(fix_chars(text))
    found, last_genus = [], None
    by_epithet = collections.defaultdict(set)
    for sp in paper_species:
        g, e = sp.split(" ", 1)
        by_epithet[e].add(g)
    for m in BINOMIAL_ANY.finditer(text):
        g, e = m.group(1), m.group(2)
        if e in NOT_EPITHET:
            continue
        if g.endswith("."):
            cands = [x for x in by_epithet.get(e, ()) if x[0] == g[0]]
            if last_genus and last_genus[0] == g[0]:
                g = last_genus
            elif cands:
                g = sorted(cands)[0]
            else:
                continue
        elif not names.is_genus(g):
            continue
        else:
            last_genus = g
        name = f"{g} {e}"
        if name in found:
            continue
        if require_known and name not in paper_species and names.resolve(name)["status"] == "unknown":
            continue
        found.append(name)
    return found


# ------------------------------------------------------------------ main entry
def extract_figures(pdf_path, lines, clean, names, paper_species=()):
    """Find the figures of one paper; return a list of figure records (see module doc).
    Nothing is written: save_species_images() renders the ones to keep."""
    import pymupdf

    paper_species = set(paper_species)
    doc = pymupdf.open(pdf_path)

    by_page = collections.defaultdict(list)
    for r in lines:
        by_page[r["p"]].append(r)
    clean_keys = {(r["p"], r["x0"], r["y0"]) for r in clean}

    figures = []
    for pno, page in enumerate(doc):
        rows = by_page.get(pno, [])
        W, H = page.rect.width, page.rect.height

        # caption blocks
        blocks = collections.defaultdict(list)
        for r in rows:
            blocks[r["blk"]].append(r)
        captions = []
        for blk, rs in blocks.items():
            first = norm_ws(fix_chars(line_text(rs[0])))
            m = CAPTION_RE.match(first)
            if m:
                text = norm_ws(fix_chars(" ".join(line_text(r) for r in rs)))
                text = re.sub(r"(\w)- (\w)", r"\1\2", text)
                if len(text) < 25 and not CONTINUED_RE.search(text):
                    continue                 # a title inside a tree ("Fig. 2. cmd"), not a caption
                box = _union([(r["x0"], r["y0"], r["x1"], r["y1"]) for r in rs])
                captions.append({"num": int(m.group(1)), "part": m.group(2) or "", "text": text, "box": box,
                                 "blk": blk, "continued": bool(CONTINUED_RE.search(text[:40]))})
        caption_blks = {c["blk"] for c in captions}

        # prose = blocks of kept body text with at least one wide line (paragraphs, not labels)
        prose = []
        for blk, rs in blocks.items():
            if blk in caption_blks:
                continue
            kept = [r for r in rs if (r["p"], r["x0"], r["y0"]) in clean_keys]
            if kept and any(r["x1"] - r["x0"] >= 0.3 * W for r in kept):
                prose += [(r["x0"], r["y0"], r["x1"], r["y1"]) for r in rs]
        prose_set = set(prose)
        labels = [r for r in rows if r["blk"] not in caption_blks
                  and (r["x0"], r["y0"], r["x1"], r["y1"]) not in prose_set
                  and TOP < r["y0"] and r["y1"] < H - BOTTOM]
        graphics = _graphics(page)
        if not graphics and not captions:
            continue

        taken = []
        for c in sorted(captions, key=lambda c: c["box"][1]):
            cb = c["box"]
            others = [o["box"] for o in captions if o is not c]
            # region above the caption
            top = max([b[3] for b in prose if b[3] <= cb[1] + 1 and _overlap_x(b, cb)] +
                      [b[3] for b in others if b[3] <= cb[1] + 1] + [TOP])
            region = (0, top, W, cb[1])
            inside = [g for g in graphics if g[1][1] >= top - 2 and g[1][3] <= cb[1] + 2]
            if not inside:                                   # caption above the figure
                bottom = min([b[1] for b in prose if b[1] >= cb[3] - 1 and _overlap_x(b, cb)] +
                             [b[1] for b in others if b[1] >= cb[3] - 1] + [H - BOTTOM])
                region = (0, cb[3], W, bottom)
                inside = [g for g in graphics if g[1][1] >= cb[3] - 2 and g[1][3] <= bottom + 2]
            if not inside or sum(_area(g[1]) for g in inside) < 0.01 * W * H and \
                    not any(g[0] == "img" for g in inside):
                c["box_fig"] = None
                figures.append(_record(c, pno, None, False, "", names, paper_species, []))
                continue
            lab = [r for r in labels if r["y0"] >= region[1] - 2 and r["y1"] <= region[3] + 2]
            box = _union([g[1] for g in inside] + [(r["x0"], r["y0"], r["x1"], r["y1"]) for r in lab])
            taken.append(box)
            photo = sum(_area(g[1]) for g in inside if g[0] == "img") > 0.5 * _area(box)
            label_text = " ".join(line_text(r) for r in lab)
            figures.append(_record(c, pno, box, photo, label_text, names, paper_species,
                                   [g for g in inside]))

        # graphics on the page that no caption claimed (e.g. first page of a two-page tree)
        rest = [g for g in graphics
                if not any(g[1][0] >= t[0] - 2 and g[1][1] >= t[1] - 2 and g[1][2] <= t[2] + 2
                           and g[1][3] <= t[3] + 2 for t in taken)
                and not any(g[1][1] >= b[1] - 1 and g[1][3] <= b[3] + 1 and g[1][0] >= b[0] - 1
                            and g[1][2] <= b[2] + 1 for b in prose)
                and not (g[0] == "drw" and max(g[1][2] - g[1][0], g[1][3] - g[1][1]) < 9)]   # glyphs
        has_table = any(TABLE_RE.match(norm_ws(fix_chars(line_text(r)))) for r in rows)
        if has_table:
            rest = []                        # tables are not figures (step 3 reads tables)
        n_img = sum(1 for g in rest if g[0] == "img")
        n_vert = sum(1 for g in rest if g[0] == "drw" and g[1][3] - g[1][1] > 3 and g[1][2] - g[1][0] < 2)
        if rest and (n_img >= 1 and sum(_area(g[1]) for g in rest if g[0] == "img") > 0.05 * W * H
                     or n_vert >= 10):
            box = _union([g[1] for g in rest])
            n_text = sum(1 for r in rows if (r["p"], r["x0"], r["y0"]) in clean_keys and r["y0"] >= box[1]
                         and r["y1"] <= box[3] and r["x0"] >= box[0] - 2 and r["x1"] <= box[2] + 2)
            n_wide = sum(1 for r in rows if r["y0"] >= box[1] and r["y1"] <= box[3]
                         and r["x1"] - r["x0"] >= 0.4 * W)
            if n_text > 3 or n_wide > 8:
                continue                     # a text page with some rules or symbols, not a figure
            lab = [r for r in labels if r["y0"] >= box[1] - 2 and r["y1"] <= box[3] + 2]
            box = _union([box] + [(r["x0"], r["y0"], r["x1"], r["y1"]) for r in lab])
            nxt = _next_caption_number(doc, pno)
            c = {"num": nxt, "part": "", "text": "", "continued": False, "uncaptioned": True}
            photo = sum(_area(g[1]) for g in rest if g[0] == "img") > 0.5 * _area(box)
            figures.append(_record(c, pno, box, photo, " ".join(line_text(r) for r in lab), names,
                                   paper_species, rest))
    return _tidy(figures)


def _tidy(figures):
    """Join a caption without graphics to the uncaptioned figure next to it, and let
    "(Continued)" parts inherit kind and species from the first part."""
    for c in [f for f in figures if not f["bbox"] and not f["uncaptioned"]]:
        near = [u for u in figures if u["uncaptioned"] and u["bbox"] and abs(u["page"] - c["page"]) <= 1
                and u["figure"] in (c["figure"], None)]
        if near:
            u = near[0]
            u.update({k: c[k] for k in ("figure", "part", "caption", "kind", "main_species",
                                        "species_in_caption")})
            u["uncaptioned"] = False
            u["note"] = f"caption on page {c['page']}"
            c["drop"] = True
    figures = [f for f in figures if not f.get("drop")]
    first = {}
    for f in figures:
        if f["continued"] and f["figure"] in first:
            m = first[f["figure"]]
            f["kind"], f["main_species"] = m["kind"], m["main_species"]
            f["species_in_caption"] = m["species_in_caption"]
            f["note"] = f"continued from page {m['page']}"
        elif not f["uncaptioned"]:
            first.setdefault(f["figure"], f)
    return figures


def _next_caption_number(doc, pno):
    for q in range(pno, min(pno + 3, len(doc))):
        for b in doc[q].get_text("blocks"):
            m = CAPTION_RE.match(norm_ws(fix_chars(b[4])))
            if m:
                return int(m.group(1))
    return None


def _close(a, b):
    """Same name, or one spelling slip apart (same genus, epithets 85% alike)."""
    import difflib
    ga, _, ea = a.partition(" ")
    gb, _, eb = b.partition(" ")
    return a == b or (ga == gb and difflib.SequenceMatcher(None, ea, eb).ratio() >= 0.85)


BAD_FILENAME_CHARS = re.compile(r'[<>:"/\\|?*\x00-\x1f]')


def save_species_images(pdf_path, figures, sections, out_dir, dpi=150, all_figures=False):
    """Render the species images of one paper and set "file" on their figure records.

    A figure is a species image when it is a plate (photographs, not a tree or drawing) about one
    species: the caption starts with or names only that species ("Fig. 20. Neosartorya coreana. ..."),
    or exactly one species heading cites the figure ("... MycoBank MB817398. Fig. 6.").
    File name: fig<number>_p<page>_<species as printed in the paper>.jpg
    Every other figure gets "file": null and "skipped": the reason. all_figures=True saves them too.
    """
    import pymupdf

    cited_by = collections.defaultdict(list)
    for s in sections:
        for n in figure_numbers(s.get("nomenclature", "")):
            cited_by[n].append(s["species"])
    out_dir.mkdir(parents=True, exist_ok=True)          # every paper gets a figures/ folder, even if empty
    doc = pymupdf.open(pdf_path)
    used = collections.Counter()
    saved = 0
    for f in figures:
        f["file"], f["skipped"] = None, ""
        species = f["main_species"]
        citing = set(cited_by.get(f["figure"], []))
        if f["kind"] == "plate" and len(citing) == 1 and (not species or _close(species, next(iter(citing)))):
            # one species heading cites this plate: use its spelling (the caption may have a typo,
            # e.g. caption "A. kerveii", heading "A. keveii"), or its name when the caption has none
            species = next(iter(citing))
            f["main_species"] = species
        if not f["bbox"]:
            f["skipped"] = "no graphics found for this caption"
        elif f["kind"] != "plate" and not all_figures:
            f["skipped"] = {"phylogeny": "phylogenetic tree", "uncaptioned": "no caption (tree, map or table part)",
                            "drawing": "drawing / diagram"}.get(f["kind"], f["kind"])
        elif not species and not all_figures:
            f["skipped"] = "plate of several species (comparison)"
        if f["skipped"]:
            continue
        page = doc[f["page"] - 1]
        b = f["bbox"]
        clip = pymupdf.Rect(b[0] - PAD, b[1] - PAD, b[2] + PAD, b[3] + PAD) & page.rect
        pix = page.get_pixmap(clip=clip, dpi=dpi)
        num = f"{f['figure']:02d}" if isinstance(f["figure"], int) else "xx"
        base = "uncaptioned" if f["uncaptioned"] else f"fig{num}{f['part']}"
        base += f"_p{f['page']}"
        if species:
            base += "_" + BAD_FILENAME_CHARS.sub("", species)
        used[base] += 1
        if used[base] > 1:
            base += f"_{used[base]}"
        ext = "jpg" if f.get("photo", True) else "png"
        data = pix.tobytes("jpg", jpg_quality=88) if ext == "jpg" else pix.tobytes("png")
        with open(out_dir / f"{base}.{ext}", "wb") as fh:   # overwrite in place (some synced folders forbid deleting)
            fh.write(data)
        f["file"] = f"figures/{base}.{ext}"
        saved += 1
    return saved


LEAD_NAME = re.compile(r"^(?:Figs?\.?|Figure|FIG\.?|FIGURE)\s*\d+\s*[A-Z]?\s*[.:]?\s*"
                       r"(?:Morphological characters of\s+|Morphology of\s+)?([A-Z][a-z]+ [a-z][a-z\-]+)\b")


def _record(c, pno, box, photo, label_text, names, paper_species, inside):
    cap_species = _species_in(c["text"], names, paper_species) if c["text"] else []
    lead = LEAD_NAME.match(c["text"]) if c["text"] else None
    lead = lead.group(1) if lead and names.is_genus(lead.group(1).split()[0]) \
        and lead.group(1).split()[1] not in NOT_EPITHET else None
    if lead and lead not in cap_species:
        cap_species.insert(0, lead)
    lab_species = [s for s in _species_in(label_text, names, paper_species, require_known=True)
                   if s in paper_species] if label_text else []
    if c.get("uncaptioned"):
        kind = "uncaptioned"
    elif PHYLO_RE.search(c["text"][:200]):
        kind = "phylogeny"
    elif any(g[0] == "img" for g in inside):
        kind = "plate"
    else:
        kind = "drawing"
    # the plate is about one species when the caption starts with it or names only it
    main = (lead or (cap_species[0] if len(cap_species) == 1 else None)) if kind == "plate" else None
    return {
        "figure": c["num"],
        "part": c["part"],
        "continued": c["continued"],
        "uncaptioned": bool(c.get("uncaptioned")),
        "note": (f"no caption on this page; probably part of Fig. {c['num']}" if c.get("uncaptioned") and c["num"]
                 else ""),
        "page": pno + 1,
        "file": None,                         # set by save_species_images()
        "bbox": [round(v, 1) for v in box] if box else None,
        "photo": bool(photo),
        "kind": kind,
        "caption": c["text"],
        "main_species": main,
        "species_in_caption": [_resolved(s, names) for s in cap_species],
        "species_in_labels": [_resolved(s, names) for s in lab_species],
    }


def _resolved(name, names):
    r = names.resolve(name)
    return {"name": name, "status": r["status"], "accepted_name": r["accepted_name"]}


# ------------------------------------------------------------------ link figures to sections
FIG_REF = re.compile(r"\bFigs?\.?\s*((?:\d+\s*[A-Z]?(?:\s*[–-]\s*[A-Z])?\s*(?:[,;&]|and|[–-])?\s*)+)")


def figure_numbers(text):
    """'Fig. 6.' -> [6];  'Figs 6, 7' -> [6, 7];  'Figs 6–8' -> [6, 7, 8];  'Fig. 6A–C' -> [6]"""
    nums = []
    for m in FIG_REF.finditer(text.replace("Figs ", "Figs. ")):
        part = re.sub(r"(\d)\s*[A-Z](\s*[–-]\s*[A-Z])?", r"\1", m.group(1))
        for a, b in re.findall(r"(\d+)(?:\s*[–-]\s*(\d+))?", part):
            a = int(a)
            nums += list(range(a, int(b) + 1)) if b and 0 < int(b) - a < 20 else [a]
    return sorted(set(nums))


def link_sections(sections, figures):
    """Add to every section:
         figures       saved species images of this species (cited in its heading, or the caption is about it)
         in_trees      trees and other figures that show this species (usually not saved as images)
    """
    for s in sections:
        cited = set(figure_numbers(s["nomenclature"]))
        plates, trees = [], []
        for f in figures:
            about = f["main_species"] == s["species"] or (
                f["kind"] != "phylogeny" and any(x["name"] == s["species"] for x in f["species_in_caption"]))
            # a heading's "Fig. 4" is not trusted when the caption of Fig. 4 names another species
            # (sim59 Art10: the headings of A. campestris and A. candidus cite each other's plate)
            other = f["main_species"] and not _close(f["main_species"], s["species"])
            is_plate = (f["figure"] in cited and f["kind"] != "phylogeny" and not f["uncaptioned"]
                        and not other) or about
            if is_plate and f["file"]:
                plates.append({"figure": f["figure"], "page": f["page"], "file": f["file"],
                               "how": "heading cites figure" if f["figure"] in cited else "named in caption"})
            elif any(x["name"] == s["species"] for x in f["species_in_labels"] + f["species_in_caption"]):
                trees.append({"figure": f["figure"], "page": f["page"], "file": f["file"], "kind": f["kind"]})
        s["figures"] = plates
        s["in_trees"] = trees
    return sections
