"""MycoBase extraction - workflow app (Streamlit).

Run from the repository folder:
    streamlit run app/review_app.py

  1  Upload & run     upload PDF papers -> steps 1-4 (06_run_steps.py), gap filling (11_fill_gaps.py)
                      and validation (12_validate.py), with progress
  2  Species found    per paper: species, name status, fields, values, species images
  3  Review           proposed MycoBase additions with confidence, reasons and the PDF page they come
                      from; approve, reject or correct each one
  4  Export           the approved additions as JSON / CSV for the merge (step 7)
  5  Species data     species_description_data = MycoBase + the new data for ACCEPTED species (only empty
                      columns are filled); everything outside MycoBase goes to raw_species.json

Every upload is a separate run in app_runs/<run name>/ (pdfs/, output/, additions/, decisions.csv).
MycoBase (data/species_description.json) and data/images are only read, never written.
"""
import csv
import datetime as dt
import hashlib
import io
import json
import os
import re
import subprocess
import sys
from pathlib import Path

import pandas as pd
import streamlit as st

ROOT = Path(__file__).resolve().parent.parent
SRC = ROOT / "src"
RUNS = ROOT / "app_runs"
PY = sys.executable

st.set_page_config(page_title="MycoBase extraction", page_icon="", layout="wide")


# ------------------------------------------------------------------ helpers
def run_dirs(run):
    base = RUNS / run
    return {"base": base, "pdfs": base / "pdfs", "out": base / "output", "add": base / "additions",
            "decisions": base / "decisions.csv"}


def list_runs():
    if not RUNS.exists():
        return []
    return sorted([p.name for p in RUNS.iterdir() if p.is_dir()], reverse=True)


def mtime(p):
    try:
        return os.path.getmtime(p)
    except OSError:
        return 0


@st.cache_data(show_spinner=False)
def load_json(path, _mt):
    with open(path, encoding="utf-8") as f:
        return json.load(f)


@st.cache_data(show_spinner=False)
def load_csv(path, _mt):
    return pd.read_csv(path, dtype=str, encoding="utf-8-sig").fillna("")


def read_json(p):
    return load_json(str(p), mtime(p)) if Path(p).exists() else None


def read_csv(p):
    return load_csv(str(p), mtime(p)) if Path(p).exists() else None


@st.cache_data(show_spinner=False)
def render_page(pdf, page, _mt, zoom=1.6):
    import pymupdf
    doc = pymupdf.open(pdf)
    if not 1 <= page <= len(doc):
        return None
    return doc[page - 1].get_pixmap(matrix=pymupdf.Matrix(zoom, zoom)).tobytes("png")


def run_script(args, log_box, progress=None, n_items=0):
    """Run one of the pipeline scripts and stream its output into the page."""
    cmd = [PY, "-u"] + [str(a) for a in args]
    lines = []
    proc = subprocess.Popen(cmd, cwd=ROOT, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True,
                            encoding="utf-8", errors="replace")
    done = 0
    for line in proc.stdout:
        lines.append(line.rstrip())
        if progress is not None and n_items and re.search(r"treatments=|needs OCR|duplicate|error:", line):
            done += 1
            progress.progress(min(done / n_items, 1.0), text=f"{done} / {n_items} papers")
        log_box.code("\n".join(lines[-25:]), language=None)
    proc.wait()
    return proc.returncode, "\n".join(lines)


def row_key(r):
    """Stable id of one proposed addition (record + column + source + value)."""
    h = hashlib.sha1(f"{r['mycobase_record']}|{r['column']}|{r['paper']}|{r['value']}".encode("utf-8")).hexdigest()
    return h[:16]


def load_decisions(path):
    if not path.exists():
        return {}
    with open(path, encoding="utf-8-sig") as f:
        return {r["key"]: r for r in csv.DictReader(f)}


def save_decision(path, key, row, decision, value):
    decisions = load_decisions(path)
    decisions[key] = {"key": key, "mycobase_record": row["mycobase_record"], "column": row["column"],
                      "decision": decision, "value": value, "paper": row["paper"], "pages": row["pages"],
                      "confidence": row.get("confidence", ""), "time": dt.datetime.now().isoformat(timespec="seconds")}
    with open(path, "w", encoding="utf-8-sig", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(next(iter(decisions.values()))))
        w.writeheader()
        w.writerows(decisions.values())


def linked_pdfs(dirs):
    """PDFs of this run that stay in their own folder on this computer (not copied)."""
    f = dirs["base"] / "linked_pdfs.json"
    if not f.exists():
        return []
    with open(f, encoding="utf-8") as fh:
        return [Path(p) for p in json.load(fh) if Path(p).exists()]


