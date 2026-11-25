#!/usr/bin/env python3
"""
Build a database of every US government (NHTSA) owner complaint and recall
for motorcycles, scooters and three-wheelers.

Run it from the repo folder:
    python3 tools/nhtsa_motorcycles.py            # writes to data/nhtsa/
    python3 tools/nhtsa_motorcycles.py --out DIR  # writes somewhere else

Output (in data/nhtsa/):
    motorcycles.sqlite          the database (tables described at the bottom)
    complaints.csv              same complaints, for Google Sheets / Excel
    recalls.csv                 same recalls
    model_summary.csv           one row per model: counts, mileage, top parts

How motorcycles are picked out of the 2+ million vehicle complaints:
  1. Most complaints carry the first 11 characters of the VIN. NHTSA's VIN
     decoder (vPIC) says what each one is: a Honda Gold Wing VIN decodes as
     "Motorcycle - Touring", a Polaris Sportsman as "Off-Road Vehicle - ATV",
     a Honda Civic as a passenger car. That is the main test, and it also
     gives the official model name (owners type "GL1800", the VIN says "Gold Wing").
  2. Complaints with no usable VIN fall back to the name: motorcycle-only
     brands are kept whole, and for mixed brands (Honda, Yamaha...) the model
     name must match a known motorcycle model.
Downloads and VIN lookups are cached in data/nhtsa/raw/, so later runs take a
couple of minutes. Delete that folder to refresh from NHTSA.

Personal details in the source file (VIN, city, dealer, operator name) are not
copied. Source: https://www.nhtsa.gov/nhtsa-datasets-and-apis
Complaints are owner-submitted, unverified, US only, and safety-related.
"""
import argparse, csv, io, json, os, re, sqlite3, statistics, sys, time, zipfile
import urllib.error, urllib.parse, urllib.request
from collections import Counter, defaultdict
from concurrent.futures import ThreadPoolExecutor

HERE = os.path.dirname(os.path.abspath(__file__))
UA = {"User-Agent": "moto-repair-log research"}
FFDD = "https://static.nhtsa.gov/odi/ffdd/"
CMPL_ZIP = FFDD + "cmpl/FLAT_CMPL.zip"
RCL_ZIPS = [FFDD + "rcl/FLAT_RCL_PRE_2010.zip", FFDD + "rcl/FLAT_RCL_POST_2010.zip"]
VPIC = "https://vpic.nhtsa.dot.gov/api/vehicles/"
FIRST_YEAR = 1995

# Brands that only make motorcycles/scooters (NHTSA MAKETXT, upper case).
MOTO_ONLY = {
    "HARLEY-DAVIDSON", "HARLEY DAVIDSON", "DUCATI", "KTM", "TRIUMPH", "INDIAN", "ROYAL ENFIELD",
    "APRILIA", "MOTO GUZZI", "MV AGUSTA", "CFMOTO", "CF MOTO", "ZERO", "ZERO MOTORCYCLES",
    "HUSQVARNA", "BUELL", "VICTORY", "BENELLI", "GASGAS", "LIVEWIRE", "ENERGICA", "URAL",
    "VESPA", "PIAGGIO", "SSR", "JANUS", "BETA", "SHERCO", "HYOSUNG", "KYMCO", "BIMOTA",
    "NORTON", "MOTO MORINI", "SYM", "GENUINE", "GENUINE SCOOTER", "BIG DOG", "AMERICAN IRONHORSE",
    "ULTRA", "TITAN", "CONFEDERATE", "SURRON", "SUR-RON", "SUPER SOCO", "SONDORS", "DAMON",
}
# Brands that also make cars, ATVs or boats: by name, keep only known motorcycle models.
MIXED = ["HONDA", "YAMAHA", "KAWASAKI", "SUZUKI", "BMW", "CAN-AM", "POLARIS"]
# Model words that mean ATV / side-by-side / snowmobile / watercraft (used when the VIN can't tell).
NOT_MOTO = re.compile(
    r"\b(ATV|UTV|SXS|TRX|RANCHER|FOREMAN|RUBICON|RECON|PIONEER|TALON|SPORTSMAN|RANGER|RZR|"
    r"GENERAL|OUTLANDER|RENEGADE|MAVERICK|COMMANDER|DEFENDER|TRAXTER|QUEST|BRUTE ?FORCE|KVF|"
    r"MULE|TERYX|PRAIRIE|BAYOU|KFX|GRIZZLY|KODIAK|RHINO|VIKING|WOLVERINE|YFZ|YFM|RAPTOR|BANSHEE|"
    r"BLASTER|KINGQUAD|QUADSPORT|QUADRUNNER|EIGER|OZARK|VINSON|YXZ|CFORCE|UFORCE|ZFORCE|"
    r"SNOWMOBILE|WAVERUNNER|SEA-?DOO|SKI-?DOO|JET ?SKI|GOLF)\b")
