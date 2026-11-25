"""Japan (MLIT) recalls in English, motorcycles only -> data/mlit/mlit.sqlite

MLIT lists every recall filed in Japan on https://www.mlit.go.jp/en/jidosha/vehicle_recall*.html,
one page per year, each row linking a one-page English SUMMARY PDF (campaign no., date, maker,
defect, type codes, model names, model years, number of vehicles).

Which rows are motorcycles: Japanese type designations encode the vehicle class. Motorcycle codes
end their prefix in BG/BH/BJ/BK/BL ("8BL-RN88J" = over 250 cc, "2BJ-JC92" = 51-125 cc), old ones
start "BC-" or "BA-" with a motorcycle maker. Rows from makers that only make two-wheelers are kept
too. Honda/Suzuki/BMW car rows are dropped by type code.

Run:  SSL_CERT_FILE=$(python3 -c 'import certifi; print(certifi.where())') python3 tools/mlit_recalls.py
"""
import html, os, re, sqlite3, sys, time, urllib.request
from concurrent.futures import ThreadPoolExecutor

import fitz

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DIR = os.path.join(ROOT, "data", "mlit")
BASE = "https://www.mlit.go.jp"
PAGES = ["vehicle_recall"] + [f"vehicle_recall_{y}" for y in range(2024, 2019, -1)] + \
        [f"vehicle_recall_{y}" for y in range(19, 9, -1)] + ["vehicle_recall_11_2"]
MONTHS = {m: i for i, m in enumerate(["JANUARY", "FEBRUARY", "MARCH", "APRIL", "MAY", "JUNE", "JULY", "AUGUST",
                                       "SEPTEMBER", "OCTOBER", "NOVEMBER", "DECEMBER"], 1)}
MOTO_ONLY = ("YAMAHA", "KAWASAKI", "HARLEY", "DUCATI", "TRIUMPH", "KTM", "HUSQVARNA", "PIAGGIO", "VESPA", "APRILIA",
             "MOTO GUZZI", "ROYAL ENFIELD", "MV AGUSTA", "BENELLI", "INDIAN", "GASGAS", "GAS GAS", "BIMOTA", "CFMOTO",
             "ZERO", "VICTORY", "BUELL", "MOTO MORINI", "SYM", "KYMCO", "PEUGEOT MOTOCYCLES", "BRP", "CAN-AM")
MAYBE = ("HONDA", "SUZUKI", "BMW")
MOTO_TYPE = re.compile(r"(?<![A-Z0-9])(?:[0-9A-Z]{0,2}B[GHJKL]|BC|BA|ZD[ABC])-[A-Z0-9]{2,}")
UA = {"User-Agent": "moto-repair-log-mlit/1.0"}


def get(url, tries=4):
    for i in range(tries):
        try:
            with urllib.request.urlopen(urllib.request.Request(url, headers=UA), timeout=60) as r:
                return r.read()
        except Exception:
            if i == tries - 1:
                raise
            time.sleep(3 * (i + 1))


def clean(s):
    s = re.sub(r"<br\s*/?>", "\n", s, flags=re.I)
    s = html.unescape(re.sub(r"<[^>]+>", " ", s)).replace("　", " ")
    return "\n".join(re.sub(r"\s+", " ", x).strip() for x in s.split("\n") if x.strip())


def parse_page(text):
    """Rows of (year, month, day, make, models, manufacturer, pdf_url)."""
    out, year, month, day = [], None, None, None
    for m in re.finditer(r"([A-Z]+)\s*,\s*(\d{4})|<tr[^>]*>(.*?)</tr>", text, re.S | re.I):
        if m.group(1):
            if m.group(1).upper() in MONTHS:
                month, year = MONTHS[m.group(1).upper()], int(m.group(2))
            continue
        tds = re.findall(r"<td[^>]*>(.*?)</td>", m.group(3), re.S | re.I)
        link = re.search(r'href="([^"]+\.pdf)"', m.group(3), re.I)
        if not link or len(tds) < 4:
            continue
        cells = [clean(t) for t in tds]
        if len(cells) >= 5 and re.fullmatch(r"\d{1,2}", cells[0] or ""):
            day = int(cells[0]); cells = cells[1:]
        make, models, maker = cells[0], cells[1], cells[2]
        url = link.group(1)
        url = url if url.startswith("http") else BASE + url
        out.append((year, month, day, make, models, maker, url.replace("http://", "https://")))
    return out


