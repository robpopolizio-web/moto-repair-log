"""Builds UK MOT reliability stats per motorcycle model -> data/mot/mot.sqlite

Input: data/mot/moto/test_result_YYYY.csv.gz and test_item_YYYY.csv.gz (tools/mot_download.py) and
the DVSA lookup tables in data/mot/raw/lookup/.

Definitions (also shown on the site's methodology page):
  * An "annual MOT" is a bike's first normal test (type NT) in a calendar year. Retests and
    abandoned/aborted tests are left out, so a bike that fails and is fixed counts once, as a fail.
  * "Failed first time" = the annual MOT's result was F (fail) or PRS (failed, but fixed and passed
    while still at the test station).
  * "Failed on X" = the annual MOT had at least one fail or dangerous item in X. Advisories are
    counted separately. Shares are per MOT, not shares of all faults.
  * Age = test year minus first-use year. Mileage = odometer at the test, when recorded in miles.
  * A model's class is its engine size band, so each model is compared with bikes of similar size.

Run:  python3 tools/mot_build.py
"""
import csv, glob, gzip, os, re, sqlite3, sys
from collections import Counter, defaultdict

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from parts import CATEGORIES  # noqa: E402

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SRC = os.path.join(ROOT, "data", "mot", "moto")
LOOK = os.path.join(ROOT, "data", "mot", "raw", "lookup")
DB = os.path.join(ROOT, "data", "mot", "mot.sqlite")

E, EL, BAT, FUEL, COOL, CG, FD, BR, SS, WB, FB, ED, OTHER = CATEGORIES

# MOT item path (root > ... > leaf, lower case) -> (part name, category). First match wins.
# Part names are the site's names from tools/parts.py wherever the same part exists.
RULES = [
    (r"brake.*(pad|lining)", "Brake pads", BR), (r"brake.*(disc|drum|back plate)", "Brake disc", BR),
    (r"brake.*(hose|pipe)", "Brake hose or line", BR), (r"brake.*(caliper|cylinder)", "Brake caliper", BR),
    (r"master cylinder|fluid reservoir|brake fluid", "Brake master cylinder", BR),
    (r"brake.*(pedal|lever)", "Brake lever or pedal", BR), (r"brake.*(cable|rod|linkage|clevis|pivot|reaction)", "Brake cable or linkage", BR),
    (r"\babs\b|anti-lock|antilock", "ABS", BR), (r"brake.*(performance|efficiency|test)", "Brake performance", BR),
    (r"brake", "Brakes", BR),
    (r"stop lamp|brake lamp|stop light", "Brake light", EL), (r"headlamp|headlight", "Headlight", EL),
    (r"direction indicator|indicator|hazard", "Turn signal", EL), (r"rear lamp|tail|position lamp|front lamp", "Tail light", EL),
    (r"registration plate lamp|number plate lamp", "Number plate light", EL), (r"reflector", "Reflectors", EL),
    (r"horn|audible warning", "Horn", EL), (r"wiring|electrical|battery", "Wiring", EL), (r"lamp|light|signalling", "Lights", EL),
    (r"tyre", "Tyre", WB), (r"wheel bearing", "Wheel bearing", WB), (r"spoke", "Wheel spokes", WB), (r"wheel|rim|hub", "Wheel", WB),
    (r"steering head|head bearing|head race", "Steering head", SS), (r"handlebar|grip", "Handlebar", SS),
    (r"fork|front suspension", "Front suspension (forks)", SS), (r"shock absorber|damper", "Rear shock", SS),
    (r"swinging arm|swingarm|suspension arm", "Swingarm", SS), (r"spring", "Suspension springs", SS),
    (r"steering", "Steering", SS), (r"suspension", "Suspension", SS),
    (r"drive chain|chain guard|sprocket", "Chain or belt", FD), (r"drive belt|belt guard", "Chain or belt", FD),
    (r"drive system|final drive|shaft", "Final drive", FD),
    (r"exhaust|silencer|noise|emission", "Exhaust", E), (r"engine mounting", "Engine mounts", E),
    (r"throttle|twist grip", "Throttle", E), (r"clutch", "Clutch lever", CG),
    (r"fuel cap", "Fuel cap", FUEL), (r"fuel.*(hose|pipe)", "Fuel hose or line", FUEL), (r"fuel|tank", "Fuel tank", FUEL),
    (r"footrest|foot rest", "Footrests", FB), (r"seat", "Seat", FB), (r"stand", "Side or centre stand", FB),
    (r"mirror", "Mirror", FB), (r"sidecar", "Sidecar", FB), (r"structure|frame|body|mudguard|fairing|attachment", "Frame", FB),
    (r"riding control|driving control|control", "Riding controls", FB),
    (r"registration plate|reg plate|number plate|vin|identification", "Number plate and ID", OTHER),
]


