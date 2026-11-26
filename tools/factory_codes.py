"""Factory codes -> model names, taken from records that give both.

UK records (DVSA MOT, DfT fleet, DVSA recalls) mostly name bikes by factory code: ZR900BHF is a Kawasaki
Z900, DL650 a Suzuki V-Strom 650, GL1800 a Honda Gold Wing. US records use the names. This module learns
the pairs from our own data, so no mapping is typed from memory:

  1. NHTSA complaints: the VIN decoder's series (GL1800A, ZX1000-C, VL800/VL800T) next to the model the
     owner reported (Gold Wing, Ninja ZX-10R, Boulevard C50).
  2. Recall and alert texts that write both: "BANDIT 1250 (GSF1250SA)", "BR125KK (NINJA 125)",
     "ZR1000DAF/DAS, (Z1000)", "V-Strom 800DE (DL800, DL800U)", "TMAX XP530".

A few pairs our sources do not cover are listed in CURATED with the reason. Every pair keeps its evidence,
so the catalogue can show why a UK record joined a page.
"""
import re
import sqlite3
from collections import Counter, defaultdict

CODE_RE = re.compile(r"^[A-Z]{1,4}-?\d{2,4}[A-Z0-9]{0,6}$")
NOT_CODES = {"R1", "R6", "R3", "R7", "Z1", "T100", "T120", "S1000", "XSR700", "XSR900", "XSR125", "XSR155"}   # names people use
# learned pairs that are wrong: the US model the owners named is another generation or a sister bike
BLOCKED = {("HONDA", "VFR750F"), ("HONDA", "VFR750R"), ("HONDA", "NC700S"), ("HONDA", "NC750S")}


def is_code(s):
    s = s.replace(" ", "").replace("-", "").upper()
    return bool(CODE_RE.match(s)) and s not in NOT_CODES


def norm_code(s):
    return re.sub(r"[^A-Z0-9]", "", s.upper())


def _codes_in(text):
    """Codes in a string like "VL800/VL800T/VL800C" or "ZR1000DAF/DAS": DAS completes the first code."""
    out = []
    for part in re.split(r"\s*[/,;]\s*|\s+and\s+", text or ""):
        part = re.sub(r"\(.*?\)", "", part).strip()
        if not part:
            continue
        first = part.split()[0]
        if is_code(first):
            out.append(norm_code(first))
        elif out and re.fullmatch(r"[A-Z]{1,4}", part):   # "/DAS" = ZR1000 + DAS
            stem = re.match(r"^[A-Z]+\d+", out[0])
            if stem:
                out.append(stem.group(0) + part)
    return out


