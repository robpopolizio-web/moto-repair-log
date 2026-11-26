"""Builds the bike catalogue: one entry per motorcycle model, with every source's data linked to it.
-> data/catalog.sqlite   (the site will build one page per row of `bikes`)

Sources (each built by its own tool first):
  data/nhtsa/motorcycles.sqlite  US complaints, recalls (+ makers' documents), investigations,
                                 Canada + Japan recalls and UK fleet (world_sources.py)
  data/mot/mot.sqlite            UK MOT families (mot_build.py)
  data/eu/eu.sqlite              EU Safety Gate alerts (eu_safety_gate.py)
  data/dvsa_recalls/RecallsFile.csv  UK DVSA recalls (downloaded by hand: bot-protected)

How bikes are formed
  1. Every NHTSA model name becomes a candidate. Trim and edition words are stripped to find the
     model it belongs to (TRIM_WORDS: "Gold Wing Tour" -> Gold Wing, "Ultra Classic 103 Shrine" ->
     Ultra Classic). Words that name a different model (Classic, Limited, Standard, R, S...) are kept.
  2. Each UK MOT family (make + name + engine size) joins the bike whose name it matches. If the bike's
     name has an engine number (Tiger 900, Vulcan 1700), the MOT engine size must agree within 15%.
     Unmatched MOT families with 100+ MOTs become bikes of their own (UK-only models).
  3. Recalls from every country, investigations and UK fleet rows join bikes by name (strict matching,
     see world_sources.Matcher). What cannot be matched safely goes to `unassigned` for review.
Every link records the source's own name and the rule that matched it, so any merge can be undone.
Run:  python3 tools/build_catalog.py
"""
import csv, json, os, re, sqlite3, sys
from collections import Counter, defaultdict

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from world_sources import tok, make_key  # noqa: E402
import factory_codes  # noqa: E402
import mot_build  # noqa: E402   (its DVSA name rules: first_word)

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
NHTSA = os.path.join(ROOT, "data", "nhtsa", "motorcycles.sqlite")
MOT = os.path.join(ROOT, "data", "mot", "mot.sqlite")
EU = os.path.join(ROOT, "data", "eu", "eu.sqlite")
DVSA = os.path.join(ROOT, "data", "dvsa_recalls", "RecallsFile.csv")
OUT = os.path.join(ROOT, "data", "catalog.sqlite")

# words that only name a trim, edition or engine option of the same model
TRIM_WORDS = {"ABS", "NON", "DCT", "SE", "SP", "TOUR", "INTERSTATE", "SHRINE", "ANNIVERSARY", "TH", "EDITION", "SPECIAL",
              "96", "103", "107", "110", "114", "117", "121", "TWIN", "COOLED", "CVO_KEEP"}
NEVER_ALONE = {"MOTORCYCLE", "MOTORCYCLES", "UNKNOWN", "OTHER", "ALL", "SCOOTER", "MOPED", "ATV"}
MAKE_DISPLAY = {"BMW": "BMW", "KTM": "KTM", "MV AGUSTA": "MV Agusta", "CFMOTO": "CFMoto", "HARLEY-DAVIDSON": "Harley-Davidson",
                "CAN-AM": "Can-Am", "GASGAS": "GasGas", "SYM": "SYM", "LIVEWIRE": "LiveWire", "AJS": "AJS",
                "BSA": "BSA", "MZ": "MZ", "CCM": "CCM", "AJP": "AJP", "SWM": "SWM", "TGB": "TGB", "LML": "LML", "WK": "WK",
                "UM": "UM", "FB MONDIAL": "FB Mondial", "MBK": "MBK", "ATK": "ATK", "AMC": "AMC", "BSA REGAL": "BSA Regal"}


# factory codes some sources use for a model known by name: (make, first word of code) -> name
CODE_ALIASES = {("HONDA", "GL"): "Gold Wing", ("HONDA", "GOLDWING"): "Gold Wing"}
# factory codes DVSA records use for bikes sold under a name (GLR125 is the CB125F, NSC110 the Vision 110)
UK_CODES = {("HONDA", "GLR"): "CB125F", ("HONDA", "NSC"): "Vision", ("HONDA", "WW"): "PCX", ("HONDA", "SH"): "SH",
            ("HONDA", "FES"): "S-Wing", ("HONDA", "NSS"): "Forza", ("HONDA", "ANF"): "Innova", ("HONDA", "SCV"): "Lead",
            ("YAMAHA", "XP"): "TMAX"}
# factory codes for bikes better known by name: joined-name regex -> replacement
SYNONYMS = {"SUZUKI": [(r"^GSF(\d)", r"BANDIT\1")], "HONDA": [(r"^CBR1100X$", "CBR1100XX"), (r"^VFR800FI$", "VFR800")]}
# variant codes after a model name; group 1 is the model. Only merged when that model exists.
VARIANT_SUFFIX = {
    "HONDA": [r"(.*\d[A-Z]*?[A-Z])[A-HJ-NPQ9]"],                         # year letter: CBF125MB = 2011 CBF125M
    "*": [r"(?!.*GSA$)(.*\d[A-Z]*?[A-Z])A", r"(.*\d.*?)ABS", r"(.*\d[A-Z]*)FI"],   # A = ABS (CB500XA), FI = fuel injection
    "SUZUKI": [r"(.*\d[A-Z]*?)[KLM]\d"],                                 # K7 = 2007, L1 = 2011
    "YAMAHA": [r"(.*\d[A-Z]?)[A-Z]{0,2}C"],                               # California models (YZFR1KC)
}
# A UK MOT family whose bikes were first registered 8+ years before (or after) every year of a model is an
# older (or newer) generation that shares the name: the 1970s Z900 is not the 2017 Z900.
ERA_GAP = 8
# UK factory-code pages under the name riders use (the code stays in the name for search)
KNOWN_AS = {("HONDA", "XL1000V"): "Varadero XL1000V", ("HONDA", "NT650V"): "Deauville NT650V",
            ("HONDA", "NT700V"): "Deauville NT700V", ("HONDA", "XL650V"): "Transalp XL650V",
            ("HONDA", "XL600V"): "Transalp XL600V", ("HONDA", "XL700V"): "Transalp XL700V",
            ("HONDA", "CB600F"): "Hornet CB600F", ("HONDA", "CBF125M"): "CBF125", ("HONDA", "FJS600"): "Silver Wing FJS600",
            ("YAMAHA", "YZF1000"): "Thunderace YZF1000R", ("YAMAHA", "YP250"): "Majesty YP250",
            ("KAWASAKI", "ER650"): "ER-6n", ("SUZUKI", "GSF650"): "Bandit 650"}
# UK MOT families whose records only give a shared word, told apart by engine size (checked by hand against
# the records' own spellings: SPEED at 860 cc is 75% "SPEEDMASTER" / "SPEED MASTER 865")
FAMILY_RULES = [("TRIUMPH", "SPEED", 850, 870, "Speedmaster"), ("TRIUMPH", "SPEED", 780, 800, "Speedmaster"),
                ("TRIUMPH", "SPEED", 870, 970, "Speed Triple"), ("TRIUMPH", "SPEED", 740, 760, "Speed Triple"),
                ("TRIUMPH", "SPEED", 1190, 1210, "Speed Twin")]
