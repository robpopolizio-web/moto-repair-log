"""Site architecture for motorcycleproblems.com, generated from the catalogue.

Template (Site Architecture Generator) mapped to this business, as market-research.md sets out:
  Homepage                                  -> Homepage
  GBP category pages > one page per service -> Brand pages > one page per model
  Location hub > one page per area          -> not built yet (engine platform pages: too few models per engine so far)
  Service x location pages                  -> none: "years to avoid" is a section of each model page
  Blog, About (+ Methodology), Contact      -> as they are

One model page per model name: generation and engine-size entries in the catalogue
("Street Glide (2007-2011)") are sections of that page, not pages.

Writes to OUT: site-architecture.xlsx (tabs: Structure, Internal linking), the same two tabs as CSV,
and site-architecture-diagram.md (mermaid).
Run: python3 tools/build_site_architecture.py "<output folder>"
"""
import csv, os, re, sqlite3, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from model_names import display, make_display
from collections import defaultdict

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CAT = os.path.join(ROOT, "data", "catalog.sqlite")
NHTSA = os.path.join(ROOT, "data", "nhtsa", "motorcycles.sqlite")
OUT = sys.argv[1] if len(sys.argv) > 1 else "."
DOMAIN = "motoercycleproblems.com"   # spelling still open in business-info.md

# Thresholds: a model page needs some data to say anything; a years page needs several years of it
MODEL_MIN = dict(mot=1000, complaints=5, recalls=3)
YEARS_MIN = dict(mot=5000, complaints=10)
# First pages to build (market-research.md, "Subreddit-first models" and "Where to start")
WAVE1 = {("Yamaha", "MT-07"), ("Yamaha", "MT-09"), ("Harley-Davidson", "Street Glide"),
         ("Harley-Davidson", "Road Glide"), ("Harley-Davidson", "Road King")}

# Engine platform pages and separate years-to-avoid pages are off (decided 2026-11-26): too few models per
# engine for now, and "years to avoid" is a section of the model page. Switch on to bring them back.
BUILD_ENGINE_PAGES = False
BUILD_YEARS_PAGES = False

# Engine platforms: models that used each engine (in some or all of their years)
PLATFORMS = [
    ("Yamaha CP2 engine", "yamaha-cp2", "cp2 engine problems", "Yamaha",
     ["MT-07", "Tracer 700", "XSR700", "Tenere 700"], "689 cc parallel twin, 2014 on"),
    ("Yamaha CP3 engine", "yamaha-cp3", "cp3 engine problems", "Yamaha",
     ["MT-09", "Tracer 900", "XSR900"], "847 cc and 890 cc triple, 2014 on"),
    ("Harley-Davidson Milwaukee-Eight engine", "milwaukee-eight", "milwaukee eight problems", "Harley-Davidson",
     ["Street Glide", "Road Glide", "Road King", "Electra Glide Ultra Limited", "Fat Boy", "Breakout", "Low Rider",
      "Street Bob", "Low Rider ST"], "107, 114 and 117 cubic inch V-twin, 2017 on"),
    ("Harley-Davidson Twin Cam engine", "twin-cam", "twin cam problems", "Harley-Davidson",
     ["Street Glide", "Road Glide", "Road King", "Electra Glide Ultra Classic", "Electra Glide Classic", "Fat Boy",
      "Breakout", "Street Bob", "Low Rider", "Heritage Softail Classic", "Softail Deluxe", "Dyna Wide Glide",
      "Dyna Street Bob", "Dyna Low Rider", "Dyna Super Glide"], "88, 96, 103 and 110 cubic inch V-twin, 1999 to 2017"),
    ("Harley-Davidson Revolution Max engine", "revolution-max", "revolution max engine problems", "Harley-Davidson",
     ["Pan America", "Sportster S", "Nightster"], "975 cc and 1250 cc liquid-cooled V-twin, 2021 on"),
    ("Harley-Davidson Evolution Sportster engine", "sportster-evolution", "sportster evolution engine problems", "Harley-Davidson",
     ["Sportster 883", "Sportster 1200", "Iron 883", "Forty-Eight", "Sportster 1200 Custom", "Seventy-Two",
      "Iron 1200", "Sportster 1200 Roadster"], "883 cc and 1200 cc air-cooled V-twin, 1986 to 2022"),
    ("KTM LC8c engine", "ktm-lc8c", "ktm 790 890 engine problems", "KTM",
     ["790 Duke", "790 Adventure"], "799 cc and 889 cc parallel twin, 2018 on"),
    ("Kawasaki 649 cc twin", "kawasaki-649-twin", "kawasaki 650 twin problems", "Kawasaki",
     ["Ninja 650", "Z650", "Versys 650", "ER-6n"], "649 cc parallel twin, 2006 on"),
    ("Suzuki 645 cc V-twin", "suzuki-645-v-twin", "suzuki sv650 engine problems", "Suzuki",
     ["SV650", "V-Strom 650", "Gladius 650"], "645 cc V-twin, 1999 on"),
    ("Honda 471 cc twin", "honda-471-twin", "honda cb500 engine problems", "Honda",
     ["CB500F", "CB500X", "CBR500R", "Rebel 500"], "471 cc parallel twin, 2013 on"),
    ("Honda NC700 and NC750 twin", "honda-nc-twin", "honda nc750 engine problems", "Honda",
     ["NC700X", "NC750X", "NC700S", "NC750S"], "670 cc and 745 cc parallel twin, 2012 on"),
    ("Triumph 675 and 765 triple", "triumph-675-765-triple", "triumph 675 triple problems", "Triumph",
     ["Street Triple", "Daytona 675"], "675 cc and 765 cc triple, 2006 on"),
    ("Triumph 1050 triple", "triumph-1050-triple", "triumph 1050 triple problems", "Triumph",
     ["Speed Triple 1050", "Tiger 1050", "Speed Triple"], "1050 cc triple, 2005 to 2020"),
    ("BMW R 1200 and R 1250 boxer", "bmw-boxer-1200-1250", "bmw r1200 boxer problems", "BMW",
     ["R 1200 GS", "R 1200 RT", "R 1200 R", "R 1250 GS", "R 1250 RT"], "1170 cc and 1254 cc flat twin, 2004 on"),
]

