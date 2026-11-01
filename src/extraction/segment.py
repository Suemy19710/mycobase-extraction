"""Step 2 - Segmentation: find where each species section starts and ends.

A line starts a species section (a "heading") when all of these hold:
  * it begins with a bold "Genus epithet"
  * its font is larger than the body text, OR a nomenclatural cue follows
    (MycoBank / MB number / sp. nov. / comb. nov. / Fig. n / citation with a year)
  * the genus is a known genus (accepted list or MycoBank), OR a naming cue is present
    (sp. nov. / MycoBank / MB number / citation with a year - "Fig. n" alone is not enough here)
  * it is not a whole-line bold sub-heading ("Phylogenetic analysis") or a bold label ("Type:")
A section ends at the next heading or at a major heading (DISCUSSION, REFERENCES, ...).
If the paper has a TAXONOMY heading, only the part after it is searched.

Each section is then classified:
  kind      treatment   - has description fields (Etymology, Typus, Micromorphology, ...)
            name_entry  - only a name + citation (+ type), e.g. accepted-species lists
  name      resolved with names.NameIndex: accepted / synonym / not_accepted / unknown
  target    mycobase    - accepted or synonym of an accepted species (goes on to MycoBase)
            raw_only    - everything else (kept in the raw output, not in MycoBase)
"""
import re

from .text import (canonical_label, fix_chars, join_lines, lead_spans, line_text, norm_ws,
                   standalone_label, starts_with_label)

END_HEADINGS = re.compile(r"^(DISCUSSION|ACKNOWLEDG|REFERENCES|CONCLUSION|SUPPLEMENTARY|APPENDIX|"
                          r"Discussion|Acknowledg|References|Conclusion)")
TAXONOMY_HEADINGS = re.compile(r"(TAXONOMY|Taxonomy|SPECIES DESCRIPTIONS|Species descriptions|TAXONOMIC PART)")
NON_EPITHETS = {"section", "sect", "subgenus", "subg", "series", "ser", "spp", "sp", "species", "and",
                "et", "group", "clade", "complex", "gen", "nov", "is", "are", "was", "has", "in", "the",
                "at", "on", "of", "for", "by", "with", "from", "to", "rate", "rates", "test", "tests", "novelties"}
BINOMIAL = re.compile(r"^([A-Z][a-z]+)\s+([a-z][a-z\-]+)\b")
CITATION_CUE = re.compile(r"MycoBank|Mycobank|\bMB\s?\d{4,}|\[MB|\b(sp|comb|nom|stat)\.\s*nov\.|\bnom\.\s*inval|"
                          r"\bFigs?\.\s*\d|:\s*\d+[\d\s–-]*\.\s*(1[7-9]|20)\d\d")
# the same cues without "Fig. n": strong enough on their own when the genus is not known
# ("Growth at different temperatures ... (Fig. 5)" is a methods heading, not a species)
NAME_CUE = re.compile(r"MycoBank|Mycobank|\bMB\s?\d{4,}|\[MB|\b(sp|comb|nom|stat)\.\s*nov\.|\bnom\.\s*inval|"
                      r":\s*\d+[\d\s–-]*\.\s*(1[7-9]|20)\d\d")
DESCRIPTIVE_FIELDS = {"Description", "Micromorphology", "Macromorphology", "Colony characters", "Colony diam",
                      "Diagnosis", "Distinguishing characters", "Etymology", "Extrolites", "Notes",
                      "Similar species", "Additional materials examined", "Typus", "Molecular markers"}


def heading_name(r, body, is_genus, next_lines=()):
    """Return 'Genus epithet' if line r is a species heading, else None."""
    sp = lead_spans(r)
    # a first letter set apart in another font ("A" + "spergillus clavatonanicus", bold) counts as bold
    first_letter = len(sp) > 1 and len(sp[0]["t"].strip()) == 1 and not sp[0]["b"] and sp[1]["b"]
    if not sp or not (sp[0]["b"] or first_letter):
        return None
    bold, rest = "", ""
    for k, s in enumerate(r["sp"]):
        if s["b"] or not s["t"].strip() or (first_letter and s is sp[0]):
            bold += s["t"]
        else:
            rest = "".join(x["t"] for x in r["sp"][k:])
            break
    m = BINOMIAL.match(norm_ws(fix_chars(bold)))       # "aurantiacoﬂavus" -> "aurantiacoflavus"
    if not m or m.group(2) in NON_EPITHETS:
        return None
    if ":" in rest[:3]:
        return None                                   # bold label like "Aspergillus sp.: ..."
    context = line_text(r) + " " + " ".join(line_text(x) for x in next_lines)
    cue = bool(CITATION_CUE.search(context))
    larger = sp[0]["s"] >= body + 0.4
    if not (is_genus(m.group(1)) or NAME_CUE.search(context)):
        return None                                   # unknown genus needs a real naming cue
    if not (larger or cue):
        return None
    if not rest.strip() and not cue:
        return None                                   # whole-line bold sub-heading
    return f"{m.group(1)} {m.group(2)}"