# names that start like another model's but are a different bike (Z900RS is not a trim of the Z900)
SEPARATE = {"KAWASAKI": {"Z900RS", "Z650RS"}, "TRIUMPH": {"SPEEDTWIN", "SPEEDTRIPLE"}}
# Harley-Davidson factory codes (used by DVSA, DfT and often Transport Canada) -> model names.
# A trailing I (fuel injection) is ignored: FLSTCI = FLSTC.
HD_CODES = {
    "FLHX": "Street Glide", "FLHXS": "Street Glide Special", "FLHTCU": "Electra Glide Ultra Classic",
    "FLHTK": "Electra Glide Ultra Limited", "FLHTC": "Electra Glide Classic", "FLHT": "Electra Glide Standard",
    "FLHTP": "Electra Glide Police", "FLHR": "Road King", "FLHRC": "Road King Classic", "FLHRS": "Road King Special",
    "FLTRX": "Road Glide", "FLTRXS": "Road Glide Special", "FLTRU": "Road Glide Ultra", "FLTR": "Road Glide",
    "FLHTCUTG": "Tri Glide Ultra", "FLRT": "Freewheeler", "FLSTF": "Fat Boy", "FLFB": "Fat Boy", "FLFBS": "Fat Boy",
    "FLSTFB": "Fat Boy Lo", "FLSTC": "Heritage Softail Classic", "FLHC": "Heritage Classic", "FLHCS": "Heritage Classic",
    "FLSTN": "Softail Deluxe", "FLDE": "Softail Deluxe", "FXST": "Softail Standard", "FXSTC": "Softail Custom",
    "FXSTB": "Night Train", "FXBR": "Breakout", "FXBRS": "Breakout", "FXSB": "Breakout", "FXSBSE": "CVO Breakout",
    "FLSB": "Sport Glide", "FXBB": "Street Bob", "FXBBS": "Street Bob", "FXLR": "Low Rider", "FXLRS": "Low Rider S",
    "FXLRST": "Low Rider ST", "FXFB": "Fat Bob", "FXFBS": "Fat Bob", "FXDF": "Dyna Fat Bob", "FXDWG": "Dyna Wide Glide",
    "FXDB": "Dyna Street Bob", "FXDL": "Dyna Low Rider", "FXDC": "Dyna Super Glide Custom", "FXD": "Dyna Super Glide",
    "FLD": "Dyna Switchback", "FXDBP": "Dyna Street Bob", "XL883N": "Iron 883", "XL1200X": "Forty-Eight",
    "XL1200C": "Sportster 1200 Custom", "XL1200NS": "Iron 1200", "XL1200CX": "Roadster", "XL1200V": "Seventy-Two",
    "XL883L": "Sportster SuperLow", "XL883R": "Sportster 883 Roadster", "XL883": "Sportster 883", "XLH883": "Sportster 883",
    "XL1200": "Sportster 1200", "XLH1200": "Sportster 1200", "XL1200T": "SuperLow 1200T", "RA1250": "Pan America",
    "RA1250S": "Pan America Special", "PAN": "Pan America", "RH975": "Nightster", "RH1250S": "Sportster S",
    "XG750": "Street 750", "XG500": "Street 500", "XG750A": "Street Rod", "VRSCA": "V-Rod", "VRSCF": "V-Rod Muscle",
    "VRSCDX": "Night Rod Special", "VRSCD": "Night Rod", "VRSCAW": "V-Rod", "FXSTD": "Softail Deuce",
}


def slug(s):
    return re.sub(r"[^a-z0-9]+", "-", s.lower()).strip("-")


def base_tokens(t):
    """Strip trailing trim words: ELECTRA GLIDE ULTRA CLASSIC 103 SHRINE -> ELECTRA GLIDE ULTRA CLASSIC."""
    t = list(t)
    while len(t) > 1 and (t[-1] in TRIM_WORDS or re.fullmatch(r"\d+TH", t[-1]) or (t[-1] == "ABS")):
        t.pop()
    # "NON ABS" leaves "NON"
    if len(t) > 1 and t[-1] == "NON":
        t.pop()
    # R / RS / RR / S after a word name are trims (Street Triple RS -> Street Triple), but not after a
    # number (CB1000R, ZX-10R stay) and never when only one word would be left (Monster S, GSX-R)
    if len(t) >= 3 and t[-1] in ("R", "RS", "RR", "S") and t[-2].isalpha() and len(t[-2]) >= 4:
        t.pop()
    return t


def engine_number(t):
    """An engine size written in the name (Tiger 900 -> 900, Vulcan 1700 -> 1700), or None."""
    for w in t:
        if re.fullmatch(r"\d{3,4}", w) and 49 <= int(w) <= 2500:
            return int(w)
    return None