def mine(nhtsa_db, eu_db=None):
    """[(make, code, name, source, weight)] pairs found in our data."""
    pairs = []
    n = sqlite3.connect(nhtsa_db)
    # 1. VIN series next to the owner's model
    for mk, fam, series, k in n.execute(
            "select make, model_family, vin_series, count(*) from complaints where vin_series<>'' group by 1,2,3"):
        for c in _codes_in(series):
            pairs.append((mk, c, fam, "NHTSA VIN series", k))
    # 2. US recalls that list only codes ("certain 2017-2018 ZR900AH, ZR900BH and ZR900BJ motorcycles") under one model
    camp = defaultdict(lambda: [set(), ""])
    for c, mk, fam, defect in n.execute("select campaign, make, model_family, defect from recalls"):
        camp[(c, mk)][0].add(fam)
        camp[(c, mk)][1] = defect or ""
    for (c, mk), (fams, defect) in camp.items():
        m = re.search(r"recalling (?:certain )?(.{3,300}?) (?:motorcycles?|scooters?|vehicles)\b", defect)
        if not m:
            continue
        head = m.group(1)
        listed = {norm_code(x) for x in re.findall(r"(?<![\w-])([A-Z]{1,4}-?\d{3,4}[A-Z]{0,4}\d?)\b", re.sub(r"\(.*?\)", "", head))
                  if is_code(x)}
        # a campaign family that starts a listed code is filed under the code (ZR900 for ZR900AH); the rest are names (Z900)
        coded = {f for f in fams if is_code(f) and any(c.startswith(norm_code(f)) for c in listed)}
        named = fams - coded if listed else {f for f in fams if not is_code(f)}
        codes = listed | {norm_code(f) for f in coded} | ({norm_code(f) for f in fams if is_code(f)} if not named else set())
        # the model names: the campaign's one named model, or else names in brackets after the codes
        # ("ZR900C, ZR900E and ZR900N (Z900RS ABS, Z900RS CAFE ABS, and Z900RS SE ABS)")
        if len(listed) > 4:
            continue        # a recall of many models filed under one says nothing about each code (24V113000)
        if len(named) == 1:
            names = named
        elif not named and head.count("(") == 1:
            names = {x.strip() for x in re.split(r",\s*(?:and\s+)?|\s+and\s+", re.search(r"\((.*?)\)", head).group(1)) if x.strip()}
        else:
            continue
        for code in codes:
            for nm in names:
                if norm_code(code) != norm_code(nm):
                    pairs.append((mk, code, nm, "NHTSA recall " + c, 1))
    # 3. recall and alert texts naming both
    texts = [(mk, model, src) for src, mk, model in n.execute("select source, make, model from world_recalls")]
    texts += [(mk, d, "NHTSA recall") for mk, d in n.execute("select distinct make, defect from recalls")]
    if eu_db:
        e = sqlite3.connect(eu_db)
        for brand, name, typ, desc in e.execute("select brand, name, type_numberOfModel, description from alerts"):
            for t in (name, typ, desc):
                texts.append((brand, t, "EU Safety Gate"))
    for mk, t, src in texts:
        for m in re.finditer(r"([A-Za-z][A-Za-z0-9\- .]{1,40}?)\s*\(\s*([^()]{2,60})\)", t or ""):
            a, b = m.group(1).strip(), m.group(2).strip()
            ca, cb = _codes_in(a), _codes_in(b)
            if cb and not is_code(a.split()[-1] if a.split() else ""):
                for c in cb:                       # NAME (CODE)
                    pairs.append((mk, c, a, src, 1))
            elif ca and len(a.split()) == 1 and re.search(r"[A-Za-z]{3,}", b) and not cb:
                pairs.append((mk, ca[0], b, src, 1))   # CODE (NAME)
        # "TMAX XP530", "Ninja 500 EX500GR", "EX250 NINJA 250R": a name and a code side by side
        words = (t or "").split()
        if 2 <= len(words) <= 4 and "(" not in (t or ""):
            codes = [w for w in words if is_code(w)]
            rest = [w for w in words if not is_code(w)]
            if len(codes) == 1 and "-" not in codes[0] and rest and re.search(r"[A-Za-z]{3,}", " ".join(rest)):
                pairs.append((mk, norm_code(codes[0]), " ".join(rest), src, 1))
    # a name that lists several models ("YZF-R1/MAJESTY") says nothing about which one the code is
    return [p for p in pairs if numbers_agree(p[1], p[2]) and "/" not in p[2] and ((p[0] or "").upper(), p[1]) not in BLOCKED]


def numbers_agree(code, name):
    """A name with an engine number must be near the code's: not Z800 = Ninja 300, but XTZ690 = Tenere 700."""
    nn = [int(x) for x in re.findall(r"(?<![A-Za-z])(\d{3,4})(?!\d)", name)]
    cn = [int(x) for x in re.findall(r"\d{3,4}", code)]
    if not nn or not cn:
        return True
    return any(abs(a - b) <= 0.15 * max(a, b) for a in nn for b in cn)


