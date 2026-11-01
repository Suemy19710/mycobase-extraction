"""Step 4 - Value parsing: turn field text into the exact values of the MycoBase backbone columns.

    Typus: China, Beijing, indoor air, May 2014, isolated by B.D. Sun (holotype CBS H-22506,
           culture ex-type CBS 140611 = CGMCC3. 18197 = DTO 317-C7).
    ->  TYPUS     "CBS H-22506 (holotype)"
        EX_TYPUS  "CBS 140611 = CGMCC 3.18197 = DTO 317-C7"

    ITS barcode: KU866647. (Alternative markers: BenA = KU866835; CaM = KU866731; RPB2 = KU866991).
    ->  ITS GenBank ID "KU866647", BenA GenBank ID "KU866835", CaM ..., RPB2 ...

    Talaromyces aerius A.J. Chen, Frisvad & Samson, sp. nov. MycoBank MB817398. Fig. 6.   (on page 124)
    ->  MYCOBANK "817398", status "sp. nov.", YEAR "2016",
        Literature "A.J. Chen, Frisvad & Samson, Stud. Mycol. 84: 124. 2016."   (paper citation + page)

Columns produced (MycoBase names): MYCOBANK, Literature, YEAR, TYPUS, EX_TYPUS, ITS/BenA/CaM/RPB2
GenBank ID, section; plus status, type_kind, Basionym and colony_diam (medium -> mm) for later use.
A value that cannot be found is left empty - never guessed.
"""
import collections
import re

from .text import fix_chars, line_text, norm_ws

# ------------------------------------------------------------------ paper citation
JOURNALS = {"studies in mycology": "Stud. Mycol.", "persoonia": "Persoonia", "ima fungus": "IMA Fungus",
            "fungal diversity": "Fungal Diversity", "mycologia": "Mycologia", "mycological progress": "Mycol. Prog.",
            "mycokeys": "MycoKeys", "fungal systematics and evolution": "Fungal Syst. Evol.",
            "antonie van leeuwenhoek": "Antonie van Leeuwenhoek", "journal of fungi": "J. Fungi"}
JOURNAL_RE = re.compile(r"(" + "|".join(re.escape(j) for j in JOURNALS) + r")\s*(\d{1,4})\s*[:,]\s*(\d{1,4})\s*[–-]\s*(\d{1,4})",
                        re.I)


def paper_citation(lines, pdf_name=""):
    """Journal, volume, first page, year and the PDF-page -> printed-page offset of one paper.

    The offset comes from the page numbers printed in the margins (most common difference), so the
    printed page of a heading on PDF page 6 is found as 124 in Stud. Mycol. 84: 119-158."""
    first = " ".join(fix_chars(line_text(r)) for r in lines if r["p"] <= 1)
    cit = {"journal": "", "volume": "", "first_page": None, "year": "", "page_offset": None}
    m = JOURNAL_RE.search(first)
    if m:
        cit.update(journal=JOURNALS[m.group(1).lower()], volume=m.group(2), first_page=int(m.group(3)))
    y = re.search(r"(?:Copyright|©)\D{0,10}\b(19\d\d|20\d\d)\b", first)   # "Copyright © 2016, CBS-KNAW"
    if not y and m:
        y = re.search(r"\b(19\d\d|20\d\d)\b", first[m.end():m.end() + 40])
    cit["year"] = y.group(1) if y else ""
    maxy = max((r["y1"] for r in lines), default=0)
    offsets = collections.Counter()
    for r in lines:
        if r["y0"] < 60 or r["y1"] > maxy - 45:
            t = norm_ws(line_text(r))
            if re.fullmatch(r"\d{1,4}", t):
                offsets[int(t) - (r["p"] + 1)] += 1
    if offsets:
        off, n = offsets.most_common(1)[0]
        if n >= 3:
            cit["page_offset"] = off
    if cit["page_offset"] is None and cit["first_page"]:
        cit["page_offset"] = cit["first_page"] - 1
    return cit


# ------------------------------------------------------------------ helpers
ACCESSION = r"[A-Z]{1,2}_?\d{5,8}(?:\.\d)?"
STATUS_RE = re.compile(r"\b(?:sp|comb|nom|stat|gen)\.\s*nov\b\.?|\bnom\.\s*inval\b\.?|\bnom\.\s*illeg\b\.?")
TYPE_KINDS = ("holotype", "neotype", "lectotype", "epitype", "isotype", "isoneotype", "syntype")
# a culture collection or herbarium number: CBS 140611, CBS H-22506, CGMCC 3.18197, DTO 317-C7, IMI 061455ii,
# NRRL A-3676, IBT 23439, Thom 4640.5, LSHB BB.356
STRAIN = re.compile(r"\b([A-Z][A-Za-z]{1,7})\s?((?:[A-Z]{1,2}-?\s?)?\d[\d.\-/]*[A-Za-z]{0,3}\d*)")


