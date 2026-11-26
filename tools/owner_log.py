"""Owner repair log -> catalogue.

Reads the owner log (data/owner_log/entries_review.json, saved from the Google Sheet "Moto Repair Log data",
tab "entries (review)"; email column dropped) and matches each entry to a model page (tools/model_pages.csv).
Writes into catalog.sqlite:
  owner_entries   one row per entry, with the page it belongs to (url blank when no page matches)
  owner_summary   per page: owners, bikes, repairs, check-ins, top parts, median repair mileage (only when n >= 5)
A missing unit is read as miles (most posts are US/UK); km are converted.
"""
import csv, json, os, re, sqlite3, statistics, sys
from collections import Counter, defaultdict

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "tools"))
from model_names import display

DATA = os.path.join(ROOT, "data")
MIN_N = 5

# owner-log names that no catalogue name or alias spells the same way
MANUAL = {
    ("Yamaha", "fz07"): "mt07", ("Yamaha", "fz09"): "mt09", ("Yamaha", "fj09"): "tracer900", ("Yamaha", "r1"): "yzfr1",
    ("Yamaha", "r6"): "yzfr6", ("Yamaha", "r3"): "yzfr3", ("Yamaha", "r7"): "yzfr7", ("Honda", "blackbird"): "cbr1100xxsuperblackbird",
    ("Honda", "goldwing"): "goldwing", ("Honda", "vfr"): "vfr800", ("Harley-Davidson", "rgs"): "roadglidespecial",
    ("Harley-Davidson", "streetglidespecial"): "streetglidespecial", ("KTM", "duke390"): "390duke", ("KTM", "duke200"): "200duke",
    ("BMW", "k1600"): "k1600gt", ("BMW", "rninet"): "rninet",
    ("Honda", "pc800"): "pacificcoast", ("Honda", "gl1100"): "goldwinggl1100", ("Honda", "gl1000goldwing"): "goldwinggl1000",
    ("Honda", "superhawk996"): "vtr1000ffirestormsuperhawk", ("Honda", "shadow1100ace"): "vt1100shadowace",
    ("Honda", "crf1100africatwin"): "africatwincrf1100", ("Honda", "crf1100a4africatwinadventuresports"): "africatwinadventuresports",
    ("Kawasaki", "zx6rj2"): "ninjazx6r", ("Suzuki", "dl1000vstrom"): "vstrom1000", ("Ducati", "supersport950s"): "supersport",
    ("Aprilia", "rsv4factory"): "rsv4", ("Yamaha", "fz6s2"): "fz6", ("Yamaha", "fjr"): "fjr1300",
    ("Harley-Davidson", "flhc"): "heritageclassic", ("Harley-Davidson", "sg"): "streetglide",
}


def key(s):
    return re.sub(r"[^a-z0-9]", "", s.lower())


def main():
    c = sqlite3.connect(os.path.join(DATA, "catalog.sqlite"))
    pages = list(csv.DictReader(open(os.path.join(ROOT, "tools", "model_pages.csv"))))
    url_of_id = {int(i): p["url"] for p in pages for i in p["bike_ids"].split()}
    names = defaultdict(dict)            # make -> name key -> url
    for p in pages:
        names[p["make"]][key(p["model"])] = p["url"]
    for bid, mk, md in c.execute("select bike_id, make, model from bikes"):
        if bid in url_of_id:
            names[mk].setdefault(key(re.sub(r"\s*\(.*?\)$", "", md)), url_of_id[bid])
    for bid, mk, md in c.execute("select bike_id, source_make, source_model from aliases"):
        if bid in url_of_id:
            names[mk].setdefault(key(md), url_of_id[bid])

    def match(make, model):
        cands = names.get(make, {})
        tries = [model, re.sub(r"\s*\(.*?\)", "", model), re.sub(r"^.*\((.*)\).*$", r"\1", model),
                 display(make, model), re.sub(r"\s+(gen \d+|\d{4})$", "", model, flags=re.I)]
        for t in tries:
            k = key(t)
            k = MANUAL.get((make, k), k)
            if k in cands:
                return cands[k]
        k = key(model)
        pref = [u for n, u in cands.items() if len(n) >= 4 and (k.startswith(n) and len(k) - len(n) <= 3)]
        return pref[0] if len(set(pref)) == 1 else ""

    entries = json.load(open(os.path.join(DATA, "owner_log", "entries_review.json")))
    c.execute("drop table if exists owner_entries")
    c.execute("""create table owner_entries (entry_id TEXT PRIMARY KEY, url TEXT, make TEXT, model TEXT, year INT,
                 owner TEXT, type TEXT, miles INT, mileage_type TEXT, part TEXT, notes TEXT, source TEXT, source_url TEXT)""")
    unmatched = Counter()
    for e in entries:
        url = match(e["brand"], e["model"])
        if not url:
            unmatched[(e["brand"], e["model"])] += 1
        try:
            odo = float(e["odometer"])
            miles = int(round(odo * 0.621371)) if e["unit"] == "km" else int(odo)
        except ValueError:
            miles = None
        c.execute("insert into owner_entries values (?,?,?,?,?,?,?,?,?,?,?,?,?)",
                  (e["entry_id"], url, e["brand"], e["model"], int(e["year"]) if e["year"].isdigit() else None,
                   e["garage_id"], e["type"], miles, e["mileage_type"], e["part_failed"], e["notes"], e["source"], e["source_url"]))
    c.execute("drop table if exists owner_summary")
    c.execute("""create table owner_summary (url TEXT PRIMARY KEY, owners INT, bikes INT, repairs INT, checkins INT,
                 top_parts TEXT, median_repair_miles INT, max_miles INT)""")
    by = defaultdict(list)
    for r in c.execute("select url, owner, model, year, type, miles, mileage_type, part from owner_entries where url != ''"):
        by[r[0]].append(r)
    for url, rs in by.items():
        reps = [r for r in rs if r[4] == "repair"]
        exact = [r[5] for r in reps if r[5] and r[6] == "exact"]
        parts = Counter(re.split(r",| \(", r[7])[0].strip().capitalize() for r in reps if r[7])
        c.execute("insert into owner_summary values (?,?,?,?,?,?,?,?)",
                  (url, len({r[1] for r in rs}), len({(r[1], r[2], r[3]) for r in rs}), len(reps),
                   sum(1 for r in rs if r[4] == "checkin"), "; ".join(f"{p} ({n})" for p, n in parts.most_common(5)),
                   int(statistics.median(exact)) if len(exact) >= MIN_N else None,
                   max((r[5] or 0) for r in rs) or None))
    c.commit()
    n = c.execute("select count(*), sum(url != '') from owner_entries").fetchone()
    print(f"entries {n[0]}, matched to a page {n[1]}, pages with owner data {len(by)}")
    print("unmatched:", unmatched.most_common(60))


if __name__ == "__main__":
    main()