def all_pdfs(dirs):
    up = sorted(dirs["pdfs"].glob("*.pdf")) if dirs["pdfs"].exists() else []
    return up + [p for p in linked_pdfs(dirs) if p.name not in {u.name for u in up}]


PAPER_FOLDERS = ["studies_in_mycology", "sim59", "vol84", "half_studies"]   # where command-line runs read PDFs


def pdf_of(dirs, paper):
    for p in all_pdfs(dirs):
        if p.stem == paper:
            return p
    for folder in PAPER_FOLDERS:                       # a run made on the command line
        p = ROOT / folder / f"{paper}.pdf"
        if p.exists():
            return p
    return None


# hover help for the column headers (shown as a small ⓘ tooltip)
HELP = {
    "paper": "File name of the paper (without .pdf).",
    "status": "ok = read; needs OCR = scanned PDF without text (skipped); duplicate = same paper under "
              "another file name (read once); error = could not be read.",
    "species descriptions": "Species treatments found: a species heading followed by a description "
                            "(Etymology, Typus, Micromorphology ...). Name-list entries are counted separately.",
    "→ MycoBase": "Descriptions whose name is ACCEPTED in MycoBase (Visagie et al. 2025), or an old name "
                  "(synonym) whose current name in MycoBank is accepted. Only these may fill empty MycoBase "
                  "columns - after review. MycoBase data is never replaced.",
    "raw only": "Descriptions outside MycoBase's scope: the name is not on the accepted list "
                "(e.g. Colletotrichum, Chaetomium - not Eurotiales) or not in MycoBank at all. "
                "They are extracted and kept in the output, but never proposed for MycoBase.",
    "name entries": "Species only listed with name and citation (e.g. a list of accepted species or new "
                    "combinations), without a description.",
    "species images": "Plates saved as images that show one species (trees, maps and comparison plates "
                      "are not saved).",
    "seconds": "Time to process the paper.",
    "species in paper": "The name as printed in the paper.",
    "kind": "treatment = full description; name_entry = only a name and citation.",
    "name status": "accepted = on the accepted list; synonym = old name of an accepted species; "
                   "not_accepted = in MycoBank but outside the accepted list; unknown = not in MycoBank.",
    "accepted name": "The MycoBase name the species belongs to (for a synonym: the current, accepted name).",
    "target": "mycobase = may fill empty MycoBase columns (accepted or synonym); raw_only = kept in the "
              "output only.",
    "pages": "PDF pages of the species section.",
    "fields": "Number of fields found in the description (step 3).",
    "image": "✓ = a species image (plate) was saved for this species.",
}


def col_help(df):
    return {c: st.column_config.Column(help=HELP[c]) for c in df.columns if c in HELP}


CONF_ICON = {"high": "🟢 high", "medium": "🟡 medium", "low": "🔴 low"}

# ------------------------------------------------------------------ sidebar: choose a run
st.sidebar.title("MycoBase extraction")
runs = list_runs()
choice = st.sidebar.selectbox("Run", ["➕ new run"] + runs, index=0 if not runs else 1,
                              help="Each upload is kept as a separate run in app_runs/")
if choice == "➕ new run":
    default = dt.datetime.now().strftime("run_%Y-%m-%d_%H%M")
    run = st.sidebar.text_input("Name of the new run", value=default)
    run = re.sub(r"[^\w\-]", "_", run.strip()) or default
else:
    run = choice
dirs = run_dirs(run)
st.sidebar.caption(f"Folder: app_runs/{run}")
with st.sidebar.expander("How it works"):
    wf = ROOT / "data" / "illustations" / "workflow.png"
    if wf.exists():
        st.image(str(wf))
    st.markdown("MycoBase is the trusted reference: the tool only **proposes what MycoBase does not have**, "
                "and a curator approves it. `data/species_description.json` is never written.")

tab_run, tab_species, tab_review, tab_export, tab_data = st.tabs(
    ["1 · Upload & run", "2 · Species found", "3 · Review additions", "4 · Export", "5 · Species description data"])