# Bike types hub (approved 2026-11-26). (name, also called, slug, plural for headings, target keyword, examples)
TYPES = [
    ("Dual sport", "dual-purpose", "dual-sport", "Dual sport motorcycles", "most reliable dual sport motorcycle",
     "Kawasaki KLR650, Suzuki DR650S, Honda XR650L, Honda CRF300L"),
    ("Adventure", "ADV, adventure touring", "adventure", "Adventure motorcycles", "most reliable adventure motorcycle",
     "BMW R 1200 GS, Honda Africa Twin, Yamaha Tenere 700, KTM 790 Adventure"),
    ("Cruiser", "", "cruiser", "Cruisers", "most reliable cruiser motorcycle",
     "Harley-Davidson Fat Boy, Yamaha V Star 650, Kawasaki Vulcan 900, Honda Shadow"),
    ("Touring", "tourer, full-dress tourer", "touring", "Touring motorcycles", "most reliable touring motorcycle",
     "Honda Gold Wing, Harley-Davidson Electra Glide, BMW K 1600 GTL"),
    ("Sport touring", "sports tourer", "sport-touring", "Sport touring motorcycles", "most reliable sport touring motorcycle",
     "Yamaha FJR1300, Kawasaki Concours 14, Honda ST1300, Yamaha Tracer 900"),
    ("Supersport", "middleweight sportbike, 600 supersport", "supersport", "Supersport motorcycles", "most reliable supersport",
     "Yamaha YZF-R6, Kawasaki Ninja ZX-6R, Honda CBR600RR, Suzuki GSX-R600"),
    ("Superbike", "litre bike, liter bike", "superbike", "Superbikes", "most reliable superbike",
     "Yamaha YZF-R1, Honda CBR1000RR, Kawasaki Ninja ZX-10R, Suzuki GSX-R1000"),
    ("Naked", "naked bike, streetfighter", "naked", "Naked bikes", "most reliable naked bike",
     "Yamaha MT-07, Yamaha MT-09, Kawasaki Z900, Triumph Street Triple"),
    ("Muscle", "muscle bike, power cruiser", "muscle", "Muscle bikes", "most reliable muscle bike",
     "Yamaha Vmax, Suzuki Boulevard M109R, Ducati Diavel, Triumph Rocket III"),
    ("Scrambler", "", "scrambler", "Scramblers", "most reliable scrambler motorcycle",
     "Ducati Scrambler, Triumph Street Scrambler, BMW R nineT Scrambler"),
    ("Café racer", "cafe racer", "cafe-racer", "Café racers", "most reliable cafe racer",
     "Triumph Thruxton, BMW R nineT Racer, Royal Enfield Continental GT"),
    ("Modern classic", "retro, neo-retro", "modern-classic", "Modern classic motorcycles", "most reliable modern classic motorcycle",
     "Triumph Bonneville, Kawasaki Z900RS, Yamaha XSR700, Kawasaki W800"),
    ("Classic", "vintage, classic motorcycle", "classic", "Classic motorcycles", "classic motorcycle reliability",
     "Norton Commando, Triumph Bonneville T140, BSA A65, Moto Guzzi V50"),
    ("Flat tracker", "tracker", "flat-tracker", "Flat trackers", "most reliable flat tracker motorcycle",
     "Indian FTR 1200, Husqvarna Svartpilen 401"),
    ("Bagger", "", "bagger", "Baggers", "most reliable bagger",
     "Harley-Davidson Street Glide, Harley-Davidson Road Glide, Indian Chieftain"),
    ("Dirt bike", "trail bike, off-road bike", "dirt-bike", "Dirt bikes", "most reliable dirt bike",
     "Honda CRF450R, Yamaha YZ250, KTM 250 EXC-F, Honda CRF250L"),
    ("Trials", "trials bike", "trials", "Trials bikes", "most reliable trials bike",
     "Montesa Cota 4RT, GasGas TXT, Beta Evo"),
    ("Supermoto", "supermotard, motard", "supermoto", "Supermoto bikes", "most reliable supermoto",
     "KTM 690 SMC R, Husqvarna 701 Supermoto, Suzuki DR-Z400SM"),
    ("Minibike", "mini moto, monkey bike", "minibike", "Minibikes", "most reliable mini bike",
     "Honda Grom (MSX125), Honda Monkey, Kawasaki Z125"),
    ("Scooter", "", "scooter", "Scooters", "most reliable scooter",
     "Honda PCX125, Vespa 125, Yamaha TMAX, Suzuki Burgman 400"),
    ("Moped (50 cc)", "50cc moped", "moped", "Mopeds (50 cc)", "most reliable moped",
     "Piaggio Zip 50, Peugeot Speedfight 50"),
    ("Underbone", "step-through, cub", "underbone", "Underbones", "most reliable underbone motorcycle",
     "Honda Super Cub C125, Honda C90, Honda Innova 125"),
    ("Tricycle", "trike, three-wheeler", "tricycle", "Trikes and three-wheelers", "most reliable trike",
     "Harley-Davidson Tri Glide, Can-Am Spyder, Can-Am Ryker"),
    ("Electric", "electric motorcycle, e-motorcycle", "electric", "Electric motorcycles", "most reliable electric motorcycle",
     "Zero SR/F, LiveWire One, Energica Ego"),
    ("Sidecar", "sidecar outfit, sidecar combination", "sidecar", "Sidecar motorcycles", "sidecar motorcycle reliability",
     "Ural Gear Up, Ural Patrol"),
]