MEDIA_NAMES = r"CYA|MEA|YES|OA|CREA|DG18|CY20S|M40Y|M60Y|CYAS|MEA10S|CZ|CZA|G25N|PDA"


def clean_strain(s):
    """'CGMCC3. 18197' -> 'CGMCC 3.18197';  'CBS140611' -> 'CBS 140611';  'IMI 061455ii.' -> 'IMI 061455ii'"""
    s = norm_ws(s).rstrip(".,;)")
    s = re.sub(r"(\d)T$", r"\1", s)                             # "NRRL 35723T" (T = ex-type mark)
    s = re.sub(r"(\d)\.\s+(\d)", r"\1.\2", s)                    # broken at a line end
    s = re.sub(r"(\d)\s*-\s*([A-Z0-9])", r"\1-\2", s)
    m = re.match(r"([A-Z][A-Za-z]{1,7})\s?(.*)$", s)
    return f"{m.group(1)} {m.group(2)}".strip() if m else s


def strains(text):
    """Culture numbers in '... CBS 140611 = CGMCC3. 18197 = DTO 317-C7' (split at '=' or ';')."""
    out = []
    text = re.sub(r"(\d)\.\s+(\d)", r"\1.\2", text)              # "CGMCC3. 18197" broken at a line end
    for part in re.split(r"\s*[=;]\s*", text):
        part = part.strip(" .,()")
        m = STRAIN.search(part)
        if m and not re.fullmatch(ACCESSION, m.group(1) + m.group(2)):
            s = clean_strain(m.group(0))
            if s not in out and not re.match(r"(Fig|Figs|ITS|BenA|CaM|RPB2|Table|" + MEDIA_NAMES + r")\b", s):
                out.append(s)
    return out


# ------------------------------------------------------------------ the parsers
def parse_mycobank(nomenclature):
    m = re.search(r"Myco-?\s?Bank\s*(?:no\.?\s*)?(?:MB)?\s*(\d{4,7})|\[MB\s*(\d{4,7})\]|\bMB\s?(\d{5,7})", nomenclature)
    return next((g for g in m.groups() if g), "") if m else ""


def parse_literature(species, nomenclature, page, cit):
    """Authors + place of publication, as MycoBase writes it."""
    t = norm_ws(fix_chars(nomenclature))
    t = re.sub(r"^" + re.escape(species) + r"\s*", "", t)
    t = re.sub(r"\s*\[(?:anamorph|teleomorph)[^\]]*\]", "", t)     # "[anamorph: A. fischerianus ...]"
    t = re.split(r"\s*(?:\[?\s*Myco-?\s?Bank|\[MB|\bMB\s?\d|\(?Figs?\.?\s*\d|–\s*MycoBank|≡|"
                 r"\bBasionym\b)", t)[0]
    t = t.lstrip(" ,.;").rstrip(" ,;[(–-")
    status = STATUS_RE.search(t)
    authors = t[:status.start()].strip(" ,") if status else t
    has_place = bool(re.search(r":\s*\d+", t) or re.search(r"\b(1[7-9]\d\d|20\d\d)\b", t))
    # "Mycologia 100: 787. 2008", "Gen. Aspergillus: 506. 1965.", "Manual of the aspergilli: 153. 1929."
    if has_place:
        lit = STATUS_RE.sub("", t).replace(" ,", ",").strip(" ,")
        lit = re.sub(r",\s*,", ",", lit)
    elif status and authors and cit.get("journal") and cit.get("volume") and page:
        lit = f"{authors}, {cit['journal']} {cit['volume']}: {page}. {cit['year']}".strip()   # this paper
    else:
        lit = ""
    if lit and not lit.endswith("."):
        lit += "."
    years = re.findall(r"\b(1[7-9]\d\d|20\d\d)\b", lit)
    return lit, (years[-1] if years else ""), (norm_ws(status.group(0)) if status else "")


