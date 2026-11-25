"""Builds the model reliability pages in site/ from hand-checked summaries.
Data: Google Sheet 'entries (review)' and 'Model notes', reviewed 24 Nov 2026.
Run: python3 tools/build_model_pages.py
"""
import html, json, os

CSS = """
:root{--bg:#f5f3ee;--card:#fff;--ink:#1c1c1a;--muted:#6a675f;--line:#e2ded4;--accent:#b8430f;--accent-soft:#fbeee6;--ok:#2e6b3c;--ok-soft:#e6f2e8}
*{box-sizing:border-box}
body{margin:0;background:var(--bg);color:var(--ink);font:17px/1.6 system-ui,-apple-system,"Segoe UI",Roboto,Helvetica,Arial,sans-serif}
.wrap{max-width:760px;margin:0 auto;padding:24px 18px 80px}
nav.crumbs{font-size:.85rem;color:var(--muted);margin-bottom:10px}
nav.crumbs a{color:var(--muted)}
h1{font-size:2rem;line-height:1.15;margin:6px 0 10px;letter-spacing:-.01em}
h2{font-size:1.3rem;margin:34px 0 10px;line-height:1.25}
h3{font-size:1.05rem;margin:22px 0 6px}
p{margin:0 0 14px}
a{color:var(--accent)}
.lede{font-size:1.08rem;color:#3a3833}
.meta{font-size:.85rem;color:var(--muted);margin-bottom:18px}
.stats{display:grid;grid-template-columns:repeat(4,1fr);gap:10px;margin:22px 0}
.stat{background:var(--card);border:1px solid var(--line);border-radius:12px;padding:14px 8px;text-align:center}
.stat b{display:block;font-size:1.6rem;line-height:1.15}
.stat span{font-size:.78rem;color:var(--muted)}
.answer{background:var(--card);border:1px solid var(--line);border-left:4px solid var(--accent);border-radius:10px;padding:16px 18px;margin:8px 0 6px}
.answer p:last-child{margin:0}
table{width:100%;border-collapse:collapse;background:var(--card);border:1px solid var(--line);border-radius:12px;overflow:hidden;font-size:.93rem;margin:6px 0 8px}
th,td{text-align:left;padding:10px 12px;border-bottom:1px solid var(--line);vertical-align:top}
th{background:#faf8f3;font-size:.8rem;text-transform:uppercase;letter-spacing:.04em;color:var(--muted)}
tr:last-child td{border-bottom:0}
td.n{text-align:center;font-weight:700;white-space:nowrap}
.issue{background:var(--card);border:1px solid var(--line);border-radius:12px;padding:16px 18px;margin:12px 0}
.issue h3{margin-top:0}
.tag{display:inline-block;font-size:.75rem;font-weight:700;padding:2px 8px;border-radius:999px;background:var(--accent-soft);color:var(--accent);margin-left:6px;vertical-align:2px}
ul{padding-left:20px;margin:0 0 14px}
li{margin:4px 0}
.ok{color:var(--ok);font-weight:600}
.cta{background:var(--ink);color:#fff;border-radius:14px;padding:22px;margin:34px 0}
.cta h2{margin-top:0;color:#fff}
.cta a.btn{display:inline-block;background:#fff;color:var(--ink);font-weight:700;padding:11px 18px;border-radius:9px;text-decoration:none;margin-top:4px}
.note{font-size:.88rem;color:var(--muted)}
footer{margin-top:40px;font-size:.85rem;color:var(--muted);border-top:1px solid var(--line);padding-top:16px}
@media(max-width:560px){.stats{grid-template-columns:repeat(2,1fr)}h1{font-size:1.6rem}table{font-size:.86rem}th,td{padding:8px}}
"""

def e(s): return html.escape(s, quote=True)

