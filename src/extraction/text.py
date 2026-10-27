"""Small text and style helpers shared by all steps.

A "line" is a dict produced by layout.pdf_lines():
  {"p": page, "blk": block no., "x0","y0","x1","y1": position, "W": page width,
   "sp": [{"t": text, "s": font size, "b": bold 0/1, "i": italic 0/1}, ...],
   "rot": rotated text 0/1, "tbl": inside a ruled table 0/1}
"""
import json
import re
from pathlib import Path

CONFIG_DIR = Path(__file__).resolve().parents[2] / "config"

# characters that PDFs use for ligatures / special spaces -> plain text
_CHAR_FIXES = {
    "ﬁ": "fi", "ﬂ": "fl", "ﬀ": "ff", "ﬃ": "ffi", "ﬄ": "ffl",
    "­": "",            # soft hyphen
    " ": " ", " ": " ", " ": " ", " ": " ", " ": " ",
}


def fix_chars(s):
    for a, b in _CHAR_FIXES.items():
        s = s.replace(a, b)
    return s


def norm_ws(s):
    return re.sub(r"\s+", " ", s).strip()


def line_text(r):
    return fix_chars("".join(s["t"] for s in r["sp"]))


def lead_spans(r):
    """Spans that contain visible text."""
    return [s for s in r["sp"] if s["t"].strip()]


def line_size(r):
    """Most common font size on the line."""
    sz = [s["s"] for s in r["sp"] if s["t"].strip()]
    return max(set(sz), key=sz.count) if sz else 0


def join_lines(texts):
    """Join wrapped lines into one paragraph and undo end-of-line hyphenation.

    "pro-" + "duces"  -> "produces"   (letter before hyphen, lower-case after)
    "DTO 355-" + "I1" -> "DTO 355-I1" (keep the hyphen, no space)
    """
    out = ""
    for t in texts:
        t = t.strip()
        if not t:
            continue
        if not out:
            out = t
        elif out.endswith("-") and len(out) > 1:
            if out[-2].isalpha() and t[:1].islower():
                out = out[:-1] + t
            else:
                out = out + t
        else:
            out = out + " " + t
    return norm_ws(out)


# --------------------------------------------------------------------------------------
# Field labels ("Etymology:", "Typus:", ...). The vocabulary lives in config/label_dictionary.json
# --------------------------------------------------------------------------------------
def _load_labels():
    path = CONFIG_DIR / "label_dictionary.json"
    with open(path, encoding="utf-8") as f:
        return json.load(f)["labels"]


LABELS = _load_labels()


def canonical_label(label):
    """Map a paper heading to a MycoBase field name, or None if the heading is unknown."""
    l = norm_ws(label).lower().rstrip(":.").strip()
    if l.startswith("colony diam"):
        return "Colony diam"
    if l in LABELS:
        return LABELS[l]
    head = l.split(",")[0].split("(")[0].strip()      # "culture characteristics, 25 °C, 7 d"
    return LABELS.get(head)


LABEL_RE = re.compile(r"^([^:]{2,70}?):\s*")
LABEL_DOT_RE = re.compile(r"^([A-Z][^:.]{2,40}?)\.\s+")


def starts_with_label(r):
    """If the line starts with a bold/italic run-in label, return the label text.

    Accepted forms:  "Etymology: ..."  (styled text + colon)
                     "Etymology. ..."  (only for labels in the dictionary)
                     "Extrolites asperfuran ..." (known bold label, colon forgotten)
    """
    sp = lead_spans(r)
    if not sp or not (sp[0]["b"] or sp[0]["i"]):
        return None
    t = fix_chars("".join(s["t"] for s in r["sp"])).lstrip()
    m = LABEL_RE.match(t)
    if not m:
        m = LABEL_DOT_RE.match(t)
        if not m or not canonical_label(m.group(1)):
            lead = ""
            for s in r["sp"]:
                if s["b"] or s["i"]:
                    lead += s["t"]
                else:
                    break
            lead = norm_ws(fix_chars(lead)).rstrip(":. ")
            if lead and canonical_label(lead) and len(norm_ws(t)) > len(lead) + 1:
                return lead
            return None
    label = norm_ws(m.group(1))
    styled = norm_ws(fix_chars("".join(s["t"] for s in r["sp"] if (s["b"] or s["i"]))))
    if len(styled) < 0.4 * len(label.replace(" ", "")):
        return None                       # mostly plain text: not a label
    if re.search(r"\d{4}", label):
        return None                       # contains a year: a citation, not a label
    return label


def standalone_label(r):
    """A short, fully bold line without a colon, e.g. 'Morphological characteristics'."""
    sp = lead_spans(r)
    if sp and all(s["b"] for s in sp):
        t = norm_ws(line_text(r))
        if 3 <= len(t) <= 40 and ":" not in t and not re.search(r"\d", t):
            return t
    return None