# Pairs our sources do not cover, checked by hand. UK records use these codes for bikes sold under the name.
CURATED = [
    ("Kawasaki", "ZR900A", "Z900", "2017 Z900; ZR900A/B are in NHTSA recall 17V703 filed under Z900"),
    ("Kawasaki", "ZR900B", "Z900", "Z900 ABS (Europe), see 17V703"),
    ("Kawasaki", "ZR900D", "Z900", "Z900 70 kW (A2 licence) version"),
    ("Kawasaki", "ZR900F", "Z900", "Z900 from 2020"),
    ("Kawasaki", "ER650H", "Z650", "Z650 from 2017 (Kawasaki ER650H)"),
    ("Kawasaki", "ER650K", "Z650", "Z650 from 2020"),
    ("Kawasaki", "ZX1000G", "Ninja 1000", "Z1000SX / Ninja 1000 2011-2013"),
    ("Kawasaki", "ZX1000H", "Ninja 1000", "Z1000SX / Ninja 1000 ABS 2011-2013"),
    ("Kawasaki", "ZX1000L", "Ninja 1000", "Z1000SX / Ninja 1000 2014-2016"),
    ("Kawasaki", "ZX1000M", "Ninja 1000", "Z1000SX / Ninja 1000 ABS 2014-2016"),
    ("Kawasaki", "ZX1000W", "Ninja 1000", "Ninja 1000SX from 2020"),
    ("Kawasaki", "ZX1000N", "Ninja 1000", "Z1000SX / Ninja 1000 2017-2019"),
    ("Kawasaki", "ZR1000B", "Z1000", "Z1000 2007-2009 (ZR1000A is in the VIN series)"),
    ("Kawasaki", "ZR1000D", "Z1000", "Z1000 2010-2013"),
    ("Kawasaki", "ZR1000F", "Z1000", "Z1000 2014-2020"),
    ("Kawasaki", "ZR1000G", "Z1000", "Z1000 R Edition"),
    ("Honda", "CRF1000L", "Africa Twin", "CRF1000L is the Africa Twin; the Adventure Sports is CRF1000L2 / CRF1000A2"),
    ("Yamaha", "VMX12", "Vmax 1200", "the 1985-2007 V-Max 1200; VMX12C / VMX12NC are in the VIN series"),
    ("Kawasaki", "ZR750J", "Z750", "Z750 2004-2006 (the Z750S is ZR750K)"),
    ("Kawasaki", "ZR750L", "Z750", "Z750 2007-2012"),
    ("Kawasaki", "ZR750", "Z750", "bare ZR750 records: the 2004-2012 Z750 is by far the most common ZR750"),
    ("Kawasaki", "ZR800*", "Z800", "every ZR800 is a Z800 (2013-2016): ZR800A/B/C/D/F"),
    ("Kawasaki", "ZX1400B", "Ninja ZX-14", "ZZR1400 ABS 2006-2007 (ZX1400A/C are in the VIN series)"),
]


