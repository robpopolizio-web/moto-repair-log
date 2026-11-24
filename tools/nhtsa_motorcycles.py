#!/usr/bin/env python3
"""
Pull US government (NHTSA) owner complaints for motorcycles, plus recalls for
the models that have complaints, and save them as CSV files you can open in
Google Sheets or Excel.

Run it from the repo folder:
    python3 tools/nhtsa_motorcycles.py

What it does:
  1. Downloads NHTSA's complaints file (every safety complaint since 1995,
     all vehicles, a few hundred MB). Cached in data/nhtsa/raw/ so later runs
     are quick; delete that folder to refresh.
  2. Asks NHTSA's vehicle database (vPIC) which models of Honda, Yamaha,
     Kawasaki, Suzuki and BMW are motorcycles, so cars and ATVs are left out.
     Motorcycle-only brands (Harley-Davidson, Ducati, KTM...) are kept whole.
  3. Keeps motorcycle complaints and writes:
       data/nhtsa/motorcycle_complaints.csv   one row per complaint and part
       data/nhtsa/model_summary.csv           complaints per model, top parts
       data/nhtsa/motorcycle_recalls.csv      recalls for those models (API)
  Personal details in the source file (VIN, city, dealer, operator name) are
  not copied.

Data is public US government data: https://www.nhtsa.gov/nhtsa-datasets-and-apis
Complaints are owner-submitted, unverified, US only, and safety-related.
"""
import csv, io, json, os, re, sys, time, urllib.parse, urllib.request, zipfile
from collections import Counter, defaultdict

HERE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(HERE, "..", "data", "nhtsa")
RAW = os.path.join(OUT, "raw")
UA = {"User-Agent": "moto-repair-log research (contact via site)"}

CMPL_URLS = [
    "https://static.nhtsa.gov/odi/ffdd/cmpl/FLAT_CMPL.zip",
    "https://www-odi.nhtsa.dot.gov/downloads/folders/Complaints/FLAT_CMPL.zip",
]
VPIC = "https://vpic.nhtsa.dot.gov/api/vehicles/GetModelsForMakeYear/make/{make}/modelyear/{year}/vehicletype/motorcycle?format=json"
RECALLS = "https://api.nhtsa.gov/recalls/recallsByVehicle?make={make}&model={model}&modelYear={year}"

# Brands that only make motorcycles (as they appear in NHTSA's MAKETXT, upper case).
MOTO_ONLY = {
    "HARLEY-DAVIDSON", "HARLEY DAVIDSON", "DUCATI", "KTM", "TRIUMPH", "INDIAN", "ROYAL ENFIELD",
    "APRILIA", "MOTO GUZZI", "MV AGUSTA", "CFMOTO", "CF MOTO", "ZERO", "ZERO MOTORCYCLES",
    "HUSQVARNA", "BUELL", "VICTORY", "BENELLI", "GASGAS", "LIVEWIRE", "ENERGICA", "URAL",
    "VESPA", "PIAGGIO", "SSR", "JANUS", "BETA", "SHERCO", "HYOSUNG", "KYMCO",
}
# Brands that also make cars, ATVs or boats: keep only models vPIC lists as motorcycles.
MIXED = ["HONDA", "YAMAHA", "KAWASAKI", "SUZUKI", "BMW", "CAN-AM"]
FIRST_YEAR = 1995

# Complaints flat file: tab separated, no header, 51 fields (see CMPL.txt).
F = dict(ODINO=1, MAKE=3, MODEL=4, YEAR=5, CRASH=6, FAILDATE=7, FIRE=8, INJURED=9, DEATHS=10,
         COMP=11, MILES=17, DESC=19, CMPL_TYPE=20, ORIG_OWNER=23, PROD_TYPE=45)


def key(s):
    return re.sub(r"[^a-z0-9]", "", str(s).lower())


def get(url, tries=4):
    for i in range(tries):
        try:
            with urllib.request.urlopen(urllib.request.Request(url, headers=UA), timeout=120) as r:
                return r.read()
        except Exception as e:  # network hiccup or rate limit: wait and retry
            if i == tries - 1:
                raise
            time.sleep(2 * (i + 1))


def download_complaints():
    os.makedirs(RAW, exist_ok=True)
    dest = os.path.join(RAW, "FLAT_CMPL.zip")
    if os.path.exists(dest) and os.path.getsize(dest) > 1_000_000:
        print("Using cached", dest)
        return dest
    for url in CMPL_URLS:
        try:
            print("Downloading", url, "(large file, a few minutes)...")
            req = urllib.request.Request(url, headers=UA)
            with urllib.request.urlopen(req, timeout=600) as r, open(dest + ".part", "wb") as f:
                while True:
                    chunk = r.read(1 << 20)
                    if not chunk:
                        break
                    f.write(chunk)
            os.replace(dest + ".part", dest)
            return dest
        except Exception as e:
            print("  failed:", e)
    sys.exit("Could not download the complaints file. Check your internet connection and try again.")


def motorcycle_models():
    """{MAKE: set(model keys)} for mixed brands, from vPIC. Cached."""
    cache = os.path.join(RAW, "vpic_motorcycle_models.json")
    if os.path.exists(cache):
        return {m: set(v) for m, v in json.load(open(cache)).items()}
    out = defaultdict(set)
    years = range(FIRST_YEAR, time.localtime().tm_year + 2)
    for make in MIXED:
        print(f"Listing {make} motorcycle models", end="", flush=True)
        for y in years:
            try:
                data = json.loads(get(VPIC.format(make=urllib.parse.quote(make.lower()), year=y)))
                for r in data.get("Results", []):
                    out[make].add(key(r.get("Model_Name", "")))
            except Exception:
                pass
            print(".", end="", flush=True)
            time.sleep(0.15)
        print(f" {len(out[make])} models")
    json.dump({m: sorted(v) for m, v in out.items()}, open(cache, "w"))
    return out


