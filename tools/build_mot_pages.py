"""Builds the UK MOT reliability pages in site/mot/ from data/mot/mot.sqlite (tools/mot_build.py).

  /mot/                      hub: all makes
  /mot/<make>/               models of one make
  /mot/<make>/<model>-<cc>cc/  one model family: failure rates by part, age, mileage and year,
                             each compared with bikes of the same engine size
  /mot/methodology/          how every number is defined

Also writes data/mot/links.json so the US complaint pages can link to the matching MOT pages.
Run before build_complaint_pages.py (which writes the sitemap including these pages).
"""
import html, json, os, re, shutil, sqlite3, sys
from collections import defaultdict

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from build_model_pages import CSS as BASE_CSS  # noqa: E402
from world_sources import Matcher  # noqa: E402

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DB = os.path.join(ROOT, "data", "mot", "mot.sqlite")
NHTSA = os.path.join(ROOT, "data", "nhtsa", "motorcycles.sqlite")
OUT = os.path.join(ROOT, "site", "mot")
LINKS = os.path.join(ROOT, "data", "mot", "links.json")
SITE = "https://motorcycle-reliability-index.pages.dev"
MIN_TESTS = 100

CSS = BASE_CSS + """
.wrap.wide{max-width:960px}
td.num,th.num{text-align:right;white-space:nowrap}
.bar{display:inline-block;height:8px;border-radius:4px;background:var(--accent);vertical-align:middle;margin-right:6px}
.hi{color:#b3261e;font-weight:600}.lo{color:#1e7b34;font-weight:600}
.filter{width:100%;font:inherit;padding:10px 12px;border:1px solid var(--line);border-radius:9px;margin:6px 0 10px}
.small{font-size:.88rem;color:var(--muted)}
"""
MAKE_NAMES = {"BMW": "BMW", "KTM": "KTM", "MV AGUSTA": "MV Agusta", "CFMOTO": "CFMoto", "SYM": "SYM", "AJS": "AJS",
              "HARLEY-DAVIDSON": "Harley-Davidson", "HARLEY DAVIDSON": "Harley-Davidson", "MZ": "MZ", "BSA": "BSA",
              "TGB": "TGB", "WK": "WK", "AJP": "AJP", "SWM": "SWM", "UM": "UM", "LML": "LML", "GASGAS": "GasGas"}


def e(s):
    return html.escape(str(s), quote=True)


def slug(s):
    return re.sub(r"[^a-z0-9]+", "-", s.lower()).strip("-") or "x"


def make_name(m):
    return MAKE_NAMES.get(m, " ".join(w.capitalize() for w in m.split()))


def model_name(m):
    """DVSA writes names in capitals. Words with digits stay as codes (MT-07, CB1300); others get
    capitalised (TIGER -> Tiger)."""
    return " ".join(w if re.search(r"\d", w) else w.capitalize() for w in m.split())


def pct(x, d=1):
    return f"{x * 100:.{d}f}%"


def nice_date(iso):
    import datetime
    d = datetime.date.fromisoformat(iso[:10])
    return f"{d.day} {d.strftime('%B %Y')}"


def compare(rate, base):
    if not base or rate is None:
        return ""
    r = rate / base
    if r >= 1.25:
        return f'<span class="hi">{r:.1f}× average</span>'
    if r <= 0.8:
        return f'<span class="lo">{r:.1f}× average</span>'
    return "about average"