class CodeMap:
    """Looks up a source's factory code: the longest learned code it starts with wins, e.g.
    ZX1000C -> Ninja ZX-10R while ZX1000G -> Ninja 1000. A code whose learned names disagree is skipped.
    Codes whose name has no bike of its own (ZR900C = Z900RS) are kept in `labels` to name that bike."""

    def __init__(self, pairs, resolve, base=lambda s: s.upper(), make_key=lambda s: (s or "").upper(), owned=lambda key: False,
                 same=lambda key, name: "".join(key[1]) == norm_code(name)):
        """owned(key): the bike is a US model with its own complaints. A code that already names such a model
        (CBR600RR, VFR800) stays with it, whatever a recall list or one owner's VIN says."""
        # resolve(make, name) -> bike key or None: names must belong to a bike we have
        votes, lab = defaultdict(Counter), defaultdict(Counter)
        self.evidence = defaultdict(list)
        pairs = list(pairs) + [(mk, c, nm, "curated: " + why, 3) for mk, c, nm, why in CURATED]
        self_named = {}
        for mk, code, name, src, w in pairs:
            if len(code) < 3:
                continue
            if (mk, code) not in self_named:
                k0 = resolve(mk, code)
                self_named[(mk, code)] = k0 if (k0 is not None and owned(k0)) else None
            if self_named[(mk, code)] is not None:
                continue
            # "NINJA" next to ZX10R means the Ninja ZX-10R, not the bike called Ninja
            key = resolve(mk, f"{name} {code}")
            if key is None or code not in "".join(key[1]):
                key = resolve(mk, name)
            if src.startswith("curated") and key is not None and not same(key, name):
                key = None        # a checked name joins only the model of exactly that name (Z750 is not the Z750S)
            mkk = make_key(mk or "")
            if key is None:
                # a model with no bike of its own, but a US recall filed under the code (ZR900C = Z900RS)
                ck = resolve(mk, code)
                if ck is not None and "".join(ck[1]) == code:
                    votes[(ck[0], code)][ck] += w
                    self.evidence[(ck[0], code)].append((src, name))
                nm = re.sub(r"^[-\s]+", "", name).strip()
                if re.fullmatch(r"[A-Za-z][A-Za-z0-9 .\-]{1,24}", nm) and re.search(r"[A-Za-z]", nm) and re.search(r"\d", nm) and len(nm) >= 3:
                    lab[(mkk, code)][base(nm)] += w
                continue
            votes[(key[0], code)][key] += w
            self.evidence[(key[0], code)].append((src, name))
            nm = re.sub(r"^[-\s]+", "", name).strip()
            if "".join(key[1]) == code and norm_code(nm) != code and re.fullmatch(r"[A-Za-z][A-Za-z0-9 .\-]{1,24}", nm) \
                    and re.search(r"[A-Za-z]", nm) and re.search(r"\d", nm) and len(nm) >= 3:
                lab[(mkk, code)][base(nm)] += w      # the US recall is filed under the code; the name is in its text
        self.map = {}
        for (mk, code), v in votes.items():
            best, w = v.most_common(1)[0]
            if w >= 0.8 * sum(v.values()):
                self.map[(mk, code)] = best
        self.labels = {}
        for k, v in lab.items():
            best, w = v.most_common(1)[0]
            if w >= 0.6 * sum(v.values()) and (k not in self.map or "".join(self.map[k][1]) == k[1]):
                self.labels[k] = best
        self.by_make = defaultdict(list)
        for (mk, code), key in self.map.items():
            self.by_make[mk].append((code, key))
        for mk in self.by_make:
            self.by_make[mk].sort(key=lambda x: -len(x[0]))

    @staticmethod
    def variants(joined):
        """Yamaha writes engine sizes short in codes: XVS1100 = XVS11, VMX1200 = VMX12, XVS650 = XVS65."""
        out = [joined]
        short = re.sub(r"^([A-Z]+\d{2})0{1,2}(?=[A-Z]|$)", r"\1", joined)
        if short != joined:
            out.append(short)
        return out

    def label_of(self, make_k, joined):
        """The name a code stands for when that model has no US page (ZR750L -> Z750, ZR800CDS -> Z800)."""
        best = None
        for (mk, code), name in self.labels.items():
            c = code.rstrip("*")
            if mk != make_k or not joined.startswith(c) or len(joined) - len(c) > 5:
                continue
            tail = joined[len(c):]
            if tail[:1].isdigit() and c[-1:].isdigit():
                continue
            if mk == "KAWASAKI" and c[-1:].isdigit() and tail[:1].isalpha() and not code.endswith("*"):
                continue
            if best is None or len(c) > len(best[0]):
                best = (c, name)
        return best

    @staticmethod
    def code_part(tokens):
        """The code at the start of a record's tokens: ZR 900 EJF CAFE -> ZR900EJF, DL 650 A ABS -> DL650A."""
        out, after = [], 0          # letter groups seen after the engine number
        for t in tokens:
            if after or (out and out[-1].isdigit() and t.isalpha()):
                # the first letter group after the number is the variant (CJFB, A, L); a second one is a word
                if t.isalpha() and (after or len(t) > 5 or t in ("ABS", "SE", "SP", "LE", "TH")):
                    break
                after += t.isalpha()
            out.append(t)
        return "".join(out)

    def lookup(self, make_k, joined):
        """Bike key for a joined source code (ZR900BHF, DL650AL2), or None.
        The code must be followed only by a short variant/year/market tail (up to 5 letters or digits)."""
        for j in self.variants(joined):
            for code, key in self.by_make.get(make_k, []):
                if code.endswith("*"):           # curated: any variant of this code
                    if j.startswith(code[:-1]) and len(j) - len(code) + 1 <= 5 and not j[len(code) - 1:][:1].isdigit():
                        return key, code
                    continue
                if not (j.startswith(code) and len(j) - len(code) <= 5):
                    continue
                tail = j[len(code):]
                # the next character must not continue the engine number: ZX10 is not ZX1000
                if tail[:1].isdigit() and code[-1:].isdigit():
                    continue
                # Kawasaki's letter after the engine number is the model (ZX1000C = ZX-10R, ZX1000G = Ninja 1000),
                # so a learned code without it cannot name a record that has one
                # Honda and Yamaha likewise (NC700S is not the NC700X), except A for ABS (XVS650A, DL650A)
                if code[-1:].isdigit() and tail[:1].isalpha() and (
                        make_k == "KAWASAKI" or (make_k in ("HONDA", "YAMAHA") and tail[:1] not in "AD")):
                    continue
                # a bare code is only safe when it was learned itself, or no longer learned code of another
                # model starts with it (CRF1000 = Africa Twin although CRF1000A2 = Africa Twin Adventure Sports)
                if code != j and any(k != key for c, k in self.by_make[make_k] if len(c) > len(j) and c.startswith(j)):
                    return None
                return key, code
        # a bare code (ZR1000) whose learned variants all belong to one model (ZR1000A/B/D/F = Z1000)
        longer = Counter(k for c, k in self.by_make.get(make_k, []) if c.startswith(joined) and len(c) > len(joined) and not c.endswith("*"))
        if longer:
            best, n = longer.most_common(1)[0]
            if n >= 3 and n >= 0.8 * sum(longer.values()):
                return best, joined + "*"
        return None