def page(m):
    rows = "".join(
        f"<tr><td>{e(r[0])}</td><td class='n'>{r[1]}</td><td>{e(r[2])}</td></tr>" for r in m["table"])
    issues = "".join(
        f"<div class='issue'><h3>{e(i['title'])}<span class='tag'>{e(i['tag'])}</span></h3>"
        + "".join(f"<p>{p}</p>" for p in i["body"]) + "</div>" for i in m["issues"])
    gens = ""
    if m.get("gens"):
        gens = ("<h2>By model year</h2><p>Only where the owner said which year or generation they have. "
                "Some owners have had more than one.</p><table><thead><tr><th>Years</th><th>Owners</th><th>What they reported</th></tr></thead><tbody>"
                + "".join(f"<tr><td>{e(g[0])}</td><td class='n'>{g[1]}</td><td>{e(g[2])}</td></tr>" for g in m["gens"])
                + "</tbody></table>")
    high = "".join(f"<li>{x}</li>" for x in m["high"])
    tips = "".join(f"<li>{x}</li>" for x in m["tips"])
    notcounted = "".join(f"<li>{x}</li>" for x in m["notcounted"])
    sources = "".join(f"<li><a href='{e(u)}' rel='nofollow noopener' target='_blank'>{e(t)}</a></li>" for t, u in m["sources"])
    ld = {"@context": "https://schema.org", "@type": "Article", "headline": m["h1"], "description": m["desc"],
          "datePublished": "2026-11-24", "dateModified": "2026-11-24",
          "author": {"@type": "Organization", "name": "Moto Repair Log"}}
    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{e(m['title'])}</title>
<meta name="description" content="{e(m['desc'])}">
<script type="application/ld+json">{json.dumps(ld)}</script>
<style>{CSS}</style>
</head>
<body>
<div class="wrap">
<nav class="crumbs"><a href="/">Moto Repair Log</a> › Reliability reports › {e(m['short'])}</nav>
<h1>{e(m['h1'])}</h1>
<p class="meta">Owner reports collected November 2026 · {m['owners']} owners · Updated as more owners add their bikes</p>
<p class="lede">{m['lede']}</p>
<div class="stats">
  <div class="stat"><b>{m['owners']}</b><span>owners</span></div>
  <div class="stat"><b>{m['with_fail']}</b><span>had a part fail</span></div>
  <div class="stat"><b>{m['clean']}</b><span>nothing failed</span></div>
  <div class="stat"><b>{e(m['top_mileage'])}</b><span>highest mileage reported</span></div>
</div>
<div class="answer">{''.join(f'<p>{p}</p>' for p in m['answer'])}</div>
<h2>Most reported problems</h2>
<table><thead><tr><th>Problem</th><th>Owners</th><th>When it showed up</th></tr></thead><tbody>{rows}</tbody></table>
<p class="note">Owners = how many of the {m['owners']} owners reported it. One owner can report several problems.</p>
<h2>What owners reported, in detail</h2>
{issues}
{gens}
<h2>High-mileage bikes</h2>
<ul>{high}</ul>
<h2>What owners say to check</h2>
<ul>{tips}</ul>
<div class="cta">
  <h2>Own {m['article']} {e(m['short'])}?</h2>
  <p>Add what failed on yours and at what mileage, or log that nothing has broken. It takes a minute and every bike makes this page more accurate.</p>
  <a class="btn" href="{e(m['cta'])}">Add your {e(m['short'])}</a>
