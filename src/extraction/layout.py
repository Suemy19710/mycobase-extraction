"""Step 1 - Layout reconstruction.

Turns a PDF into clean lines in reading order, keeping each line's font size, bold and italic.

    lines = pdf_lines("paper.pdf")            # every text line, with style and position
    clean, body = clean_lines(lines)          # page clutter removed, reading order fixed

What clean_lines() does:
  * finds the body font size (the most common size in the paper)
  * removes running headers/footers (text repeated in the top/bottom margins of many pages)
    and page numbers - only in the margins, so numbers inside the text are kept
  * removes figure and table captions ("Fig. 3", "Table 2") and small print (tables, footnotes),
    but keeps small-print label paragraphs ("Additional materials examined: ...") and synonym
    lines ("≡ ...", "= ...") under a heading
    (the figures themselves are not lost: figures.py saves each one as an image with its species)
  * removes rotated text (landscape tables) and, optionally, ruled tables
  * orders two-column pages: left column, then right column
  * merges fragments of one justified line back into one line
"""
import collections
import hashlib
import os
import re

from .text import fix_chars, line_size, line_text, norm_ws, starts_with_label

# margins (PDF points) where running headers, footers and page numbers live
TOP_MARGIN = 60
BOTTOM_MARGIN = 45


def pdf_lines(path, find_tables=False):
    """Read every text line of a PDF with its spans' font size, bold and italic."""
    import pymupdf

    doc = pymupdf.open(path)
    out = []
    for pno, page in enumerate(doc):
        W = page.rect.width
        tables = []
        if find_tables:                      # slower: ~0.1 s per page
            try:
                tables = [pymupdf.Rect(t.bbox) for t in page.find_tables(strategy="lines").tables]
            except Exception:
                tables = []
        d = page.get_text("dict", flags=pymupdf.TEXT_PRESERVE_LIGATURES)
        for b in d["blocks"]:
            if b.get("type") != 0:           # images
                continue
            for ln in b["lines"]:
                spans = [{"t": s["text"], "s": round(s["size"], 1),
                          "b": int(bool(s["flags"] & 16) or ".B" in s["font"] or "Bold" in s["font"]),
                          "i": int(bool(s["flags"] & 2) or "Italic" in s["font"] or ".I" in s["font"])}
                         for s in ln["spans"] if s["text"]]
                if not spans:
                    continue
                x0, y0, x1, y1 = ln["bbox"]
                r = pymupdf.Rect(ln["bbox"])
                in_table = any((r & t).get_area() > 0.6 * max(r.get_area(), 1e-6) for t in tables)
                out.append({"p": pno, "blk": b["number"], "x0": round(x0, 1), "y0": round(y0, 1),
                            "x1": round(x1, 1), "y1": round(y1, 1), "W": round(W), "sp": spans,
                            "tbl": int(in_table), "rot": int(abs(ln["dir"][1]) > 0.1)})
    return out


def has_text_layer(lines, min_chars=500):
    """False for scanned PDFs (images only) - those need OCR first."""
    return sum(len(s["t"].strip()) for r in lines for s in r["sp"]) >= min_chars


def body_size(lines):
    """Font size of the body text = the size that covers the most characters."""
    c = collections.Counter()
    for r in lines:
        for s in r["sp"]:
            c[s["s"]] += len(s["t"].strip())
    return c.most_common(1)[0][0]


