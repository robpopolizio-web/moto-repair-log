"""Builds the NHTSA complaint and recall pages in site/complaints/ from data/nhtsa/motorcycles.sqlite.
Also writes site/sitemap.xml and site/robots.txt.
Run: python3 tools/build_complaint_pages.py
"""
import html, json, os, re, shutil, sqlite3, statistics, sys
from collections import Counter, defaultdict
from urllib.parse import quote

sys.path.insert(0, os.path.dirname(__file__))
from build_model_pages import CSS as BASE_CSS  # same look as the reliability reports

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DB = os.path.join(ROOT, "data", "nhtsa", "motorcycles.sqlite")
OUT = os.path.join(ROOT, "site", "complaints")
SITE = "https://motorcycle-reliability-index.pages.dev"
MIN_COMPLAINTS = 3          # a model gets its own page with this many complaints, or any recall
EXCERPTS = 12               # owner complaints quoted per model page
REPORTS = {                 # hand-checked owner reports that exist for a model
    ("Yamaha", "MT-07"): "/yamaha-mt-07-reliability/",
    ("Yamaha", "MT-09"): "/yamaha-mt-09-reliability/",
}

CSS = BASE_CSS + """
.wrap.wide{max-width:960px}
.bar{display:inline-block;height:8px;border-radius:4px;background:var(--accent);vertical-align:middle;margin-right:6px}
td.num,th.num{text-align:right;white-space:nowrap}
details.rc{background:var(--card);border:1px solid var(--line);border-radius:12px;padding:12px 16px;margin:10px 0}
details.rc summary{cursor:pointer;font-weight:600}
details.rc summary span{font-weight:400;color:var(--muted);font-size:.9rem}
details.rc p{margin:10px 0 0;font-size:.95rem}
blockquote{background:var(--card);border:1px solid var(--line);border-radius:12px;margin:12px 0;padding:14px 18px;font-size:.95rem}
blockquote .who{display:block;font-size:.8rem;color:var(--muted);margin-bottom:6px}
.filter{width:100%;font:inherit;padding:10px 12px;border:1px solid var(--line);border-radius:9px;margin:6px 0 10px}
.cols{columns:3 220px;column-gap:24px;padding-left:18px}
.warn{background:#fff8e6;border:1px solid #f0dca8;border-radius:10px;padding:12px 16px;font-size:.92rem}
"""

# NHTSA's component codes, grouped into plain English. First match wins.
GROUPS = [
    ("Engine and cooling", ("Engine",)),
    ("Clutch, gearbox and final drive", ("Power Train",)),
    ("Fuel system", ("Fuel", "Hybrid")),
    ("Brakes and ABS", ("Service Brakes", "Parking Brake")),
    ("Throttle and cruise control", ("Vehicle Speed Control",)),
    ("Lights", ("Exterior Lighting", "Interior Lighting")),
    ("Electrical and instruments", ("Electrical System",)),
    ("Suspension", ("Suspension",)),
    ("Steering", ("Steering",)),
    ("Frame and bodywork", ("Structure", "Latches")),
    ("Wheels", ("Wheels",)),
    ("Tyres", ("Tires",)),
    ("Rider aids (traction, stability)", ("Electronic Stability", "Traction Control", "Forward Collision", "Lane Departure", "Back Over")),
    ("Airbag", ("Air Bags",)),
    ("Seat", ("Seats", "Seat Belts")),
    ("Mirrors and windscreen", ("Visibility",)),
    ("Accessories and equipment", ("Equipment", "Child Seat", "Tether")),
]
OTHER = "Other or not stated"


def group_of(component):
    for name, prefixes in GROUPS:
        if any(component.startswith(p) for p in prefixes):
            return name
    return OTHER