def parse_type(fields):
    """TYPUS (specimen + kind) and EX_TYPUS (culture numbers) from Typus / Type / Ex-type / Other no. fields."""
    typus = fields.get("Typus", "")
    ex_field = fields.get("Ex-type", "")
    other = fields.get("Other no. of the type", "")
    kind, specimen, ex = "", "", []

    # "(holotype CBS H-22506, culture ex-type CBS 140611 = ...)"  /  "IMI 86806. Culture ex-type: CBS 589.65 = ..."
    m = re.search(r"\b(" + "|".join(TYPE_KINDS) + r")\b\s*(?:of [^,;:]{0,40})?,?\s*(?:designated[^,;:]{0,40})?[:\s]*"
                  r"(?:here designated as\s*)?([A-Z][A-Za-z]{1,7}\s?(?:[A-Z]{1,2}-?\s?)?\d[\w.\-/]*)", typus, re.I)
    if m:
        kind, specimen = m.group(1).lower(), clean_strain(m.group(2))
        if kind.startswith("iso"):                              # "FMR 5588; isotype IMI 370867"
            first_ = strains(typus[:m.start()].split(".")[0])
            if first_:
                kind, specimen = "", first_[0]
    mx = re.search(r"(?:culture\s+)?ex-?\s?(?:epi|neo|holo|iso)?type[:\s]*(.+?)(?:\)|\.\s+[A-Z]|$)", typus, re.I)
    if mx:
        ex = strains(mx.group(1))
    if not specimen:
        before = re.split(r"(?:culture\s+)?ex-?\s?(?:epi|neo|holo|iso)?type", typus, flags=re.I)[0]
        ss = strains(before.split(",")[0]) if before.strip() else []
        if ss:
            specimen = ss[0]                                        # "IMI 86806. Culture ex-type: ..."
    if ex_field:
        ex = ex or strains(ex_field)
    if not ex and specimen and not mx and not kind:
        # older papers: "Type: CBS 544.65, from canned apples" + "Other no. of the type: ATCC 1020; DSM 3700"
        if re.match(r"(CBS|NRRL|IBT|DTO|ATCC|IMI|CCF)\b", specimen) and not re.search(r"\bH-", specimen):
            ex = [specimen] + [s for s in strains(other) if s != specimen]
    typus_value = f"{specimen} ({kind})" if specimen and kind else specimen
    return typus_value, kind, " = ".join(ex)


def parse_barcodes(text):
    out = {}
    for gene, pat in (("ITS", r"ITS(?:\s*barcode)?\s*[:=]?\s*(" + ACCESSION + ")"),
                      ("BenA", r"(?:BenA|benA|β-tubulin|beta-tubulin|tub2)\s*[:=]?\s*(" + ACCESSION + ")"),
                      ("CaM", r"(?:CaM|cmd|[Cc]almodulin)\s*[:=]?\s*(" + ACCESSION + ")"),
                      ("RPB2", r"(?:RPB2|rpb2)\s*[:=]?\s*(" + ACCESSION + ")")):
        m = re.search(pat, text)
        if m:
            out[gene] = m.group(1).split(".")[0]
    if "ITS" not in out:
        m = re.match(r"\s*(" + ACCESSION + r")\b", text)            # "ITS barcode: KU866647." -> field = "KU866647. ..."
        if m:
            out["ITS"] = m.group(1).split(".")[0]
    return out


MEDIA = r"(?:CYA|MEA|YES|OA|CREA|DG18|CY20S|M40Y|M60Y|CYAS|MEA10S|CZ|CZA|G25N|PDA|M\d+Y)"


def parse_colony_diam(text):
    """'CYA 17-18; CYA 30 °C 20-22; CYA 37 °C No growth; MEA25: 66-80 mm' -> {medium/temperature: value}"""
    out = collections.OrderedDict()
    for med, temp, val in re.findall(r"(" + MEDIA + r")\s*(\d{2})?\s*(?:°\s?C)?\s*(?:\(\d+\s*d\))?\s*:?\s*"
                                     r"(>?\d+(?:\s*[–-]\s*>?\d+)?(?:\s*mm)?|[Nn]o growth|weak growth|microcolonies)",
                                     text):
        key = f"{med} {temp} °C" if temp else med
        out.setdefault(key, norm_ws(val).replace(" mm", ""))
    return dict(out)


def parse_section(fields):
    m = re.search(r"\bsect(?:ion|\.)\s+([A-Z][a-z\-]+)", fields.get("Classification", ""))
    return m.group(1) if m else ""


def parse_values(section, cit):
    """All step-4 values of one species section (step-2 record with step-3 'fields')."""
    f = section.get("fields", {})
    pdf_page = section["pages"][0]
    page = pdf_page + cit["page_offset"] if cit.get("page_offset") is not None else None
    lit, year, status = parse_literature(section["species"], section["nomenclature"], page, cit)
    typus, kind, ex = parse_type(f)
    bc = parse_barcodes(f.get("Molecular markers", ""))
    return collections.OrderedDict([
        ("MYCOBANK", parse_mycobank(section["nomenclature"])),
        ("Literature", lit), ("YEAR", year), ("status", status),
        ("TYPUS", typus), ("type_kind", kind), ("EX_TYPUS", ex),
        ("ITS GenBank ID", bc.get("ITS", "")), ("BenA GenBank ID", bc.get("BenA", "")),
        ("CaM GenBank ID", bc.get("CaM", "")), ("RPB2 GenBank ID", bc.get("RPB2", "")),
        ("section", parse_section(f)), ("Basionym", norm_ws(f.get("Basionym", ""))),
        ("printed_page", page), ("colony_diam", parse_colony_diam(f.get("Colony diam", ""))),
    ])


VALUE_COLUMNS = ["MYCOBANK", "Literature", "YEAR", "status", "TYPUS", "type_kind", "EX_TYPUS", "ITS GenBank ID",
                 "BenA GenBank ID", "CaM GenBank ID", "RPB2 GenBank ID", "section", "Basionym", "printed_page"]
