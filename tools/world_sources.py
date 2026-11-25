"""Loads the non-US sources into data/nhtsa/motorcycles.sqlite and links them to our model pages.

  world_recalls        Canada (Transport Canada VRDB, 1975 on) and Japan (MLIT, 2011 on) motorcycle recalls
  world_recall_models  which of our (make, model_family) each recall row matches
  uk_fleet             motorcycles licensed / SORN in Great Britain by make and model (DfT VEH0120, latest quarter)
  uk_fleet_models      which of our models each UK fleet row matches
  investigation_models which of our models each NHTSA investigation row matches (nhtsa_investigations.py)

Matching is deliberately strict: same make, and the other country's model name is our model name
or starts with it as whole words ("VULCAN 1700 VAQUERO ABS" matches "Vulcan 1700", but "GL1800"
does not match "Gold Wing"). Unmatched rows stay in the tables for later work.

Inputs: data/canada/vrdb_full_monthly.csv, data/mlit/mlit.sqlite (tools/mlit_recalls.py),
data/dvla/df_VEH0120_GB.csv.   Run:  python3 tools/world_sources.py
"""
import csv, os, re, sqlite3, sys, unicodedata
from collections import defaultdict

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DB = os.path.join(ROOT, "data", "nhtsa", "motorcycles.sqlite")
CANADA = os.path.join(ROOT, "data", "canada", "vrdb_full_monthly.csv")
MLIT = os.path.join(ROOT, "data", "mlit", "mlit.sqlite")
VEH0120 = os.path.join(ROOT, "data", "dvla", "df_VEH0120_GB.csv")

MAKE_ALIASES = {
    "INDIAN MOTORCYCLE": "INDIAN", "INDIAN MOTORCYCLE COMPANY": "INDIAN", "HARLEY DAVIDSON": "HARLEY-DAVIDSON",
    "H-D": "HARLEY-DAVIDSON", "GAS GAS": "GASGAS", "MOTO-GUZZI": "MOTO GUZZI", "CF MOTO": "CFMOTO",
    "ROYAL-ENFIELD": "ROYAL ENFIELD", "M.V. AGUSTA": "MV AGUSTA", "MV": "MV AGUSTA", "BRP": "CAN-AM",
    "ZERO MOTORCYCLES": "ZERO", "TRIUMPH MOTORCYCLES": "TRIUMPH", "BMW MOTORRAD": "BMW",
}


# factory codes other countries use for a model NHTSA files under its name: (make, first word) -> family
MODEL_ALIASES = {("HONDA", "GL"): "Gold Wing", ("HONDA", "GOLDWING"): "Gold Wing"}


def tok(s):
    s = unicodedata.normalize("NFKC", s or "").upper()
    s = re.sub(r"(?<=[A-Z])(?=\d)|(?<=\d)(?=[A-Z])", " ", s)   # CB1000R -> CB 1000 R
    return re.sub(r"[^A-Z0-9]+", " ", s).split()


def make_key(m):
    m = " ".join(tok(m)).replace("HARLEY DAVIDSON", "HARLEY-DAVIDSON").replace("CAN AM", "CAN-AM")
    return MAKE_ALIASES.get(m, m)


class Matcher:
    def __init__(self, con):
        self.by_make = defaultdict(list)
        for mk, fam in con.execute("select make, model_family from models union select make, model_family from recalls"):
            t = tok(fam)
            if t and " ".join(t) not in (" ".join(tok(mk)), "MOTORCYCLE", "MOTORCYCLES", "UNKNOWN", "OTHER", "ALL"):
                self.by_make[make_key(mk)].append((t, mk, fam))
        for k in self.by_make:   # longest name first, so "VULCAN 1700 VAQUERO" beats "VULCAN 1700"
            self.by_make[k].sort(key=lambda x: -len(x[0]))

    def match(self, make, model):
        """Our (make, family) for one foreign model name, or None."""
        mt = tok(model)
        if not mt:
            return None
        cands = self.by_make.get(make_key(make), [])
        alias = MODEL_ALIASES.get((make_key(make), mt[0]))
        if alias and len(mt) > 1 and mt[1] in ("1000", "1100", "1200", "1500", "1800") or (alias and mt[0] == "GOLDWING"):
            for t, mk, fam in cands:
                if fam == alias:
                    return mk, fam
        for t, mk, fam in cands:
            if mt[:len(t)] == t:
                return mk, fam
        # same words written together or apart ("GOLDWING 1800" ~ "Gold Wing")
        joined = ["".join(mt[:k]) for k in range(1, len(mt) + 1)]
        for t, mk, fam in cands:
            if "".join(t) in joined:
                return mk, fam
        return None