def page(title, desc, crumbs, body, canonical, built, ld=None, wide=False):
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
<footer>Data: DVSA anonymised MOT test results for Great Britain, contains public sector information licensed under the Open Government Licence v3.0. Last updated {e(nice_date(built))}. · <a href="/mot/methodology/">How we calculate this</a> · <a href="/mot/">All makes</a> · <a href="/complaints/">US complaints and recalls</a> · <a href="/">Log your bike on Moto Repair Log</a></footer>
</div>
</body>
</html>
"""


def write(path, text):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        f.write(text)


def main():
    con = sqlite3.connect(DB)
    con.row_factory = sqlite3.Row
    meta = dict(con.execute("select key, value from meta").fetchall())
    built, years = meta["built_at"], meta["years"].split(",")
    yr = f"{min(years)} to {max(years)}" if len(years) > 1 else years[0]
    classes = {r["cc_band"]: dict(r) for r in con.execute("select * from classes")}
    cparts = defaultdict(dict)
    for r in con.execute("select * from class_parts"):
        cparts[r["cc_band"]][(r["kind"], r["part"])] = r["rate"]
    cbands = defaultdict(dict)
    for r in con.execute("select * from class_bands"):
        cbands[r["cc_band"]][(r["band_type"], r["band"])] = (r["tests"], r["fail_rate"])
    models = [dict(r) for r in con.execute(f"select * from models where tests >= {MIN_TESTS} order by tests desc")]
    parts, bands, yrs, trims = (defaultdict(list) for _ in range(4))
    for r in con.execute("select * from model_parts"):
        parts[(r["make"], r["model_key"])].append(dict(r))
    for r in con.execute("select * from model_bands"):
        bands[(r["make"], r["model_key"])].append(dict(r))
    for r in con.execute("select * from model_years order by first_use_year desc"):
        yrs[(r["make"], r["model_key"])].append(dict(r))
    for r in con.execute("select * from model_trims order by tests desc"):
        trims[(r["make"], r["model_key"])].append(dict(r))

    # links to the US complaint pages: same make + model name
    matcher = Matcher(sqlite3.connect(NHTSA)) if os.path.exists(NHTSA) else None
    pu = os.path.join(ROOT, "data", "nhtsa", "page_urls.json")   # written by build_complaint_pages.py
    us_url = json.load(open(pu)) if os.path.exists(pu) else {}

    if os.path.isdir(OUT):
        shutil.rmtree(OUT)
    sitemap, by_make, links = ["/mot/", "/mot/methodology/"], defaultdict(list), defaultdict(list)
    used = set()
    for m in models:
        key = (m["make"], m["model_key"])
        mk, nm = make_name(m["make"]), model_name(m["model"])
        cc = m["cc"]
        era = m["era"] if "era" in m.keys() else None    # one generation of a name used twice (mot_build.find_eras)
        title_name = f"{mk} {nm}" + (f" ({cc} cc)" if cc else "") + (f" {era}" if era else "")
        url = f"/mot/{slug(mk)}/{slug(nm)}" + (f"-{cc}cc" if cc else "") + (f"-{era}" if era else "") + "/"
        n = 2
        while url in used:
            url = url[:-1] + f"-{n}/"; n += 1
        used.add(url)
        m["url"], m["title_name"] = url, title_name
        by_make[mk].append(m)
        cls = classes.get(m["cc_band"]) or {}
        base = cls.get("fail_rate")
        cp = cparts.get(m["cc_band"], {})
        ps = parts[key]
        cats = sorted([p for p in ps if p["kind"] == "fail_category"], key=lambda p: -p["rate"])
        fails = sorted([p for p in ps if p["kind"] == "fail"], key=lambda p: -p["rate"])
        advs = sorted([p for p in ps if p["kind"] == "advisory"], key=lambda p: -p["rate"])
        us = matcher.match(m["make"], m["model"]) if matcher else None
        if us:
            links[f"{us[0]}|{us[1]}"].append({"url": url, "name": title_name, "tests": m["tests"]})

        top3 = ", ".join(f"<b>{e(p['part'].lower())}</b> ({pct(p['rate'])})" for p in fails[:3])
        cmp_txt = ""
        if base:
            r = m["fail_rate"] / base
            word = "more often than" if r >= 1.15 else "less often than" if r <= 0.87 else "about as often as"
            cmp_txt = f" That is {word} the average for {e(m['cc_band'])} bikes ({pct(base)})."
        answer = (f"<p><b>{pct(m['fail_rate'])}</b> of {e(title_name)} annual MOTs in Great Britain were failed first time "
                  f"({m['tests']:,} MOTs, {yr}).{cmp_txt}</p>")
        if fails:
            answer += f"<p>The parts it failed on most: {top3}.</p>"
        if m["median_miles"]:
            answer += f"<p>Typical mileage at MOT: <b>{m['median_miles']:,} miles</b>.</p>"

        body = [f"<h1>{e(title_name)} MOT failures: what fails and when</h1>",
                f'<p class="meta">Updated {e(nice_date(built))} · {m["tests"]:,} UK MOTs of {m["vehicles"]:,} bikes, {e(yr)}</p>',
                '<div class="stats">',
                f'<div class="stat"><b>{pct(m["fail_rate"])}</b><span>failed first time</span></div>',
                (f'<div class="stat"><b>{pct(base)}</b><span>average, {e(m["cc_band"])}</span></div>' if base else ""),
                f'<div class="stat"><b>{m["tests"]:,}</b><span>MOTs analysed</span></div>',
                (f'<div class="stat"><b>{m["median_miles"]:,} mi</b><span>median mileage at MOT</span></div>' if m["median_miles"] else ""),
                "</div>", f'<div class="answer">{answer}</div>']
        if us and us_url.get(f"{us[0]}|{us[1]}"):
            body.append(f'<p>See also: <a href="{e(us_url[f"{us[0]}|{us[1]}"])}">US safety complaints and recalls for the {e(us[0])} {e(us[1])}</a>, which cover engine, electrical and other faults the MOT does not test.</p>')

        if cats:
            rows = "".join(f"<tr><td>{e(p['part'])}</td><td class='num'><span class='bar' style='width:{max(2, round(140 * p['rate'] / cats[0]['rate']))}px'></span>{pct(p['rate'])}</td>"
                           f"<td class='num'>{pct(cp.get(('fail_category', p['part']), 0))}</td><td>{compare(p['rate'], cp.get(('fail_category', p['part'])))}</td></tr>"
                           for p in cats if p["rate"] >= 0.002)
            body += ["<h2>What it fails on</h2>",
                     f"<p>Share of annual MOTs that failed on each area. A bike can fail on more than one. Compared with all {e(m['cc_band'])} bikes.</p>",
                     f"<table><thead><tr><th>Area</th><th class='num'>{e(nm)}</th><th class='num'>Class average</th><th></th></tr></thead><tbody>{rows}</tbody></table>"]
        if fails:
            rows = "".join(f"<tr><td>{e(p['part'])}</td><td class='num'>{pct(p['rate'])}</td><td class='num'>{pct(cp.get(('fail', p['part']), 0))}</td>"
                           f"<td>{compare(p['rate'], cp.get(('fail', p['part'])))}</td></tr>" for p in fails[:15] if p["rate"] >= 0.003)
            body += ["<h3>By part</h3>", f"<table><thead><tr><th>Part</th><th class='num'>Failed on it</th><th class='num'>Class average</th><th></th></tr></thead><tbody>{rows}</tbody></table>"]
        for bt, label, order in (("age", "By age", ["0-3 years", "4-6 years", "7-10 years", "11-15 years", "16+ years"]),
                                 ("mileage", "By mileage", ["under 5k mi", "5-10k mi", "10-20k mi", "20-40k mi", "40k+ mi"])):
            bs = {b["band"]: b for b in bands[key] if b["band_type"] == bt}
            rows = "".join(f"<tr><td>{e(b)}</td><td class='num'>{bs[b]['tests']:,}</td><td class='num'>{pct(bs[b]['fail_rate'])}</td>"
                           f"<td class='num'>{pct(cbands[m['cc_band']].get((bt, b), (0, 0))[1])}</td></tr>"
                           for b in order if b in bs and bs[b]["tests"] >= 20)
            if rows:
                body += [f"<h2>{label}</h2>", f"<table><thead><tr><th>{label[3:].capitalize()}</th><th class='num'>MOTs</th><th class='num'>Failed first time</th><th class='num'>Class average</th></tr></thead><tbody>{rows}</tbody></table>"]
        ys = [y for y in yrs[key] if y["tests"] >= 20]
        if len(ys) > 1:
            rows = "".join(f"<tr><td>{y['first_use_year']}</td><td class='num'>{y['tests']:,}</td><td class='num'>{pct(y['fail_rate'])}</td>"
                           f"<td class='num'>{(str(format(y['median_miles'], ',')) + ' mi') if y['median_miles'] else '-'}</td></tr>" for y in ys)
            body += ["<h2>By year first registered</h2>", "<p>Use this to judge a used bike: how often bikes from the same year fail, and their usual mileage.</p>",
                     f"<table><thead><tr><th>First registered</th><th class='num'>MOTs</th><th class='num'>Failed first time</th><th class='num'>Median mileage</th></tr></thead><tbody>{rows}</tbody></table>"]
        if advs:
            rows = "".join(f"<tr><td>{e(p['part'])}</td><td class='num'>{pct(p['rate'])}</td><td class='num'>{pct(cp.get(('advisory', p['part']), 0))}</td></tr>"
                           for p in advs[:10] if p["rate"] >= 0.005)
            body += ["<h2>Advisories: wear the tester noticed</h2>", "<p>Items that passed but were noted as wearing or needing attention soon. A good list of things to check on a used bike.</p>",
                     f"<table><thead><tr><th>Part</th><th class='num'>Noted on</th><th class='num'>Class average</th></tr></thead><tbody>{rows}</tbody></table>"]
        tr = trims[key]
        if tr:
            body += ["<h2>Which bikes are included</h2>",
                     f"<p class='small'>DVSA records the model name as typed at registration. This page groups these names, all with a {e(cc)} cc engine (<a href='/mot/methodology/'>how</a>):</p>",
                     "<p class='small'>" + ", ".join(f"{e(t['name'])} ({t['tests']:,})" for t in tr[:20]) + (" and others" if len(tr) > 20 else "") + "</p>"]
        body.append(f"""<div class="cta"><h2>Own a {e(mk)} {e(nm)}?</h2><p>The MOT only shows what fails a safety check. Tell us what actually broke on yours and at what mileage, or log that nothing has. It takes a minute.</p><a class="btn" href="/?brand={e(mk)}&amp;model={e(nm)}&amp;src=mot">Add your bike</a></div>""")
        desc = (f"{title_name}: {pct(m['fail_rate'])} of {m['tests']:,} UK MOTs failed first time"
                + (f" vs {pct(base)} for {m['cc_band']} bikes" if base else "") + ". What fails, by part, age, mileage and year.")
        ld = {"@context": "https://schema.org", "@type": "Dataset", "name": f"{title_name} MOT test results",
              "description": desc, "url": SITE + url, "license": "https://www.nationalarchives.gov.uk/doc/open-government-licence/version/3/",
              "isBasedOn": "https://www.data.gov.uk/dataset/c63fca52-ae4c-4b75-bab5-8b4735e1a4c9/anonymised-mot-tests-and-results",
              "dateModified": built[:10]}
        write(os.path.join(ROOT, "site", url.strip("/"), "index.html"),
              page(f"{title_name} MOT failures and reliability | UK MOT data", desc,
                   [("MOT data", "/mot/"), (mk, f"/mot/{slug(mk)}/"), (f"{nm}" + (f" {cc} cc" if cc else ""), None)],
                   "\n".join(body), url, built, ld))
        sitemap.append(url)

    # make pages
    for mk, ms in sorted(by_make.items()):
        rows = "".join(f"<tr><td><a href='{m['url']}'>{e(m['title_name'][len(mk) + 1:])}</a></td><td class='num'>{m['tests']:,}</td>"
                       f"<td class='num'>{pct(m['fail_rate'])}</td><td class='num'>{pct(classes.get(m['cc_band'], {}).get('fail_rate') or 0)}</td></tr>"
                       for m in sorted(ms, key=lambda x: -x["tests"]))
        body = [f"<h1>{e(mk)} motorcycles: UK MOT failure rates by model</h1>",
                f'<p class="meta">Updated {e(nice_date(built))} · {len(ms)} models · DVSA MOT records {e(yr)}</p>',
                '<input class="filter" placeholder="Filter models" oninput="f(this)" aria-label="Filter models">',
                f"<table id='t'><thead><tr><th>Model</th><th class='num'>MOTs</th><th class='num'>Failed first time</th><th class='num'>Class average</th></tr></thead><tbody>{rows}</tbody></table>",
                "<script>function f(i){var q=i.value.toLowerCase();document.querySelectorAll('#t tbody tr').forEach(function(r){r.style.display=r.textContent.toLowerCase().indexOf(q)>-1?'':'none'})}</script>"]
        u = f"/mot/{slug(mk)}/"
        write(os.path.join(OUT, slug(mk), "index.html"),
              page(f"{mk} MOT failure rates by model | UK MOT data", f"UK MOT first-time failure rates for {len(ms)} {mk} motorcycle models, compared with bikes of the same engine size.",
                   [("MOT data", "/mot/"), (mk, None)], "\n".join(body), u, built, wide=True))
        sitemap.append(u)

    # hub
    tot = sum(c["tests"] for c in classes.values())
    crow = "".join(f"<tr><td>{e(b)}</td><td class='num'>{classes[b]['tests']:,}</td><td class='num'>{pct(classes[b]['fail_rate'])}</td></tr>"
                   for b in ["up to 125 cc", "126-500 cc", "501-900 cc", "over 900 cc", "electric"] if b in classes)
    mrow = "".join(f"<tr><td><a href='/mot/{slug(mk)}/'>{e(mk)}</a></td><td class='num'>{len(ms)}</td><td class='num'>{sum(m['tests'] for m in ms):,}</td></tr>"
                   for mk, ms in sorted(by_make.items(), key=lambda kv: -sum(m["tests"] for m in kv[1])))
    body = f"""<h1>Motorcycle MOT failure rates, by make and model</h1>