# ------------------------------------------------------------------ 1 upload & run
with tab_run:
    st.header("Upload papers and run the pipeline")
    st.markdown("Steps: **1** layout → **2** species → **3** fields → **4** values → gap filling → "
                "**5** validation. Scanned PDFs without text are reported as *needs OCR*.")
    files = st.file_uploader("PDF papers", type=["pdf"], accept_multiple_files=True,
                             help="Up to 2 GB per file (set in .streamlit/config.toml). For very large or many "
                                  "papers, the folder option below is faster.")
    with st.expander("…or use PDFs from a folder on this computer (no upload, nothing is copied)"):
        folder = st.text_input("Folder", placeholder=r"C:\Users\...\mycobase-extraction\studies_in_mycology")
        if folder:
            fp = Path(folder.strip().strip('"'))
            found = sorted(fp.glob("*.pdf")) if fp.is_dir() else ([fp] if fp.suffix.lower() == ".pdf" and fp.exists() else [])
            if not found:
                st.warning("No PDF files found there.")
            else:
                pick = st.multiselect(f"{len(found)} PDF(s) found - choose", [p.name for p in found],
                                      default=[p.name for p in found][:5])
                if st.button("Add to this run"):
                    dirs["base"].mkdir(parents=True, exist_ok=True)
                    linked = [str(p) for p in linked_pdfs(dirs)]
                    linked += [str(p) for p in found if p.name in pick and str(p) not in linked]
                    with open(dirs["base"] / "linked_pdfs.json", "w", encoding="utf-8") as fh:
                        json.dump(linked, fh, ensure_ascii=False, indent=1)
                    st.rerun()
    have = [p.name for p in all_pdfs(dirs)]
    if have:
        st.caption(f"Already in this run: {len(have)} PDF(s) - " + ", ".join(have[:6]) + (" …" if len(have) > 6 else ""))
    c1, c2 = st.columns([1, 3])
    with_figures = c2.checkbox("Save species images", value=True)
    if c1.button("▶ Run", type="primary", disabled=not (files or have)):
        dirs["pdfs"].mkdir(parents=True, exist_ok=True)
        for f in files or []:
            (dirs["pdfs"] / f.name).write_bytes(f.getbuffer())
        pdfs = all_pdfs(dirs)
        n = len(pdfs)
        progress = st.progress(0.0, text=f"0 / {n} papers")
        log = st.empty()
        # the PDF paths go into a file: many long paths on the command line hit the Windows limit (WinError 206)
        dirs["base"].mkdir(parents=True, exist_ok=True)
        pdf_list = dirs["base"] / "pdf_list.txt"
        pdf_list.write_text("\n".join(str(p) for p in pdfs), encoding="utf-8")
        args = [SRC / "06_run_steps.py", "--pdf-list", pdf_list, "--out", dirs["out"]]
        if not with_figures:
            args.append("--no-figures")
        with st.status("Steps 1-4: reading the papers …", expanded=True) as status:
            code, _ = run_script(args, log, progress, n)
            if code != 0:
                status.update(label="Steps 1-4 failed - see the log", state="error")
                st.stop()
            status.update(label="Gap filling: what MycoBase does not have yet …")
            code, out11 = run_script([SRC / "11_fill_gaps.py", "--out", dirs["out"], "--save", dirs["add"]], log)
            if code != 0:
                status.update(label="Gap filling failed - see the log", state="error")
                st.stop()
            status.update(label="Step 5: validation …")
            code, out12 = run_script([SRC / "12_validate.py", "--out", dirs["out"], "--additions", dirs["add"]], log)
            if code != 0 and "nothing" not in out12 and "not found" not in out12:
                status.update(label="Validation failed - see the log", state="error")
                st.stop()
            status.update(label="Done - open the next tabs", state="complete", expanded=False)
        st.cache_data.clear()
        st.success("Finished. Look at **2 · Species found**, then review in **3 · Review additions**.")

    stats = read_json(dirs["out"] / "run_stats.json")
    if stats:
        st.subheader("Papers in this run")
        df = pd.DataFrame([{"paper": s.get("paper", ""), "status": s.get("status", ""),
                            "species descriptions": s.get("treatments", ""), "→ MycoBase": s.get("treatments_for_mycobase", ""),
                            "raw only": s.get("treatments_raw_only", ""), "name entries": s.get("name_entries", ""),
                            "species images": s.get("figures_saved", ""), "seconds": s.get("seconds", "")} for s in stats])
        df = df.astype(str)                       # papers that failed or need OCR have empty counts
        st.caption("Hover over a column name (ⓘ) for what it means.")
        st.dataframe(df, width="stretch", hide_index=True, column_config=col_help(df))