def item_map():
    """rfr_id -> (part, category) for motorcycle classes 1 and 2."""
    groups = {}
    for r in csv.DictReader(open(os.path.join(LOOK, "item_group.csv"), encoding="utf-8", errors="replace"), delimiter="|"):
        if r["test_class_id"] in ("1", "2"):
            groups[(r["test_item_set_section_id"], r["test_item_id"])] = r

    def path(sec, iid):
        out, seen = [], set()
        while (sec, iid) in groups and iid not in seen and iid != "0":
            seen.add(iid)
            g = groups[(sec, iid)]
            out.append(g["item_name"].strip())
            iid = g["parent_id"]
        return " > ".join(reversed(out)).lower()

    out = {}
    for r in csv.DictReader(open(os.path.join(LOOK, "item_detail.csv"), encoding="utf-8", errors="replace"), delimiter="|"):
        if r["test_class_id"] not in ("1", "2"):
            continue
        p = path(r["test_item_set_section_id"], r["test_item_id"]) + " > " + (r["rfr_desc"] or "").lower()
        for pat, part, cat in RULES:
            if re.search(pat, p):
                out[r["rfr_id"]] = (part, cat)
                break
        else:
            out.setdefault(r["rfr_id"], ("Other", OTHER))
    return out


def first_word(model):
    w = (model or "").strip().upper().split()
    return re.sub(r"[^A-Z0-9-]+", "", w[0]) if w else ""


def norm_word(w, cc=0):
    """Name for comparing records; the display keeps the most common real spelling.
    MT-07, MT07, MT07-ABS, MT-07A -> MT07;  MT10-SP -> MT10;  TIGER1050 at 1050 cc -> TIGER.
    Other letters after the number are kept, so CB125F and CB125R stay different bikes."""
    w = w.replace("-", "")
    w = re.sub(r"(?<=\d)(ABS|SP|SE|A)$", "", w) or w
    m = re.fullmatch(r"([A-Z]+)(\d{3,4})", w)
    if m and cc and abs(int(m.group(2)) - cc) <= 0.1 * cc:
        w = m.group(1)
    return w


def cc10(cc):
    try:
        return int(round(float(cc) / 10.0)) * 10
    except (TypeError, ValueError):
        return 0


FAMILY = {}   # (make, first word, cc10) -> (family name, family cc); filled by build_families()