def parse_pdf(text):
    t = re.sub(r"[ \t]+", " ", text)
    g = lambda pat: (re.search(pat, t, re.S | re.I) or [None, None])[1]
    camp = g(r"CAMPAIGN\s*No\.?\s*\n?\s*([0-9]+)")
    date = g(r"DATE\s*\n\s*([A-Za-z]+\.? ?\d{1,2}\.? ?\d{4})")
    defect = g(r"DESCRIPTION\s+OF\s*\n?\s*DEFECT\s*\n(.*?)\n\s*\n?\s*TYPE\b")
    if defect:
        defect = re.sub(r"\s+", " ", defect).strip()
    total = g(r"TOTAL\s*\n\s*([\d,]+)")
    types = sorted(set(MOTO_TYPE.findall(t)))
    return camp, date, defect, int(total.replace(",", "")) if total else None, types


def main():
    os.makedirs(os.path.join(DIR, "pdf"), exist_ok=True)
    rows = []
    for p in PAGES:
        path = os.path.join(DIR, p + ".html")
        if not os.path.exists(path):
            try:
                open(path, "wb").write(get(f"{BASE}/en/jidosha/{p}.html"))
            except Exception as ex:
                print("skip", p, ex); continue
        rows += [(p,) + r for r in parse_page(open(path, encoding="utf-8", errors="replace").read())]
    seen, cand = set(), []
    for r in rows:
        if r[7] in seen:
            continue
        seen.add(r[7])
        mk = (r[4] + " " + r[6]).upper()
        if any(k in mk for k in MOTO_ONLY + MAYBE):
            cand.append(r)
    print(f"{len(rows)} rows on {len(PAGES)} pages, {len(seen)} unique PDFs, {len(cand)} from motorcycle makers")

    def pdf_text(r):
        path = os.path.join(DIR, "pdf", r[7].rsplit("/", 1)[-1])
        try:
            if not os.path.exists(path):
                open(path, "wb").write(get(r[7]))
            return r, "".join(p.get_text() for p in fitz.open(path))
        except Exception as ex:
            return r, ""

    con = sqlite3.connect(os.path.join(DIR, "mlit.sqlite"))
    con.executescript("""drop table if exists recalls;
    create table recalls (pdf_url TEXT PRIMARY KEY, page TEXT, year INT, month INT, day INT, make TEXT, models TEXT,
      manufacturer TEXT, campaign TEXT, date_text TEXT, defect TEXT, units INT, type_codes TEXT, why_moto TEXT, pdf_text TEXT);""")
    kept = 0
    with ThreadPoolExecutor(4) as pool:
        for r, text in pool.map(pdf_text, cand):
            camp, date, defect, units, types = parse_pdf(text) if text else (None,) * 4 + ([],)
            mk = (r[4] + " " + r[6]).upper()
            only = any(k in mk for k in MOTO_ONLY)
            moto_types = [x for x in types if not x.startswith(("BA-",)) or only]
            if not (moto_types or (only and not types)):
                continue
            why = "type code" if moto_types else "motorcycle-only maker"
            # the year: from the page (one page per year), else the PDF file name (YYMMDD_...)
            pm = re.search(r"_(\d+)(?:_2)?$", r[0])
            year = (2026 if not pm else int(pm.group(1)) + (2000 if len(pm.group(1)) == 2 else 0))
            fm = re.match(r"(\d{2})(\d{2})(\d{2})_", r[7].rsplit("/", 1)[-1])
            if fm and 2000 + int(fm.group(1)) in (year, year + 1, year - 1):
                year, month, day = 2000 + int(fm.group(1)), int(fm.group(2)), int(fm.group(3))
            else:
                month, day = r[2] if r[1] == year else None, r[3]
            r = (r[0], year, month, day) + r[4:]
            con.execute("insert into recalls values (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                        (r[7], r[0], r[1], r[2], r[3], r[4], r[5].replace("\n", " / "), r[6], camp, date, defect, units,
                         " ".join(moto_types), why, text))
            kept += 1
    con.commit()
    print(f"{kept} motorcycle recalls saved to data/mlit/mlit.sqlite")
    for y, n in con.execute("select year, count(*) from recalls group by year order by year"):
        print(" ", y, n)


if __name__ == "__main__":
    sys.exit(main())