# ------------------------------------------------------------------ 2 species found
with tab_species:
    st.header("Species found in the papers")
    paper_dirs = sorted(p for p in dirs["out"].glob("*") if (p / "sections.json").exists()) if dirs["out"].exists() else []
    if not paper_dirs:
        st.info("No results yet - upload and run papers in tab 1.")
    else:
        paper = st.selectbox("Paper", [p.name for p in paper_dirs], key="sp_paper")
        sections = read_json(dirs["out"] / paper / "sections.json") or []
        figs = {f["file"]: f for f in (read_json(dirs["out"] / paper / "figures.json") or []) if f.get("file")}
        tbl = pd.DataFrame([{"species in paper": s["species"], "kind": s["kind"], "name status": s["name"]["status"],
                             "accepted name": s["name"]["accepted_name"], "target": s["target"],
                             "pages": f"{s['pages'][0]}-{s['pages'][1]}", "fields": len(s.get("fields", {})),
                             "image": "✓" if s.get("figures") else ""} for s in sections])
        m1, m2, m3 = st.columns(3)
        m1.metric("Species descriptions", int((tbl["kind"] == "treatment").sum()) if len(tbl) else 0)
        m2.metric("→ MycoBase (accepted / synonym)", int((tbl["target"] == "mycobase").sum()) if len(tbl) else 0)
        m3.metric("With species image", int((tbl["image"] == "✓").sum()) if len(tbl) else 0)
        st.dataframe(tbl, width="stretch", hide_index=True, column_config=col_help(tbl))
        if sections:
            sp = st.selectbox("Species", [s["species"] for s in sections], key="sp_species")
            s = next(x for x in sections if x["species"] == sp)
            left, right = st.columns([3, 2])
            with left:
                st.markdown(f"**{s['nomenclature']}**")
                st.caption(f"{s['name']['status']} · accepted name: {s['name']['accepted_name'] or '-'} · "
                           f"target: {s['target']} · pages {s['pages'][0]}-{s['pages'][1]}")
                st.markdown("**Fields (step 3)**")
                for k, v in s.get("fields", {}).items():
                    lab = s.get("field_labels", {}).get(k, k)
                    st.markdown(f"- **{k}** <span style='color:gray'>({lab})</span>: {v}", unsafe_allow_html=True)
                vals = {k: str(v) for k, v in s.get("values", {}).items() if v and k != "colony_diam"}
                if vals:
                    st.markdown("**Values (step 4)**")
                    st.table(pd.DataFrame(vals.items(), columns=["MycoBase column", "value"]))
            with right:
                for f in s.get("figures", []):
                    img = dirs["out"] / paper / f["file"]
                    if img.exists():
                        st.image(str(img), caption=(figs.get(f["file"], {}).get("caption") or f["file"])[:200])

# ------------------------------------------------------------------ 3 review
with tab_review:
    st.header("Review the proposed MycoBase additions")
    adds = read_csv(dirs["add"] / "additions_validated.csv")
    if adds is None:
        adds = read_csv(dirs["add"] / "mycobase_additions.csv")
    imgs = read_csv(dirs["add"] / "images_validated.csv")
    if imgs is None:
        imgs = read_csv(dirs["add"] / "mycobase_images.csv")
    if adds is None and imgs is None:
        st.info("No proposals yet - run papers in tab 1. (Only accepted species with empty MycoBase "
                "columns get proposals.)")
    else:
        rows = []
        if adds is not None:
            for r in adds.to_dict("records"):
                rows.append({**r, "kind": "value"})
        if imgs is not None:
            for r in imgs.to_dict("records"):
                rows.append({**r, "kind": "image", "column": "(image)", "value": r["image"], "pages": r.get("page", ""),
                             "status": "ok"})
        decisions = load_decisions(dirs["decisions"])
        for r in rows:
            r["key"] = row_key(r)
            d = decisions.get(r["key"])
            r["decision"] = d["decision"] if d else "open"
            r["confidence"] = r.get("confidence") or "medium"

        f1, f2, f3, f4 = st.columns(4)
        conf_f = f1.multiselect("Confidence", ["low", "medium", "high"], default=["low", "medium", "high"])
        dec_f = f2.multiselect("Decision", ["open", "approved", "rejected", "corrected"], default=["open"])
        rec_f = f3.selectbox("Species", ["(all)"] + sorted({r["mycobase_record"] for r in rows}), key="rv_species")
        kind_f = f4.selectbox("Kind", ["(all)", "value", "image"])
        view = [r for r in rows if r["confidence"] in conf_f and r["decision"] in dec_f
                and (rec_f == "(all)" or r["mycobase_record"] == rec_f) and (kind_f == "(all)" or r["kind"] == kind_f)]
        view.sort(key=lambda r: ({"low": 0, "medium": 1, "high": 2}[r["confidence"]], r["mycobase_record"], r["column"]))

        n_open = sum(1 for r in rows if r["decision"] == "open")
        st.caption(f"{len(rows)} proposals · {n_open} still open · showing {len(view)}")
        if view:
            vt = pd.DataFrame([{"confidence": CONF_ICON[r["confidence"]], "species": r["mycobase_record"],
                                "column": r["column"], "value": str(r["value"])[:90], "decision": r["decision"]}
                               for r in view])
            st.dataframe(vt, width="stretch", hide_index=True, height=230)
            labels = [f"{i + 1}. {r['mycobase_record']} · {r['column']} · {r['confidence']}" for i, r in enumerate(view)]
            i = st.selectbox("Open a proposal", range(len(view)), format_func=lambda k: labels[k])
            r = view[i]
            left, right = st.columns([2, 3])
            with left:
                st.subheader(f"{r['mycobase_record']} · {r['column']}")
                st.markdown(f"**Confidence:** {CONF_ICON[r['confidence']]}")
                if r.get("reasons"):
                    st.warning(r["reasons"])
                st.caption(f"from {r['paper']} · page {r['pages']} · species in paper: {r.get('species_in_paper', '')}"
                           + (f" · {r['via']}" if r.get("via") else ""))
                if r["kind"] == "image":
                    img = dirs["add"] / r["value"]
                    if img.exists():
                        st.image(str(img), caption=str(r.get("caption", ""))[:200])
                    new_value = r["value"]
                else:
                    new_value = st.text_area("Value (edit to correct)", value=str(r["value"]), height=160)
                b1, b2, b3 = st.columns(3)
                if b1.button("✓ Approve", type="primary", width="stretch"):
                    dec = "corrected" if new_value != str(r["value"]) else "approved"
                    save_decision(dirs["decisions"], r["key"], r, dec, new_value)
                    st.rerun()
                if b2.button("✗ Reject", width="stretch"):
                    save_decision(dirs["decisions"], r["key"], r, "rejected", "")
                    st.rerun()
                if b3.button("↺ Reset", width="stretch"):
                    save_decision(dirs["decisions"], r["key"], r, "open", "")
                    st.rerun()
            with right:
                pdf = pdf_of(dirs, r["paper"])
                page = int(str(r["pages"]).split("-")[0]) if str(r["pages"]).split("-")[0].isdigit() else None
                if pdf and page:
                    png = render_page(str(pdf), page, mtime(pdf))
                    if png:
                        st.image(png, caption=f"{pdf.name} - PDF page {page}", width="stretch")
                else:
                    st.info("PDF page not available for this run.")
        else:
            st.success("Nothing to show with these filters.")