# Car, SUV and motorhome models sold under bike brand names (Honda cars, Suzuki cars, BMW cars,
# Triumph's old sports cars, Damon motorhomes). Owners sometimes type these on a bike complaint, and
# recalls for them must never be matched to a motorcycle.
NOT_BIKE_MODEL = {
    "Honda": r"ACCORD|CIVIC|CR-?V|HR-?V|PASSPORT|PILOT|ODYSSEY|ELEMENT|FIT|INSIGHT|RIDGELINE|PRELUDE|S2000|CR-?Z|CROSSTOUR|CLARITY|DEL SOL|PROLOGUE",
    "Suzuki": r"SAMURAI|SIDEKICK|(GRAND )?VITARA|XL-?7|X-90|FORENZA|RENO|VERONA|AERIO|ESTEEM|SWIFT|SX4|KIZASHI|EQUATOR",
    "BMW": r"[1-8] ?SERIES|[1-8]\d\d[DEI]S?|X[1-7]|Z[348]|M[2-8]|I[3-8]|IX\d?|MINI|ALPINA",
    "Triumph": r"SPITFIRE|GT6|TR[2-8]|TR250|STAG|HERALD|DOLOMITE|TOLEDO|VITESSE",
    "Damon": r"(?!HYPER)",  # Damon Motor Coach makes motorhomes; Damon Motors' bikes are all "Hyper..."
    "Yamaha": r"GOLF ?CAR|DRIVE2?",
    "Polaris": r"RANGER|GENERAL|RZR|SPORTSMAN|GEM",
}
NOT_BIKE_MODEL = {k: re.compile(rf"^\s*({v})\b", re.I) for k, v in NOT_BIKE_MODEL.items()}


def not_bike_model(mk, model):
    rx = NOT_BIKE_MODEL.get(mk)
    return bool(rx and rx.search(model or ""))


MAKE_NAMES = {
    "HARLEY DAVIDSON": "Harley-Davidson", "HARLEY-DAVIDSON": "Harley-Davidson", "BMW": "BMW",
    "KTM": "KTM", "CF MOTO": "CFMoto", "CFMOTO": "CFMoto", "MV AGUSTA": "MV Agusta",
    "CAN-AM": "Can-Am", "GASGAS": "GasGas", "SSR": "SSR", "ZERO MOTORCYCLES": "Zero",
    "LIVEWIRE": "LiveWire", "SYM": "SYM", "SUR-RON": "Sur-Ron", "SURRON": "Sur-Ron",
    "GENUINE SCOOTER": "Genuine", "BIGDOG": "Big Dog", "BIG DOG": "Big Dog",
    "AMERICAN IRONHORSE": "American IronHorse",
}
# How the VIN decoder names makes -> normal brand names.
VIN_MAKES = {
    "SPYDER": "Can-Am", "CAN-AM": "Can-Am", "INDIAN MOTORCYCLE": "Indian", "BIG DOG MOTORCYCLES": "Big Dog",
    "HYOSUNG MOTORS & MACHINERY": "Hyosung", "ZERO MOTORCYCLES": "Zero", "SLINGSHOT": "Polaris",
    "AMERICAN IRONHORSE MOTORCYCLES": "American IronHorse", "MV AGUSTA MOTOR": "MV Agusta",
    "VANDERHALL MOTOR WORKS": "Vanderhall", "EXCELSIOR-HENDERSON MOTORCYCLES": "Excelsior-Henderson",
    "IRBITSKI MOTOTSICLETNY ZAVOD": "Ural", "KTMMEX": "KTM", "GENUINE SCOOTERS": "Genuine",
    "ELECTRA MECCANICA VEHICLES CORP.": "ElectraMeccanica", "BAJAJ AUTO": "Bajaj",
    "JOHNNY PAG MOTORCYCLES": "Johnny Pag", "TAIWAN GOLDEN BEE": "TGB",
}
MIXED_NAMES = {MAKE_NAMES.get(m, m.title()) for m in MIXED}
# Off-road body classes that are still motorcycles (dirt bikes), unlike ATVs and side-by-sides.
DIRT_BIKE = re.compile(r"motocross|dirt bike|enduro", re.I)
# Same bike sold under two names in the US.
FAMILY_ALIASES = {
    ("Yamaha", "fz07"): "MT-07", ("Yamaha", "fz09"): "MT-09", ("Yamaha", "fz10"): "MT-10",
    ("Yamaha", "mt07"): "MT-07", ("Yamaha", "mt09"): "MT-09", ("Yamaha", "mt10"): "MT-10",
}

