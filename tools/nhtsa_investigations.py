"""NHTSA defect investigations (1972 onward) for motorcycles -> table investigations in motorcycles.sqlite.

An investigation is NHTSA looking into a possible defect, often before or instead of a recall
(preliminary evaluations PE, engineering analyses EA, recall queries RQ, defect petitions DP...).
FLAT_INV has one row per investigation x make/model/year.

Which rows are motorcycles: the investigation led to one of our motorcycle recalls, or the make
only builds motorcycles, or the make also builds cars (Honda, Suzuki, BMW...) and the model name is
one of our motorcycle models.

Run after nhtsa_motorcycles.py:  python3 tools/nhtsa_investigations.py
"""
import io, os, re, sqlite3, sys, zipfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DB = os.path.join(ROOT, "data", "nhtsa", "motorcycles.sqlite")
SRC = os.path.join(ROOT, "data", "nhtsa", "raw", "FLAT_INV.zip")
MIXED = {"HONDA", "SUZUKI", "BMW", "POLARIS", "PIAGGIO", "MAHINDRA", "BAJAJ", "KAWASAKI", "YAMAHA", "CAN-AM", "BRP"}
TYPE = {"PE": "Preliminary evaluation", "EA": "Engineering analysis", "RQ": "Recall query", "DP": "Defect petition",
        "AQ": "Audit query", "RP": "Recall petition", "IR": "Information request"}


def norm(s):
    return re.sub(r"[^A-Z0-9]+", " ", (s or "").upper()).strip()


def main():
    con = sqlite3.connect(DB)
    camps = {c for (c,) in con.execute("select distinct campaign from recalls")}
    makes = {norm(m) for (m,) in con.execute("select distinct make from complaints union select distinct make from recalls")}
    fams = {(norm(m), norm(f)) for m, f in con.execute(
        "select make, model_family from models union select make, model_family from recalls")}
    moto_only = {m for m in makes if m not in MIXED and m not in ("UNKNOWN MANUFACTURER", "IC", "UM", "ULTRA", "TITAN",
                                                               "INDEPENDENCE", "GENUINE", "FUSION", "BOOM")}
    rows = []
    with zipfile.ZipFile(SRC) as z:
        with z.open("FLAT_INV.txt") as f:
            for line in io.TextIOWrapper(f, encoding="latin-1", newline=""):
                p = line.rstrip("\r\n").split("\t")
                if len(p) < 11:
                    continue
                act, make, model, year, comp, mfr, od, cd, camp, subj, summ = (x.strip() for x in p[:11])
                mk, md = norm(make), norm(model)
                camp9 = camp if len(camp) == 9 else ""
                why = None
                if camp9 and camp9 in camps:
                    why = "led to a motorcycle recall"
                elif mk in moto_only:
                    why = "motorcycle make"
                elif mk in MIXED and (mk, md) in fams and md not in (mk, "MOTORCYCLE", "UNKNOWN", "OTHER", "ALL"):
                    why = "motorcycle model"
                elif mk in MIXED and "MOTORCYCLE" in (comp + " " + subj + " " + summ).upper():
                    why = "mentions motorcycle"
                if why:
                    rows.append((act, make.title() if make.isupper() else make, model, int(year) if year.isdigit() and year != "9999" else None,
                                 comp, mfr, od, cd, camp9 or None, subj, summ, TYPE.get(act[:2], act[:2]), why))
    con.executescript("""drop table if exists investigations;
    create table investigations (action TEXT, make TEXT, model TEXT, year INT, component TEXT, manufacturer TEXT,
      opened TEXT, closed TEXT, campaign TEXT, subject TEXT, summary TEXT, kind TEXT, why TEXT);
    create index ix_inv_model on investigations(make, model);""")
    con.executemany("insert into investigations values (?,?,?,?,?,?,?,?,?,?,?,?,?)", rows)
    con.commit()
    n = con.execute("select count(distinct action) from investigations").fetchone()[0]
    print(f"{n} motorcycle investigations ({len(rows)} make/model/year rows)")
    for k, c in con.execute("select why, count(distinct action) from investigations group by why"):
        print(" ", k, c)


if __name__ == "__main__":
    sys.exit(main())