<p class="meta">Updated {e(nice_date(built))} · {tot:,} annual motorcycle MOTs in Great Britain, {e(yr)} · {len(models)} model pages</p>
<p class="lede">Every motorcycle MOT in Great Britain, from DVSA's test records. For each bike: how often it fails first time, which parts it fails on, and how that changes with age and mileage, compared with bikes of the same engine size.</p>
<h2>Average by engine size</h2>
<table><thead><tr><th>Engine size</th><th class='num'>MOTs</th><th class='num'>Failed first time</th></tr></thead><tbody>{crow}</tbody></table>
<h2>Makes</h2>
<table><thead><tr><th>Make</th><th class='num'>Models</th><th class='num'>MOTs</th></tr></thead><tbody>{mrow}</tbody></table>
<p class="small"><a href="/mot/methodology/">How we calculate this</a></p>"""
    write(os.path.join(OUT, "index.html"), page("Motorcycle MOT failure rates by make and model | UK MOT data",
          f"First-time MOT failure rates for {len(models)} motorcycle models from {tot:,} UK MOTs, compared with bikes of the same engine size.",
          [("MOT data", None)], body, "/mot/", built, wide=True))

    # methodology
    body = f"""<h1>How we calculate the MOT figures</h1>
<p class="meta">Updated {e(nice_date(built))}</p>
<p>The figures come from DVSA's anonymised MOT test results for Great Britain ({e(yr)}), published under the Open Government Licence. Motorcycles are test classes 1 and 2. We download every year, keep the motorcycle tests and their defects, and count them as below.</p>
<h2>Definitions</h2>
<ul>
<li><b>Annual MOT.</b> A bike's first normal test in a calendar year. Retests, appeals and aborted tests are left out, so a bike that fails and is fixed counts once, as a fail.</li>
<li><b>Failed first time.</b> The annual MOT's result was a fail, including "PRS": failed, fixed and passed while still at the test station.</li>
<li><b>Failed on a part.</b> The annual MOT had at least one fail or dangerous defect on that part. Shown as a share of all annual MOTs of that model, so 4% means 4 in 100 MOTs failed on it. This is not the same as a part's share of all faults.</li>
<li><b>Advisory.</b> An item the tester noted as worn or needing attention, but that did not fail the bike.</li>
<li><b>Age.</b> Test year minus the year the bike was first used. <b>Mileage</b> is the odometer reading at the MOT; implausible readings are left out.</li>
<li><b>Class average.</b> The same figure for all bikes with an engine of the same size band: up to 125 cc, 126-500 cc, 501-900 cc, over 900 cc, or electric. Highlighted when a model is at least 1.25 times or at most 0.8 times the average.</li>
</ul>
<h2>Which bikes count as one model</h2>
<p>DVSA stores the model name as it was typed when the bike was registered, so one bike appears under many spellings and a name like "MT" can mean different bikes. We group records into a model family by make, the first word of the model name and the engine size:</p>
<ul>
<li>Names are compared without hyphens and without an ABS, A, SP or SE ending after the model number (MT-07, MT07 and MT-07A are one bike).</li>
<li>A number that only repeats the engine size is ignored (Tiger 1050 at 1,050 cc is a Tiger).</li>
<li>Engine sizes of one name within 3% of each other count as one engine (1,280 and 1,300 cc).</li>
<li>A bare name ("MT" at 690 cc) joins a longer name that starts with it ("MT-07") when that name holds at least 80% of the longer names at that engine size. Otherwise it stays on its own.</li>
</ul>
<p>Each page lists the names it includes. Models need at least {MIN_TESTS} annual MOTs for a page.</p>
<h2>Limits</h2>
<ul><li>The MOT checks safety items (brakes, lights, tyres, steering, suspension, structure). It does not test engines, gearboxes or electronics, so those failures are not here. For those, see the <a href="/complaints/">US complaints</a> and owner reports.</li>
<li>Bikes only need an MOT from three years old, so new models have few results.</li>
<li>Owners who maintain their bikes before the test fail less, and that is not spread evenly across models.</li></ul>"""
    write(os.path.join(OUT, "methodology", "index.html"), page("How we calculate motorcycle MOT failure rates", "Definitions and grouping rules behind our UK motorcycle MOT figures.",
          [("MOT data", "/mot/"), ("Methodology", None)], body, "/mot/methodology/", built))

    with open(LINKS, "w") as f:
        json.dump(links, f)
    with open(os.path.join(ROOT, "data", "mot", "sitemap_urls.json"), "w") as f:
        json.dump(sitemap, f)
    print(f"{len(models)} MOT model pages, {len(by_make)} make pages; {len(links)} US models linked")


if __name__ == "__main__":
    sys.exit(main())
