"""Adds the makers' own recall documents to data/nhtsa/motorcycles.sqlite.

For every motorcycle recall campaign already in the database (built by nhtsa_motorcycles.py) this:
  1. asks NHTSA's safetyIssues API for the campaign's document list (the maker's Part 573 defect
     report, owner letters, dealer notices, NHTSA acknowledgements ...) -> table recall_documents
  2. downloads the newest Part 573 defect report PDF and pulls out the sections the short NHTSA
     summary leaves out: cause, chronology, supplier, remedy type, how the new part differs and
     when production was fixed -> table recall_details

Downloads are cached in data/nhtsa/raw/recall_docs/, so a re-run only fetches what is new.
Reports filed before about 2013 are free-form letters or scans; for those only the document list
and whatever text could be extracted are stored.

Run:  SSL_CERT_FILE=$(python3 -c 'import certifi; print(certifi.where())') python3 tools/nhtsa_recall_docs.py
"""
import json, os, re, sqlite3, sys, time, urllib.request
from concurrent.futures import ThreadPoolExecutor

import fitz  # PyMuPDF

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DB = os.path.join(ROOT, "data", "nhtsa", "motorcycles.sqlite")
CACHE = os.path.join(ROOT, "data", "nhtsa", "raw", "recall_docs")
API = "https://api.nhtsa.gov/safetyIssues/byNhtsaId?nhtsaId={}"
UA = {"User-Agent": "moto-repair-log-recall-docs/1.0"}

# file-name prefix -> plain-English kind
KINDS = {
    "RCLRPT": "Defect report (Part 573)",       # 2012 onward, structured form
    "RCDNN": "Defect report (Part 573)",        # before 2012, free-form letter
    "RCONL": "Owner letter",
    "RCRN": "Owner letter",                     # renotification
    "RCMN": "Dealer notice",
    "RCRIT": "Workshop instructions and service bulletin",
    "RCSB": "Workshop instructions and service bulletin",
    "RCQPR": "Quarterly progress report",
    "RCLQRT": "Quarterly progress report",
    "FRCL": "Same recall in other countries",
    "RCMR": "Correspondence with NHTSA",
    "RCNOC": "Correspondence with NHTSA",
    "RCORRD": "Other",
    "RMISC": "Other",
    "RCAK": "NHTSA acknowledgement",
    "RCFK": "NHTSA acknowledgement",
    "RCMQ": "NHTSA acknowledgement",            # missing quarterly report notice
}
REPORT_PREFIXES = ("RCLRPT", "RCDNN")


def kind_of(fname):
    p = re.match(r"[A-Z]+", fname.upper())
    return KINDS.get(p.group(0) if p else "", "Other")


def get(url, tries=4):
    for i in range(tries):
        try:
            with urllib.request.urlopen(urllib.request.Request(url, headers=UA), timeout=60) as r:
                return r.read()
        except Exception as ex:  # network hiccups, 5xx
            if i == tries - 1:
                raise
            time.sleep(2 * (i + 1))


def cached(path, url):
    if not os.path.exists(path):
        data = get(url)
        tmp = path + ".part"
        with open(tmp, "wb") as f:
            f.write(data)
        os.replace(tmp, path)
    with open(path, "rb") as f:
        return f.read()


# ------------------------------------------------------------------ Part 573 parsing
# Two layouts: 2012-2024 ("Description of the Cause : ...") and 2024 on ("Description of the cause:\n...").
FOOTER = re.compile(r"(?:Page\s*\n?\s*\d+\s*\n)?Part 573 Safety Recall Report\s*\n\s*\d\dV-?\d+\s*\n(?:Page\s*\n?\s*\d+\s*\n)?"
                    r"The information contained in this report was submitted pursuant to 49 CFR §\s*573\s*\n(?:Page \d+ of \d+\s*\n)?")