def build_families(paths):
    """A model family is (make, first word of the DVSA model name, engine size).
    1. Names are compared without hyphens or an "ABS" suffix (MT-07 = MT07 = MT07-ABS).
    2. Engine sizes of one name within 3% of each other are one engine (CB1300: 1280 and 1300 cc).
    3. A bare name ("MT" at 690 cc) is merged into a longer name that starts with it ("MT-07") when
       that one holds at least 80% of the longer names' MOTs at the same engine size.
    The family is shown under its most common spelling and engine size."""
    cnt = Counter()
    for path in paths:
        with gzip.open(path, "rt", encoding="utf-8", errors="replace") as f:
            cols = f.readline().rstrip("\n").split("|")
            ix = {c: i for i, c in enumerate(cols)}
            mi, mo, ci = ix["make"], ix["model"], ix.get("cylinder_capacity")
            for line in f:
                p = line.rstrip("\n").split("|")
                if len(p) == len(cols):
                    cnt[(p[mi].strip().upper(), first_word(p[mo]), cc10(p[ci]) if ci is not None else 0)] += 1
    # 1 + 2: (make, normalised word) -> clusters of engine sizes
    spell = defaultdict(Counter)                 # (make, nword) -> spelling counts
    sizes = defaultdict(Counter)                 # (make, nword) -> cc counts
    for (mk, fw, c), n in cnt.items():
        nw = norm_word(fw, c)
        spell[(mk, nw)][fw] += n
        sizes[(mk, nw)][c] += n
    cc_of = {}                                   # (make, nword, cc) -> canonical cc
    for key, ccs in sizes.items():
        groups = []
        for c in sorted(ccs):
            if groups and c and groups[-1][-1] and (c - groups[-1][-1]) <= 0.03 * c:
                groups[-1].append(c)
            else:
                groups.append([c])
        for g in groups:
            top = max(g, key=lambda x: ccs[x])
            for c in g:
                cc_of[key + (c,)] = top
    # 3: bare names -> longer names at the same (canonical) engine size
    at = defaultdict(Counter)                    # (make, cc) -> nword -> MOTs
    for (mk, fw, c), n in cnt.items():
        nw = norm_word(fw, c)
        at[(mk, cc_of[(mk, nw, c)])][nw] += n
    target = {}
    for (mk, c), words in at.items():
        for nw in words:
            longer = {w: n for w, n in words.items() if w != nw and w.startswith(nw)}
            t = nw
            if longer:
                best, n = max(longer.items(), key=lambda kv: kv[1])
                if n >= 0.8 * sum(longer.values()):
                    t = best
            target[(mk, nw, c)] = t
    members = defaultdict(Counter)             # family -> spellings of its own records
    fam_of = {}
    for (mk, fw, c), n in cnt.items():
        nw = norm_word(fw, c)
        cc = cc_of[(mk, nw, c)]
        fam = (mk, target[(mk, nw, cc)], cc)
        fam_of[(mk, fw, c)] = fam
        members[fam][fw] += n
    for key, fam in fam_of.items():
        # show the most common spelling that carries a number ("CB1300" over a bare "CB")
        sp = members[fam]
        named = [w for w, _ in sp.most_common() if re.search(r"\d", w)]
        FAMILY[key] = (named[0] if named and sp[named[0]] >= 0.05 * sum(sp.values()) else sp.most_common(1)[0][0], fam[2])
    return len(cnt)


def model_key(make, model, cc):
    mk, fw, c = (make or "").strip().upper(), first_word(model), cc10(cc)
    fam, c = FAMILY.get((mk, fw, c), (fw, c))
    return mk, f"{fam}|{c}" if fam else ""


def cc_band(cc):
    try:
        cc = int(float(cc))
    except (TypeError, ValueError):
        return None
    if cc <= 0:
        return None
    return "up to 125 cc" if cc <= 125 else "126-500 cc" if cc <= 500 else "501-900 cc" if cc <= 900 else "over 900 cc"


AGE_BANDS = [(0, 3, "0-3 years"), (4, 6, "4-6 years"), (7, 10, "7-10 years"), (11, 15, "11-15 years"), (16, 200, "16+ years")]
MILE_BANDS = [(0, 4999, "under 5k mi"), (5000, 9999, "5-10k mi"), (10000, 19999, "10-20k mi"), (20000, 39999, "20-40k mi"),
              (40000, 10 ** 7, "40k+ mi")]


def band(v, bands):
    for lo, hi, name in bands:
        if lo <= v <= hi:
            return name
    return None