# Complaints flat file: tab separated, no header, 51 fields (see cmpl/CMPL.txt). 0-based.
C = dict(ODINO=1, MAKE=3, MODEL=4, YEAR=5, CRASH=6, FAILDATE=7, FIRE=8, INJURED=9, DEATHS=10,
         COMP=11, STATE=13, VIN=14, LDATE=16, MILES=17, DESC=19, PURCH=22, ORIG_OWNER=23,
         SPEED=31, PROD_TYPE=45, REPAIRED=46, MEDICAL=47, TOWED=48)
# Recalls flat files: 29 fields (see rcl/RCL.txt). 0-based.
R = dict(ID=0, CAMPNO=1, MAKE=2, MODEL=3, YEAR=4, COMP=6, MFG=7, TYPE=10, POTAFF=11, ODATE=12,
         BY=13, RCDATE=15, DEFECT=19, CONSEQ=20, REMEDY=21, NOTES=22, DND=27, PARK=28)


def key(s):
    return re.sub(r"[^a-z0-9]", "", str(s).lower())


def make_name(m):
    return MAKE_NAMES.get(m, m.title())


def iso(d):
    d = (d or "").strip()
    return f"{d[:4]}-{d[4:6]}-{d[6:8]}" if re.fullmatch(r"(19|20)\d{6}", d) else None


def num(s):
    s = (s or "").strip()
    return int(s) if s.isdigit() else None


def yn(s):
    return {"Y": 1, "N": 0}.get((s or "").strip().upper())


def clean(s):
    return " ".join((s or "").split())


def get(url, data=None, tries=4):
    body = urllib.parse.urlencode(data).encode() if data else None
    for i in range(tries):
        try:
            with urllib.request.urlopen(urllib.request.Request(url, body, UA), timeout=120) as r:
                return r.read()
        except urllib.error.HTTPError as e:
            if 400 <= e.code < 500 and e.code != 429:  # a real answer, retrying won't change it
                return e.read()
            if i == tries - 1:
                raise
        except Exception:
            if i == tries - 1:
                raise
        time.sleep(2 * (i + 1))


def download(url, raw):
    dest = os.path.join(raw, url.rsplit("/", 1)[1])
    if os.path.exists(dest) and os.path.getsize(dest) > 1_000_000:
        print("Using cached", os.path.basename(dest))
        return dest
    print("Downloading", url, "...")
    with urllib.request.urlopen(urllib.request.Request(url, headers=UA), timeout=600) as r, \
            open(dest + ".part", "wb") as f:
        while chunk := r.read(1 << 20):
            f.write(chunk)
    os.replace(dest + ".part", dest)
    return dest


def lines(zpath):
    with zipfile.ZipFile(zpath) as z:
        name = next(n for n in z.namelist() if n.upper().endswith(".TXT"))
        with z.open(name) as fh:
            for line in io.TextIOWrapper(fh, encoding="latin-1", newline=""):
                yield line.rstrip("\r\n").split("\t")


def cached(path, compute):
    if os.path.exists(path):
        return json.load(open(path))
    out = compute()
    json.dump(out, open(path, "w"))
    return out