def part_of(component):
    """Most specific readable part name, e.g. 'Power Train:Manual Transmission' -> 'Manual transmission'."""
    bits = [b.strip() for b in component.split(":") if b.strip()]
    if len(bits) < 2:
        return None
    last = bits[-1]
    if last.lower() in ("gasoline", "diesel", "front", "rear", "other", "unknown or other"):
        last = " ".join(bits[-2:]) if len(bits) > 2 else bits[-1] + " " + bits[0].lower()
        last = {"Engine Gasoline": "Engine", "Suspension rear": "Rear suspension", "Suspension front": "Front suspension"}.get(last, last)
    if last == "Rear":
        last = "Rear suspension"
    return last[:1].upper() + last[1:].lower().replace("abs", "ABS").replace("12v/24v/48v", "12V")


def e(s):
    return html.escape(str(s), quote=True)


def slug(s):
    s = s.lower().replace("&", " and ").replace("+", " plus ")
    s = re.sub(r"[^a-z0-9]+", "-", s).strip("-")
    return s or "model"


def fmt(n):
    return f"{n:,}"


def tidy(text):
    """NHTSA text is often all caps. Turn shouting into sentence case and drop redaction marks."""
    t = re.sub(r"\s+", " ", (text or "")).strip()
    t = t.replace("*TR", "").replace("*AK", "").replace("*JB", "").replace("*NM", "")
    t = re.sub(r"\s\*[A-Z]{2}\b", "", t)
    letters = [c for c in t if c.isalpha()]
    if letters and sum(c.isupper() for c in letters) / len(letters) > 0.7:
        t = t.lower()
        t = re.sub(r"(^|[.!?]\s+)([a-z])", lambda m: m.group(1) + m.group(2).upper(), t)
        t = re.sub(r"\bi\b", "I", t)
    return t


def years_label(ys):
    ys = sorted(set(y for y in ys if y))
    if not ys:
        return "year not stated"
    if len(ys) == 1:
        return str(ys[0])
    runs, start, prev = [], ys[0], ys[0]
    for y in ys[1:]:
        if y != prev + 1:
            runs.append((start, prev)); start = y
        prev = y
    runs.append((start, prev))
    return ", ".join(str(a) if a == b else f"{a}-{b}" for a, b in runs)


def median(xs):
    return int(statistics.median(xs)) if xs else None


def page(title, desc, crumbs, body, canonical, ld=None, wide=False):
    crumb_html = " › ".join(f'<a href="{e(u)}">{e(t)}</a>' if u else e(t) for t, u in crumbs)
    ld_html = f'<script type="application/ld+json">{json.dumps(ld)}</script>' if ld else ""
    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{e(title)}</title>
<meta name="description" content="{e(desc)}">
<link rel="canonical" href="{SITE}{canonical}">
{ld_html}
<style>{CSS}</style>
</head>
<body>
<div class="wrap{' wide' if wide else ''}">
<nav class="crumbs">{crumb_html}</nav>
{body}
<footer>Complaint and recall data: US National Highway Traffic Safety Administration (NHTSA), downloaded {e(BUILT[:10])}. Complaints are written by owners, are not verified by NHTSA, and cover the US only. Counts are not adjusted for how many of each bike were sold. · <a href="/complaints/">All makes</a> · <a href="/">Log your bike on Moto Repair Log</a></footer>
</div>
</body>
</html>
"""


def write(path, text):
    full = os.path.join(OUT, path, "index.html") if path else os.path.join(OUT, "index.html")
    os.makedirs(os.path.dirname(full), exist_ok=True)
    with open(full, "w") as f:
        f.write(text)


def cta(make, model, sl):
    href = f"/?brand={quote(make)}&model={quote(model)}&src=nhtsa-{sl}"
    return f"""<div class="cta">
  <h2>Own a {e(make)} {e(model)}?</h2>
  <p>NHTSA only hears about safety problems from US riders. Tell us what actually failed on yours and at what mileage, or log that nothing has broken. It takes a minute.</p>
  <a class="btn" href="{e(href)}">Add your {e(model)}</a>
