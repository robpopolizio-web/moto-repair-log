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
                "CAN-AM": "Can-Am", "GASGAS": "GasGas", "SYM": "SYM", "LIVEWIRE": "LiveWire", "AJS": "AJS"}


# factory codes some sources use for a model known by name: (make, first word of code) -> name
CODE_ALIASES = {("HONDA", "GL"): "Gold Wing", ("HONDA", "GOLDWING"): "Gold Wing"}
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
    out = sqlite3.connect(OUT + ".part")
    out.executescript("""
    create table bikes (bike_id INTEGER PRIMARY KEY, make TEXT, model TEXT, slug TEXT, cc INT, origin TEXT,
      us_complaints INT DEFAULT 0, us_recalls INT DEFAULT 0, world_recalls INT DEFAULT 0, mot_tests INT DEFAULT 0,
      uk_licensed INT DEFAULT 0, investigations INT DEFAULT 0, first_year INT, last_year INT);
    create table aliases (bike_id INT, source TEXT, source_make TEXT, source_model TEXT, source_cc INT, rule TEXT);
    create table bike_us_models (bike_id INT, make TEXT, model_family TEXT);
    create table bike_mot (bike_id INT, make TEXT, model_key TEXT, tests INT, rule TEXT);
    create table bike_recalls (bike_id INT, source TEXT, country TEXT, campaign TEXT, foreign_model TEXT, rule TEXT);
    create table bike_investigations (bike_id INT, action TEXT);
    create table bike_uk_fleet (bike_id INT, licensed INT, sorn INT, quarter TEXT);
    create table unassigned (source TEXT, make TEXT, model TEXT, cc INT, detail TEXT, weight INT);
    create table meta (key TEXT PRIMARY KEY, value TEXT);
    """)
    bikes = {}            # (make_key, base tokens tuple) -> bike dict
    index = defaultdict(list)   # make_key -> [(base tokens, bike key)]

    def add_bike(mk_disp, model_disp, origin, cc=None):
        key = (make_key(mk_disp), tuple(base_tokens(tok(model_disp))))
        if key not in bikes:
            bikes[key] = {"make": mk_disp, "model": model_disp, "origin": origin, "cc": cc, "names": Counter(),
                          "us": [], "mot": [], "rec": [], "inv": set(), "fleet": [0, 0, None], "years": set(),
                          "us_complaints": 0, "us_recalls": set(), "aliases": []}
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
        b["us"].append((mk, fam))
        b["us_complaints"] += f["complaints"]
        b["us_recalls"] |= f.get("camps", set())
        b["years"] |= f["years"]
        b["aliases"].append(("NHTSA", mk, fam, None, "same name" if tuple(base_tokens(t)) == tuple(t) else "trim of " + " ".join(base_tokens(t)).title()))

    def find(make, model, cc=None):
        """Bike key for a source name, or (None, reason)."""
        mt = tok(model)
        if not mt or " ".join(mt) in NEVER_ALONE:
            return None, "no model name"
        bt = base_tokens(mt)
        if make_key(make) == "HARLEY-DAVIDSON":
            code = "".join(bt[:2]) if len(bt) > 1 and bt[1].isdigit() else bt[0]
            for c in (code, re.sub(r"I$", "", code), bt[0], re.sub(r"I$", "", bt[0])):
                if c in HD_CODES:
                    bt = tok(HD_CODES[c])
                    break
        alias = CODE_ALIASES.get((make_key(make), bt[0]))
        if alias and (bt[0] == "GOLDWING" or (len(bt) > 1 and bt[1] in ("1000", "1100", "1200", "1500", "1800")) or (cc and cc >= 1000)):
            bt = tok(alias)
        cands = sorted(index.get(make_key(make), []), key=lambda x: -len(x[0]))
        hit = None
        for t, key in cands:
            if bt[:len(t)] == t or "".join(t) in ["".join(bt[:k]) for k in range(1, len(bt) + 1)]:
                hit = (key, "name")
                break
        if not hit:
            for t, key in cands:
                distinctive = len(t) >= 2 and any(c.isalpha() for w in t for c in w) or (len(t) == 1 and len(t[0]) >= 5 and t[0].isalpha())
                if distinctive and any(bt[i:i + len(t)] == t for i in range(1, len(bt) - len(t) + 1)):
                    hit = (key, "name inside")
                    break
        if not hit:
            starts = {key for t, key in cands if t[:len(bt)] == bt and len(t) > len(bt)}
            if len(starts) >= 2:
                return None, "fits several models: " + ", ".join(sorted(bikes[k]["model"] for k in starts)[:4])
            return None, "no matching model"
        key, rule = hit
        en = engine_number(list(key[1]))
        if cc and en and abs(en - cc) > 0.15 * en:
            return None, f"engine size {cc} cc does not fit {bikes[key]['model']}"
        return key, rule

    # ---- 2. UK MOT families
    if os.path.exists(MOT):
        m = sqlite3.connect(MOT)
        rows = m.execute("select make, model_key, model, cc, tests from models order by tests desc").fetchall()
        trims = defaultdict(list)
        for mk, mkey, name, t in m.execute("select make, model_key, name, tests from model_trims"):
            trims[(mk, mkey)].append((name, t))
        for mk, mkey, model, cc, tests in rows:
            # 1. vote: match each full DVSA name in the family ("STREET TRIPLE R", "FLHX STREET GLIDE")
            votes, matched = Counter(), 0
            fam_tokens = tok(model)
            for name, t in trims[(mk, mkey)]:
                if tok(name)[:len(fam_tokens) + 1] == fam_tokens:   # a bare "TIGER" says nothing about which Tiger
                    continue
                key, rule = find(mk, name, cc)
                if key:
                    votes[key] += t; matched += t
            key, rule = None, ""
            fam_word = re.sub(r"[^A-Z]", "", model.upper().split()[0]) if model.strip() else ""
            if votes:
                best, v = votes.most_common(1)[0]
                bike_letters = re.sub(r"[^A-Z]", "", "".join(best[1]))
                # a family named after another word (TRACER) is a different model, even if its records say "MT-07 TRACER"
                if fam_word and fam_word not in bike_letters and bike_letters not in fam_word:
                    votes = Counter()
                elif v >= 0.7 * matched and matched >= 0.25 * tests:
                    key, rule = best, f"full names ({round(100 * v / tests)}% of MOTs)"
            # 2. the family name itself, with its engine size when the name has no number
            if not key and cc and not re.search(r"\d", model):
                # the bike called "<name> <number>" whose number is closest to the engine size (TIGER 1220 cc -> Tiger 1200)
                ft = tok(model)
                best = None
                for t, k2 in index.get(make_key(mk), []):
                    if len(t) == len(ft) + 1 and t[:len(ft)] == ft and t[-1].isdigit():
                        d = abs(int(t[-1]) - cc) / cc
                        if d <= 0.15 and (best is None or d < best[0]):
                            best = (d, k2)
                if best:
                    key, rule = best[1], "name + engine size"
            if not key:
                key, rule = find(mk, model, cc)
                if key:
                    bl = re.sub(r"[^A-Z]", "", "".join(key[1]))
                    if fam_word and fam_word not in bl and bl not in fam_word:
                        key, rule = None, "different model word"
            if not key:
                if tests >= 100 and (re.search(r"\d", model) or rule == "different model word") and not rule.startswith("fits several"):
                    disp_mk = MAKE_DISPLAY.get(mk, " ".join(w.capitalize() for w in mk.split()))
                    best_name = max(trims[(mk, mkey)], key=lambda x: x[1])[0] if trims[(mk, mkey)] else model
                    disp = model if re.search(r"\d", model) else f"{model.title()} {cc}"
                    key, rule = add_bike(disp_mk, disp, "UK MOT", cc), "new UK-only model"
                else:
                    out.execute("insert into unassigned values (?,?,?,?,?,?)", ("UK MOT", mk, model, cc, rule or "bare name", tests))
                    continue
            b = bikes[key]
            b["mot"].append((mk, mkey, tests, rule))
            b["cc"] = b["cc"] or cc
            b["aliases"].append(("UK MOT", mk, model, cc, rule))

    # ---- 3. recalls from other countries, investigations, UK fleet
    for src, country, camp, mk, model in n.execute("select source, country, campaign, make, model from world_recalls"):
        names = [x.strip() for x in re.split(r"\s*/\s*|\n|,\s*", model or "") if x.strip()] or [model or ""]
        done = set()
        for name in names:
            for mm in (mk or "").split("/"):
                key, rule = find(mm, name)
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
    for mk, gen, model, lic, sorn, q in n.execute("select make, gen_model, model, licensed, sorn, quarter from uk_fleet"):
        key, rule = find(mk, model)
        if not key and gen.upper().startswith(mk.upper()):
            key, rule = find(mk, gen[len(mk):])
        if key:
            f = bikes[key]["fleet"]
            f[0] += lic or 0; f[1] += sorn or 0; f[2] = q
        elif (lic or 0) >= 200 and "MODEL MISSING" not in (model or "").upper():
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

    # ---- write
    bid = 0
    used_slugs = set()
    for key, b in sorted(bikes.items(), key=lambda kv: (kv[1]["make"], kv[1]["model"])):
        bid += 1
        s = f"{slug(b['make'])}/{slug(b['model'])}"
        while s in used_slugs:
            s += "-2"
        used_slugs.add(s)
        if b["model"].isupper() and len(b["model"]) > 3:      # "TIGER 1050 ABS SE" -> "Tiger 1050"
            base = list(key[1])
            raw = b["model"].split()
            keep = [w for w in raw if any(w.upper().replace("-", "") == "".join(tok(w)) and t in tok(w) for t in base)] or raw
            b["model"] = " ".join(w if re.search(r"\d", w) else w.capitalize() for w in keep[:max(1, len(base))])
        ys = sorted(b["years"])
        out.execute("insert into bikes values (?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                    (bid, b["make"], b["model"], s, b["cc"], b["origin"], b["us_complaints"], len(b["us_recalls"]),
                     len({(x[0], x[2]) for x in b["rec"]}), sum(x[2] for x in b["mot"]), b["fleet"][0], len(b["inv"]),
                     ys[0] if ys else None, ys[-1] if ys else None))
        out.executemany("insert into aliases values (?,?,?,?,?,?)", [(bid,) + a for a in b["aliases"]])
        out.executemany("insert into bike_us_models values (?,?,?)", [(bid,) + u for u in b["us"]])
        out.executemany("insert into bike_mot values (?,?,?,?,?)", [(bid,) + x for x in b["mot"]])
        out.executemany("insert into bike_recalls values (?,?,?,?,?,?)", [(bid,) + x for x in b["rec"]])
        out.executemany("insert into bike_investigations values (?,?)", [(bid, a) for a in sorted(b["inv"])])
        if b["fleet"][2]:
            out.execute("insert into bike_uk_fleet values (?,?,?,?)", (bid,) + tuple(b["fleet"]))
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