def main():
    con = sqlite3.connect(DB)
    m = Matcher(con)
    con.executescript("""
    drop table if exists world_recalls; drop table if exists world_recall_models;
    drop table if exists uk_fleet; drop table if exists uk_fleet_models; drop table if exists investigation_models;
    create table world_recalls (source TEXT, country TEXT, campaign TEXT, date TEXT, make TEXT, model TEXT, year INT,
      system TEXT, description TEXT, units INT, url TEXT);
    create table world_recall_models (source TEXT, campaign TEXT, make TEXT, model_family TEXT, foreign_model TEXT, year INT);
    create table uk_fleet (make TEXT, gen_model TEXT, model TEXT, fuel TEXT, licensed INT, sorn INT, quarter TEXT);
    create table uk_fleet_models (make TEXT, model_family TEXT, licensed INT, sorn INT, quarter TEXT);
    create table investigation_models (action TEXT, make TEXT, model_family TEXT);
    """)

    # ---- Canada
    n = hit = 0
    for r in csv.DictReader(open(CANADA, encoding="utf-8", errors="replace")):
        if r["CATEGORY_ETXT"] != "Motorcycle":
            continue
        n += 1
        camp, yr = r["RECALL_NUMBER_NUM"], int(float(r["YEAR"])) if r["YEAR"] else None
        units = int(float(r["UNIT_AFFECTED_NBR"])) if r["UNIT_AFFECTED_NBR"] else None
        con.execute("insert into world_recalls values (?,?,?,?,?,?,?,?,?,?,?)",
                    ("Transport Canada", "Canada", camp, r["RECALL_DATE_DTE"][:10], r["MAKE_NAME_NM"], r["MODEL_NAME_NM"], yr,
                     r["SYSTEM_TYPE_ETXT"], r["COMMENT_ETXT"].strip(), units,
                     f"https://wwwapps.tc.gc.ca/Saf-Sec-Sur/7/VRDB-BDRV/search-recherche/detail.aspx?lang=eng&rn={camp}"))
        got = m.match(r["MAKE_NAME_NM"], r["MODEL_NAME_NM"])
        if got:
            hit += 1
            con.execute("insert into world_recall_models values (?,?,?,?,?,?)",
                        ("Transport Canada", camp, got[0], got[1], r["MODEL_NAME_NM"], yr))
    print(f"Canada: {n} motorcycle recall rows, {hit} matched to our models")

    # ---- Japan
    n = hit = 0
    mcon = sqlite3.connect(MLIT)
    for url, y, mo, d, make, models, camp, defect, units, maker in mcon.execute(
            "select pdf_url, year, month, day, make, models, campaign, defect, units, manufacturer from recalls"):
        n += 1
        date = f"{y}-{mo:02d}-{d:02d}" if y and mo and d else (str(y) if y else None)
        mk = make.split("/")[0]
        con.execute("insert into world_recalls values (?,?,?,?,?,?,?,?,?,?,?)",
                    ("MLIT", "Japan", camp or url.rsplit("/", 1)[-1], date, mk, models, None, None, defect, units, url))
        names = [x.strip() for x in re.split(r"\s*/\s*|\n|,\s*", models or "") if x.strip()]
        found = set()
        for name in names:
            for mm in make.split("/"):
                got = m.match(mm, name)
                if got and got not in found:
                    found.add(got)
                    con.execute("insert into world_recall_models values (?,?,?,?,?,?)",
                                ("MLIT", camp or url.rsplit("/", 1)[-1], got[0], got[1], name, None))
        hit += bool(found)
    print(f"Japan: {n} motorcycle recalls, {hit} matched to our models")

    # ---- UK fleet (latest quarter)
    rows = csv.reader(open(VEH0120, encoding="utf-8", errors="replace"))
    head = next(rows)
    q = head[6]
    agg = defaultdict(lambda: [0, 0])
    for r in rows:
        if r[0] != "Motorcycles":
            continue
        v = int(r[6]) if r[6].isdigit() else 0
        agg[(r[1], r[2], r[3], r[4])][0 if r[5] == "Licensed" else 1] += v
    fam = defaultdict(lambda: [0, 0])
    for (mk, gen, model, fuel), (lic, sorn) in agg.items():
        con.execute("insert into uk_fleet values (?,?,?,?,?,?,?)", (mk, gen, model, fuel, lic, sorn, q))
        got = m.match(mk, model) or m.match(mk, gen[len(mk):].strip() if gen.upper().startswith(mk.upper()) else gen)
        if got:
            fam[got][0] += lic; fam[got][1] += sorn
    for (mk, f), (lic, sorn) in fam.items():
        con.execute("insert into uk_fleet_models values (?,?,?,?,?)", (mk, f, lic, sorn, q))
    tot = sum(a[0] for a in agg.values())
    print(f"UK fleet {q}: {tot:,} licensed motorcycles in {len(agg):,} make/model rows; "
          f"{len(fam)} of our models matched ({sum(v[0] for v in fam.values()):,} bikes)")

    # ---- NHTSA investigations -> our models
    if con.execute("select 1 from sqlite_master where name='investigations'").fetchone():
        seen = set()
        for act, mk, model in con.execute("select action, make, model from investigations").fetchall():
            got = m.match(mk, model)
            if got and (act, got) not in seen:
                seen.add((act, got))
                con.execute("insert into investigation_models values (?,?,?)", (act, got[0], got[1]))
        print(f"NHTSA investigations: {len({a for a, _ in seen})} matched to {len({g for _, g in seen})} of our models")
    con.execute("insert or replace into meta values ('world_built_at', datetime('now'))")
    con.commit()


if __name__ == "__main__":
    sys.exit(main())