</div>"""


def caveat():
    return """<p class="warn">These are complaints US owners filed with NHTSA, the US road safety agency. NHTSA does not check them, they are mostly about safety (stalling, brakes, fires, crashes), and popular bikes get more complaints simply because more of them are on the road. Use them to see <b>what goes wrong</b>, not to compare how often.</p>"""


# ---------------------------------------------------------------- load
con = sqlite3.connect(DB)
con.row_factory = sqlite3.Row
BUILT = con.execute("select value from meta where key='built_at'").fetchone()[0]

models = [dict(r) for r in con.execute("select * from models")]
comps = defaultdict(list)
for r in con.execute("select complaint_id, component from complaint_components"):
    comps[r["complaint_id"]].append(r["component"])
complaints = defaultdict(list)
for r in con.execute("select * from complaints"):
    d = dict(r)
    d["components"] = comps.get(d["id"], [])
    d["groups"] = sorted(set(group_of(c) for c in d["components"])) or [OTHER]
    d["parts"] = sorted(set(p for p in (part_of(c) for c in d["components"]) if p))
    if d["miles"] is not None and not (0 < d["miles"] < 300000):
        d["miles"] = None
    complaints[(d["make"], d["model_family"])].append(d)

recalls = defaultdict(lambda: defaultdict(list))   # (make, family) -> campaign -> rows
for r in con.execute("select * from recalls"):
    recalls[(r["make"], r["model_family"])][r["campaign"]].append(dict(r))

# give each make/model a unique slug
make_slug = {}
for m in sorted(set(x["make"] for x in models) | set(k[0] for k in recalls)):
    s = slug(m)
    while s in make_slug.values():
        s += "-2"
    make_slug[m] = s

PLACEHOLDER = {"motorcycle", "motorcycles", "unknown", "other", "scooter", "all", "none", "n/a", "na"}


def placeholder(make, fam):
    f = fam.lower().strip()
    return f in PLACEHOLDER or (f == make.lower() and make != "LiveWire")


paged = {}  # (make, family) -> url
for m in sorted(models, key=lambda x: -x["complaints"]):
    key = (m["make"], m["model_family"])
    if placeholder(*key):
        continue
    if m["complaints"] >= MIN_COMPLAINTS or recalls.get(key):
        used = {u for (mk, _), u in paged.items() if mk == m["make"]}
        base = f"/complaints/{make_slug[m['make']]}/{slug(m['model_family'])}/"
        url, n = base, 2
        while url in used:
            url = base[:-1] + f"-{n}/"; n += 1
        paged[key] = url

if os.path.isdir(OUT):
    shutil.rmtree(OUT)
os.makedirs(OUT)


# ---------------------------------------------------------------- recall block
def recall_html(camps):
    out = []
    for camp, rows in sorted(camps.items(), key=lambda kv: kv[1][0]["report_date"] or "", reverse=True):
        r = rows[0]
        ys = years_label([x["year"] for x in rows])
        date = (r["report_date"] or "")[:10]
        units = f" · {fmt(r['units_affected'])} bikes" if r["units_affected"] else ""
        comp = group_of(r["component"] or "") if r["component"] else OTHER
        flags = " · <b>Do not ride until fixed</b>" if any(x["do_not_drive"] for x in rows) else ""
        out.append(f"""<details class="rc"><summary>{e(comp)}: {e(ys)} <span>· {e(camp)} · {e(date)}{units}{flags}</span></summary>