def main():
    rfr = item_map()
    S = lambda: {"tests": 0, "fails": 0, "vehicles": set(), "miles": Counter(), "cat": Counter(), "part": Counter(), "adv": Counter(),
                 "age": defaultdict(lambda: [0, 0]), "mile": defaultdict(lambda: [0, 0]), "year": defaultdict(lambda: [0, 0, Counter()]),
                 "names": Counter(), "cc": Counter(), "makes": Counter()}
    print(f"model families: {build_families(sorted(glob.glob(os.path.join(SRC, 'test_result_*.csv.gz'))))} raw make/model/size names", flush=True)
    models = defaultdict(S)
    classes = defaultdict(S)
    years_done = []
    for rpath in sorted(glob.glob(os.path.join(SRC, "test_result_*.csv.gz"))):
        year = rpath[-11:-7]
        ipath = os.path.join(SRC, f"test_item_{year}.csv.gz")
        if not os.path.exists(ipath):
            continue
        # annual MOT per vehicle: its first NT test that year
        first = {}
        with gzip.open(rpath, "rt", encoding="utf-8", errors="replace") as f:
            cols = f.readline().rstrip("\n").split("|")
            ix = {c: i for i, c in enumerate(cols)}
            for line in f:
                p = line.rstrip("\n").split("|")
                if len(p) < len(cols) or p[ix["test_type"]] != "NT" or p[ix["test_result"]] not in ("P", "F", "PRS"):
                    continue
                vid, date = p[ix["vehicle_id"]], p[ix["test_date"]]
                if vid not in first or date < first[vid][0]:
                    first[vid] = (date, p)
        keep = {p[ix["test_id"]]: (vid, p) for vid, (d, p) in first.items()}
        fails = defaultdict(set)   # test_id -> set of (kind, part, cat)
        with gzip.open(ipath, "rt", encoding="utf-8", errors="replace") as f:
            icols = f.readline().rstrip("\n").split("|")
            iix = {c: i for i, c in enumerate(icols)}
            for line in f:
                p = line.rstrip("\n").split("|")
                tid = p[iix["test_id"]]
                if tid not in keep:
                    continue
                kind = p[iix["rfr_type_code"]]
                dang = "dangerous_mark" in iix and p[iix["dangerous_mark"]] == "D"
                part, cat = rfr.get(p[iix["rfr_id"]], ("Other", OTHER))
                k = "F" if kind in ("F", "P") or dang else "A" if kind == "A" else None
                if k:
                    fails[tid].add((k, part, cat))
        for tid, (vid, p) in keep.items():
            mk, mkey = model_key(p[ix["make"]], p[ix["model"]], p[ix["cylinder_capacity"]] if "cylinder_capacity" in ix else None)
            if not mkey or mkey.split("|")[0] in ("UNCLASSIFIED", "UNKNOWN", "OTHER", "MODELMISSING"):
                continue
            failed = p[ix["test_result"]] in ("F", "PRS")
            try:
                fu = int(p[ix["first_use_date"]][:4])
                age = int(year) - fu
            except (ValueError, IndexError):
                fu, age = None, None
            try:
                miles = int(float(p[ix["test_mileage"]]))
            except (ValueError, IndexError):
                miles = None
            if miles is not None and not (0 < miles < 300000):
                miles = None
            cb = cc_band(p[ix["cylinder_capacity"]]) if "cylinder_capacity" in ix else None
            if "fuel_type" in ix and p[ix["fuel_type"]] in ("EL",):
                cb = "electric"
            items = fails.get(tid, set())
            for st in (models[(mk, mkey)], classes[cb] if cb else None):
                if st is None:
                    continue
                st["tests"] += 1
                st["fails"] += failed
                st["vehicles"].add(vid)
                if miles:
                    st["miles"][miles // 100] += 1
                for c in {c for k, _, c in items if k == "F"}:
                    st["cat"][c] += 1
                for pt in {pt for k, pt, _ in items if k == "F"}:
                    st["part"][pt] += 1
                for pt in {pt for k, pt, _ in items if k == "A"}:
                    st["adv"][pt] += 1
                if age is not None and 0 <= age < 100:
                    a = band(age, AGE_BANDS); st["age"][a][0] += 1; st["age"][a][1] += failed
                if miles:
                    b = band(miles, MILE_BANDS); st["mile"][b][0] += 1; st["mile"][b][1] += failed
                if fu:
                    y = st["year"][fu]; y[0] += 1; y[1] += failed
                    if miles:
                        y[2][miles // 100] += 1
            st = models[(mk, mkey)]
            st["names"][p[ix["model"]].strip().upper()] += 1
            st["makes"][p[ix["make"]].strip().upper()] += 1
            if cb:
                st["cc"][cb] += 1
        years_done.append(year)
        print(f"{year}: {len(keep):,} annual motorcycle MOTs", flush=True)

    def med(hist):
        """Median from a Counter of 100-mile buckets."""
        n = sum(hist.values())
        if not n:
            return None
        run = 0
        for b in sorted(hist):
            run += hist[b]
            if run * 2 >= n:
                return b * 100 + 50

    con = sqlite3.connect(DB + ".part")
    con.executescript("""
    create table models (make TEXT, model_key TEXT, model TEXT, cc INT, cc_band TEXT, tests INT, vehicles INT, fail_rate REAL,
      median_miles INT, PRIMARY KEY (make, model_key));
    create table model_parts (make TEXT, model_key TEXT, kind TEXT, part TEXT, category TEXT, tests INT, rate REAL);
    create table model_bands (make TEXT, model_key TEXT, band_type TEXT, band TEXT, tests INT, fail_rate REAL);
    create table model_years (make TEXT, model_key TEXT, first_use_year INT, tests INT, fail_rate REAL, median_miles INT);
    create table model_trims (make TEXT, model_key TEXT, name TEXT, tests INT);
    create table classes (cc_band TEXT PRIMARY KEY, tests INT, vehicles INT, fail_rate REAL, median_miles INT);
    create table class_parts (cc_band TEXT, kind TEXT, part TEXT, category TEXT, tests INT, rate REAL);
    create table class_bands (cc_band TEXT, band_type TEXT, band TEXT, tests INT, fail_rate REAL);
    create table meta (key TEXT PRIMARY KEY, value TEXT);
    """)
    cat_of = {pt: c for pt, c in rfr.values()}

    def write(prefix, key, st):
        for kind, ctr in (("fail", st["part"]), ("advisory", st["adv"])):
            for pt, n in ctr.items():
                con.execute(f"insert into {prefix}_parts values ({','.join('?' * (len(key) + 5))})",
                            key + (kind, pt, cat_of.get(pt, OTHER), n, n / st["tests"]))
        for c, n in st["cat"].items():
            con.execute(f"insert into {prefix}_parts values ({','.join('?' * (len(key) + 5))})",
                        key + ("fail_category", c, c, n, n / st["tests"]))
        for bt, d in (("age", st["age"]), ("mileage", st["mile"])):
            for b, (t, fl) in d.items():
                con.execute(f"insert into {prefix}_bands values ({','.join('?' * (len(key) + 4))})", key + (bt, b, t, fl / t))

    for (mk, mkey), st in models.items():
        if st["tests"] < 30:
            continue
        name = mkey.split("|")[0]
        for nm, k in st["names"].most_common(25):
            con.execute("insert into model_trims values (?,?,?,?)", (mk, mkey, nm, k))
        cb = st["cc"].most_common(1)[0][0] if st["cc"] else None
        con.execute("insert into models values (?,?,?,?,?,?,?,?,?)",
                    (mk, mkey, name, int(mkey.split("|")[1]) or None, cb, st["tests"], len(st["vehicles"]), st["fails"] / st["tests"], med(st["miles"])))
        write("model", (mk, mkey), st)
        for y, (t, fl, ms) in st["year"].items():
            if t >= 10:
                con.execute("insert into model_years values (?,?,?,?,?,?)", (mk, mkey, y, t, fl / t, med(ms)))
    for cb, st in classes.items():
        con.execute("insert into classes values (?,?,?,?,?)", (cb, st["tests"], len(st["vehicles"]), st["fails"] / st["tests"], med(st["miles"])))
        write("class", (cb,), st)
    con.execute("insert into meta values ('years', ?)", (",".join(years_done),))
    con.execute("insert into meta values ('built_at', datetime('now'))")
    con.commit()
    con.close()
    os.replace(DB + ".part", DB)
    print(f"models with 30+ MOTs: {sum(1 for s in models.values() if s['tests'] >= 30):,}; years {', '.join(years_done)}")


if __name__ == "__main__":
    sys.exit(main())