def vpic_moto_models(raw):
    """{MAKE: [model keys]} that vPIC lists as motorcycles, for the mixed brands."""
    def compute():
        out = defaultdict(set)
        for make in MIXED:
            print(f"Listing {make} motorcycle models", end="", flush=True)
            for y in range(FIRST_YEAR, time.localtime().tm_year + 2):
                url = f"{VPIC}GetModelsForMakeYear/make/{urllib.parse.quote(make.lower())}/modelyear/{y}/vehicletype/motorcycle?format=json"
                try:
                    for r in json.loads(get(url)).get("Results", []):
                        out[make].add(key(r.get("Model_Name", "")))
                except Exception:
                    pass
                print(".", end="", flush=True)
                time.sleep(0.1)
            print(f" {len(out[make])}")
        return {m: sorted(v) for m, v in out.items()}
    return {m: set(v) for m, v in cached(os.path.join(raw, "vpic_motorcycle_models.json"), compute).items()}


def decode_wmis(wmis, raw):
    """{WMI: True if vPIC says it builds motorcycles}. A WMI is the first 3 VIN characters."""
    path = os.path.join(raw, "vpic_wmi.json")
    have = json.load(open(path)) if os.path.exists(path) else {}
    todo = sorted(w for w in wmis if w not in have)
    if todo:
        print(f"Looking up {len(todo):,} VIN manufacturer codes...")

        def one(w):
            try:
                res = json.loads(get(f"{VPIC}DecodeWMI/{urllib.parse.quote(w)}?format=json")).get("Results", [])
                return w, any("motorcycle" in (r.get("VehicleType") or "").lower() for r in res)
            except Exception:
                return w, None
        with ThreadPoolExecutor(6) as ex:
            for i, (w, v) in enumerate(ex.map(one, todo), 1):
                if v is not None:
                    have[w] = v
                if i % 500 == 0:
                    print(f"  {i:,}/{len(todo):,}")
                    json.dump(have, open(path, "w"))
        json.dump(have, open(path, "w"))
    return have


def decode_vins(vins, raw):
    """{VIN11: [vehicle_type, make, model, series, body_class]} from vPIC's batch decoder."""
    path = os.path.join(raw, "vpic_vins.json")
    have = json.load(open(path)) if os.path.exists(path) else {}
    todo = sorted(v for v in vins if v not in have)
    if todo:
        print(f"Decoding {len(todo):,} motorcycle VINs (50 per request)...")
        batches = [todo[i:i + 50] for i in range(0, len(todo), 50)]

        def one(batch):
            try:
                res = json.loads(get(VPIC + "DecodeVINValuesBatch/",
                                     {"format": "json", "DATA": ";".join(batch)})).get("Results", [])
                return [(r["VIN"].upper(), [r.get(k) or "" for k in
                         ("VehicleType", "Make", "Model", "Series", "BodyClass")]) for r in res]
            except Exception:
                return []
        with ThreadPoolExecutor(4) as ex:
            for i, res in enumerate(ex.map(one, batches), 1):
                have.update(res)
                if i % 50 == 0:
                    print(f"  {i * 50:,}/{len(todo):,}")
                    json.dump(have, open(path, "w"))
        json.dump(have, open(path, "w"))
    return have