def base_key(make, model, mixed):
    """Model key to group by if this is a motorcycle, else None.
    NHTSA often adds a trim word ("MT-07 ABS"), so it is matched to the vPIC model name."""
    k = key(model)
    if not k:
        return None
    if make in MOTO_ONLY:
        return re.sub(r"abs$", "", k) or k
    if make in mixed:
        if k in mixed[make]:
            return k
        hits = [m for m in mixed[make] if len(m) >= 3 and (k.startswith(m) or m.startswith(k))]
        return max(hits, key=len) if hits else None
    return None


def main():
    os.makedirs(OUT, exist_ok=True)
    zpath = download_complaints()
    mixed = motorcycle_models()

    rows, seen = [], set()
    with zipfile.ZipFile(zpath) as z:
        name = next(n for n in z.namelist() if n.upper().endswith(".TXT"))
        with z.open(name) as fh:
            for line in io.TextIOWrapper(fh, encoding="latin-1", newline=""):
                f = line.rstrip("\r\n").split("\t")
                if len(f) <= F["PROD_TYPE"] or f[F["PROD_TYPE"]] != "V":
                    continue
                make, model = f[F["MAKE"]].strip().upper(), f[F["MODEL"]].strip()
                bk = base_key(make, model, mixed)
                if not bk:
                    continue
                miles = f[F["MILES"]].strip()
                rows.append({
                    "odi_number": f[F["ODINO"]].strip(),
                    "make": make.title(),
                    "model": model,
                    "model_key": bk,
                    "year": "" if f[F["YEAR"]].strip() in ("9999", "") else f[F["YEAR"]].strip(),
                    "component": f[F["COMP"]].strip().title(),
                    "miles_at_failure": "" if miles in ("", "0") else miles,
                    "fail_date": f[F["FAILDATE"]].strip(),
                    "crash": f[F["CRASH"]].strip(),
                    "fire": f[F["FIRE"]].strip(),
                    "injured": f[F["INJURED"]].strip(),
                    "original_owner": f[F["ORIG_OWNER"]].strip(),
                    "description": " ".join(f[F["DESC"]].split()),
                    "source": "NHTSA complaint",
                })

    if not rows:
        sys.exit("No motorcycle complaints found. The file layout may have changed; check CMPL.txt.")

    cols = list(rows[0].keys())
    with open(os.path.join(OUT, "motorcycle_complaints.csv"), "w", newline="", encoding="utf-8") as fo:
        w = csv.DictWriter(fo, fieldnames=cols); w.writeheader(); w.writerows(rows)

    # Summary per make + model: unique complaints, years, share with mileage, top parts.
    by = defaultdict(list)
    for r in rows:
        by[(r["make"], r["model_key"])].append(r)
    summary = []
    for (make, mk), rs in by.items():
        odis = {r["odi_number"] for r in rs}
        names = Counter(r["model"] for r in rs)
        comps = Counter(r["component"] for r in rs)
        years = sorted({r["year"] for r in rs if r["year"]})
        with_miles = {r["odi_number"] for r in rs if r["miles_at_failure"]}
        summary.append({
            "make": make, "model": names.most_common(1)[0][0], "complaints": len(odis),
            "with_mileage": len(with_miles), "years": f"{years[0]}-{years[-1]}" if years else "",
            "top_components": "; ".join(f"{c} ({n})" for c, n in comps.most_common(5)),
        })
    summary.sort(key=lambda s: -s["complaints"])
    with open(os.path.join(OUT, "model_summary.csv"), "w", newline="", encoding="utf-8") as fo:
        w = csv.DictWriter(fo, fieldnames=list(summary[0].keys())); w.writeheader(); w.writerows(summary)

    # Recalls for every make/model/year that has complaints (official API).
    combos = sorted({(r["make"], r["model"], r["year"]) for r in rows if r["year"]})
    print(f"Fetching recalls for {len(combos)} model-years...")
    recalls, seen_r = [], set()
    for i, (make, model, year) in enumerate(combos, 1):
        url = RECALLS.format(make=urllib.parse.quote(make), model=urllib.parse.quote(model), year=year)
        try:
            data = json.loads(get(url))
        except Exception:
            continue
        for r in data.get("results", []) or data.get("Results", []):
            camp = r.get("NHTSACampaignNumber", "")
            if (camp, model, year) in seen_r:
                continue
            seen_r.add((camp, model, year))
            recalls.append({
                "campaign": camp, "make": make, "model": model, "year": year,
                "component": r.get("Component", ""), "date": r.get("ReportReceivedDate", ""),
                "summary": " ".join(str(r.get("Summary", "")).split()),
                "consequence": " ".join(str(r.get("Consequence", "")).split()),
                "remedy": " ".join(str(r.get("Remedy", "")).split()),
            })
        if i % 50 == 0:
            print(f"  {i}/{len(combos)}")
        time.sleep(0.15)
    if recalls:
        with open(os.path.join(OUT, "motorcycle_recalls.csv"), "w", newline="", encoding="utf-8") as fo:
            w = csv.DictWriter(fo, fieldnames=list(recalls[0].keys())); w.writeheader(); w.writerows(recalls)

    print("\nDone.")
    print(f"  {len({r['odi_number'] for r in rows}):,} motorcycle complaints across {len(summary):,} models")
    print(f"  {len(recalls):,} recall entries")
    print("  Top 10 models by complaints:")
    for s in summary[:10]:
        print(f"    {s['complaints']:5}  {s['make']} {s['model']}  ({s['years']})")
    print("Files are in data/nhtsa/")


if __name__ == "__main__":
    main()