HEADER = re.compile(r"U\.S\. Department\s*\nof Transportation.*?OMB Control No\.:\s*[\d-]+\s*\n", re.S)
L = {  # label patterns, tolerant of line breaks inside labels and " :" vs ":"
    "cause": r"Description of the cause\s*:",
    "warning": r"Identification of any warning\s+that can occur\s*:",
    "supplier_blk": r"Component Manufacturer",
    "involved": r"Involved Components",
    "chronology": r"\nChronology\s*:?[ \t]*\n",
    "related": r"Related NHTSA Recall Number",
    "remedy_hdr": r"\nDescription of Remedy\s*:?[ \t]*\n",
    "remedy_type": r"Remedy Type\s*:",
    "remedy_program": r"Description of remedy program\s*:",
    "remedy_differs": r"How remedy component differs\s+from recalled component\s*:",
    "production_fix": r"Identify how/when recall condition\s+was corrected in production\s*:",
    "after_prod": r"Reimbursement Plan|Recall Schedule",
    "fmvss": r"FMVSS\s?1\s*:",
}


def grab(t, start, ends, keep_lines=False):
    m = re.search(start, t, re.I)
    if not m:
        return None
    rest = t[m.end():]
    cut = len(rest)
    for end in ends:
        n = re.search(end, rest, re.I)
        if n and n.start() < cut:
            cut = n.start()
    val = rest[:cut]
    if keep_lines:
        return val.strip() or None
    val = re.sub(r"\s+", " ", val).strip()
    return None if not val or val.upper() in ("N/A", "NA", "NR", "NONE", "N/A.") else val


ITEM = re.compile(r"^(\d{1,2}[.)]\s|[•▪\-–]\s|On |In |By |From |Between |Beginning |(January|February|March|April|May|June|July|"
                  r"August|September|October|November|December|Jan|Feb|Mar|Apr|Jun|Jul|Aug|Sep|Sept|Oct|Nov|Dec)\.?,? ?(\d|[-–]|through|to |and |of )|"
                  r"\d{1,2}/\d{1,2}/\d{2,4}|\d{4}[/-]\d)")


def steps_of(raw):
    items = []
    for line in raw.splitlines():
        line = line.strip()
        if not line:
            continue
        if not items or ITEM.match(line):
            items.append(line)
        else:
            items[-1] += " " + line
    items = [re.sub(r"\s+", " ", re.sub(r"^\d{1,2}[.)]\s|^[•▪\-–]\s", "", x)).strip() for x in items]
    items = [x for x in items if x and x.upper() not in ("NR", "N/A")]
    return "\n".join(items) or None


def parse_573(text):
    t = "\n" + HEADER.sub("\n", FOOTER.sub("\n", text))
    out = {
        "cause": grab(t, L["cause"], [L["warning"], L["supplier_blk"], r"Supplier Identification", L["involved"]]),
        "warning": grab(t, L["warning"], [L["supplier_blk"], r"Supplier Identification", L["involved"]]),
        "remedy_type": grab(t, L["remedy_type"], [r"\n"]),
        "remedy_program": grab(t, L["remedy_program"], [L["remedy_differs"]]),
        "remedy_differs": grab(t, L["remedy_differs"], [L["production_fix"]]),
        "production_fix": grab(t, L["production_fix"], [L["after_prod"]]),
        "fmvss": grab(t, L["fmvss"], [r"FMVSS\s?2", r"\n"]),
        "supplier": None, "supplier_country": None,
    }
    raw = grab(t, L["chronology"], [L["related"], L["remedy_hdr"], L["remedy_program"]], keep_lines=True)
    out["chronology"] = steps_of(raw) if raw else None
    m = re.search(r"Component Manufacturer(.*?)(?:Involved Components|\nChronology)", t, re.S | re.I)
    if m:
        n = re.search(r"\nName\s*:\s*\n?(.+)", "\n" + m.group(1))
        c = re.search(r"\nCountry\s*:\s*\n?(.+)", "\n" + m.group(1))
        out["supplier"] = n.group(1).strip().rstrip(",") if n and n.group(1).strip() not in ("NR", "N/A") else None
        out["supplier_country"] = c.group(1).strip() if c and c.group(1).strip() not in ("NR", "N/A") else None
    if out["remedy_type"]:
        out["remedy_type"] = out["remedy_type"].split("Consumer Advisories")[0].strip() or None
    return out