def clean_lines(lines):
    """Remove page clutter and return (clean lines in reading order, body font size)."""
    B = body_size(lines)
    small = B - 1.2
    maxy = max(r["y1"] for r in lines)

    def in_margin(r):
        return r["y0"] < TOP_MARGIN or r["y1"] > maxy - BOTTOM_MARGIN

    # running headers/footers: same text (digits ignored) in the margins of many pages
    repeated = collections.Counter(re.sub(r"\d+", "#", norm_ws(line_text(r))) for r in lines if in_margin(r))
    n_pages = len({r["p"] for r in lines}) or 1
    running = {k for k, v in repeated.items() if v >= max(3, n_pages * 0.15)}

    blocks = collections.defaultdict(list)
    for r in lines:
        blocks[(r["p"], r.get("blk", 0))].append(r)

    keep = []
    for rs in blocks.values():
        first = norm_ws(line_text(rs[0]))
        if re.match(r"^(Fig\.|Figs\.|Figure|FIG\.|Table|TABLE)\s*\d", first):
            continue                                            # caption block
        first_small = line_size(rs[0]) < small
        block_is_label = bool(starts_with_label(rs[0]))
        for r in rs:
            t = norm_ws(line_text(r))
            if not t or r.get("tbl") or r.get("rot"):
                continue
            if line_size(r) < small:
                synonym_line = not first_small and re.match(r"^[≡=?]|^\? ?=", t)
                if not (block_is_label or synonym_line):
                    continue                                    # table cell, footnote, caption text
            if in_margin(r) and re.sub(r"\d+", "#", t) in running:
                continue                                        # running header / footer
            if in_margin(r) and re.fullmatch(r"[\d\s–-]+", t):
                continue                                        # page number
            if (r["y0"] < 45 or r["y1"] > maxy - 20) and len(t) < 90:
                continue                                        # extreme margin (journal name, URL)
            keep.append(r)

    # reading order: page, column (left/right), top to bottom
    for r in keep:
        r["col"] = 0 if r["x0"] < r["W"] * 0.47 else 1
    keep.sort(key=lambda r: (r["p"], r["col"], round(r["y0"]), r["x0"]))

    # justified text is sometimes split into several pieces on the same baseline: merge them
    merged = []
    for r in keep:
        if merged:
            m = merged[-1]
            if (m["p"] == r["p"] and m["col"] == r["col"] and abs(m["y0"] - r["y0"]) < 2.5
                    and r["x0"] > m["x0"]):
                m["sp"] = m["sp"] + [{"t": " ", "s": r["sp"][0]["s"], "b": 0, "i": 0}] + r["sp"]
                m["x1"] = max(m["x1"], r["x1"])
                continue
        merged.append(dict(r, sp=list(r["sp"])))
    return merged, B


def styled_text(r):
    """Line text with **bold** and _italic_ marks - for the debug file."""
    out = ""
    for s in r["sp"]:
        t = fix_chars(s["t"])
        if t.strip():
            if s["b"]:
                t = f"**{t}**"
            if s["i"]:
                t = f"_{t}_"
        out += t
    return out


def write_debug_text(clean, body, path):
    """Write the clean lines to a text file to check layout reconstruction by eye.

    Each line:  p<page> c<column> <size>pt | text with **bold** and _italic_
    """
    with open(path, "w", encoding="utf-8") as f:
        f.write(f"# body font size: {body} pt   lines: {len(clean)}\n")
        last = None
        for r in clean:
            key = (r["p"], r["col"])
            if key != last:
                f.write(f"\n=== page {r['p'] + 1}, {'left' if r['col'] == 0 else 'right'} column ===\n")
                last = key
            f.write(f"p{r['p'] + 1} c{r['col']} {line_size(r):>4}pt | {styled_text(r)}\n")


def file_fingerprint(path):
    """Identify the same paper saved under another name or as another PDF build:
    page count + text of the first two pages. Falls back to the file bytes."""
    h = hashlib.sha1()
    try:
        import pymupdf
        doc = pymupdf.open(path)
        txt = "".join(doc[i].get_text() for i in range(min(2, len(doc))))
        txt = re.sub(r"\W+", "", fix_chars(txt)).lower()
        if len(txt) > 500:
            h.update(txt[:6000].encode("utf-8"))
            return f"text-{len(doc)}-{h.hexdigest()}"
    except Exception:
        pass
    size = os.path.getsize(path)
    with open(path, "rb") as f:
        h.update(f.read(1 << 20))
        if size > 1 << 20:
            f.seek(size - (1 << 20))
            h.update(f.read(1 << 20))
    return f"bytes-{size}-{h.hexdigest()}"