def main():
    n = sqlite3.connect(NHTSA)
    n.row_factory = sqlite3.Row
    if os.path.exists(OUT + ".part"):
        os.remove(OUT + ".part")          # left by a failed run
    out = sqlite3.connect(OUT + ".part")
    out.executescript("""
    create table bikes (bike_id INTEGER PRIMARY KEY, make TEXT, model TEXT, slug TEXT, cc INT, origin TEXT,
      us_complaints INT DEFAULT 0, us_recalls INT DEFAULT 0, world_recalls INT DEFAULT 0, mot_tests INT DEFAULT 0,
      uk_licensed INT DEFAULT 0, investigations INT DEFAULT 0, first_year INT, last_year INT);
    create table aliases (bike_id INT, source TEXT, source_make TEXT, source_model TEXT, source_cc INT, rule TEXT);
    create table bike_us_models (bike_id INT, make TEXT, model_family TEXT, year_from INT, year_to INT);
    create table bike_family_members (family_bike_id INT, member_bike_id INT);
    create table bike_mot (bike_id INT, make TEXT, model_key TEXT, tests INT, rule TEXT);
    create table bike_recalls (bike_id INT, source TEXT, country TEXT, campaign TEXT, foreign_model TEXT, rule TEXT);
    create table bike_investigations (bike_id INT, action TEXT);
    create table bike_uk_fleet (bike_id INT, licensed INT, sorn INT, quarter TEXT);
    create table unassigned (source TEXT, make TEXT, model TEXT, cc INT, detail TEXT, weight INT);
    create table meta (key TEXT PRIMARY KEY, value TEXT);
    """)
    bikes = {}            # (make_key, base tokens tuple) -> bike dict
    index = defaultdict(list)   # make_key -> [(base tokens, bike key)]

    def add_bike(mk_disp, model_disp, origin, cc=None, era=None, umbrella=None):
        """era=(from, to) makes an older generation its own bike: it is never matched by name, only by its MOTs.
        umbrella=[bike keys]: UK records that only say "R1150" or "SPRINT" and fit several models: a family page."""
        key = (make_key(mk_disp), tuple(base_tokens(tok(model_disp))) + ((f"@{era[0]}",) if era else ()) + (("@ALL",) if umbrella else ()))
        if key not in bikes:
            bikes[key] = {"make": mk_disp, "model": model_disp, "origin": origin, "cc": cc, "names": Counter(),
                          "us": [], "mot": [], "rec": [], "inv": set(), "fleet": [0, 0, None], "years": set(),
                          "us_complaints": 0, "us_recalls": set(), "aliases": [], "era": era, "mot_years": [],
                          "umbrella": list(umbrella) if umbrella else None}
            if not era and not umbrella:
                index[key[0]].append((list(key[1]), key))
        return key

    # ---- 1. NHTSA families
    fams = defaultdict(lambda: {"complaints": 0, "years": set()})
    for r in n.execute("select make, model_family, complaints, first_year, last_year from models"):
        f = fams[(r["make"], r["model_family"])]
        f["complaints"] += r["complaints"] or 0
        f["years"] |= {y for y in (r["first_year"], r["last_year"]) if y}
    for r in n.execute("select make, model_family, campaign, year from recalls"):
        f = fams[(r["make"], r["model_family"])]
        f.setdefault("camps", set()).add(r["campaign"])
        if r["year"]:
            f["years"].add(r["year"])
    for (mk, fam), f in sorted(fams.items(), key=lambda kv: -kv[1]["complaints"]):
        t = tok(fam)
        if not t or " ".join(t) in NEVER_ALONE or " ".join(t) == " ".join(tok(mk)):
            out.execute("insert into unassigned values (?,?,?,?,?,?)", ("NHTSA", mk, fam, None, "placeholder model name", f["complaints"]))
            continue
        # display name: the shortest family name with these base tokens (Gold Wing, not Gold Wing Tour)
        key = add_bike(mk, fam, "NHTSA")
        b = bikes[key]
        if len(tok(fam)) < len(tok(b["model"])):
            b["model"] = fam
        b["us"].append((mk, fam, None, None))
        b["us_complaints"] += f["complaints"]
        b["us_recalls"] |= f.get("camps", set())
        b["years"] |= f["years"]
        b["aliases"].append(("NHTSA", mk, fam, None, "same name" if tuple(base_tokens(t)) == tuple(t) else "trim of " + " ".join(base_tokens(t)).title()))

    codes = None          # factory codes, learned once the US models exist (below)
    famy = {}             # UK MOT family -> (first-use year from, to)

    def find(make, model, cc=None, use_codes=True):
        """Bike key for a source name, or (None, reason)."""
        mt = tok(model)
        if not mt or " ".join(mt) in NEVER_ALONE:
            return None, "no model name"
        bt = base_tokens(mt)
        bt0 = list(bt)
        if make_key(make) == "HARLEY-DAVIDSON":
            code = "".join(bt[:2]) if len(bt) > 1 and bt[1].isdigit() else bt[0]
            for c in (code, re.sub(r"I$", "", code), bt[0], re.sub(r"I$", "", bt[0])):
                if c in HD_CODES:
                    bt = tok(HD_CODES[c])
                    break
        uk = UK_CODES.get((make_key(make), bt[0]))
        if uk:   # WW 125 A-P -> PCX 125, GLR 125 1WH-H -> CB125F, NSC 110 M -> Vision 110
            ut = tok(uk)
            rest = bt[1:]
            if rest and rest[0] in ut:
                rest = rest[1:]
            bt = ut + rest
        alias = CODE_ALIASES.get((make_key(make), bt[0]))
        if alias and (bt[0] == "GOLDWING" or (len(bt) > 1 and bt[1] in ("1000", "1100", "1200", "1500", "1800")) or (cc and cc >= 1000)):
            bt = tok(alias)
        coded = "code " if bt != bt0 else ""     # the name came from a code table (FLSTF -> Fat Boy)
        if codes and use_codes and factory_codes.is_code(codes.code_part(bt0)):
            # a factory code learned from records that give both wins over a name that merely starts the same
            # (ZR900BHF is a Z900, not the recall-only "ZR900"; ER650H is a Z650, not an ER-6n)
            r = codes.lookup(make_key(make), codes.code_part(bt0))
            if r and r[0] in bikes:
                en = engine_number(list(r[0][1]))
                if not (cc and en and abs(en - cc) > 0.15 * en):
                    return r[0], f"factory code {r[1]}"
        cands = sorted(index.get(make_key(make), []), key=lambda x: -len(x[0]))
        hit = None
        sep = [x for x in SEPARATE.get(make_key(make), ()) if "".join(bt).startswith(x)]
        for t, key in cands:
            if sep and len("".join(t)) < len(sep[0]):
                continue
            if bt[:len(t)] == t or "".join(t) in ["".join(bt[:k]) for k in range(1, len(bt) + 1)]:
                hit = (key, "name")
                break
        if not hit:
            for t, key in cands:
                distinctive = len(t) >= 2 and any(c.isalpha() for w in t for c in w) or (len(t) == 1 and len(t[0]) >= 5 and t[0].isalpha())
                if distinctive and any(bt[i:i + len(t)] == t for i in range(1, len(bt) - len(t) + 1)):
                    hit = (key, "name inside")
                    break
        if not hit and codes and use_codes:
            # a factory code learned from records that give both (ZR900BHF -> Z900, DL650AL2 -> V-Strom 650)
            r = codes.lookup(make_key(make), codes.code_part(bt0))
            if r and r[0] in bikes:
                key = r[0]
                en = engine_number(list(key[1]))
                if not (cc and en and abs(en - cc) > 0.15 * en):
                    return key, f"factory code {r[1]}"
        if not hit:
            cc = cc or engine_number(bt)   # "VESPA GTS 300 SUPER" says its own size
            starts = {key for t, key in cands if t[:len(bt)] == bt and len(t) > len(bt)}
            if cc and starts:
                # MT at 690 cc can only be the MT-07; YZF at 120 cc is none of R1/R3/R6/R7
                # a bike whose real engine size is known must fit it too: ZR at 810 cc is the Z800, not the Z900 (948 cc)
                starts = {k for k in starts if not (bikes[k]["cc"] and abs(bikes[k]["cc"] - cc) > 0.12 * bikes[k]["cc"])}
                size = {k: engine_number(list(k[1])) or bikes[k]["cc"] for k in starts}
                # 12% when the bike's own engine size is known, 8% for the number in its name (900 for a 948 cc Z900)
                tol = {k: 0.12 if bikes[k]["cc"] else 0.08 for k in starts}
                fit = sorted((k for k in starts if size[k] and abs(size[k] - cc) <= tol[k] * size[k]), key=lambda k: abs(size[k] - cc))
                # clearly closest wins: MT at 690 cc is the MT-07 (689), not the 2006 MT-03 (660)
                if len(fit) >= 2 and abs(size[fit[0]] - cc) <= 0.03 * cc and \
                        abs(size[fit[0]] - cc) * 3 < abs(size[fit[1]] - cc) and size[fit[0]] != size[fit[1]]:
                    fit = fit[:1]
                if len(fit) == 1:
                    return fit[0], "name + engine size"
                if not fit and all(size.values()):
                    return None, "no model with this engine size"
                if fit:
                    starts = set(fit)
            if len(starts) >= 2:
                find.cands = list(starts)
                return None, "fits several models: " + ", ".join(sorted(bikes[k]["model"] for k in starts)[:4])
            return None, "no matching model"
        key, rule = hit
        en = engine_number(list(key[1]))
        if cc and en and abs(en - cc) > 0.15 * en:
            return None, f"engine size {cc} cc does not fit {bikes[key]['model']}"
        return key, coded + rule

    # factory codes -> the US models they belong to, learned from records that give both
    pairs = factory_codes.mine(NHTSA, EU if os.path.exists(EU) else None)
    codes = factory_codes.CodeMap(pairs, lambda mk, nm: find(mk, nm, use_codes=False)[0],
                                  base=lambda nm: " ".join(w for w in nm.split() if w.upper() not in TRIM_WORDS | {"CAFÉ"}) or nm,
                                  make_key=make_key, owned=lambda k: k in bikes and bikes[k]["us_complaints"] > 0,
                                  same=lambda k, nm: list(k[1]) == base_tokens(tok(nm)))
    print(f"factory codes learned: {len(codes.map)} linked to a model, {len(codes.labels)} naming a model of their own")

    # ---- 2. UK MOT families
    if os.path.exists(MOT):
        m = sqlite3.connect(MOT)
        rows = m.execute("select make, model_key, model, cc, tests, year_from, year_to from models order by tests desc").fetchall()
        trims = defaultdict(list)
        for mk, mkey, name, t in m.execute("select make, model_key, name, tests from model_trims"):
            trims[(mk, mkey)].append((name, t))
        def span(b):
            """The years a bike covers: its US model years and the first-use years of the MOTs linked so far."""
            ys = []
            if b["years"]:
                ys += [min(b["years"]) - 2, max(b["years"]) + 1]
            for y0, y1 in b["mot_years"]:
                ys += [y0, y1]
            return (min(ys), max(ys)) if ys else None

        def other_era(key, y0, y1):
            b = bikes[key]
            # US data from only a year or two says little about when a model was sold: a modern UK family
            # (Piaggio Typhoon 50, sold since 1995) is not another generation of the 2025 US listing
            if not b["mot_years"] and b["years"] and max(b["years"]) - min(b["years"]) <= 2 and y1 and y1 >= 2010:
                return False
            sp = span(b)
            return bool(sp and y0 and y1 and (y1 < sp[0] - ERA_GAP or y0 > sp[1] + ERA_GAP))

        era_kids = defaultdict(list)    # bike -> its older/newer generations

        def link(mk, mkey, model, cc, tests, y0, y1, last):
            famy[(mk, mkey)] = (y0, y1)
            # 0a. a shared word told apart by engine size (FAMILY_RULES)
            for rmk, rname, lo, hi, target in FAMILY_RULES:
                if make_key(mk) == rmk and model.strip().upper() == rname and cc and lo <= cc <= hi:
                    k0 = add_bike(MAKE_DISPLAY.get(rmk, rmk.title()), target, "UK MOT", cc)
                    if other_era(k0, y0, y1):
                        break
                    bikes[k0]["mot"].append((mk, mkey, tests, f"family rule {rname} {lo}-{hi} cc = {target}"))
                    if y0 and y1:
                        bikes[k0]["mot_years"].append((y0, y1))
                    bikes[k0]["cc"] = bikes[k0]["cc"] or cc
                    return True
            # 0. a factory code that names a model with no US page (ZR750L = Z750)
            fj = codes.code_part(tok(model))
            if factory_codes.is_code(fj) and not codes.lookup(make_key(mk), fj):
                lb = codes.label_of(make_key(mk), fj)
                if lb:
                    # exactly that model (add_bike returns it when it exists): Z750, not the Z750S that "Z750" also starts
                    k0 = add_bike(MAKE_DISPLAY.get(make_key(mk), make_key(mk).title()), lb[1], "UK MOT", cc)
                    b0 = bikes[k0]
                    b0["mot"].append((mk, mkey, tests, f"factory code {lb[0]} = {lb[1]}"))
                    if y0 and y1:
                        b0["mot_years"].append((y0, y1))
                    b0["cc"] = b0["cc"] or cc
                    b0["aliases"].append(("UK MOT", mk, model, cc, f"factory code {lb[0]} = {lb[1]}"))
                    return True
            # 1. vote: match each full DVSA name in the family ("STREET TRIPLE R", "FLHX STREET GLIDE")
            votes, matched, by_code = Counter(), 0, Counter()
            fam_tokens = tok(model)
            for name, t in trims[(mk, mkey)]:
                if tok(name)[:len(fam_tokens) + 1] == fam_tokens:   # a bare "TIGER" says nothing about which Tiger
                    continue
                key, rule = find(mk, name, cc)
                if key:
                    votes[key] += t; matched += t
                    if rule.startswith(("code", "factory code")):
                        by_code[key] += t
            key, rule = None, ""
            fam_word = re.sub(r"[^A-Z]", "", model.upper().split()[0]) if model.strip() else ""
            if votes:
                best, v = votes.most_common(1)[0]
                bike_letters = re.sub(r"[^A-Z]", "", "".join(best[1]))
                fk, fr = find(mk, model, cc)
                # a family named after another word (TRACER) is a different model, even if its records say "MT-07 TRACER";
                # unless the family's name is a factory code of that model (FLSTF = Fat Boy, CRF1000 = Africa Twin)
                if fam_word and fam_word not in bike_letters and bike_letters not in fam_word and not (fk == best and fr.startswith(("code", "factory code"))) and by_code[best] < 0.7 * v:
                    votes = Counter()
                elif v >= 0.7 * matched and matched >= 0.25 * tests:
                    key, rule = best, f"full names ({round(100 * v / tests)}% of MOTs)"
            if not key and re.fullmatch(r"[A-Z]{1,4}", model.strip()) and cc:
                # a bare code with its engine size: "CRF" at 1000 cc is the CRF1000 (Africa Twin)
                for size in dict.fromkeys((cc, int(round(cc / 50.0)) * 50, int(round(cc / 100.0)) * 100)):
                    r = codes.lookup(make_key(mk), model.strip() + str(size))
                    if r and r[0] in bikes:
                        key, rule = r[0], f"factory code {r[1]} (name + engine size)"
                        break
                    j = model.strip() + str(size)
                    lab = [nm for (m2, c), nm in codes.labels.items() if m2 == make_key(mk) and (c == j or (c.endswith("*") and j.startswith(c[:-1])))]
                    if lab:   # a code naming a model with no US page yet: "ZR" at 810 cc is the Z800
                        key = add_bike(MAKE_DISPLAY.get(make_key(mk), make_key(mk).title()), lab[0], "UK MOT", cc)
                        rule = f"factory code {j} = {lab[0]}"
                        break
            # 2. the family name itself, with its engine size when the name has no number
            if not key and cc and not re.search(r"\d", model):
                # the bike called "<name> <number>" whose number is closest to the engine size (TIGER 1220 cc -> Tiger 1200)
                ft = tok(model)
                best = None
                for t, k2 in index.get(make_key(mk), []):
                    if len(t) == len(ft) + 1 and t[:len(ft)] == ft and t[-1].isdigit():
                        if bikes[k2]["cc"] and abs(bikes[k2]["cc"] - cc) > 0.12 * bikes[k2]["cc"]:
                            continue      # its real engine size rules it out (ZR at 810 cc is not the 948 cc Z900)
                        d = abs(int(t[-1]) - cc) / cc
                        if d <= (0.15 if bikes[k2]["cc"] else 0.08) and (best is None or d < best[0]):
                            best = (d, k2)
                # but not when a longer name with another engine size also fits (CB at 470 cc: CB450 or CB500F/X?)
                if best:
                    other = {engine_number(t) or bikes[k2]["cc"] for t, k2 in index.get(make_key(mk), [])
                             if len(t) > len(ft) + 1 and t[:len(ft)] == ft}
                    other = {e for e in other if e and abs(e - cc) <= 0.15 * cc}
                    if other - {int(best[1][1][-1])}:
                        best = None
                if best:
                    key, rule = best[1], "name + engine size"
            code = UK_CODES.get((make_key(mk), (tok(model) or [""])[0]))
            if not key and code:
                key, rule = find(mk, code, cc)
                model = code if not key else model
            if not key:
                key, rule = find(mk, model, cc)
                if key and not rule.startswith(("code", "factory code")):
                    bl = re.sub(r"[^A-Z]", "", "".join(key[1]))
                    if fam_word and fam_word not in bl and bl not in fam_word:
                        key, rule = None, "different model word"
            def loose(k):   # matched only roughly: by engine size, inside a longer name, or its number is off (M821 vs M900)
                en = engine_number([t for t in k[1] if not t.startswith("@")])
                return "engine size" in rule or rule.startswith("name inside") or bool(en and cc and abs(en - cc) > 0.05 * en)
            if key and other_era(key, y0, y1) and loose(key):
                # a loose match that is also decades apart is simply a different model (M821 is not the M900)
                key, rule = None, "no matching model"
                if tests >= 100:
                    disp_mk = MAKE_DISPLAY.get(make_key(mk), " ".join(w.capitalize() for w in make_key(mk).split()))
                    key, rule = add_bike(disp_mk, model if re.search(r"\d", model) else f"{model.title()} {cc}", "UK MOT", cc), "new UK-only model"
            if key and other_era(key, y0, y1):
                # same name, another generation: its own bike, named with its years
                if tests < 100:
                    out.execute("insert into unassigned values (?,?,?,?,?,?)", ("UK MOT", mk, model, cc, f"older/newer generation of {bikes[key]['model']}", tests))
                    return True
                b0, parent = bikes[key], key
                same = [k for k in era_kids[parent] if not other_era(k, y0, y1)]
                key = same[0] if same else add_bike(b0["make"], b0["model"], "UK MOT", cc, era=(y0, y1))
                if not same:
                    era_kids[parent].append(key)
                rule = f"generation {y0}-{y1} of {b0['model']}"
            if not key and not last and rule.startswith("fits several"):
                return False   # retry once every named model has its engine size from its own records
            name_only = rule in ("no matching model", "no model with this engine size") and \
                len(re.sub(r"[^A-Z]", "", model.upper())) >= (1 if cc else 3)      # "SH" at 125 cc is the Honda SH125
            if not key and last and rule.startswith("fits several") and tests >= 100:
                # the records only say "R1150" or "SPRINT": a family page linking the models it can be
                disp_mk = MAKE_DISPLAY.get(make_key(mk), " ".join(w.capitalize() for w in make_key(mk).split()))
                disp = model if re.search(r"\d", model) else f"{model.title() if model.isupper() and len(model) > 4 else model} {cc}"
                key, rule = add_bike(disp_mk, disp, "UK MOT family", cc, umbrella=getattr(find, "cands", [])), "family of several models"
            if not key:
                if tests >= 100 and (re.search(r"\d", model) or rule == "different model word" or name_only) and not rule.startswith("fits several"):
                    disp_mk = MAKE_DISPLAY.get(make_key(mk), " ".join(w.capitalize() for w in make_key(mk).split()))
                    best_name = max(trims[(mk, mkey)], key=lambda x: x[1])[0] if trims[(mk, mkey)] else model
                    # "Vespa 125", not "Vespa 120": the size its riders write, when the records give one
                    sizes = Counter()
                    for nm, t in trims[(mk, mkey)]:
                        for w in tok(nm):
                            if w.isdigit() and cc and abs(int(w) - cc) <= 0.12 * int(w):
                                sizes[int(w)] += t
                    size = sizes.most_common(1)[0][0] if sizes else cc
                    disp = model if re.search(r"\d", model) else f"{model.title() if model.isupper() and len(model) > 4 else model} {size}"   # Vespa 125, YZF 125
                    key, rule = add_bike(disp_mk, disp, "UK MOT", cc), "new UK-only model"
                else:
                    out.execute("insert into unassigned values (?,?,?,?,?,?)", ("UK MOT", mk, model, cc, rule or "bare name", tests))
                    return True
            b = bikes[key]
            b["mot"].append((mk, mkey, tests, rule))
            if y0 and y1:
                b["mot_years"].append((y0, y1))
            b["cc"] = b["cc"] or cc
            b["aliases"].append(("UK MOT", mk, model, cc, rule))
            return True

        later = [r for r in rows if not link(*r, last=False)]
        for r in later:
            link(*r, last=True)

    # code-named US models take the name their code stands for, findable by it from here on (ZR900C -> Z900RS)
    for k, b in list(bikes.items()):
        j = "".join(k[1])
        if b.get("era") or b.get("umbrella") or not factory_codes.is_code(j) or codes.lookup(k[0], j):
            continue
        lb = codes.label_of(k[0], j)
        if lb:
            index[k[0]].append((base_tokens(tok(lb[1])), k))

    def find_any(make, name):
        """A recall's model text: as written, without its brackets, or the code in them ("ROAD STAR (XV1600)")."""
        tries = [name]
        if "(" in name:
            tries += [re.sub(r"\(.*?\)", " ", name).strip()] + re.findall(r"\((.*?)\)", name)
        rule = ""
        for t in tries:
            if t.strip():
                key, rule = find(make, t)
                if key:
                    return key, rule
        return None, rule

    # ---- 3. recalls from other countries, investigations, UK fleet
    for src, country, camp, mk, model in n.execute("select source, country, campaign, make, model from world_recalls"):
        names = [x.strip() for x in re.split(r"\s*/\s*|\n|,\s*", model or "") if x.strip()] or [model or ""]
        done = set()
        for name in names:
            for mm in (mk or "").split("/"):
                key, rule = find_any(mm, name)
                if key and key not in done:
                    done.add(key)
                    bikes[key]["rec"].append((src, country, camp, name, rule))
                    bikes[key]["aliases"].append((src, mm, name, None, rule))
        if not done:
            out.execute("insert into unassigned values (?,?,?,?,?,?)", (src, mk, model, None, f"recall {camp}", 1))
    for act, mk, model in n.execute("select distinct action, make, model from investigations"):
        key, rule = find(mk, model)
        if key:
            bikes[key]["inv"].add(act)
    fleet_left = defaultdict(lambda: [0, 0, None])
    for mk, gen, model, lic, sorn, q in n.execute("select make, gen_model, model, licensed, sorn, quarter from uk_fleet"):
        clean = re.sub(r"\b(E[345]5?|EURO ?[345])\b", "", model or "", flags=re.I).strip()     # emission tags
        key, rule = find(mk, clean)
        if not key:
            # DVLA writes Honda-style codes with ABS and year letters: "CBF 125 NA-J" = CBF125N, "NC 750 XA-P" = NC750X
            fw = mot_build.first_word(clean)
            if fw and fw != "".join(tok(clean)):
                key, rule = find(mk, fw)
        if not key and gen.upper().startswith(mk.upper()):
            key, rule = find(mk, gen[len(mk):])
        if key:
            f = bikes[key]["fleet"]
            f[0] += lic or 0; f[1] += sorn or 0; f[2] = q
        elif (lic or 0) >= 200 and "MODEL MISSING" not in (model or "").upper():
            fleet_left[(make_key(mk), clean.upper())][0] += lic or 0
            fleet_left[(make_key(mk), clean.upper())][1] += sorn or 0
            fleet_left[(make_key(mk), clean.upper())][2] = q
    # what is left is mostly models too new for an MOT (first test at 3 years) and not sold in the US
    for (mk, model), (lic, sorn, q) in sorted(fleet_left.items(), key=lambda kv: -kv[1][0]):
        out.execute("insert into unassigned values (?,?,?,?,?,?)", ("UK fleet", mk, model, None, "licensed bikes", lic))

    # ---- EU Safety Gate
    if os.path.exists(EU):
        e = sqlite3.connect(EU)
        for case, brand, name, typ, desc, country in e.execute(
                "select caseNumber, brand, name, type_numberOfModel, description, notifyingCountry from alerts"):
            done = set()
            # the model is in the name, or else in the type field or description ("PCX125: JF28...", "XL883, XL1200C")
            chunks = []
            for field in (name, typ, desc):
                parts = [c.strip() for c in re.split(r"\s*(?:[,;/:()]|\band\b|\bmodels?\b)\s*", field or "") if c.strip()]
                chunks += parts
                if done or any(find(brand or "", c)[0] for c in parts):
                    break
            for nm in chunks:
                if len(nm) > 40 or not re.search(r"[A-Za-z]", nm):
                    continue
                key, rule = find(brand or "", nm)
                if key and key not in done:
                    done.add(key)
                    bikes[key]["rec"].append(("EU Safety Gate", country, case, nm, rule))
                    bikes[key]["aliases"].append(("EU Safety Gate", brand, nm, None, rule))
            if not done:
                out.execute("insert into unassigned values (?,?,?,?,?,?)", ("EU Safety Gate", brand, name, None, f"alert {case}", 1))

    # UK DVSA recalls come in through world_recalls (tools/world_sources.py)

    # ---- 4. merge names that are the same bike
    # Sources name one model differently: a factory code (GSF600 = Bandit 600), a shorter form of the
    # name (ZX-6R = Ninja ZX-6R, R6 = YZF-R6), or a variant code (CB500XA = CB500X with ABS,
    # GSF1250SAK7 = 2007 GSF1250SA, YZFR1KC = Yamaha's California R1). Merge them into one bike.
    def canon(b):
        t = [w for w in tok(re.sub(r"\(.*?\)", " ", b["model"])) if w != "REDUNDANT"]
        j = "".join(base_tokens(t))
        for pat, rep in SYNONYMS.get(make_key(b["make"]), []):
            j = re.sub(pat, rep, j)
        return j

    fwd = {}      # merged bike -> the bike it went into

    def merge_into(dst, src):
        for k_, v_ in list(bikes.items()):
            if v_ is src:
                fwd[k_] = next(k2 for k2, v2 in bikes.items() if v2 is dst)
                break
        for f in ("us", "mot", "rec", "aliases", "mot_years"):
            dst[f] += src[f]
        for f in ("inv", "years", "us_recalls"):
            dst[f] |= src[f]
        dst["names"] += src["names"]
        dst["us_complaints"] += src["us_complaints"]
        dst["fleet"][0] += src["fleet"][0]; dst["fleet"][1] += src["fleet"][1]
        dst["fleet"][2] = dst["fleet"][2] or src["fleet"][2]
        dst["cc"] = dst["cc"] or src["cc"]
        if dst["origin"] != "NHTSA" and src["origin"] == "NHTSA":
            dst["origin"] = "NHTSA"

    merged, merge_log = 0, []
    def us_named(k):
        return bikes[k]["origin"] == "NHTSA" and bikes[k]["us_complaints"] > 0

    # bikes named by a factory code: join the model the code belongs to (ZR900 -> Z900, GSX1300R -> Hayabusa),
    # or take the name the code stands for when that model has no bike yet (ZR900C -> Z900RS)
    labels = defaultdict(list)
    for (mk, code), name in codes.labels.items():
        labels[mk].append((code, name))
    for mk in labels:
        labels[mk].sort(key=lambda x: -len(x[0]))
    for k in list(bikes):
        if k not in bikes or bikes[k].get("era"):
            continue
        j = "".join(k[1])
        if not factory_codes.is_code(j):
            continue
        r = codes.lookup(k[0], j)
        if r and r[0] != k and r[0] in bikes and not (us_named(k) and us_named(r[0])):
            merge_log.append((bikes[k]["make"], bikes[k]["model"], bikes[r[0]]["model"]))
            merge_into(bikes[r[0]], bikes.pop(k))
            merged += 1
            continue
        for code, name in labels.get(k[0], []):
            c = code.rstrip("*")
            if j.startswith(c) and len(j) - len(c) <= 5:
                bikes[k]["aliases"].append(("factory code", bikes[k]["make"], bikes[k]["model"], None, f"named {name}"))
                bikes[k]["model"] = name
                break
    for _ in range(4):   # chains: GSF1250SAK7 -> GSF1250SA -> GSF1250S -> Bandit 1250S
        by = defaultdict(dict)
        ctoks = {}
        for key, b in bikes.items():
            if b.get("era") or b.get("umbrella"):     # an older generation or a family page keeps its own page
                continue
            by[make_key(b["make"])].setdefault(canon(b), []).append(key)
            ctoks[key] = [w for w in base_tokens(tok(re.sub(r"\(.*?\)", " ", b["model"]))) if w != "REDUNDANT"]
        target = {}
        def plan(group, prefer):
            # never merge two US models that both have their own complaints (Shadow Spirit vs Shadow Aero)
            if sum(us_named(k) for k in group) > 1:
                return
            def plain(k):   # the name is already the one people use (Bandit 400, not GSF400; CBR1100XX, not CBR1100X)
                return "".join(ctoks[k]) == canon(bikes[k]) and not bikes[k]["model"].lower().startswith("redundant")
            keep = max(prefer, key=lambda k: (plain(k), us_named(k), bikes[k]["origin"] == "NHTSA", sum(x[2] for x in bikes[k]["mot"])))
            for k in group:
                if k != keep and k not in target and keep not in target and k not in target.values():
                    target[k] = keep
        for mk, names in by.items():
            for j, keys in names.items():
                if len(keys) > 1:                                   # same name once brackets and trims go
                    plan(keys, keys)
                if not (re.search(r"\d", j) and re.search(r"[A-Z]", j)):
                    continue
                for cut in VARIANT_SUFFIX.get(mk, []) + VARIANT_SUFFIX["*"]:
                    m = re.fullmatch(cut, j)
                    if m and m.group(1) in names and m.group(1) != j:
                        plan(keys + names[m.group(1)], names[m.group(1)])   # keep the plain model name
                        break
                else:
                    # a shorter form of a longer name: ZX-6R = Ninja ZX-6R, R6 = YZF-R6, T100 = Bonneville T100.
                    # The extra part must be a word of 3+ letters (not C90 = XC90, Z650 = KZ650).
                    # Compared word by word, so M800 is not the end of V-STROM 800.
                    mine = ctoks[keys[0]]
                    longer = [j2 for j2 in names if j2 != j and any(
                        len(t2) > len(mine) and t2[-len(mine):] == mine and all(w.isalpha() and len(w) >= 3 for w in t2[:-len(mine)])
                        for t2 in (ctoks[k] for k in names[j2]))]
                    if len(longer) == 1:
                        plan(keys + names[longer[0]], names[longer[0]])
        if not target:
            break
        for k, keep in target.items():
            if k in bikes and keep in bikes:
                merge_log.append((bikes[k]["make"], bikes[k]["model"], bikes[keep]["model"]))
                merge_into(bikes[keep], bikes.pop(k))
                merged += 1
    print(f"merged {merged} duplicate names")

    def follow(k):
        seen = set()
        while k in fwd and k not in seen:
            seen.add(k); k = fwd[k]
        return k

    # ---- 5. family pages whose models turned out to be one bike after merging fold into it
    for k in [k for k, b in bikes.items() if b.get("umbrella")]:
        members = {follow(m) for m in bikes[k]["umbrella"]} & set(bikes)
        if len(members) == 1:
            dst = next(iter(members))
            merge_log.append((bikes[k]["make"], bikes[k]["model"], bikes[dst]["model"]))
            u = bikes.pop(k); u["umbrella"] = None
            merge_into(bikes[dst], u)
        else:
            bikes[k]["umbrella"] = sorted(members)

    # ---- 6. one engine size per page
    # A page whose UK records come in clearly different engine sizes (Gold Wing GL1000 ... GL1800, Tiger 800 /
    # 955 / 1200, Africa Twin CRF1000 / CRF1100) is split: each size joins the model with that number in its
    # name, or gets its own page. US complaints and recalls follow by model year when the years do not overlap.
    cyears = defaultdict(Counter)            # (make, US family) -> model year -> complaints
    for mk_, fam_, y_, k_ in n.execute("select make, model_family, year, count(*) from complaints group by 1, 2, 3"):
        cyears[(mk_, fam_)][y_] += k_
    ryears = defaultdict(set)               # (make, US family) -> {(model year, campaign)}
    for mk_, fam_, y_, c_ in n.execute("select make, model_family, year, campaign from recalls"):
        ryears[(mk_, fam_)].add((y_, c_))

    def fcc(x):
        return int(x[1].split("|")[1] or 0)

    def no_number(name):
        return re.sub(r"\s*\b\d{2,4}\b", "", name).strip()

    def nice(name):           # "AGILITY" -> "Agility", "K SERIES" -> "K Series"; codes stay as written
        return " ".join(w.capitalize() if w.isalpha() and w.isupper() and len(w) > 2 else w for w in name.split())

    def words(tokens):        # tokens without engine numbers: F 650 GS -> F GS
        return [t for t in tokens if not t.isdigit() and not t.startswith("@")]

    split_log = []
    for key in list(bikes):
        b = bikes.get(key)
        if not b or b.get("umbrella") or len(b["mot"]) < 2:
            continue
        tot = sum(x[2] for x in b["mot"])
        clusters = []
        def era_of(x):
            return famy.get((x[0], x[1])) or (None, None)
        for x in sorted(b["mot"], key=lambda x: (fcc(x), era_of(x)[0] or 0)):
            c, (e0, e1) = fcc(x), era_of(x)
            # same size within 5%, and not decades apart (Tiger 885 of 1993-2003 vs Tiger 900 of 2020)
            hit = next((cl for cl in clusters if c and cl["last"] and abs(c - cl["topcc"]) <= 0.05 * c and
                        not (e0 and cl["e"][0] and (e1 < cl["e"][0] - 5 or e0 > cl["e"][1] + 5))), None)
            if hit:
                hit["f"].append(x); hit["last"] = c
                if x[2] > hit["top"]:
                    hit["topcc"] = c                            # compared with its biggest family's size and years
                    if e0:
                        hit["e"] = (e0, e1)
                    hit["top"] = x[2]
            else:
                clusters.append({"f": [x], "last": c, "e": (e0, e1), "top": x[2], "topcc": c})
        for cl in clusters:
            cl["t"] = sum(x[2] for x in cl["f"])
            top = max(cl["f"], key=lambda x: x[2])
            cl["cc"], cl["code"] = fcc(top), top[1].split("|")[0]
            # registration years of its biggest family (stray old records in small ones would stretch it)
            sp = famy.get((top[0], top[1]))
            cl["span"] = sp if sp and sp[0] else None
        big = [cl for cl in clusters if cl["t"] >= 300 and (cl["t"] >= 0.05 * tot or cl["t"] >= 1000) and cl["cc"]]
        if len(big) < 2:
            continue
        main = max(big, key=lambda cl: cl["t"])
        base = [t for t in key[1] if not t.startswith("@")]
        en_main = engine_number(base) or engine_number(tok(b["model"]))
        if en_main and abs(en_main - main["cc"]) > 0.1 * en_main:
            # the name's own number decides which size is this page (Vision 110 keeps the 110, not the 50)
            near = [cl for cl in big if abs(cl["cc"] - en_main) <= 0.1 * en_main]
            if near:
                main = max(near, key=lambda cl: cl["t"])
        # a code names the size unless it only repeats the page's number (V-Strom 1000 / DL1000: use its years)
        named_code = lambda cl: factory_codes.is_code(cl["code"]) and cl["code"] not in "".join(base) and \
            not (en_main and str(en_main) in cl["code"])
        parts_ = [(key, main["span"])] if main["span"] else []      # (bike, registration years) of each size
        renamed_main = False
        def sibling(cl):
            best = None
            for k2, b2 in bikes.items():
                if k2 == key or b2.get("era") or b2.get("umbrella") or k2[0] != key[0]:
                    continue
                t2 = [t for t in k2[1] if not t.startswith("@")]
                if words(t2) != words(base):     # same name apart from the number: Tiger 1200, F 800 GS
                    continue
                e2 = engine_number(t2)
                if cl["span"] and other_era(k2, *cl["span"]):
                    continue          # that model is another generation
                if e2 and abs(e2 - cl["cc"]) <= 0.04 * e2 and (best is None or len(t2) < best[0]):
                    best = (len(t2), k2)
            return best

        order = [main] + [cl for cl in big if cl is not main]
        for cl in order:
            if cl is main and en_main:
                continue
            # 1. a model with this engine size in its name (Tiger at 1220 cc -> Tiger 1200; the Tiger 800 too)
            dest = None
            best = sibling(cl)
            if best:
                dest = best[1]
                if cl is main:       # its biggest size has its own model: the next size is this page's own
                    rest = [c2 for c2 in big if c2 is not main and not sibling(c2)]
                    keep_ = max(rest, key=lambda c2: c2["t"]) if rest else None
                    if keep_:
                        order.remove(keep_)
            elif cl is main:
                continue             # the page keeps its biggest size unless a model is named for it
            else:
                bm = nice(b["model"])
                apart = cl["span"] and main["span"] and (cl["span"][1] < main["span"][0] or cl["span"][0] > main["span"][1])
                other_engine = en_main and abs(cl["cc"] - en_main) > 0.25 * en_main
                if named_code(cl):          # Gold Wing GL1500, Africa Twin CRF1100
                    nm = f"{no_number(bm) if en_main else bm} {cl['code']}"
                elif other_engine:          # Vision 110 -> Vision 50
                    nm = f"{no_number(bm)} {cl['cc']}"
                elif apart:                 # another generation: Tiger (1999-2006), V-Strom 1000 (2014-2019)
                    nm = f"{bm} ({cl['span'][0]}-{cl['span'][1]})"
                elif en_main:
                    nm = f"{no_number(bm)} {cl['cc']}"
                else:                       # sold alongside: X9 (about 460 cc); sizes are recorded to 10 cc
                    nm = f"{bm} (about {cl['cc']} cc)"
                dest = add_bike(b["make"], nm, "UK MOT", cl["cc"])
                if bikes[dest].get("era") or bikes[dest].get("umbrella") or dest == key:
                    continue
            d = bikes[dest]
            for x in cl["f"]:
                b["mot"].remove(x)
                d["mot"].append(x[:3] + (x[3] + f"; engine size split from {b['model']}",))
            d["cc"] = d["cc"] or cl["cc"]
            if cl["span"]:
                parts_.append((dest, cl["span"]))
            split_log.append((b["make"], b["model"], cl["code"], cl["cc"], cl["t"], d["model"]))
        # US model years go to the size whose UK registration years hold them; the nearest when none does;
        # the page's own size when several do (Tiger 800 and 1200 were sold side by side)
        if len(parts_) > 1 and b["us"]:
            def owner(y):
                if y is None:
                    return key
                inside = [k_ for k_, (a_, z_) in parts_ if a_ <= y <= z_]
                if len(inside) == 1:
                    return inside[0]
                if inside:
                    return key
                return min(parts_, key=lambda p_: min(abs(y - p_[1][0]), abs(y - p_[1][1])))[0]
            newus = defaultdict(list)
            for mk_, fam_, y0_, y1_ in b["us"]:
                ys_ = sorted(({y_ for y_ in cyears[(mk_, fam_)]} | {y_ for y_, _ in ryears[(mk_, fam_)]}) - {None})
                ys_ = [y_ for y_ in ys_ if y_ and (y0_ is None or y_ >= y0_) and (y1_ is None or y_ <= y1_)]
                if not ys_:
                    newus[key].append((mk_, fam_, y0_, y1_)); continue
                # contiguous runs of years with one owner become one range; the ends stay open
                runs, prev = [], None
                for y_ in ys_:
                    o_ = owner(y_)
                    if runs and runs[-1][0] == o_:
                        runs[-1][2] = y_
                    else:
                        runs.append([o_, y_, y_])
                for i_, (o_, a_, z_) in enumerate(runs):
                    lo_ = y0_ if i_ == 0 else a_
                    hi_ = y1_ if i_ == len(runs) - 1 else runs[i_ + 1][1] - 1
                    newus[o_].append((mk_, fam_, lo_, hi_))
            b["us"] = newus.pop(key, [])
            for o_, lst in newus.items():
                bikes[o_]["us"] += lst
        if named_code(main) and not en_main and not renamed_main and any(s[1] == b["model"] for s in split_log):
            b["model"] = f"{b['model']} {main['code']}"         # Gold Wing -> Gold Wing GL1800
            renamed_main = True
    for b in bikes.values():
        b["mot_years"] = [famy[(x[0], x[1])] for x in b["mot"] if famy.get((x[0], x[1]), (None,))[0]]
        b["us_complaints"] = sum(v for mk_, fam_, y0_, y1_ in b["us"] for y_, v in cyears[(mk_, fam_)].items()
                                 if (y0_ is None or (y_ or 0) >= y0_) and (y1_ is None or (y_ or 0) <= y1_))
        b["us_recalls"] = {c_ for mk_, fam_, y0_, y1_ in b["us"] for y_, c_ in ryears[(mk_, fam_)]
                           if (y0_ is None or (y_ or 0) >= y0_) and (y1_ is None or (y_ or 0) <= y1_)}
        yy = [y_ for mk_, fam_, y0_, y1_ in b["us"] for y_ in cyears[(mk_, fam_)]
              if y_ and (y0_ is None or y_ >= y0_) and (y1_ is None or y_ <= y1_)]
        if b["us"] and not b.get("era"):
            b["years"] = set(yy) or b["years"]
    print(f"engine-size splits: {len(split_log)}")
    out.execute("create table splits (make TEXT, from_model TEXT, family TEXT, cc INT, tests INT, to_model TEXT)")
    out.executemany("insert into splits values (?,?,?,?,?,?)", split_log)
    out.execute("create table merges (make TEXT, merged_name TEXT, into_name TEXT)")
    out.executemany("insert into merges values (?,?,?)", merge_log)

    # ---- write
    bid = 0
    used_slugs = set()
    ids = {}
    for key, b in sorted(bikes.items(), key=lambda kv: (kv[1]["make"], kv[1]["model"])):
        bid += 1
        if b["model"].isupper() and len(b["model"]) > 3:      # "TIGER 1050 ABS SE" -> "Tiger 1050"
            base = [t for t in key[1] if not t.startswith("@")]
            raw = b["model"].split()
            keep = [w for w in raw if any(w.upper().replace("-", "") == "".join(tok(w)) and t in tok(w) for t in base)] or raw
            b["model"] = " ".join(w if re.search(r"\d", w) else w.capitalize() for w in keep[:max(1, len(base))])
        b["model"] = KNOWN_AS.get((make_key(b["make"]), b["model"]), b["model"])
        if b.get("umbrella"):     # "BMW R1150 (all versions)"
            b["model"] = f"{b['model']} (all versions)"
        if b.get("era"):          # an older generation sharing the name: "Z900 (1972-1981)"
            y0, y1 = min(y for y, _ in b["mot_years"]), max(y for _, y in b["mot_years"])
            b["model"] = f"{b['model']} ({y0}-{y1})"
            b["years"] = {y0, y1}
        s = f"{slug(b['make'])}/{slug(b['model'])}"
        while s in used_slugs:
            s += "-2"
        used_slugs.add(s)
        ys = sorted(b["years"])
        out.execute("insert into bikes values (?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                    (bid, b["make"], b["model"], s, b["cc"], b["origin"], b["us_complaints"], len(b["us_recalls"]),
                     len({(x[0], x[2]) for x in b["rec"]}), sum(x[2] for x in b["mot"]), b["fleet"][0], len(b["inv"]),
                     ys[0] if ys else None, ys[-1] if ys else None))
        out.executemany("insert into aliases values (?,?,?,?,?,?)", [(bid,) + a for a in b["aliases"]])
        out.executemany("insert into bike_us_models values (?,?,?,?,?)", [(bid,) + u for u in b["us"]])
        ids[key] = bid
        out.executemany("insert into bike_mot values (?,?,?,?,?)", [(bid,) + x for x in b["mot"]])
        out.executemany("insert into bike_recalls values (?,?,?,?,?,?)", [(bid,) + x for x in b["rec"]])
        out.executemany("insert into bike_investigations values (?,?)", [(bid, a) for a in sorted(b["inv"])])
        if b["fleet"][2]:
            out.execute("insert into bike_uk_fleet values (?,?,?,?)", (bid,) + tuple(b["fleet"]))
    for key, b in bikes.items():
        for m_ in b.get("umbrella") or []:
            if m_ in ids:
                out.execute("insert into bike_family_members values (?,?)", (ids[key], ids[m_]))
    # the learned factory codes, with the records that taught them (for review)
    out.execute("create table factory_codes (make TEXT, code TEXT, bike_model TEXT, label TEXT, evidence TEXT)")
    for (mk, code), key in codes.map.items():
        out.execute("insert into factory_codes values (?,?,?,?,?)", (mk, code, " ".join(key[1]), codes.labels.get((mk, code)),
                    "; ".join(sorted({f"{s_} = {n_}" for s_, n_ in codes.evidence[(mk, code)]})[:6])))
    for (mk, code), lab in codes.labels.items():
        if (mk, code) not in codes.map:
            out.execute("insert into factory_codes values (?,?,?,?,?)", (mk, code, None, lab, None))
    out.execute("insert into meta values ('built_at', datetime('now'))")
    out.commit()
    out.close()
    os.replace(OUT + ".part", OUT)
    c = sqlite3.connect(OUT)
    print(c.execute("select count(*), sum(us_complaints>0), sum(mot_tests>0), sum(world_recalls>0), sum(us_complaints>0 and mot_tests>0) from bikes").fetchone(),
          "= bikes, with US complaints, with MOT, with foreign recalls, with both US and MOT")
    for src, k, w in c.execute("select source, count(*), sum(weight) from unassigned group by source"):
        print(f"  unassigned {src}: {k} rows (weight {w})")


if __name__ == "__main__":
    sys.exit(main())