# ------------------------------------------------------------------ per campaign
def fetch(camp):
    jpath = os.path.join(CACHE, "json", f"{camp}.json")
    try:
        js = json.loads(cached(jpath, API.format(camp)))
    except Exception as ex:
        return camp, None, None, f"api: {ex}"
    recs = [r for res in js.get("results", []) for r in res.get("recalls", [])]
    if not recs:
        return camp, None, None, "no recall in api"
    r = recs[0]
    docs = r.get("associatedDocuments") or []
    reports = sorted([d for d in docs if d["fileName"].upper().startswith(REPORT_PREFIXES)],
                     key=lambda d: (d["fileName"].upper().startswith("RCLRPT"), d.get("loadDate") or "", d["id"]))
    text, err = None, None
    if reports:
        d = reports[-1]  # newest = latest amendment
        ppath = os.path.join(CACHE, "pdf", d["fileName"])
        try:
            pdf = fitz.open(stream=cached(ppath, d["url"]), filetype="pdf")
            text = "".join(p.get_text() for p in pdf)
        except Exception as ex:
            err = f"pdf: {ex}"
    return camp, r, text, err


def main():
    os.makedirs(os.path.join(CACHE, "json"), exist_ok=True)
    os.makedirs(os.path.join(CACHE, "pdf"), exist_ok=True)
    con = sqlite3.connect(DB)
    camps = [c for (c,) in con.execute("select distinct campaign from recalls order by campaign")]
    con.executescript("""
    drop table if exists recall_documents;
    drop table if exists recall_details;
    create table recall_documents (
      campaign TEXT NOT NULL, doc_id INTEGER, kind TEXT, title TEXT, file_name TEXT, url TEXT,
      load_date TEXT, file_size INTEGER);
    create table recall_details (
      campaign TEXT PRIMARY KEY, subject TEXT, mfr_campaign TEXT, over_the_air INTEGER, documents INTEGER,
      report_url TEXT, structured INTEGER, cause TEXT, warning TEXT, chronology TEXT, remedy_type TEXT,
      remedy_program TEXT, remedy_differs TEXT, production_fix TEXT, supplier TEXT, supplier_country TEXT,
      fmvss TEXT, report_text TEXT, error TEXT);
    create index ix_rd_campaign on recall_documents(campaign);
    """)
    done = errs = structured = 0
    with ThreadPoolExecutor(6) as pool:
        for full, r, text, err in pool.map(fetch, camps):
            done += 1
            if r is None:
                errs += 1
                con.execute("insert into recall_details (campaign, error) values (?,?)", (full, err))
                continue
            docs = r.get("associatedDocuments") or []
            for d in docs:
                con.execute("insert into recall_documents values (?,?,?,?,?,?,?,?)",
                            (full, d["id"], kind_of(d["fileName"]), d.get("summary"), d["fileName"], d["url"],
                             (d.get("loadDate") or "")[:10], d.get("fileSize")))
            reports = sorted([d for d in docs if d["fileName"].upper().startswith(REPORT_PREFIXES)],
                             key=lambda d: (d["fileName"].upper().startswith("RCLRPT"), d.get("loadDate") or "", d["id"]))
            p = parse_573(text) if text and re.search(r"Description of the cause", text, re.I) else {}
            ok = 1 if p.get("cause") or p.get("chronology") else 0
            structured += ok
            con.execute("""insert into recall_details values (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                        (full, r.get("subject"), r.get("mfrCampaignNumber"), int(bool(r.get("overTheAirUpdate"))),
                         len(docs), reports[-1]["url"] if reports else None, ok,
                         p.get("cause"), p.get("warning"), p.get("chronology"), p.get("remedy_type"),
                         p.get("remedy_program"), p.get("remedy_differs"), p.get("production_fix"),
                         p.get("supplier"), p.get("supplier_country"), p.get("fmvss"),
                         (text or "").strip() or None, err))
            if done % 100 == 0:
                print(f"  {done}/{len(camps)} campaigns", flush=True)
                con.commit()
    con.execute("insert or replace into meta values ('recall_docs_built_at', ?)", (time.strftime("%Y-%m-%dT%H:%M:%S"),))
    con.commit()
    nd = con.execute("select count(*) from recall_documents").fetchone()[0]
    print(f"{len(camps)} campaigns, {nd} documents, {structured} defect reports parsed, {errs} errors")


if __name__ == "__main__":
    sys.exit(main())