def name_is_moto(make, model, vpic_models):
    """Fallback when there is no usable VIN."""
    k = key(model)
    if not k or (NOT_MOTO.search(model.upper()) and not (make in MOTO_ONLY and "SCRAMBLER" in model.upper())):
        return False
    if make in MOTO_ONLY:
        return True
    if make in vpic_models:
        ms = vpic_models[make]
        return k in ms or any(len(m) >= 3 and (k.startswith(m) or m.startswith(k)) for m in ms)
    return False


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default=os.path.join(HERE, "..", "data", "nhtsa"))
    out = os.path.abspath(ap.parse_args().out)
    raw = os.path.join(out, "raw")
    os.makedirs(raw, exist_ok=True)

    cmpl = download(CMPL_ZIP, raw)
    rcls = [download(u, raw) for u in RCL_ZIPS]
    vpic_models = vpic_moto_models(raw)

    # Pass 1: every VIN manufacturer code in vehicle complaints.
    print("Reading complaints (pass 1 of 2)...")
    wmis, make_count = Counter(), Counter()
    for f in lines(cmpl):
        if len(f) > C["PROD_TYPE"] and f[C["PROD_TYPE"]] == "V":
            make_count[make_name(f[C["MAKE"]].strip().upper())] += 1
            v = f[C["VIN"]].strip().upper()
            if len(v) >= 11 and v[:3].isalnum():
                wmis[v[:3]] += 1
    wmi_moto = decode_wmis(wmis, raw)

    # Pass 2: keep candidates (motorcycle VIN code, or motorcycle by name).
    print("Reading complaints (pass 2 of 2)...")
    cand = []
    for f in lines(cmpl):
        if len(f) <= C["PROD_TYPE"] or f[C["PROD_TYPE"]] != "V":
            continue
        make, model = f[C["MAKE"]].strip().upper(), f[C["MODEL"]].strip()
        v = f[C["VIN"]].strip().upper()
        vin = v[:11] if len(v) >= 11 and wmi_moto.get(v[:3]) is not None else ""
        if vin and not wmi_moto[vin[:3]]:
            continue  # VIN says car/truck/bus
        if vin or name_is_moto(make, model, vpic_models):
            cand.append((f, make, model, vin))
    vins = decode_vins({c[3] for c in cand if c[3]}, raw)

    # Decide, and learn what each typed model name decodes to (for complaints without a VIN).
    brands = {make_name(m) for m in MOTO_ONLY | set(MIXED)} | set(VIN_MAKES.values())
    # Typed makes we don't trust over the VIN: car brands (lots of complaints, not a bike brand) and placeholders.
    not_bike = {m for m, n in make_count.items() if n >= 500 and m not in brands} | {"Unknown", "Scooter", "Motorcycle", "Other", ""}
    moto_only_names = {make_name(m) for m in MOTO_ONLY}
    vin_brands = {VIN_MAKES.get(v[1].upper()) or make_name(v[1].upper()) for v in vins.values()
                  if v[1] and v[4].lower().startswith("motorcycle")}
    kept, learned = [], defaultdict(Counter)
    for f, make, model, vin in cand:
        d = vins.get(vin) if vin else None
        body = d[4] if d else ""
        if vin and not (d and d[1]) and make_name(make) not in brands | vin_brands:
            continue  # VIN didn't decode to a maker and the typed make isn't a bike brand (e.g. "Mercury Villager")
        if body:
            if not (body.lower().startswith("motorcycle") or DIRT_BIKE.search(body)):
                continue  # ATV, side-by-side, go-kart...
            method = "vin"
        elif vin:
            if NOT_MOTO.search(model.upper()) and not (make in MOTO_ONLY and "SCRAMBLER" in model.upper()):
                continue
            method = "vin_code"
        else:
            method = "name"
        mk = make_name(make)
        if method != "vin" and not_bike_model(mk, model):
            continue  # e.g. a Honda Accord complaint whose VIN didn't decode
        if d and d[1]:
            vm = d[1].upper()
            if vm == "PIAGGIO AND VESPA":
                mk = mk if mk in ("Piaggio", "Vespa") else "Vespa"
            else:
                vmk = VIN_MAKES.get(vm) or make_name(vm)
                # Use the VIN's brand when it's a known brand; otherwise keep what the owner typed
                # (the VIN often names a contract factory, e.g. "Shandong Pioneer Motorcycle" for a ZAP).
                if mk in moto_only_names:
                    pass  # owner named a bike-only brand (e.g. Victory on a Polaris VIN, Buell on a Harley VIN)
                elif (vmk in brands and mk not in MIXED_NAMES) or mk in not_bike or mk in MIXED_NAMES:
                    mk = vmk
        if d and d[2]:
            learned[(mk, key(model))][d[2]] += 1
        kept.append((f, make, mk, model, d, method))

    generic = {"polaris", "victory", "livewire", "harleydavidson", "indian", "slingshot", "spyder"}

    def usable(vin_model, mk):
        k = key(vin_model)
        return (bool(k) and k not in generic and k != key(mk) and "motor" not in k
                and not (len(k) <= 3 and k.isalpha()))

    def family(mk, model, d):
        if d and d[1].upper() == "SPYDER":
            return "Spyder " + d[2] if usable(d[2], mk) or (d[2] and len(d[2]) <= 3) else "Spyder"
        if d and d[1].upper() == "SLINGSHOT":
            return "Slingshot"
        fam = d[2] if d and usable(d[2], mk) else ""
        if not fam and learned.get((mk, key(model))):
            seen = learned[(mk, key(model))]
            top, n = seen.most_common(1)[0]
            fam = top if usable(top, mk) and n * 2 > sum(seen.values()) else ""  # only a clear majority
        if not fam:
            fam = re.sub(r"\s+ABS$", "", model.strip(), flags=re.I)
            fam = re.sub(rf"^{re.escape(mk)}\s+", "", fam, flags=re.I) or model
            fam = fam if any(ch.islower() for ch in fam) else fam.upper()
        if mk == "Can-Am" and not re.match(r"(spyder|ryker)", fam, re.I):
            fam = "Spyder " + fam
        return FAMILY_ALIASES.get((mk, key(fam)), fam)

    # One complaint row per (ODI number, vehicle); components in their own table.
    complaints, comps = {}, defaultdict(set)
    for f, make, mk, model, d, method in kept:
        y = f[C["YEAR"]].strip()
        year = int(y) if y.isdigit() and 1900 < int(y) < 2100 else None
        odi = int(f[C["ODINO"]])
        ck = (odi, mk, model.upper(), year)
        if ck not in complaints:
            miles = num(f[C["MILES"]])
            complaints[ck] = dict(
                odi_number=odi, make=mk, make_filed=make_name(make), model_family=family(mk, model, d), model_filed=model,
                vin_model=d[2] if d else None, vin_series=d[3] if d else None,
                body_class=d[4] if d and d[4] else None, year=year,
                miles=miles if miles else None, fail_date=iso(f[C["FAILDATE"]]),
                received_date=iso(f[C["LDATE"]]), purchase_date=iso(f[C["PURCH"]]),
                crash=yn(f[C["CRASH"]]), fire=yn(f[C["FIRE"]]),
                injured=num(f[C["INJURED"]]) or 0, deaths=num(f[C["DEATHS"]]) or 0,
                speed_mph=num(f[C["SPEED"]]) or None, original_owner=yn(f[C["ORIG_OWNER"]]),
                repaired=yn(f[C["REPAIRED"]]) if len(f) > C["REPAIRED"] else None,
                medical_attention=yn(f[C["MEDICAL"]]) if len(f) > C["MEDICAL"] else None,
                towed=yn(f[C["TOWED"]]) if len(f) > C["TOWED"] else None,
                state=f[C["STATE"]].strip() or None, description=clean(f[C["DESC"]]),
                matched_by=method,
            )
        c = f[C["COMP"]].strip().title()
        if c:
            comps[ck].add(c)
    # One spelling per model ("SPYDER RS" and "Spyder RS" are the same bike): most common wins.
    spell = defaultdict(Counter)
    for c in complaints.values():
        spell[(c["make"], key(c["model_family"]))][c["model_family"]] += 1
    canon = {k: v.most_common(1)[0][0] for k, v in spell.items()}
    for c in complaints.values():
        c["model_family"] = canon[(c["make"], key(c["model_family"]))]
    if not complaints:
        sys.exit("No motorcycle complaints found. The file layout may have changed; check cmpl/CMPL.txt.")

    # Recalls: keep vehicle recalls for motorcycle brands/models.
    print("Reading recalls...")
    # Only trust complaints whose typed make agrees with the VIN, so a bike filed as "Dodge" can't pull in car recalls.
    ok = [c for c in complaints.values() if c["make_filed"] == c["make"]]
    moto_keys = ({(c["make"], key(c["model_filed"])) for c in ok if not not_bike_model(c["make"], c["model_filed"])}
                 | {(c["make"], key(c["model_family"])) for c in ok})
    moto_makes = {c["make"] for c in ok}
    moto_word = re.compile(r"\b(motorcycles?|motor cycles?|scooters?|trikes?|mopeds?)\b", re.I)
    atv_word = re.compile(r"\b(all-terrain|ATVs?|off-highway|side-by-side|snowmobiles?|watercraft|ROVs?)\b", re.I)
    recalls = []
    for path in rcls:
        for f in lines(path):
            if len(f) <= R["NOTES"] or f[R["TYPE"]].strip() != "V":
                continue
            make, model = f[R["MAKE"]].strip().upper(), f[R["MODEL"]].strip()
            mk, text = make_name(make), f[R["DEFECT"]]
            if atv_word.search(text) and not moto_word.search(text):
                continue
            if not (make in MOTO_ONLY or (mk, key(model)) in moto_keys or
                    ((make in MIXED or mk in moto_makes) and moto_word.search(text))):
                continue
            if NOT_MOTO.search(model.upper()) and not (make in MOTO_ONLY and "SCRAMBLER" in model.upper()):
                continue
            if not_bike_model(mk, model):
                continue  # car or motorhome recall under a bike brand
            y = f[R["YEAR"]].strip()
            recalls.append(dict(
                record_id=int(f[R["ID"]]), campaign=f[R["CAMPNO"]].strip(), make=mk,
                model_family=canon.get((mk, key(family(mk, model, None))), family(mk, model, None)), model_filed=model,
                year=int(y) if y.isdigit() and y != "9999" else None,
                component=f[R["COMP"]].strip().title(), manufacturer=f[R["MFG"]].strip(),
                units_affected=num(f[R["POTAFF"]]), report_date=iso(f[R["RCDATE"]]),
                owner_notified_date=iso(f[R["ODATE"]]), initiated_by=f[R["BY"]].strip(),
                defect=clean(f[R["DEFECT"]]), consequence=clean(f[R["CONSEQ"]]),
                remedy=clean(f[R["REMEDY"]]), notes=clean(f[R["NOTES"]]),
                do_not_drive=yn(f[R["DND"]]) if len(f) > R["DND"] else None,
                park_outside=yn(f[R["PARK"]]) if len(f) > R["PARK"] else None,
                nhtsa_url=f"https://www.nhtsa.gov/recalls?nhtsaId={f[R['CAMPNO']].strip()}",
            ))

    write_db(out, complaints, comps, recalls)
    print(f"\nDone. {len(complaints):,} motorcycle complaints, {len({r['campaign'] for r in recalls}):,} recall campaigns.")
    print("Files are in", out)