# ------------------------------------------------------------------ 4 export
with tab_export:
    st.header("Export the approved additions")
    decisions = load_decisions(dirs["decisions"])
    ok = [d for d in decisions.values() if d["decision"] in ("approved", "corrected")]
    c1, c2, c3 = st.columns(3)
    c1.metric("Approved / corrected", len(ok))
    c2.metric("Rejected", sum(1 for d in decisions.values() if d["decision"] == "rejected"))
    c3.metric("Decisions saved", len(decisions))
    if ok:
        add_json, img_list = {}, []
        for d in ok:
            if d["column"] == "(image)":
                img_list.append({"mycobase_record": d["mycobase_record"], "image": d["value"], "paper": d["paper"],
                                 "page": d["pages"]})
            else:
                add_json.setdefault(d["mycobase_record"], {})[d["column"]] = d["value"]
        st.markdown("These files contain **only** what a curator approved. They are for the merge (step 7); "
                    "MycoBase itself is not changed here.")
        st.download_button("⬇ approved_additions.json", json.dumps(add_json, ensure_ascii=False, indent=1),
                           file_name="approved_additions.json", mime="application/json")
        buf = io.StringIO()
        w = csv.DictWriter(buf, fieldnames=list(ok[0]))
        w.writeheader()
        w.writerows(ok)
        st.download_button("⬇ approved_additions.csv", buf.getvalue().encode("utf-8-sig"),
                           file_name="approved_additions.csv", mime="text/csv")
        if img_list:
            st.download_button("⬇ approved_images.json", json.dumps(img_list, ensure_ascii=False, indent=1),
                               file_name="approved_images.json", mime="application/json")
        st.dataframe(pd.DataFrame(ok), width="stretch", hide_index=True)
    else:
        st.info("No approved additions yet - approve them in tab 3.")

# ------------------------------------------------------------------ 5 species description data
SPECIES_JSON = ROOT / "data" / "species_description.json"
MB_IMAGES = ROOT / "data" / "images"
MODES = ["Approved + high / medium confidence", "Approved only", "Everything not rejected"]


def is_empty(v):
    return v is None or str(v).strip() in ("", "{}", "[]", "None")


def mycobase_image(rec):
    for ext in (".jpg", ".jpeg", ".png", ".webp"):
        p = MB_IMAGES / f"{rec} Mycochat{ext}"
        if p.exists():
            return p
    return None