BLOG = [
    ("Motorcycle reliability statistics", "motorcycle-reliability-statistics", "motorcycle reliability statistics",
     "Every public figure on motorcycle reliability in one place, dated and sourced (market-research.md 4c.2). Link magnet."),
    ("What Consumer Reports measured about motorcycle reliability", "consumer-reports-motorcycle-reliability",
     "consumer reports motorcycle reliability", "Explainer: subscriber sample, brand level, 2008 to 2014 model years (4d.5)."),
    ("What breaks first after winter", "what-breaks-after-winter", "motorcycle won't start after winter",
     "Seasonal, publish February. Batteries, fuel and charging from owner repair logs (4b.1)."),
    ("Motorcycle recalls this month", "motorcycle-recalls-this-month", "motorcycle recalls",
     "Monthly roundup, every recall linked to its model page (4b.4). One post per month."),
    ("Pre-trip motorcycle inspection for touring season", "pre-trip-motorcycle-inspection",
     "pre-trip motorcycle inspection", "Before Daytona (March) and Sturgis (August), tied to touring models' failures (4b.5)."),
    ("First-year model watch", "first-year-model-watch", "first year motorcycle problems",
     "Living log of early owner reports on new models after EICMA and spring launches (4b.3)."),
    ("What to check when buying a used motorcycle", "used-motorcycle-checklist", "what to check when buying a used motorcycle",
     "Pre-purchase guide, links to every years-to-avoid page (3c)."),
    ("How many miles is high for a motorcycle", "high-mileage-motorcycle", "how many miles is high for a motorcycle",
     "Answered from UK MOT mileage by model (3c, 4d.2)."),
]


def slug(s):
    return re.sub(r"[^a-z0-9]+", "-", s.lower()).strip("-")


def base_name(model):
    return re.sub(r"\s*\((?:about \d+ cc|\d{4}-\d{4})\)$", "", model).strip()