SCHEMA = """
CREATE TABLE complaints (
  id INTEGER PRIMARY KEY, odi_number INTEGER NOT NULL, make TEXT NOT NULL, make_filed TEXT, model_family TEXT NOT NULL,
  model_filed TEXT, vin_model TEXT, vin_series TEXT, body_class TEXT, year INTEGER, miles INTEGER,
  fail_date TEXT, received_date TEXT, purchase_date TEXT, crash INTEGER, fire INTEGER,
  injured INTEGER, deaths INTEGER, speed_mph INTEGER, original_owner INTEGER, repaired INTEGER,
  medical_attention INTEGER, towed INTEGER, state TEXT, description TEXT, matched_by TEXT
);
CREATE TABLE complaint_components (
  complaint_id INTEGER NOT NULL REFERENCES complaints(id), component TEXT NOT NULL, component_group TEXT NOT NULL
);
CREATE TABLE recalls (
  record_id INTEGER PRIMARY KEY, campaign TEXT NOT NULL, make TEXT NOT NULL, model_family TEXT NOT NULL,
  model_filed TEXT, year INTEGER, component TEXT, component_group TEXT, manufacturer TEXT,
  units_affected INTEGER, report_date TEXT, owner_notified_date TEXT, initiated_by TEXT,
  defect TEXT, consequence TEXT, remedy TEXT, notes TEXT, do_not_drive INTEGER, park_outside INTEGER, nhtsa_url TEXT
);
CREATE TABLE models (
  make TEXT, model_family TEXT, complaints INTEGER, with_mileage INTEGER, median_miles INTEGER,
  first_year INTEGER, last_year INTEGER, crashes INTEGER, injuries INTEGER, deaths INTEGER,
  recall_campaigns INTEGER, top_components TEXT, PRIMARY KEY (make, model_family)
);
CREATE TABLE meta (key TEXT PRIMARY KEY, value TEXT);
CREATE INDEX ix_c_model ON complaints(make, model_family, year);
CREATE INDEX ix_c_odi ON complaints(odi_number);
CREATE INDEX ix_cc ON complaint_components(complaint_id);
CREATE INDEX ix_cc_group ON complaint_components(component_group);
CREATE INDEX ix_r_model ON recalls(make, model_family, year);
CREATE INDEX ix_r_campaign ON recalls(campaign);
CREATE VIRTUAL TABLE complaints_search USING fts5(description, content='complaints', content_rowid='id');
"""