def new_data(dirs, db, mode):
    """The additions that go into species_description_data: only ACCEPTED records, only EMPTY columns.

    Returns ({record: {column: row}}, {record: [image row]}, [(record, column) left out because papers disagree])."""
    adds = read_csv(dirs["add"] / "additions_validated.csv")
    if adds is None:
        adds = read_csv(dirs["add"] / "mycobase_additions.csv")
    imgs = read_csv(dirs["add"] / "images_validated.csv")
    if imgs is None:
        imgs = read_csv(dirs["add"] / "mycobase_images.csv")
    decisions = load_decisions(dirs["decisions"])

    def take(r):
        d = decisions.get(row_key(r), {}).get("decision", "open")
        if d in ("approved", "corrected"):
            return True, decisions[row_key(r)]["value"] if d == "corrected" else r["value"]
        if d == "rejected" or mode == MODES[1] or r.get("status") == "conflict":
            return False, None                      # conflicts between papers need a curator's choice
        if mode == MODES[0] and (r.get("confidence") or "medium") == "low":
            return False, None
        return True, r["value"]

    def accepted(rec):
        return rec in db and str(db[rec].get("is accepted", "")).strip().lower() == "yes"

    cand = {}
    for r in (adds.to_dict("records") if adds is not None else []):
        ok, val = take(r)
        rec, col = r["mycobase_record"], r["column"]
        if ok and accepted(rec) and is_empty(db[rec].get(col)):        # never replace MycoBase data
            cand.setdefault((rec, col), []).append({**r, "value": val})
    values, disputed = {}, []
    for (rec, col), rs in sorted(cand.items()):
        if len({re.sub(r"\s+", " ", str(x["value"])).lower() for x in rs}) > 1:
            disputed.append((rec, col))
            continue
        values.setdefault(rec, {})[col] = rs[0]
    images = {}
    for r in (imgs.to_dict("records") if imgs is not None else []):
        r = {**r, "column": "(image)", "value": r["image"], "pages": r.get("page", "")}
        ok, _ = take(r)
        if ok and accepted(r["mycobase_record"]) and (dirs["add"] / r["image"]).exists():
            images.setdefault(r["mycobase_record"], []).append(r)
    return values, images, disputed


def as_text(v):
    """A cell for a CSV: dicts and lists (e.g. Molecular markers) become JSON text."""
    return (json.dumps(v, ensure_ascii=False) if v else "") if isinstance(v, (dict, list)) else v


def species_csv(data):
    """species_description_data as CSV: one row per species; the JSON key is the Species column
    (MycoBase's own "Species" column is often empty, so it is left out)."""
    cols = []
    for rec in data.values():
        for c in rec:
            if c not in cols and c != "Species":
                cols.append(c)
    df = pd.DataFrame([{"Species": k, **{c: as_text(rec.get(c, "")) for c in cols}} for k, rec in data.items()])
    return df.to_csv(index=False).encode("utf-8-sig")          # utf-8-sig: Excel shows accents correctly


def raw_csv(raw):
    """raw_species as CSV: one row per species treatment in a paper; fields and values as columns."""
    rows = []
    for sp, lst in raw.items():
        for x in lst:
            row = {"Species (as printed)": sp, "paper": x.get("paper", ""), "pages": x.get("pages", ""),
                   "name status": x.get("name_status", ""), "accepted name": x.get("accepted_name", ""),
                   "nomenclature": x.get("nomenclature", "")}
            row.update({k: as_text(v) for k, v in (x.get("values") or {}).items()})
            row.update({f"field: {k}": as_text(v) for k, v in (x.get("fields") or {}).items()})
            row["images"] = "; ".join(x.get("images") or [])
            rows.append(row)
    return pd.DataFrame(rows).to_csv(index=False).encode("utf-8-sig")


def raw_species(dirs):
    """Species descriptions outside MycoBase (not on the accepted list), grouped by the name in the paper."""
    out = {}
    for f in sorted(dirs["out"].glob("*/sections.json")) if dirs["out"].exists() else []:
        paper = f.parent.name
        for s in read_json(f) or []:
            if s["kind"] != "treatment" or s.get("target") == "mycobase":
                continue
            out.setdefault(s["species"], []).append({
                "paper": paper, "pages": f"{s['pages'][0]}-{s['pages'][1]}", "name_status": s["name"]["status"],
                "accepted_name": s["name"]["accepted_name"], "nomenclature": s.get("nomenclature", ""),
                "fields": s.get("fields", {}),
                "values": {k: v for k, v in s.get("values", {}).items() if v},
                "images": [f"{paper}/{x['file']}" for x in s.get("figures", []) if x.get("file")]})
    return dict(sorted(out.items()))


HELP.update({
    "MycoBase records": "Records in data/species_description.json - all of them are kept unchanged.",
    "updated": "Accepted species that get at least one new value or image from the papers.",
    "new values": "Values that were EMPTY in MycoBase and are filled from a paper. Nothing is replaced.",
    "new images": "Species images (plates) from the papers for accepted species.",
    "raw species": "Species described in the papers that are not accepted in MycoBase (other genera, "
                   "unknown names). Stored in raw_species.json for later use, not in species_description_data.",
})