def pick(options, n):
    """The first wording that fits n characters; never a sentence cut mid-phrase."""
    for o in options:
        if len(o) <= n:
            return o
    return options[-1]


def fmt(n):
    return f"{n:,}"


def main():
    c = sqlite3.connect(CAT)
    n = sqlite3.connect(NHTSA)
    us_years = defaultdict(set)
    for mk, fam, y, camp in n.execute("select make, model_family, year, campaign from recalls"):
        us_years[(mk, fam)].add((y, camp))
    groups = defaultdict(lambda: {"ids": [], "mot": 0, "complaints": 0, "gens": [], "raw": []})
    for bid, mk, model, mot, cpl, origin in c.execute(
            "select bike_id, make, model, mot_tests, us_complaints, origin from bikes"):
        if origin == "UK MOT family" or "(all versions)" in model:
            continue
        if re.search(r"[/,]", model):        # NHTSA families naming several models: their records sit on each model
            continue
        g = groups[(make_display(mk), display(mk, base_name(model)))]
        g["raw"].append(base_name(model))
        g["ids"].append(bid); g["mot"] += mot or 0; g["complaints"] += cpl or 0
        if model != base_name(model):
            g["gens"].append(model[len(base_name(model)):].strip(" ()"))
    # distinct recalls per model: other countries' campaigns, plus US campaigns within each page's model years
    for key, g in groups.items():
        q = ",".join(map(str, g["ids"]))
        camps = {r for r in c.execute(f"select source || campaign from bike_recalls where bike_id in ({q})")}
        for mk, fam, y0, y1 in c.execute(f"select make, model_family, year_from, year_to from bike_us_models where bike_id in ({q})"):
            camps |= {"NHTSA" + cp for y, cp in us_years[(mk, fam)] if (y0 is None or (y or 0) >= y0) and (y1 is None or (y or 0) <= y1)}
        g["recalls"] = len(camps)

    models = {k: g for k, g in groups.items()
              if g["mot"] >= MODEL_MIN["mot"] or g["complaints"] >= MODEL_MIN["complaints"] or g["recalls"] >= MODEL_MIN["recalls"]}
    brands = defaultdict(list)
    for (mk, md), g in sorted(models.items(), key=lambda kv: -(kv[1]["mot"] + 200 * kv[1]["complaints"])):
        brands[mk].append(md)

    rows = []
    used_urls = set()
    page_ids = []

    def add(name, url, ptype, kw, h1, title, desc, status, notes, parent=""):
        titles = title if isinstance(title, list) else [title]
        descs = desc if isinstance(desc, list) else [desc]
        t, d = pick(titles, 60), pick(descs, 155)
        assert "—" not in t + d + h1, "no em dashes"
        if len(t) > 60 or len(d) > 155:
            notes = (notes + " Meta too long: shorten by hand.").strip()
        if url in used_urls:     # two catalogue names that slug the same (Rocket III / Rocket Iii): keep both, flag
            n_ = 2
            while url.rstrip("/") + f"-{n_}/" in used_urls:
                n_ += 1
            notes = (notes + f" Slug clashed with another page at {url}: check whether it is the same model.").strip()
            url = url.rstrip("/") + f"-{n_}/"
        used_urls.add(url)
        rows.append({"Page Name": name, "URL Slug": url, "Page Type": ptype, "Target Keyword": kw, "H1": h1,
                     "Meta Title": t, "Meta Description": d, "Status": status,
                     "Notes": notes, "Parent": parent})

    total_models = len(models)
    add("Home", "/", "Homepage", "motorcycle reliability",
        "Know what breaks before you buy",
        "Motorcycle Reliability Database: What Breaks and When",
        f"Repair, recall and inspection records for {fmt(total_models)} motorcycles, by model, year and mileage. 21M+ official records, each labelled by source.",
        "To build", "Fixed site description from business-info.md goes here word for word. Secondary keyword: motorcycle problems database.")

    # bike types hub and one page per type
    add("Bike types", "/types/", "Bike types hub", "types of motorcycles",
        "Motorcycle reliability by bike type",
        ["Motorcycle Reliability by Bike Type", "Motorcycle Types: Reliability"],
        f"Compare reliability across {len(TYPES)} kinds of motorcycle, from adventure bikes and cruisers to scooters and trikes, model by model.",
        "Planned", "Needs a bike type assigned to every model page before build (no data source records it).", parent="Home")
    for name, aka, tslug, plural, kw, eg in TYPES:
        label = plural.lower()
        tp = " ".join(w if w[:1] in "(0123456789" or w in ("and", "cc)") else
                      "-".join(x[:1].upper() + x[1:] for x in w.split("-")) for w in plural.split())
        add(plural, f"/types/{tslug}/", "Bike type page", kw,
            f"{plural}: reliability by model",
            [f"Most Reliable {tp}: Problems by Model", f"Most Reliable {tp}", f"{tp} Reliability"],
            [f"Which {label} break least, and what fails on each, from official recall, complaint and inspection records. Examples: {eg}.",
             f"Which {label} break least, and what fails on each, from official recall, complaint and inspection records.",
             f"Which {label} break least, and what fails on each model."],
            "Planned", (f"Also called: {aka}. " if aka else "") + f"Examples: {eg}.", parent="Bike types")

    # brand pages and their model pages
    plat_of = defaultdict(list)
    for p in PLATFORMS:
        for m in p[4]:
            plat_of[(p[3], m)].append(p)
    years_pages = []
    for mk in sorted(brands, key=lambda b: -len(brands[b])):
        bslug = slug(mk)
        mlist = brands[mk]
        add(f"{mk} reliability", f"/{bslug}/", "Brand page (category hub)", f"{mk.lower()} reliability",
            f"{mk} reliability: problems and recalls by model",
            f"{mk} Reliability: Problems and Recalls by Model",
            f"What breaks on {len(mlist)} {mk} models, at what mileage, and which years were recalled. Official records, each labelled by source.",
            "To build (wave 1)" if any((mk, m) in WAVE1 for m in mlist) else "Planned",
            f"{len(mlist)} model pages. Secondary keyword: is {mk.lower()} reliable.", parent="Home")
    for mk in sorted(brands, key=lambda b: -len(brands[b])):
        bslug = slug(mk)
        for md in brands[mk]:
            g = models[(mk, md)]
            url = f"/{bslug}/{slug(md)}/"
            src = []
            if g["mot"]: src.append(f"{fmt(g['mot'])} UK inspections")
            if g["complaints"]: src.append(f"{fmt(g['complaints'])} US owner complaints")
            if g["recalls"]: src.append(f"{fmt(g['recalls'])} recalls")
            notes = "Data: " + ", ".join(src) + "."
            if g["gens"]:
                notes += " Generation sections: " + ", ".join(sorted(set(g["gens"]))[:6]) + "."
            if plat_of.get((mk, md)) and BUILD_ENGINE_PAGES:
                notes += " Engine: " + ", ".join(p[0] for p in plat_of[(mk, md)]) + "."
            if g["mot"] >= YEARS_MIN["mot"] or g["complaints"] >= YEARS_MIN["complaints"]:
                notes += f" Years to avoid section (secondary keyword: {md.lower()} years to avoid)."
            if "(unspecified)" in md:
                notes += " Catalogue name covers several models: check before publishing."
            raw = sorted(set(g["raw"]) - {md})
            if raw:
                notes += " Also listed as: " + ", ".join(raw[:5]) + "."
            wave = (mk, md) in WAVE1
            add(f"{mk} {md} problems", url, "Model page", f"{mk.lower()} {md.lower()} problems",
                f"{mk} {md} problems and reliability",
                [f"{mk} {md} Problems: What Breaks and When", f"{mk} {md} Problems and Recalls",
                 f"{md} Problems: What Breaks and When", f"{md} Problems and Recalls"],
                [f"What fails on the {mk} {md}, at what mileage, and which years were recalled. From " + ", ".join(src) + ".",
                 f"What fails on the {mk} {md}, at what mileage, and which years were recalled. From " + " and ".join(src[:2]) + ".",
                 f"What fails on the {md}, at what mileage, and which years were recalled. From " + " and ".join(src[:2]) + ".",
                 f"What fails on the {md}, at what mileage, and which years were recalled."],
                "To build (wave 1)" if wave else "Planned", notes, parent=f"{mk} reliability")
            rows[-1]["_raw_urls"] = [f"/{bslug}/{slug(x)}/" for x in g["raw"]]
            page_ids.append((rows[-1]["URL Slug"], mk, md, " ".join(map(str, g["ids"]))))
            if g["mot"] >= YEARS_MIN["mot"] or g["complaints"] >= YEARS_MIN["complaints"]:
                years_pages.append((mk, md, url, wave))

    # engine platforms hub and pages
    if BUILD_ENGINE_PAGES:
      add("Engine platforms", "/engines/", "Engine platforms hub (location hub)", "motorcycle engine problems",
        "Motorcycle engine problems by platform",
        "Motorcycle Engine Problems by Platform",
        "Problems pooled across every model that shares an engine, for bigger samples: CP2, CP3, Milwaukee-Eight, Twin Cam and more.",
        "Planned", "Needs a platform-to-model mapping table in the catalogue before build.", parent="Home")
    for name, pslug, kw, mk, members, spec in (PLATFORMS if BUILD_ENGINE_PAGES else []):
        live = [m for m in members if (mk, m) in models]
        tname = name.replace(" engine", " Engine").replace(" twin", " Twin").replace(" triple", " Triple").replace(" boxer", " Boxer")
        add(name, f"/engines/{pslug}/", "Engine platform page", kw, f"{name} problems",
            [f"{tname} Problems Across Every Model", f"{tname} Problems by Model", f"{tname} Problems"],
            [f"Known problems with the {name}, pooled across {', '.join(live[:4])}{' and more' if len(live) > 4 else ''}. {spec}.",
             f"Known problems with the {name}, pooled across {', '.join(live[:4])}{' and more' if len(live) > 4 else ''}.",
             f"Known problems with the {name}, pooled across {', '.join(live[:3])} and more."],
            "Planned", f"{spec}. Models: {', '.join(live)}.", parent="Engine platforms")

    # model x years pages
    for mk, md, url, wave in (years_pages if BUILD_YEARS_PAGES else []):
        add(f"{mk} {md} years to avoid", url + "years-to-avoid/", "Model years page (model x years)",
            f"{md.lower()} years to avoid", f"{mk} {md} years to avoid, and the best years",
            [f"{mk} {md} Years to Avoid and Best Years", f"{mk} {md} Years to Avoid", f"{md} Years to Avoid"],
            [f"Which {mk} {md} model years had recalls, complaint clusters or high MOT failure rates, and which years are the safer buys.",
             f"Which {md} model years had recalls, complaint clusters or high MOT failure rates, and which years are the safer buys.",
             f"Which {md} model years had recalls or high failure rates, and which years are the safer buys."],
            "To build (wave 1)" if wave else "Planned",
            "Push November to February (winter buying season).", parent=f"{mk} {md} problems")

    add("Blog", "/blog/", "Blog hub", "motorcycle reliability blog", "Motorcycle reliability: findings and guides",
        "Motorcycle Reliability Findings and Guides",
        "Findings from the database, seasonal guides and the monthly recall roundup, each tied back to model pages.",
        "Planned", "", parent="Home")
    for name, bslug, kw, note in BLOG:
        add(name, f"/blog/{bslug}/", "Blog post", kw, name, name,
            f"{name}, from official recall, complaint and inspection records plus owner repair logs.",
            "To build (wave 1)" if bslug == "motorcycle-reliability-statistics" else "Planned", note, parent="Blog")
    add("About", "/about/", "About page", "about motoercycleproblems.com", "About this database",
        "About the Motorcycle Reliability Database",
        "Who runs the site, how the data is collected, what is excluded, and how it is funded.",
        "Planned", "Independence statement (market-research.md 4a.5). Owner name stays out of the URL.", parent="Home")
    add("Methodology", "/about/methodology/", "About page (methodology)", "motorcycle reliability methodology",
        "How we measure motorcycle reliability", "How We Measure Motorcycle Reliability",
        "Our definition of reliability, every data source and what it measures, sample-size rules, and how each figure is calculated.",
        "To build (wave 1)", "Build first: every other page cites it (market-research.md, Where to start).", parent="About")
    add("Contact", "/contact/", "Contact page", "contact motoercycleproblems.com", "Contact", "Contact Us",
        "Report a data error, send a correction or ask about the dataset.", "Planned",
        "No sales language (business-info.md). Data corrections and press.", parent="Home")

    counts = defaultdict(int)
    for r in rows:
        counts[r["Page Type"]] += 1

    # internal linking tab
    links = [
        ("Homepage", "Brand pages (all)", "Link to every brand page, ordered by number of model pages.", "Brand name + reliability, e.g. \"Yamaha reliability\"", "Home > Yamaha reliability"),
        ("Homepage", "Bike types hub, Blog hub, Methodology", "Link to the other hubs. Methodology from the dataset claim near the top.", "Hub name", "Home > Bike types"),
        ("Brand page", "Model pages (its own, all)", "Link to every model page under the brand, grouped by category or engine.", "Model + problems, e.g. \"MT-07 problems\"", "Yamaha reliability > Yamaha MT-07 problems"),
        ("Bike types hub", "Bike type pages (all)", "Link to every bike type page, with its other names in the link's surrounding text.", "Type name, e.g. \"Adventure motorcycles\"", "Bike types > Adventure motorcycles"),
        ("Bike type page", "Model pages (all of that type)", "Link to every model of that type, ranked by reliability, grouped by brand where the list is long.", "Brand + model", "Naked bikes > Yamaha MT-07"),
        ("Bike type page", "Bike types hub, related type pages (2 to 3)", "Breadcrumb to the hub; in-text links to the closest types.", "Type name", "Cruisers > Baggers, Muscle bikes, Touring motorcycles"),
        ("Brand page", "Bike type pages (the brand's)", "Link to each type the brand makes, as a filter row above its model list.", "Type name", "Yamaha reliability > Naked bikes"),
        ("Model page", "Bike type page (its own, 1 to 2)", "In-text link near the top; a model with two types (scrambler and modern classic) links both.", "Type name", "Yamaha MT-07 problems > Naked bikes"),
        ("Model page", "Brand page (its parent)", "Breadcrumb plus one in-text link.", "Brand + reliability", "Yamaha MT-07 problems > Yamaha reliability"),
        ("Model page", "Sibling model pages (same brand)", "2 to 4 contextual links to models in the same category or sharing the engine (e.g. MT-07 and XSR700).", "Sibling model name", "MT-07 > XSR700, Tracer 700, Tenere 700"),
        ("Model page", "Methodology", "From every figure's source label.", "how we measure", "MT-07 > Methodology"),
        ("Blog post", "Model pages, Methodology", "Every model mentioned links to its model page (to its years-to-avoid section where relevant); every figure links to its source on Methodology.", "Model name", "Recall roundup > each recalled model's page"),
        ("Blog hub", "Blog posts (all)", "Reverse date order.", "Post title", "Blog > Motorcycle reliability statistics"),
        ("All pages", "About, Methodology, Contact", "Footer links on every page.", "Page name", "Footer"),
    ]

    os.makedirs(OUT, exist_ok=True)
    # bike types per model page (tools/bike_types.csv, from assign_bike_types.py; edit by hand where wrong)
    bt_file = os.path.join(ROOT, "tools", "bike_types.csv")
    btypes = {r["url"]: r for r in csv.DictReader(open(bt_file))} if os.path.exists(bt_file) else {}
    for r in rows:
        t = next((btypes[u] for u in [r["URL Slug"]] + r.get("_raw_urls", []) if u in btypes and btypes[u]["type_1"]),
                 next((btypes[u] for u in r.get("_raw_urls", []) if u in btypes), None))
        r["Bike type"] = t["type_1"] if t else ""
        r["Second type"] = t["type_2"] if t else ""
        r["Type note"] = (t["basis"] if t and t["basis"] != "rule" else "")
    # owner repair log (tools/owner_log.py) and hand-picked owner quotes (tools/owner_quotes.csv)
    osum = {}
    try:
        for u, ow, rp, ck, mx in c.execute("select url, owners, repairs, checkins, max_miles from owner_summary"):
            osum[u] = f"{ow} owner{'s' * (ow != 1)}, {rp} repair{'s' * (rp != 1)}" + (f", up to {fmt(mx)} mi" if mx else "")
    except sqlite3.OperationalError:
        pass
    qf = os.path.join(ROOT, "tools", "owner_quotes.csv")
    quotes = {q["url"]: q for q in csv.DictReader(open(qf))} if os.path.exists(qf) else {}
    for r in rows:
        q = quotes.get(r["URL Slug"], {})
        r["Owner reports"] = osum.get(r["URL Slug"], "")
        r["Owner quote"], r["Quote source"], r["Quote fits"] = q.get("quote", ""), q.get("source", ""), q.get("fits", "")
    cols = ["Page Name", "URL Slug", "Page Type", "Target Keyword", "H1", "Meta Title", "Meta Description", "Status", "Notes",
            "Bike type", "Second type", "Type note",
            "Owner reports", "Owner quote", "Quote source", "Quote fits"]
    with open(os.path.join(ROOT, "tools", "model_pages.csv"), "w", newline="") as f:   # page -> catalogue bike_ids
        w = csv.writer(f); w.writerow(["url", "make", "model", "bike_ids"]); w.writerows(page_ids)
    lcols = ["From page type", "Links to", "Rule", "Anchor text", "Example"]
    with open(os.path.join(OUT, "site-architecture-structure.csv"), "w", newline="") as f:
        w = csv.writer(f); w.writerow(cols)
        for r in rows: w.writerow([r[k] for k in cols])
        w.writerow([]); w.writerow(["Total pages", len(rows)])
    with open(os.path.join(OUT, "site-architecture-internal-linking.csv"), "w", newline="") as f:
        w = csv.writer(f); w.writerow(lcols); w.writerows(links)

    from openpyxl import Workbook
    from openpyxl.styles import Font, PatternFill, Alignment
    wb = Workbook()
    ws = wb.active; ws.title = "Structure"
    ws.append([f"Total pages: {len(rows)}"] + [f"{t}: {k}" for t, k in counts.items()][:8])
    ws["A1"].font = Font(bold=True, size=12)
    ws.append(cols)
    for cell in ws[2]:
        cell.font = Font(bold=True, color="FFFFFF"); cell.fill = PatternFill("solid", fgColor="1F2937")
    for r in rows:
        ws.append([r[k] for k in cols])
    ws.freeze_panes = "B3"
    ws.auto_filter.ref = f"A2:P{len(rows) + 2}"
    for col, wdt in zip("ABCDEFGHIJKLMNOP", (38, 42, 30, 34, 44, 52, 70, 18, 70, 18, 18, 34, 28, 70, 40, 44)):
        ws.column_dimensions[col].width = wdt
    ws2 = wb.create_sheet("Internal linking")
    ws2.append(lcols)
    for cell in ws2[1]:
        cell.font = Font(bold=True, color="FFFFFF"); cell.fill = PatternFill("solid", fgColor="1F2937")
    for l in links:
        ws2.append(list(l))
    for col, wdt in zip("ABCDE", (24, 40, 70, 40, 52)):
        ws2.column_dimensions[col].width = wdt
    for row in ws2.iter_rows(min_row=2):
        for cell in row:
            cell.alignment = Alignment(wrap_text=True, vertical="top")
    wb.save(os.path.join(OUT, "site-architecture.xlsx"))

    # mermaid: hubs and a readable sample of children
    def nid(s):
        return re.sub(r"[^A-Za-z0-9]", "_", s)
    L = ["```mermaid", "graph TD"]
    L.append('  home["Home"]')
    top = sorted(brands, key=lambda b: -len(brands[b]))[:6]
    for mk in top:
        L.append(f'  home --> {nid("b" + mk)}["{mk} reliability"]')
        for md in brands[mk][:3]:
            mid = nid("m" + mk + md)
            L.append(f'  {nid("b" + mk)} --> {mid}["{mk} {md} problems"]')
            if BUILD_YEARS_PAGES and any(y[0] == mk and y[1] == md for y in years_pages):
                L.append(f'  {mid} --> {nid("y" + mk + md)}["{mk} {md} years to avoid"]')
        if len(brands[mk]) > 3:
            L.append(f'  {nid("b" + mk)} --> {nid("more" + mk)}["+ {len(brands[mk]) - 3} more {mk} models"]')
    rest = len(brands) - len(top)
    L.append(f'  home --> morebrands["+ {rest} more brand pages"]')
    if BUILD_ENGINE_PAGES:
      L.append('  home --> eng["Engine platforms"]')
    for name, pslug, *_ in (PLATFORMS[:6] if BUILD_ENGINE_PAGES else []):
        L.append(f'  eng --> {nid("p" + pslug)}["{name}"]')
    if BUILD_ENGINE_PAGES:
        L.append(f'  eng --> moreeng["+ {len(PLATFORMS) - 6} more engine platforms"]')
    L.append('  home --> types["Bike types"]')
    for name, aka, tslug, plural, *_ in TYPES[:6]:
        L.append(f'  types --> {nid("t" + tslug)}["{plural}"]')
    L.append(f'  types --> moretypes["+ {len(TYPES) - 6} more bike types"]')
    L.append('  home --> blog["Blog"]')
    for name, bslug, *_ in BLOG[:4]:
        L.append(f'  blog --> {nid("bl" + bslug)}["{name}"]')
    L.append(f'  blog --> moreblog["+ {len(BLOG) - 4} more posts"]')
    L.append('  home --> about["About"]')
    L.append('  about --> meth["Methodology"]')
    L.append('  home --> contact["Contact"]')
    L.append("```")
    with open(os.path.join(OUT, "site-architecture-diagram.md"), "w") as f:
        f.write("# Site architecture: motoercycleproblems.com\n\n")
        f.write(f"Total pages: {len(rows)}\n\n")
        for t, k in counts.items():
            f.write(f"- {t}: {k}\n")
        f.write("\nHome > hubs > child pages. Brand and model lists show the largest brands and a sample of their models; "
                "every page is listed in site-architecture.xlsx.\n\n")
        f.write("\n".join(L) + "\n")
    print("pages:", len(rows))
    for t, k in counts.items():
        print(f"  {t}: {k}")


if __name__ == "__main__":
    main()