<p><b>Problem.</b> {e(tidy(r['defect']))}</p>
<p><b>Risk.</b> {e(tidy(r['consequence']))}</p>
<p><b>Fix.</b> {e(tidy(r['remedy']))}</p>
<p><a href="{e(r['nhtsa_url'] or 'https://www.nhtsa.gov/recalls')}" rel="nofollow noopener" target="_blank">Check if your VIN is affected on nhtsa.gov</a></p></details>""")
    return "\n".join(out)


# ---------------------------------------------------------------- model pages
sitemap = []
make_rows = defaultdict(list)

for m in models:
    key = (m["make"], m["model_family"])
    make_rows[m["make"]].append(m)
    url = paged.get(key)
    if not url:
        continue
    make, fam = key
    cs = complaints.get(key, [])
    camps = recalls.get(key, {})
    n = len(cs)
    miles = [c["miles"] for c in cs if c["miles"]]
    med = median(miles) if len(miles) >= 5 else None
    crashes = sum(1 for c in cs if c["crash"])
    injured = sum(c["injured"] or 0 for c in cs)
    fires = sum(1 for c in cs if c["fire"])
    ys = [c["year"] for c in cs if c["year"]]

    gcount, gmiles = Counter(), defaultdict(list)
    for c in cs:
        for g in c["groups"]:
            gcount[g] += 1
            if c["miles"]:
                gmiles[g].append(c["miles"])
    pcount = Counter(p for c in cs for p in c["parts"])
    top = [g for g, _ in gcount.most_common() if g != OTHER][:3]

    # short answer
    if n:
        shares = ", ".join(f"<b>{e(g.lower())}</b> ({round(100 * gcount[g] / n)}%)" for g in top)
        answer = f"<p>{fmt(n)} US owners have filed a safety complaint about the {e(make)} {e(fam)}"
        answer += f" (model years {e(years_label(ys))})." if ys else "."
        if top:
            answer += f" The most reported areas are {shares}."
        if med:
            answer += f" Half of the complaints that gave a mileage happened before {fmt(med)} miles."
        answer += "</p>"
    else:
        answer = f"<p>No owner complaints for the {e(make)} {e(fam)} are on file with NHTSA.</p>"
    if camps:
        answer += f"<p>The bike has had <b>{len(camps)} safety recall{'s' if len(camps) != 1 else ''}</b>. Recall work is free at any {e(make)} dealer, so check your VIN (link under each recall below).</p>"

    body = [f"<h1>{e(make)} {e(fam)} problems: {fmt(n)} owner complaint{'s' if n != 1 else ''} and {len(camps)} recall{'s' if len(camps) != 1 else ''}</h1>",
            f'<p class="meta">US safety complaints and recalls from NHTSA · data to {e(BUILT[:10])}</p>',
            '<div class="stats">',
            f'<div class="stat"><b>{fmt(n)}</b><span>complaints</span></div>',
            f'<div class="stat"><b>{len(camps)}</b><span>recalls</span></div>',
            f'<div class="stat"><b>{fmt(med) + " mi" if med else "n/a"}</b><span>median mileage at complaint</span></div>',
            f'<div class="stat"><b>{crashes}</b><span>said it led to a crash</span></div>',
            "</div>",
            "<h2>The short answer</h2>", f'<div class="answer">{answer}</div>']
    if key in REPORTS:
        body.append(f'<p>We also have a <a href="{REPORTS[key]}">hand-checked report from {e(fam)} owners</a> covering non-safety failures and mileages worldwide.</p>')

    if n:
        mx = max(gcount.values())
        rows = "".join(
            f"<tr><td>{e(g)}</td><td class='num'><span class='bar' style='width:{max(4, round(60 * v / mx))}px'></span>{v}</td>"
            f"<td class='num'>{round(100 * v / n)}%</td><td class='num'>{fmt(median(gmiles[g])) if len(gmiles[g]) >= 3 else '-'}</td></tr>"
            for g, v in gcount.most_common())
        body += ["<h2>What owners complain about</h2>",
                 "<table><thead><tr><th>Area</th><th class='num'>Complaints</th><th class='num'>Share</th><th class='num'>Median miles</th></tr></thead>"
                 f"<tbody>{rows}</tbody></table>",
                 '<p class="note">One complaint can name more than one area, so shares can add up to more than 100%. Median miles only where at least 3 complaints gave a mileage.</p>']
        parts = [(p, v) for p, v in pcount.most_common(12) if v >= 2]
        if parts:
            body += ["<h3>Most named parts</h3><ul>" + "".join(f"<li>{e(p)}: {v}</li>" for p, v in parts) + "</ul>"]

        if len(set(ys)) > 1:
            byy = defaultdict(list)
            for c in cs:
                byy[c["year"]].append(c)
            ryears = Counter(y for rs in camps.values() for y in set(x["year"] for x in rs if x["year"]))
            yrows = []
            for y in sorted((k for k in byy if k), reverse=True):
                lst = byy[y]
                g1 = Counter(g for c in lst for g in c["groups"] if g != OTHER).most_common(1)
                yrows.append(f"<tr><td>{y}</td><td class='num'>{len(lst)}</td><td>{e(g1[0][0]) if g1 else '-'}</td><td class='num'>{ryears.get(y, 0)}</td></tr>")
            body += ["<h2>By model year</h2>",
                     "<table><thead><tr><th>Year</th><th class='num'>Complaints</th><th>Top area</th><th class='num'>Recalls</th></tr></thead>"
                     f"<tbody>{''.join(yrows)}</tbody></table>"]

    if camps:
        body += [f"<h2>Recalls ({len(camps)})</h2>", "<p>Newest first. Open one to read the problem, the risk and the fix.</p>", recall_html(camps)]

    if n:
        pick = sorted(cs, key=lambda c: (c["received_date"] or ""), reverse=True)
        good = [c for c in pick if len(c["description"] or "") > 120][:EXCERPTS]
        quotes = []
        for c in good:
            who = " · ".join(x for x in [
                f"{c['year']} {make} {fam}" if c["year"] else f"{make} {fam}",
                f"{fmt(c['miles'])} miles" if c["miles"] else "",
                ", ".join(c["groups"]),
                c["state"] or "",
                f"filed {c['received_date'][:7]}" if c["received_date"] else "",
                "crash" if c["crash"] else "", "fire" if c["fire"] else ""] if x)
            quotes.append(f"<blockquote><span class='who'>{e(who)} · NHTSA {c['odi_number']}</span>{e(tidy(c['description']))}</blockquote>")
        body += [f"<h2>What owners wrote</h2><p>The {len(good)} most recent complaints, as filed (lightly reformatted).</p>", "".join(quotes)]

    body.append(cta(make, fam, slug(make) + "-" + slug(fam)))
    body.append(caveat())

    title = f"{make} {fam} Problems: {fmt(n)} Complaints, {len(camps)} Recalls (NHTSA)"
    desc = (f"{fmt(n)} US owner complaints and {len(camps)} recalls for the {make} {fam}"
            + (f". Most reported: {', '.join(g.lower() for g in top)}." if top else ".")
            + (f" Median {fmt(med)} miles." if med else ""))
    ld = {"@context": "https://schema.org", "@type": "Dataset", "name": f"{make} {fam} NHTSA complaints and recalls",
          "description": desc, "creator": {"@type": "Organization", "name": "NHTSA"},
          "isBasedOn": "https://www.nhtsa.gov/nhtsa-datasets-and-apis", "dateModified": BUILT[:10]}
    write(url[len("/complaints/"):].strip("/"),
          page(title, desc, [("Moto Repair Log", "/"), ("Complaints", "/complaints/"), (make, f"/complaints/{make_slug[make]}/"), (fam, None)],
               "\n".join(body), url, ld))
    sitemap.append(url)


# ---------------------------------------------------------------- make pages
all_makes = sorted(set(make_rows) | set(k[0] for k in recalls))
make_summary = []
for make in all_makes:
    ms = sorted(make_rows.get(make, []), key=lambda x: (-x["complaints"], x["model_family"]))
    total = sum(x["complaints"] for x in ms)
    rkeys = [k for k in recalls if k[0] == make]
    ncamp = len({c for k in rkeys for c in recalls[k]})
    make_summary.append((make, total, len(ms), ncamp))
    murl = f"/complaints/{make_slug[make]}/"
    rows = []
    unpaged = []
    unstated = sum(x["complaints"] for x in ms if placeholder(make, x["model_family"]))
    for x in ms:
        u = paged.get((make, x["model_family"]))
        if placeholder(make, x["model_family"]):
            continue
        if not u:
            unpaged.append(x); continue
        rows.append(f"<tr><td><a href='{u}'>{e(x['model_family'])}</a></td><td>{e(years_label(range(x['first_year'], x['last_year'] + 1)) if x['first_year'] else '-')}</td>"
                    f"<td class='num'>{fmt(x['complaints'])}</td><td class='num'>{x['recall_campaigns'] or 0}</td>"
                    f"<td class='num'>{fmt(x['median_miles']) if x['median_miles'] and x['with_mileage'] >= 5 else '-'}</td></tr>")
    body = [f"<h1>{e(make)} motorcycle problems and recalls</h1>",
            f'<p class="meta">{fmt(total)} US owner complaints across {len(ms)} models · {ncamp} recall campaigns · NHTSA data to {e(BUILT[:10])}</p>',
            caveat()]
    if rows:
        body += ["<h2>Models</h2>", '<input class="filter" placeholder="Filter models" oninput="f(this)" aria-label="Filter models">',
                 "<table id='t'><thead><tr><th>Model</th><th>Years</th><th class='num'>Complaints</th><th class='num'>Recalls</th><th class='num'>Median miles</th></tr></thead>"
                 f"<tbody>{''.join(rows)}</tbody></table>"]
    if unpaged:
        body += [f"<h2>Models with 1 or 2 complaints</h2><ul class='cols'>"
                 + "".join(f"<li>{e(x['model_family'])} ({x['complaints']})</li>" for x in sorted(unpaged, key=lambda x: x["model_family"])) + "</ul>"]
    if unstated:
        body.append(f"<p class='note'>Plus {unstated} complaint{'s' if unstated != 1 else ''} where the owner did not say which {e(make)} model.</p>")
    # recalls whose model name did not match a complaint model
    loose = {}
    for k in rkeys:
        if k not in paged:
            for camp, rs in recalls[k].items():
                loose.setdefault(camp, []).extend(rs)
    if loose:
        body += [f"<h2>Other {e(make)} recalls ({len(loose)})</h2>",
                 "<p>Recalls for models with no matching owner complaints. The model name is as the maker filed it.</p>"]
        for camp, rs in sorted(loose.items(), key=lambda kv: kv[1][0]["report_date"] or "", reverse=True):
            names = sorted(set(x["model_family"] for x in rs))
            body.append(recall_html({camp: rs}).replace("<summary>", f"<summary>{e(', '.join(names))} · ", 1))
    body.append("""<script>function f(i){var q=i.value.toLowerCase();document.querySelectorAll('#t tbody tr').forEach(function(r){r.style.display=r.textContent.toLowerCase().indexOf(q)>=0?'':'none'})}</script>""")
    desc = f"{fmt(total)} US owner complaints and {ncamp} recalls for {make} motorcycles, by model, from NHTSA data."
    write(make_slug[make], page(f"{make} Motorcycle Problems & Recalls by Model (NHTSA)", desc,
                                [("Moto Repair Log", "/"), ("Complaints", "/complaints/"), (make, None)], "\n".join(body), murl))
    sitemap.append(murl)


# ---------------------------------------------------------------- hub
tot_c = con.execute("select count(*) from complaints").fetchone()[0]
tot_r = con.execute("select count(distinct campaign) from recalls").fetchone()[0]
mrows = "".join(f"<tr><td><a href='/complaints/{make_slug[mk]}/'>{e(mk)}</a></td><td class='num'>{fmt(t)}</td><td class='num'>{nm}</td><td class='num'>{nc}</td></tr>"
                for mk, t, nm, nc in sorted(make_summary, key=lambda x: (-x[1], -x[3])) if t or nc)
allrows = "".join(
    f"<tr><td><a href='{paged[(x['make'], x['model_family'])]}'>{e(x['make'])} {e(x['model_family'])}</a></td><td class='num'>{fmt(x['complaints'])}</td><td class='num'>{x['recall_campaigns'] or 0}</td></tr>"
    for x in sorted(models, key=lambda x: -x["complaints"]) if (x["make"], x["model_family"]) in paged)
gtot = Counter(g for cs in complaints.values() for c in cs for g in c["groups"])
grows = "".join(f"<tr><td>{e(g)}</td><td class='num'>{fmt(v)}</td><td class='num'>{round(100 * v / tot_c)}%</td></tr>" for g, v in gtot.most_common())
body = f"""<h1>Motorcycle complaints and recalls, by make and model</h1>
<p class="meta">{fmt(tot_c)} US owner complaints · {fmt(tot_r)} recall campaigns · {len(paged)} model pages · NHTSA data to {e(BUILT[:10])}</p>
<p class="lede">Every motorcycle safety complaint and recall in the US government's NHTSA database, sorted by bike. Find your model to see what owners report going wrong, at what mileage, and whether there is a recall you should get done for free.</p>
{caveat()}
<h2>Find your bike</h2>
<input class="filter" placeholder="Type a make or model, e.g. Gold Wing, R 1200 GS, KLR650" oninput="f(this)" aria-label="Find your bike">
<table id="t"><thead><tr><th>Model</th><th class="num">Complaints</th><th class="num">Recalls</th></tr></thead><tbody>{allrows}</tbody></table>
<h2>By make</h2>
<table><thead><tr><th>Make</th><th class="num">Complaints</th><th class="num">Models</th><th class="num">Recalls</th></tr></thead><tbody>{mrows}</tbody></table>
<h2>What riders complain about most</h2>
<table><thead><tr><th>Area</th><th class="num">Complaints</th><th class="num">Share</th></tr></thead><tbody>{grows}</tbody></table>
<h2>Where this comes from</h2>
<p>NHTSA publishes every complaint owners file through nhtsa.gov and every recall makers report. We took the motorcycle entries, matched each complaint to a model using its VIN where possible (86% of them) and the model name otherwise, and grouped NHTSA's technical part codes into plain English. Model names are as NHTSA and the makers use them, so some trims of the same bike appear separately.</p>
<p>Want failures beyond safety, from riders worldwide? That is what <a href="/">Moto Repair Log</a> collects. Add what broke on your bike.</p>
<script>
var rows=[].slice.call(document.querySelectorAll('#t tbody tr'));
function show(q){{var n=0;rows.forEach(function(r){{var ok=q?r.textContent.toLowerCase().indexOf(q)>=0:n<50;if(ok)n++;r.style.display=ok?'':'none'}})}}
function f(i){{show(i.value.toLowerCase().trim())}}
show('');
</script>"""
write("", page("Motorcycle Problems, Complaints & Recalls by Model (NHTSA Data)",
               f"Look up {fmt(tot_c)} US owner complaints and {fmt(tot_r)} recalls for {len(paged)} motorcycle models: what fails, at what mileage, and open recalls.",
               [("Moto Repair Log", "/"), ("Complaints", None)], body, "/complaints/", wide=False))
sitemap.insert(0, "/complaints/")

# ---------------------------------------------------------------- sitemap + robots
site = os.path.join(ROOT, "site")
extra = ["/"] + sorted("/" + d + "/" for d in os.listdir(site) if d.endswith("-reliability") and os.path.isdir(os.path.join(site, d)))
with open(os.path.join(site, "sitemap.xml"), "w") as f:
    f.write('<?xml version="1.0" encoding="UTF-8"?>\n<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">\n')
    for u in extra + sitemap:
        f.write(f"  <url><loc>{SITE}{u}</loc><lastmod>{BUILT[:10]}</lastmod></url>\n")
    f.write("</urlset>\n")
with open(os.path.join(site, "robots.txt"), "w") as f:
    f.write(f"User-agent: *\nAllow: /\nSitemap: {SITE}/sitemap.xml\n")

print(f"{len(paged)} model pages, {len(all_makes)} make pages, sitemap {len(extra) + len(sitemap)} urls")