</div>
<h2>How this was put together</h2>
<p>These are reports from real owners, mostly from a November 2026 thread in {m['community']} asking what actually broke on their bikes, plus entries made on this site. We count a part as a failure when it broke or wore out early and needed fixing, including warranty and recall work. We do not count:</p>
<ul>{notcounted}</ul>
<p>Keep the limits in mind: {m['owners']} owners is a small sample, people with problems are more likely to answer a question about problems, and most owners did not give the exact mileage when a part failed. Treat this as a list of things to check, not a failure rate.</p>
<h2>Sources</h2>
<ul>{sources}</ul>
<p>See also: <a href="{m['nhtsa']}">every US safety complaint and recall for the {e(m['short'])}</a> (NHTSA data).</p>
<footer>Moto Repair Log collects owner-reported failures by model. <a href="/">Add your bike</a> · Other reports: {m['other']}</footer>
</div>
</body>
</html>
"""

MT07 = dict(
    short="MT-07", article="an",
    title="Yamaha MT-07 Reliability: What 21 Owners Say Actually Broke",
    h1="Yamaha MT-07 reliability: what 21 owners say actually broke",
    desc="21 Yamaha MT-07 and FZ-07 owners on what failed and at what mileage: batteries, handlebar switches, a seizing rear axle nut, and a bike at 130,000 km.",
    owners=21, with_fail=15, clean=6, top_mileage="130,000 km",
    lede="We asked MT-07 owners what has actually failed on their bikes, not routine maintenance or crash damage. Here is what 21 of them reported, including the US-market FZ-07, which is the same bike under its pre-2018 name.",
    answer=[
        "The MT-07's engine and frame rarely come up. Most reported failures are small and cheap: <b>batteries</b>, <b>handlebar switches and sensors</b>, and a <b>rear axle nut that seizes</b>, usually after a shop overtightened it.",
        "Two owners reported an engine failure, one at 27,000 km and one at 17,000 miles under a previous owner, with no cause given. Six owners say nothing has failed, and one bike has covered 130,000 km with only worn switches and a tired rear shock.",
    ],
    table=[
        ("Handlebar switches and sensors (gear sensor, high/low beam, turn signal, clutch and neutral switches)", 5, "From new to 130,000 km; most around 30,000 to 72,000 km"),
        ("Battery", 4, "By about 26,000 miles, or after sitting in storage"),
        ("Rear axle nut seized", 3, "At tyre changes, around 28,000 km in one case"),
        ("Engine failure", 2, "27,000 km and 17,000 miles; cause not given"),
        ("Clutch basket (2023 bike)", 1, "Repeated clutch problems"),
        ("Turn signals popping out of their rubber mounts", 1, "Many more owners mention it as an annoyance"),
        ("Other: headlight surround cracked (warranty), headlight bulb, rear shock worn out", 3, "Shock at 130,000 km"),
    ],
    issues=[
        dict(title="Handlebar switches and sensors", tag="5 owners", body=[
            "The most common category. Two 2017 bikes had the <b>gear position sensor</b> fail, at 30,000 km and around 72,000 km. One FZ-07 needed its <b>high/low beam switch</b> cleaned at 50,000 km and its <b>turn signal switch</b> replaced at 55,000 km after a plastic part inside wore out. A 2015 FZ-07 lost its high beam switch, and a 2026 bike had the whole left switch block stop working (horn, signals, high beam).",
            "On the 130,000 km bike, the clutch and neutral switches became intermittent. These parts are cheap, but a faulty clutch or neutral switch can stop the bike starting."]),
        dict(title="Battery", tag="4 owners", body=[
            "Four owners replaced the battery: a 2016 bike \"a few times\" by 25,000 km, a 2016 bike by 26,000 miles, a 2023 bike, and a 2022 bike after it sat in storage. An XSR700 owner (same platform) says switching to LED lights reduces the load on the battery."]),
        dict(title="Rear axle nut seizing", tag="3 owners", body=[
            "Three owners had the rear axle nut seize or fuse to the thread, one at 28,000 km. Several blame shops overtightening it during tyre changes. Worth checking after any tyre change, before it gets stuck."]),
        dict(title="Engine failures", tag="2 owners", body=[
            "One owner reported the engine \"broke suddenly\" at 27,000 km. A 2015 FZ-07 had its engine blown at 17,000 miles under its first owner. Neither report says what failed or how the bike had been ridden, so these are hard to read much into. Against that, one bike is at 130,000 km and others are past 40,000 miles without engine trouble."]),
        dict(title="Clutch basket on a 2023 bike", tag="1 owner", body=[
            "One 2023 owner had recurring clutch problems and went through seven clutch plate kits. They say a recall clutch kit didn't fix it, and the problem was the clutch basket; an aftermarket clutch kit finally solved it."]),
        dict(title="Turn signals popping out", tag="common annoyance", body=[
            "Only one owner counted it as a failure, but several mention front indicators slipping out of their rubber mounts, knocked by a leg or a bike cover, or loosened by heat. To refit one: remove the plastic backing, seat the indicator, then refit the plastic to lock it in."]),
    ],
    gens=None,
    high=[
        "<b>130,000 km</b>: clutch and neutral switches intermittent and the rear shock worn out. The owner says the valves were never adjusted.",
        "<b>72,000 km</b> (2017 FZ-07): gear sensor, high/low beam switch, turn signal switch and a headlight bulb, all small electrical parts.",
        "<b>45,000 km</b>: <span class='ok'>nothing failed</span>, only routine maintenance (tyres, chain and sprockets, clutch and brakes as wear items).",
        "<b>41,000 miles</b> (2015 FZ-07): high beam switch, plus an engine blown by the first owner at 17,000 miles.",
        "<b>40,000 miles</b> (2022): rear axle nut fused, indicators loose, and a radiator holed twice by road debris.",
    ],
    tips=[
        "First valve check is at 24,000 miles. Owners say the valves are often still in spec, but check anyway.",
        "Yamaha lists a throttle body sync at the 12k service; one owner says it isn't urgent if the bike idles smoothly.",
        "Around 50,000 to 70,000 km the chain guide can wear through until the chain touches the swingarm.",
        "At very high mileage the fork chrome can pit; a Velcro fork cover protects it from stone chips.",
        "The swingarm gets surface rust on bikes ridden in the rain or all year.",
        "The XSR700 shares almost everything mechanically, so most of this applies to it too.",
    ],
    notcounted=[
        "Routine maintenance and wear items: oil, tyres, chain and sprockets, brake pads, valve adjustments.",
        "Crash damage and owner damage (one frame replaced after a rear-end collision, a broken foot peg).",
        "Road damage, such as a radiator holed by debris (one owner, twice).",
    ],
    community="r/MT07 on Reddit",
    cta="/?brand=Yamaha&model=MT-07&src=mt07-report",
    other="<a href='/yamaha-mt-09-reliability/'>Yamaha MT-09</a>",
    sources=[
        ("r/MT07: \"MT07 owners, what has actually broken on yours so far?\" (Nov 2026)", "https://www.reddit.com/r/MT07/comments/1xylfvo/"),
        ("Yamaha renamed the US FZ-07 to MT-07 for 2018 (Cycle News)", "https://cyclenews.com/2017/11/article/yamaha-changes-fz-label-mt"),
    ],
)

MT09 = dict(
    short="MT-09", article="an",
    title="Yamaha MT-09 Reliability: What 30 Owners Say Actually Broke",
    h1="Yamaha MT-09 reliability: what 30 owners say actually broke",
    desc="30 Yamaha MT-09 and FZ-09 owners on what failed: throttle sensor recall, cooling parts, batteries, and a bike at 62,000 miles with nothing broken.",
    owners=30, with_fail=11, clean=19, top_mileage="62,000 mi",
    lede="We asked MT-09 owners what has actually failed on their bikes, not routine maintenance or crash damage. Here is what 30 of them reported, across all generations, including the US-market FZ-09, which is the same bike under its pre-2018 name.",
    answer=[
        "Most MT-09 owners in this group (19 of 30) had no factory part fail, including bikes at 47,000 and 62,000 miles. The issues that do come up are mostly <b>electrical and software</b>: the throttle position sensor on 2021 and later bikes, which is covered by a recall, plus a few <b>cooling parts</b> and <b>batteries</b>.",
        "If you own or are buying a 2021 or later MT-09, check that the recall work has been done.",
    ],
    table=[
        ("Cooling parts (water pump seal, cooling fan, coolant reservoir cap)", 3, "From new to 9,600 km; two fixed under warranty"),
        ("Electronics (dash, quickshifter, turn signals)", 3, "3,000 miles to about 23,000 miles"),
        ("Throttle position sensor (TPS) or engine software, 2021 and later", 2, "Within about a year; covered by recalls"),
        ("Battery", 2, "Flat at two weeks old (warranty); dead at 13,000 km"),
        ("Clutch and stator", 1, "Around 90,000 km"),
        ("Cam chain tensioner", 1, "Mileage not given"),
    ],
    issues=[
        dict(title="Throttle position sensor and ECU recalls (2021 and later)", tag="2 owners", body=[
            "One owner's 2021-or-later bike lost its throttle position sensor after about a year. Another says their bike stalls when cold since the ECU flash done under the TPS recall, and a third owner notes some early recall work had wrong settings.",
            "This lines up with two official recalls. In 2022 Yamaha recalled all 2021 and 2022 MT-09s in the US to reprogram the ECU, because a programming error could make the engine stall. In 2025 a further recall covered 2021 to 2025 MT-09s: a software problem could damage the throttle position sensor, causing unstable idle, hesitation or stalling, fixed by an ECU update and a new sensor. Links are in the sources below."]),
        dict(title="Cooling parts", tag="3 owners", body=[
            "A 2025 bike leaked from the water pump seal from day one, fixed under warranty. A 2021-or-later bike had a cooling fan that didn't work, also replaced under warranty. On another bike the coolant reservoir cap popped off by itself at 9,600 km."]),
        dict(title="Battery", tag="2 owners", body=[
            "One battery was flat at two weeks old and replaced under warranty; another died at 13,000 km."]),
        dict(title="Electronics", tag="3 owners", body=[
            "A 2017 to 2020 bike needed a new dash at about 23,000 miles, a quickshifter failed after a year on another bike from those years, and an FZ-09 had a turn signal fail at 3,000 miles."]),
        dict(title="High mileage: clutch and stator", tag="1 owner", body=[
            "One bike needed a clutch pack and then a stator at around 90,000 km. At that distance the clutch is closer to wear than failure."]),
    ],
    gens=[
        ("2014 to 2016 (first MT-09, FZ-09 in the US)", 2, "Nothing failed. One clutch started slipping after five years on a tuned bike (counted as wear)."),
        ("2017 to 2020", 5, "Dash at about 23,000 miles; quickshifter after a year. Three bikes at 47,000 km, 47,000 miles and 56,000 km with nothing failed."),
        ("2021 to 2023 (890 cc engine)", 5, "Throttle position sensor; cooling fan (warranty). A 2023 MT-09 SP at 62,000 miles with nothing failed."),
        ("2024 and later", 5, "Water pump seal leaking from new (warranty). Others nothing so far, up to 17,500 miles."),
    ],
    high=[
        "<b>62,000 miles</b> (2023 MT-09 SP): <span class='ok'>nothing failed</span>. A stone holed the radiator, which we count as road damage.",
        "<b>56,000 km</b> (2017 to 2020): <span class='ok'>nothing failed</span>, only oil, chain, sprockets and tyres.",
        "<b>47,000 miles</b> (2017 FZ-09): <span class='ok'>nothing failed</span>, only routine maintenance.",
        "<b>47,000 km</b> (2017 to 2020): <span class='ok'>nothing failed</span>; the gear indicator is a bit glitchy and needs cleaning.",
        "<b>About 90,000 km</b>: clutch pack, then stator.",
    ],
    tips=[
        "On 2021 and later bikes, check that the ECU and throttle position sensor recall work has been done; one owner says some dealers' early recall work had the wrong settings.",
        "On 2025 bikes, one owner says there's a recall to swap two bolts so the left instrument cluster stops wobbling, and some dealers skip it. Ask for it.",
        "The fuse for the dash power outlet is inside the dash, not in the fuse box. High-draw devices like a tyre compressor blow it.",
        "Front turn signals stick out past crash bars and get knocked out. Flush-mount signals fix it. To refit one, remove the plastic backing plate first.",
        "Some oil use is normal: one owner tops up about 0.5 litres every 7,000 km.",
        "The stock rear tyre is soft; one owner got about 3,500 miles from it.",
    ],
    notcounted=[
        "Routine maintenance and wear items: oil, tyres, chain and sprockets, brake pads, a clutch slipping on a tuned high-mileage bike.",
        "Crash damage and owner damage, such as a broken fork after a crash or a turn signal snagged and pulled out.",
        "Road damage, such as a radiator holed by a stone.",
        "Aftermarket parts (an Akrapovic carbon silencer that fell apart at 30,000 miles) and problems caused by accessories (a dash fuse blown by an air compressor).",
    ],
    community="r/MT09 on Reddit",
    cta="/?brand=Yamaha&model=MT-09&src=mt09-report",
    other="<a href='/yamaha-mt-07-reliability/'>Yamaha MT-07</a>",
    sources=[
        ("r/MT09: owners on what has actually broken (Nov 2026)", "https://www.reddit.com/r/MT09/comments/1xylgb9/"),
        ("Transport Canada recall 2025-059: MT-09 throttle position sensor (2021 to 2025)", "https://recalls-rappels.canada.ca/en/alert-recall/transport-canada-recall-2025059-yamaha"),
        ("RideApart: all 2021 and 2022 MT-09s recalled for ECU programming (NHTSA 22V-130)", "https://www.rideapart.com/news/573006/yamaha-mt09-tracer9-ecu-recall/"),
        ("Yamaha MT-09, also sold as the FZ-09 in North America 2014 to 2017 (Wikipedia)", "https://en.wikipedia.org/wiki/Yamaha_MT-09"),
    ],
)

MT07["nhtsa"] = "/complaints/yamaha/mt-07/"
MT09["nhtsa"] = "/complaints/yamaha/mt-09/"

if __name__ == "__main__":
    root = os.path.join(os.path.dirname(__file__), "..", "site")
    for slug, m in [("yamaha-mt-07-reliability", MT07), ("yamaha-mt-09-reliability", MT09)]:
        d = os.path.join(root, slug); os.makedirs(d, exist_ok=True)
        open(os.path.join(d, "index.html"), "w").write(page(m))
        print("wrote", slug)