def genus_heading(r, is_genus, next_lines=()):
    """'Ovatospora X. Wei Wang, Samson & Crous, gen. nov. MycoBank MB818850' - a genus treatment.
    It is not a species, but it ends the species section before it (its Etymology, Type species
    and description belong to the genus)."""
    sp = lead_spans(r)
    if not sp or not sp[0]["b"]:
        return False
    word = norm_ws(fix_chars(sp[0]["t"]))
    if not re.fullmatch(r"[A-Z][a-z]{2,}", word):
        return False
    if len(sp) > 1 and sp[1]["b"] and re.match(r"\s*[a-z]", sp[1]["t"]):
        return False                                  # bold epithet follows: a species heading
    t = norm_ws(fix_chars(line_text(r)))
    if ":" in t[len(word):len(word) + 3]:
        return False                                  # a label ("Notes:")
    context = t + " " + " ".join(line_text(x) for x in next_lines)
    if re.search(r"\bgen\.\s*nov\.", context):
        return True
    rest = t[len(word):].strip()
    return bool(is_genus(word) and NAME_CUE.search(context) and re.match(r"(\(|[A-Z][a-z]*\.?\s|[A-Z]\.)", rest))


def _belongs_to_heading(r, cur, body):
    """Is line r (before any body text) still part of the heading's name citation?"""
    if cur["body"] or len(cur["head"]) >= 4:
        return False
    t = norm_ws(line_text(r))
    lab = starts_with_label(r)
    if lab and canonical_label(lab):
        return False                                  # a field label starts the body
    if re.match(r"^(≡|=|\?\s*=)", t):
        return False                                  # synonym lines belong to the body
    head_size = cur["head"][0]["sp"][0]["s"]
    sp = lead_spans(r)
    same_large_font = bool(sp) and sp[0]["s"] >= body + 0.4 and abs(sp[0]["s"] - head_size) < 0.3
    head_has_cue = bool(CITATION_CUE.search(" ".join(line_text(x) for x in cur["head"])))
    line_is_citation = bool(CITATION_CUE.search(t)) and len(t) < 200
    # e.g. "Talaromyces aerius A.J. Chen, Frisvad & Samson, sp. nov." + "MycoBank MB817398. Fig. 6."
    return same_large_font or not head_has_cue or line_is_citation


def find_sections(clean, body, names):
    """Split clean lines (from layout.clean_lines) into species sections."""
    start = 0
    for k, r in enumerate(clean):
        sp = lead_spans(r)
        if sp and sp[0]["b"] and TAXONOMY_HEADINGS.fullmatch(norm_ws(line_text(r))):
            start = k
            break
    sections, cur = [], None
    for k in range(start, len(clean)):
        r = clean[k]
        t = norm_ws(line_text(r))
        sp = lead_spans(r)
        big_bold = bool(sp) and sp[0]["b"] and sp[0]["s"] >= body + 1.4
        if cur and END_HEADINGS.match(t) and (big_bold or t.isupper()):
            sections.append(cur)
            cur = None
            continue
        if cur and genus_heading(r, names.is_genus, clean[k + 1:k + 3]):
            sections.append(cur)                      # a genus treatment starts: species section ends
            cur = None
            continue
        name = heading_name(r, body, names.is_genus, clean[k + 1:k + 3])
        if name:
            if cur:
                sections.append(cur)
            cur = {"name": name, "head": [r], "body": [], "pages": [r["p"], r["p"]]}
            continue
        if cur is None:
            continue
        if _belongs_to_heading(r, cur, body):
            cur["head"].append(r)
        elif big_bold and not starts_with_label(r):
            sections.append(cur)                      # a new (sub)section heading ends this one
            cur = None
        else:
            cur["body"].append(r)
        if cur:
            cur["pages"][1] = r["p"]
    if cur:
        sections.append(cur)
    return [s for s in sections if s["body"]]


def classify(section, names):
    """Add nomenclature text, kind, name resolution and target to a section."""
    labels = []
    for r in section["body"]:
        lab = starts_with_label(r) or standalone_label(r)
        if lab:
            labels.append(lab)
    fields = [canonical_label(l) for l in labels]
    n_desc = sum(1 for f in fields if f in DESCRIPTIVE_FIELDS)
    body_chars = sum(len(line_text(r)) for r in section["body"])
    if (n_desc >= 1 and len(labels) >= 2) or (not labels and body_chars >= 600):
        kind = "treatment"
    else:
        kind = "name_entry"
    res = names.resolve(section["name"])
    mb = re.search(r"MycoBank\s*(?:no\.?\s*)?(?:MB)?\s*(\d{4,7})|\[MB\s*(\d{4,7})\]|\bMB\s?(\d{5,7})",
                   join_lines([line_text(r) for r in section["head"]]))
    return {
        "species": section["name"],
        "nomenclature": join_lines([line_text(r) for r in section["head"]]),
        "mycobank_in_paper": next((g for g in mb.groups() if g), "") if mb else "",
        "pages": [section["pages"][0] + 1, section["pages"][1] + 1],
        "kind": kind,
        "labels_found": labels,
        "body_lines": len(section["body"]),
        "name": res,
        "target": "mycobase" if res["status"] in ("accepted", "synonym") else "raw_only",
    }
