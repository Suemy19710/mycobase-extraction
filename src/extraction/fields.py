"""Step 3 - Field extraction: split each species section into MycoBase fields.

A species section (from step 2) is a heading plus body lines such as

    Etymology: Latin, aerius refers to its origin, isolated from indoor air.
    Typus: China, Beijing, indoor air, May 2014 (holotype CBS H-22506, culture ex-type CBS 140611 ...).
    ITS barcode: KU866647. (Alternative markers: BenA = KU866835; CaM = KU866731; RPB2 = KU866991).
    Colony diam, 7 d (mm): CYA 17-18; CYA 30 °C 20-22; ...

Each line that starts with a field label opens a new field; the following lines belong to it until
the next label. The label is mapped to a MycoBase column with config/label_dictionary.json
("ITS barcode" -> "Molecular markers", "Diagnostic features" -> "Diagnosis", ...).

Which labels count:
  * a styled run-in label: bold/italic text + colon ("Etymology:"), or a known label + full stop
  * a short fully bold line ("Description", "Morphological characteristics")
  * a known label in plain text at the start of a paragraph ("In: Talaromyces section ...")
  * unknown labels only when they recur in at least 25 % of the paper's treatments (min. 3), so a
    styled word inside one description does not split it
Lines "≡ Genus epithet ..." / "= Genus epithet ..." right under the heading become "Synonyms".
Unlabelled text right under the heading (older papers: Latin diagnosis + description) is kept as
"Description".

Labels that are not in the dictionary are kept under their own name and listed as unmapped, so the
dictionary can be extended without code changes.
"""
import collections
import re

from .text import (LABEL_RE, canonical_label, fix_chars, join_lines, line_text, norm_ws,
                   standalone_label, starts_with_label)

# MycoBase description columns, in the order they are written to species_fields.csv
FIELD_ORDER = ["Synonyms", "Basionym", "Typus", "Ex-type", "Other no. of the type", "Herb", "Etymology",
               "Diagnosis", "Description", "Molecular markers", "Colony diam", "Colony characters",
               "Macromorphology", "Micromorphology", "Cardinal temperatures", "Physiology", "Extrolites",
               "Chemical markers", "Important mycotoxins", "Distinguishing characters", "Similar species",
               "Habitats and distribution", "Distribution", "Ecology and habitats", "Pathogenicity",
               "Typical cultures", "Additional materials examined", "Classification", "Morphs", "Anamorph",
               "Teleomorph", "Notes", "References"]

SYNONYM_LINE = re.compile(r"^\s*(≡|=|\?\s*=)\s*[A-Z][a-z]+\.?\s+[a-z]")     # not "= NRRL 4993 = ATCC ..."
TYPE_IN_TEXT = re.compile(r"((?:Holotype|Neotype|Lectotype|Epitype|Typus)\b[^.]{0,80}?here designated"
                          r"(?:[^.]|\.(?=\d))*\.)")      # "... designated as CBS 112.55T (dried culture) ..."


def _plain_known_label(r, prev):
    """'In: Talaromyces section ...' in plain text: a dictionary label that starts a paragraph."""
    if prev is not None and prev["p"] == r["p"] and prev.get("blk") == r.get("blk"):
        return None                                   # not the first line of a paragraph
    t = fix_chars(line_text(r)).lstrip()
    m = LABEL_RE.match(t)
    if m and len(m.group(1).split()) <= 4 and canonical_label(m.group(1)) and not re.search(r"\d{4}", m.group(1)):
        return norm_ws(m.group(1))
    return None


def learn_labels(sections):
    """Labels of one paper: dictionary labels always count, others must recur across treatments.
    Returns (set of accepted labels in lower case, Counter label -> number of treatments)."""
    treatments = [s for s in sections if s.get("kind", "treatment") == "treatment"]
    c = collections.Counter()
    for s in treatments:
        seen = set()
        for r in s["body"]:
            lab = starts_with_label(r) or standalone_label(r)
            if lab:
                seen.add(norm_ws(lab).lower())
        c.update(seen)
    n = len(treatments)
    need = max(3, int(0.25 * n + 0.5)) if n >= 4 else 2
    learned = {l for l, k in c.items() if k >= need} | {l for l in c if canonical_label(l)}
    return learned, c


def split_fields(body, learned):
    """Split the body lines of one section into fields.

    Returns a list of {"field": MycoBase column or None, "label": label as printed, "text": ...}
    in reading order (a label can occur twice, e.g. two "Notes").
    """
    parts = []
    cur = {"field": "_preamble", "label": "", "lines": []}

    def flush():
        if cur["lines"] or cur["field"] != "_preamble":
            parts.append({"field": cur["field"], "label": cur["label"], "text": join_lines(cur["lines"])})

    prev = None
    for r in body:
        full = fix_chars(line_text(r)).strip()
        lab = starts_with_label(r)
        if not (lab and lab.lower() in learned):
            lab = _plain_known_label(r, prev)
        if lab:
            flush()
            rest = full[full.find(lab) + len(lab):] if lab in full else LABEL_RE.sub("", full, count=1)
            cur = {"field": canonical_label(lab), "label": lab, "lines": [re.sub(r"^\s*[:.]\s*", "", rest)]}
        elif cur["field"] in ("_preamble", "Synonyms") and SYNONYM_LINE.match(full):
            if cur["field"] != "Synonyms":
                flush()
                cur = {"field": "Synonyms", "label": "≡ / =", "lines": []}
            cur["lines"].append(re.sub(r"^\s*(≡|=|\?\s*=)\s*", "", full) + ";")
        elif standalone_label(r) and standalone_label(r).lower() in learned:
            flush()
            sl = standalone_label(r)
            cur = {"field": canonical_label(sl), "label": sl, "lines": []}
        else:
            cur["lines"].append(full)
        prev = r
    flush()

    out = []
    for p in parts:
        if p["field"] == "_preamble":
            if len(p["text"]) <= 40:
                continue                              # a stray line, not a description
            out.append({"field": "Description", "label": "(unlabelled text under the heading)",
                        "text": p["text"]})
        else:
            out.append(p)
    # older papers: "Holotype of X, here designated as CBS 112.55" inside the unlabelled text
    if not any(p["field"] == "Typus" for p in out):
        for p in out:
            m = TYPE_IN_TEXT.search(p["text"]) if p["label"].startswith("(unlabelled") else None
            if m:
                out.append({"field": "Typus", "label": "(from unlabelled text)", "text": m.group(1)})
                break
    return out


def fields_dict(parts):
    """Merge the parts into {MycoBase column: text}; unmapped labels go under 'Other: <label>'.
    Also returns {column: label(s) as printed} for provenance."""
    fields, labels = collections.OrderedDict(), collections.OrderedDict()
    for p in parts:
        key = p["field"] or f"Other: {p['label']}"
        if key in fields and p["text"]:
            fields[key] = (fields[key] + " " + p["text"]).strip()
            if p["label"] not in labels[key].split(" | "):
                labels[key] += " | " + p["label"]
        else:
            fields[key] = p["text"]
            labels[key] = p["label"]
    return fields, labels


def extract_fields(sections):
    """Add 'fields', 'field_labels' and 'unmapped_labels' to every section of one paper (in place).
    `sections` are step-2 sections (with 'body' lines); returns the paper's label counts."""
    learned, counts = learn_labels(sections)
    for s in sections:
        parts = split_fields(s["body"], learned)
        fields, labels = fields_dict(parts)
        s["fields"], s["field_labels"] = fields, labels
        s["unmapped_labels"] = [labels[k] for k in fields if k.startswith("Other: ")]
    return counts