with tab_data:
    st.header("species_description_data - MycoBase + what the papers add")
    st.markdown("All MycoBase records are kept **as they are**. Accepted species only get values for columns that "
                "are **empty** in MycoBase, plus species images. Species outside MycoBase go to "
                "`raw_species.json`. `data/species_description.json` is never written.")
    db = read_json(SPECIES_JSON)
    if db is None:
        st.error(f"{SPECIES_JSON} not found.")
    elif not dirs["out"].exists():
        st.info("No results yet - upload and run papers in tab 1.")
    else:
        mode = st.radio("Which proposals go in", MODES, horizontal=True, key="sd_mode",
                        help="Approved / corrected proposals (tab 3) always go in, rejected never. Proposals where "
                             "two papers disagree go in only after approval.")
        values, images, disputed = new_data(dirs, db, mode)
        raw = raw_species(dirs)
        updated = sorted(set(values) | set(images))
        m = st.columns(5)
        m[0].metric("MycoBase records", len(db), help=HELP["MycoBase records"])
        m[1].metric("Accepted species updated", len(updated), help=HELP["updated"])
        m[2].metric("New values", sum(len(v) for v in values.values()), help=HELP["new values"])
        m[3].metric("New images", sum(len(v) for v in images.values()), help=HELP["new images"])
        m[4].metric("Raw species (other file)", len(raw), help=HELP["raw species"])
        if disputed:
            st.caption(f"{len(disputed)} column(s) left out because papers disagree - approve one value in tab 3.")

        which = st.radio("Show", ["Accepted species with new data", "All accepted species", "Raw species (outside MycoBase)"],
                         horizontal=True, key="sd_which")
        if which == "Raw species (outside MycoBase)":
            names = list(raw)
        elif which == "All accepted species":
            names = sorted(k for k, v in db.items() if str(v.get("is accepted", "")).lower() == "yes")
        else:
            names = updated
        if not names:
            st.info("Nothing to show - no new data for accepted species with this choice.")
        else:
            tbl = pd.DataFrame([{"species": n, "new values": len(values.get(n, {})), "new images": len(images.get(n, []))}
                                for n in names]) if which != "Raw species (outside MycoBase)" else \
                pd.DataFrame([{"species": n, "papers": ", ".join(sorted({x["paper"] for x in raw[n]})),
                               "name status": raw[n][0]["name_status"],
                               "images": sum(len(x["images"]) for x in raw[n])} for n in names])
            st.dataframe(tbl.astype(str), width="stretch", hide_index=True, height=220, column_config=col_help(tbl))
            sp = st.selectbox("Species", names, key="sd_species")
            left, right = st.columns([3, 2])
            if which == "Raw species (outside MycoBase)":
                for x in raw[sp]:
                    with left:
                        st.markdown(f"**{x['nomenclature'] or sp}**")
                        st.caption(f"{x['paper']} · pages {x['pages']} · {x['name_status']} · "
                                   f"accepted name: {x['accepted_name'] or '-'}")
                        for k, v in x["fields"].items():
                            st.markdown(f"- **{k}**: {v}")
                        vals = {k: str(v) for k, v in x["values"].items() if k != "colony_diam"}
                        if vals:
                            st.table(pd.DataFrame(vals.items(), columns=["column", "value"]))
                    with right:
                        for im in x["images"]:
                            p = dirs["out"] / im
                            if p.exists():
                                st.image(str(p), caption=p.name)
            else:
                rec, new = db[sp], values.get(sp, {})
                with left:
                    st.markdown(f"### *{sp}*")
                    st.caption("🆕 = new from a paper (the column was empty in MycoBase). Everything else is MycoBase.")
                    for col, val in rec.items():
                        if col in new:
                            r = new[col]
                            st.markdown(f"- 🆕 **{col}**: {r['value']}  \n  <span style='color:gray'>from {r['paper']} · "
                                        f"page {r['pages']} · {CONF_ICON.get(r.get('confidence') or 'medium', '')}</span>",
                                        unsafe_allow_html=True)
                        elif not is_empty(val):
                            st.markdown(f"- **{col}**: {val}")
                    for col, r in new.items():
                        if col not in rec:                      # a MycoBase column this record did not have
                            st.markdown(f"- 🆕 **{col}**: {r['value']}  \n  <span style='color:gray'>from {r['paper']} · "
                                        f"page {r['pages']} · {CONF_ICON.get(r.get('confidence') or 'medium', '')}</span>",
                                        unsafe_allow_html=True)
                    n_empty = sum(1 for c, v in rec.items() if is_empty(v) and c not in new)
                    if n_empty:
                        st.caption(f"{n_empty} column(s) still empty.")
                with right:
                    p = mycobase_image(sp)
                    if p:
                        st.image(str(p), caption="MycoBase image")
                    for r in images.get(sp, []):
                        st.image(str(dirs["add"] / r["image"]),
                                 caption=f"🆕 {r['paper']} · Fig. {r['figure']} · page {r['page']} - "
                                         f"{str(r.get('caption', ''))[:160]}")
                    if not p and not images.get(sp):
                        st.caption("No image for this species.")

        st.divider()
        save_dir = dirs["base"] / "species_description_data"
        st.markdown(f"**Save** writes to `app_runs/{run}/species_description_data/`: "
                    "`species_description_data.json` / `.csv` (all MycoBase records + new values), `species_images.json` "
                    "+ `images/`, `new_values.csv` (where each new value comes from) and `raw_species.json` / `.csv`.")
        if st.button("💾 Save species_description_data", type="primary"):
            import shutil
            md5 = hashlib.md5(SPECIES_JSON.read_bytes()).hexdigest()
            data = json.loads(SPECIES_JSON.read_text(encoding="utf-8"))      # a fresh copy, not the cached one
            for rec, cols in values.items():
                for col, r in cols.items():
                    assert is_empty(data[rec].get(col)), (rec, col)        # safety: never overwrite
                    data[rec][col] = r["value"]
            (save_dir / "images").mkdir(parents=True, exist_ok=True)
            img_index = {}
            for rec in sorted(k for k, v in data.items() if str(v.get("is accepted", "")).lower() == "yes"):
                lst = []
                p = mycobase_image(rec)
                if p:
                    lst.append({"file": f"data/images/{p.name}", "source": "MycoBase"})
                for r in images.get(rec, []):
                    src = dirs["add"] / r["image"]
                    shutil.copy2(src, save_dir / "images" / src.name)
                    lst.append({"file": f"images/{src.name}", "source": f"{r['paper']} fig {r['figure']} p{r['page']}",
                                "caption": r.get("caption", "")})
                if lst:
                    img_index[rec] = lst
            with open(save_dir / "species_description_data.json", "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False, indent=1)
            with open(save_dir / "species_images.json", "w", encoding="utf-8") as f:
                json.dump(img_index, f, ensure_ascii=False, indent=1)
            with open(save_dir / "raw_species.json", "w", encoding="utf-8") as f:
                json.dump(raw, f, ensure_ascii=False, indent=1)
            (save_dir / "species_description_data.csv").write_bytes(species_csv(data))
            (save_dir / "raw_species.csv").write_bytes(raw_csv(raw))
            used = [{"mycobase_record": rec, "column": col, "value": r["value"], "paper": r["paper"],
                     "pages": r["pages"], "confidence": r.get("confidence", ""), "species_in_paper": r.get("species_in_paper", "")}
                    for rec, cols in values.items() for col, r in cols.items()]
            with open(save_dir / "new_values.csv", "w", encoding="utf-8-sig", newline="") as f:
                w = csv.DictWriter(f, fieldnames=["mycobase_record", "column", "value", "paper", "pages", "confidence",
                                                  "species_in_paper"])
                w.writeheader()
                w.writerows(used)
            assert hashlib.md5(SPECIES_JSON.read_bytes()).hexdigest() == md5      # MycoBase not touched
            st.success(f"Saved {len(data)} records ({len(updated)} updated), {len(raw)} raw species → "
                       f"app_runs/{run}/species_description_data/")
        if (save_dir / "species_description_data.json").exists():
            # a run saved before the CSV export existed: make the CSVs from the saved JSON once
            for name, make in (("species_description_data", species_csv), ("raw_species", raw_csv)):
                if (save_dir / f"{name}.json").exists() and not (save_dir / f"{name}.csv").exists():
                    (save_dir / f"{name}.csv").write_bytes(
                        make(json.loads((save_dir / f"{name}.json").read_text(encoding="utf-8"))))
            d1, d2 = st.columns(2)
            d1.download_button("⬇ species_description_data.json",
                               (save_dir / "species_description_data.json").read_bytes(),
                               file_name="species_description_data.json", mime="application/json")
            d1.download_button("⬇ species_description_data.csv",
                               (save_dir / "species_description_data.csv").read_bytes(),
                               file_name="species_description_data.csv", mime="text/csv",
                               help="One row per species; opens in Excel")
            if (save_dir / "raw_species.json").exists():
                d2.download_button("⬇ raw_species.json", (save_dir / "raw_species.json").read_bytes(),
                                   file_name="raw_species.json", mime="application/json")
                d2.download_button("⬇ raw_species.csv", (save_dir / "raw_species.csv").read_bytes(),
                                   file_name="raw_species.csv", mime="text/csv",
                                   help="One row per species treatment in a paper; opens in Excel")
