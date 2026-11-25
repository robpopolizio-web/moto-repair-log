"""EU Safety Gate (formerly RAPEX) motorcycle alerts, 2005 onward -> data/eu/eu.sqlite

Safety Gate publishes one XML report per week (index: /api/download/weeklyReport/list/xml/en),
CC0 licence. Motor vehicle recalls notified by EU/EEA countries are in category "Motor vehicles".

Which alerts are motorcycles: the product type says motorcycle/moped/scooter/tricycle/quad, or the EU
type-approval number is under the two-and-three-wheeler regulations (168/2013, earlier 2002/24 or
92/61). Reports are cached in data/eu/reports/, so re-runs only fetch new weeks.

Run:  SSL_CERT_FILE=$(python3 -c 'import certifi; print(certifi.where())') python3 tools/eu_safety_gate.py
"""
import html, os, re, sqlite3, sys, time, urllib.request
from concurrent.futures import ThreadPoolExecutor

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DIR = os.path.join(ROOT, "data", "eu")
INDEX = "https://ec.europa.eu/safety-gate-alerts/api/download/weeklyReport/list/xml/en"
UA = {"User-Agent": "moto-repair-log-safety-gate/1.0"}
MOTO_PRODUCT = re.compile(r"motor\s?cycle|motorbike|moped|scooter|tricycle|quadricycle|quad bike|\bATV\b|two-wheel|2-wheel|enduro|motocross", re.I)
MOTO_APPROVAL = re.compile(r"168/2013|2002/24|92/61")
FIELDS = ["caseNumber", "publicationDate", "reference", "category", "product", "brand", "name", "type_numberOfModel",
          "riskType", "danger", "measures", "URLrecall", "description", "notifyingCountry", "countryOfOrigin", "level",
          "companyRecallCode", "productionDates"]


def get(url, tries=4):
    for i in range(tries):
        try:
            with urllib.request.urlopen(urllib.request.Request(url, headers=UA), timeout=120) as r:
                return r.read()
        except Exception:
            if i == tries - 1:
                raise
            time.sleep(5 * (i + 1))


def val(block, tag):
    m = re.search(rf"<{tag}(?:\s[^>]*)?>(.*?)</{tag}>", block, re.S)
    if not m:
        return None
    v = re.sub(r"<!\[CDATA\[(.*?)\]\]>", r"\1", m.group(1), flags=re.S)
    v = html.unescape(re.sub(r"\s+", " ", v)).strip()
    return v or None


def main():
    os.makedirs(os.path.join(DIR, "reports"), exist_ok=True)
    idx = get(INDEX).decode("utf-8")
    open(os.path.join(DIR, "weekly_list.xml"), "w", encoding="utf-8").write(idx)
    reports = [(val(b, "reference"), html.unescape(val(b, "URL") or "")) for b in re.findall(r"<weeklyReport>(.*?)</weeklyReport>", idx, re.S)]
    print(f"{len(reports)} weekly reports", flush=True)

    def fetch(ref_url):
        ref, url = ref_url
        path = os.path.join(DIR, "reports", f"{ref}.xml")
        if not os.path.exists(path) or ref.startswith("Report-2026"):   # the current year can still change
            try:
                open(path, "wb").write(get(url))
            except Exception as ex:
                return ref, None, str(ex)
        return ref, open(path, encoding="utf-8", errors="replace").read(), None

    con = sqlite3.connect(os.path.join(DIR, "eu.sqlite"))
    con.executescript(f"""drop table if exists alerts;
      create table alerts (report TEXT, {', '.join(f'{f} TEXT' for f in FIELDS)}, why TEXT);""")
    n_all = n_moto = errs = 0
    with ThreadPoolExecutor(4) as pool:
        for ref, text, err in pool.map(fetch, reports):
            if err:
                errs += 1
                print("  failed", ref, err, flush=True)
                continue
            for block in re.findall(r"<notifications\b.*?</notifications>", text, re.S):
                n_all += 1
                row = {f: val(block, f) for f in FIELDS}
                if (row["category"] or "").lower() != "motor vehicles":
                    continue
                prod = " ".join(filter(None, [row["product"], row["description"], row["name"]]))
                why = ("product type" if MOTO_PRODUCT.search(row["product"] or "") else
                       "type approval" if MOTO_APPROVAL.search(row["type_numberOfModel"] or "") else
                       "description" if MOTO_PRODUCT.search(prod) else None)
                if why:
                    n_moto += 1
                    con.execute(f"insert into alerts values ({','.join('?' * (len(FIELDS) + 2))})",
                                [ref] + [row[f] for f in FIELDS] + [why])
    con.commit()
    print(f"{n_all:,} alerts read, {n_moto:,} motorcycle alerts saved, {errs} reports failed")
    for k, c in con.execute("select why, count(*) from alerts group by why"):
        print(" ", k, c)


if __name__ == "__main__":
    sys.exit(main())