def group(c):
    return c.split(":")[0].strip()


def write_db(out, complaints, comps, recalls):
    path = os.path.join(out, "motorcycles.sqlite")
    tmp = path + ".tmp"
    if os.path.exists(tmp):
        os.remove(tmp)
    db = sqlite3.connect(tmp)
    db.executescript(SCHEMA)
    ccols = list(next(iter(complaints.values())).keys())
    rows = sorted(complaints.items(), key=lambda kv: (kv[1]["make"], kv[1]["model_family"], kv[1]["year"] or 0, kv[0][0]))
    for i, (ck, c) in enumerate(rows, 1):
        db.execute(f"INSERT INTO complaints (id,{','.join(ccols)}) VALUES (?{',?' * len(ccols)})",
                   [i] + [c[k] for k in ccols])
        db.executemany("INSERT INTO complaint_components VALUES (?,?,?)",
                       [(i, comp, group(comp)) for comp in sorted(comps[ck])])
    if recalls:
        rcols = list(recalls[0].keys()) + ["component_group"]
        db.executemany(f"INSERT INTO recalls ({','.join(rcols)}) VALUES ({','.join('?' * len(rcols))})",
                       [[r[k] for k in rcols[:-1]] + [group(r["component"])] for r in recalls])
    db.execute("INSERT INTO complaints_search(complaints_search) VALUES ('rebuild')")

    # Per-model summary.
    by = defaultdict(list)
    for i, (ck, c) in enumerate(rows, 1):
        by[(c["make"], c["model_family"])].append((i, ck, c))
    rec = defaultdict(set)
    for r in recalls:
        rec[(r["make"], r["model_family"])].add(r["campaign"])
    summary = []
    for (mk, fam), items in by.items():
        miles = [c["miles"] for _, _, c in items if c["miles"] and c["miles"] < 300_000]
        years = [c["year"] for _, _, c in items if c["year"]]
        groups = Counter(g for _, ck, _ in items for g in {group(x) for x in comps[ck]})
        summary.append(dict(
            make=mk, model_family=fam, complaints=len({c["odi_number"] for _, _, c in items}),
            with_mileage=len(miles), median_miles=int(statistics.median(miles)) if miles else None,
            first_year=min(years) if years else None, last_year=max(years) if years else None,
            crashes=sum(1 for _, _, c in items if c["crash"]), injuries=sum(c["injured"] for _, _, c in items),
            deaths=sum(c["deaths"] for _, _, c in items), recall_campaigns=len(rec[(mk, fam)]),
            top_components="; ".join(f"{g} ({n})" for g, n in groups.most_common(5)),
        ))
    summary.sort(key=lambda s: -s["complaints"])
    db.executemany(f"INSERT INTO models VALUES ({','.join('?' * len(summary[0]))})",
                   [list(s.values()) for s in summary])
    db.executemany("INSERT INTO meta VALUES (?,?)", [
        ("built_at", time.strftime("%Y-%m-%d %H:%M")), ("source", "NHTSA ODI flat files + vPIC"),
        ("complaints", str(len(complaints))), ("recall_rows", str(len(recalls))),
        ("note", "Owner-submitted, unverified, US-only safety complaints. Not adjusted for sales volume."),
    ])
    db.commit()
    db.execute("VACUUM")
    db.close()
    os.replace(tmp, path)

    def dump(name, sql):
        cur = sqlite3.connect(path).execute(sql)
        with open(os.path.join(out, name), "w", newline="", encoding="utf-8") as fo:
            w = csv.writer(fo)
            w.writerow([d[0] for d in cur.description])
            w.writerows(cur)
    dump("complaints.csv", """SELECT c.*, (SELECT group_concat(component, '; ') FROM complaint_components
                             WHERE complaint_id = c.id) AS components FROM complaints c ORDER BY c.id""")
    dump("recalls.csv", "SELECT * FROM recalls ORDER BY make, model_family, year")
    dump("model_summary.csv", "SELECT * FROM models ORDER BY complaints DESC")


if __name__ == "__main__":
    main()
