"""One vocabulary for parts across the site.

CATEGORIES are exactly the categories of the Moto Repair Log form (site/index.html, CATEGORIES), so a
part is in the same category whether an owner logged it on the site or filed it with NHTSA.

NHTSA files each complaint and recall under a code such as "Service Brakes, Hydraulic:Foundation
Components:Hoses, Lines/Piping, And Fittings". part_name() turns a code into one plain motorcycle
name ("Brake hose or line"), and category() gives its form category. Codes are matched on the longest
known prefix, so "Exterior Lighting:Brake Lights:Switch" and "Electrical System:Ignition:Switch" get
different names instead of both becoming "Switch".
"""
import re

CATEGORIES = ['Engine', 'Electrical & lights', 'Battery & charging', 'Fuel system', 'Cooling',
              'Clutch & gearbox', 'Final drive', 'Brakes & ABS', 'Suspension & steering', 'Wheels & bearings',
              'Frame & bodywork', 'Electronics & dash', 'Other']
OTHER = 'Other'

E, EL, BAT, FUEL, COOL, CG, FD, BR, SS, WB, FB, ED = CATEGORIES[:12]

# normalised code prefix -> (part name, category). Longest prefix wins.
RULES = {
    # ---- engine
    "engine and engine cooling": ("Engine", E),
    "engine and engine cooling:engine": ("Engine", E),
    "engine and engine cooling:engine:gasoline": ("Engine", E),
    "engine and engine cooling:engine:diesel": ("Engine", E),
    "engine and engine cooling:engine:hard parts internal/mechanical": ("Engine internals", E),
    "engine and engine cooling:critical fasteners": ("Engine bolts", E),
    "engine and engine cooling:engine:oil/lubrication": ("Engine oil system", E),
    "engine and engine cooling:engine:oil/lubrication:pump": ("Oil pump", E),
    "engine and engine cooling:engine:oil/lubrication:oil cooler": ("Oil cooler", COOL),
    "engine and engine cooling:engine:gasoline:belts and associated pulleys": ("Cam belt or chain", E),
    "engine and engine cooling:engine:gasoline:turbo/supercharger": ("Turbo or supercharger", E),
    "engine and engine cooling:engine:crank/camshaft position sensor": ("Crank or cam sensor", ED),
    "engine and engine cooling:engine:engine control module (ecu/ecm)": ("Engine computer (ECU)", ED),
    "engine and engine cooling:engine:engine control module (ecu/ecm):software": ("Engine computer (ECU) software", ED),
    "engine and engine cooling:exhaust system": ("Exhaust", E),
    "engine and engine cooling:exhaust system:manifold/header/muffler/tail pipe": ("Exhaust", E),
    "engine and engine cooling:exhaust system:emission control": ("Emissions parts", E),
    "engine and engine cooling:exhaust system:emission control:crankcase (pcv)": ("Crankcase breather", E),
    "engine and engine cooling:exhaust system:emission control:catalytic convertor": ("Catalytic converter", E),
    "engine and engine cooling:exhaust system:emission control:gas recirculation valve (egr valve)": ("Emissions parts", E),
    "vehicle speed control": ("Throttle", E),
    "vehicle speed control:throttle": ("Throttle", E),
    "vehicle speed control:cables": ("Throttle cable", E),
    "vehicle speed control:linkages": ("Throttle cable", E),
    "vehicle speed control:accelerator pedal": ("Throttle", E),
    "vehicle speed control:throttle:throttle position sensor (tps)": ("Throttle position sensor", ED),
    "vehicle speed control:throttle:actuator/stepper motor": ("Throttle position sensor", ED),
    "vehicle speed control:cruise control": ("Cruise control", ED),
    # ---- cooling
    "engine and engine cooling:cooling system": ("Cooling system", COOL),
    "engine and engine cooling:cooling system:radiator assembly": ("Radiator", COOL),
    "engine and engine cooling:cooling system:fan": ("Cooling fan", COOL),
    "engine and engine cooling:cooling system:hoses/lines/piping/fittings": ("Coolant hose", COOL),
    # ---- fuel
    "fuel system": ("Fuel system", FUEL),
    "fuel system:delivery": ("Fuel pump or line", FUEL),
    "fuel system:delivery:fuel pump": ("Fuel pump", FUEL),
    "fuel system:delivery:fuel pump:control/drive module": ("Fuel pump", FUEL),
    "fuel system:delivery:hoses, lines/piping, and fittings": ("Fuel hose or line", FUEL),
    "fuel system:fuel injection system": ("Fuel injection", FUEL),
    "fuel system:fuel injection system:injectors": ("Fuel injector", FUEL),
    "fuel system:fuel injection system:fuel rail": ("Fuel injection", FUEL),
    "fuel system:carburetor system": ("Carburettor", FUEL),
    "fuel system:fuel filter": ("Fuel filter", FUEL),
    "fuel system:storage": ("Fuel tank", FUEL),
    "fuel system:storage:tank assembly": ("Fuel tank", FUEL),
    "fuel system:storage:tank assembly:mounting": ("Fuel tank mount", FUEL),
    "fuel system:storage:tank assembly:filler pipe and cap": ("Fuel cap", FUEL),
    "fuel system:storage:tank assembly:pressure relief devices": ("Fuel tank", FUEL),
    "fuel system:storage:auxillary tank": ("Fuel tank", FUEL),
    "fuel system:storage:fuel gauge system": ("Fuel gauge", ED),
    "fuel system:storage:evaporative emissions": ("Fuel tank vent", FUEL),
    "electrical system:instrument panel:fuel gauge": ("Fuel gauge", ED),
    # ---- electrical & lights
    "electrical system": ("Electrical", EL),
    "electrical system:wiring": ("Wiring", EL),
    "electrical system:wiring:fuses and circuit breakers": ("Fuse", EL),
    "electrical system:wiring:connectors/plugs/receptacles": ("Wiring connector", EL),
    "electrical system:ignition": ("Ignition", EL),
    "electrical system:ignition:switch": ("Ignition switch", EL),
    "electrical system:ignition:module": ("Ignition module", EL),
    "electrical system:ignition:coil": ("Ignition coil", EL),
    "electrical system:ignition:coil:spark plugs": ("Spark plug", EL),
    "electrical system:starter assembly": ("Starter motor", EL),
    "electrical system:starter assembly:relay": ("Starter relay", EL),
    "electrical system:starter assembly:solenoid": ("Starter relay", EL),
    "electrical system:horn": ("Horn", EL),
    "electrical system:motorcycle handlebar switch pod left/right": ("Handlebar switches", EL),
    "electrical system:motorcycle starter interlock system- clutch,neutral,sidestand": ("Clutch, neutral or sidestand switch", EL),
    "exterior lighting": ("Lights", EL),
    "interior lighting": ("Dash lights", ED),
    "exterior lighting:headlights": ("Headlight", EL),
    "exterior lighting:headlights:bulbs": ("Headlight", EL),
    "exterior lighting:headlights:switch": ("Handlebar switches", EL),
    "exterior lighting:headlights:high/low beam dimmer switch": ("Handlebar switches", EL),
    "exterior lighting:headlights:concealment devices": ("Headlight", EL),
    "exterior lighting:brake lights": ("Brake light", EL),
    "exterior lighting:brake lights:switch": ("Brake light switch", EL),
    "exterior lighting:tail lights": ("Tail light", EL),
    "exterior lighting:turn signal": ("Turn signal", EL),
    "exterior lighting:turn signal:switch": ("Handlebar switches", EL),
    "exterior lighting:turn signal:flasher unit": ("Turn signal", EL),
    "exterior lighting:turn signal:bulbs": ("Turn signal", EL),
    "exterior lighting:hazard flashing warning lights": ("Turn signal", EL),
    "exterior lighting:back up lights": ("Lights", EL),
    # ---- battery & charging (incl. electric bikes)
    "electrical system:12v/24v/48v battery": ("Battery", BAT),
    "electrical system:12v/24v/48v battery:cables": ("Battery cable", BAT),
    "electrical system:alternator/generator/regulator": ("Charging system (stator, regulator)", BAT),
    "electrical system:propulsion system": ("Electric drive system", BAT),
    "electrical system:propulsion system:traction battery": ("Drive battery (electric bike)", BAT),
    "electrical system:propulsion system:traction battery:management system/energy control module (bms/becm)": ("Drive battery (electric bike)", BAT),
    "electrical system:propulsion system:traction battery:thermal management": ("Drive battery (electric bike)", BAT),
    "electrical system:propulsion system:traction motor": ("Electric motor", BAT),
    "electrical system:propulsion system:cables": ("Electric drive wiring", BAT),
    "electrical system:propulsion system:fuses, relays, contacts, and shunts": ("Electric drive wiring", BAT),
    "electrical system:propulsion system:dc/dc converter": ("Electric drive system", BAT),
    "electrical system:propulsion system:charging": ("Charger (electric bike)", BAT),
    "hybrid propulsion system": ("Electric drive system", BAT),
    # ---- electronics & dash
    "electrical system:software": ("Electronics software", ED),
    "electrical system:instrument cluster/panel": ("Dash and gauges", ED),
    "electrical system:instrument panel": ("Dash and gauges", ED),
    "electrical system:instrument panel:speedometer/odometer": ("Speedometer", ED),
    "electrical system:integrated trailer brake control": ("Other electronics", ED),
    "equipment:electrical": ("Accessory electronics", ED),
    "equipment:electrical:radio/tape deck/cd etc.": ("Audio system", ED),
    "equipment:electrical:navigational system(global positioning system)": ("Navigation", ED),
    "communication": ("Crash alert system", ED),
    "electronic stability control": ("Stability control", ED),
    "traction control system": ("Traction control", ED),
    "forward collision avoidance": ("Radar cruise and collision warning", ED),
    "lane departure": ("Blind spot warning", ED),
    "back over prevention": ("Reverse camera", ED),
    "tires:pressure monitoring and regulating systems": ("Tyre pressure sensor", ED),
    # ---- clutch & gearbox
    "power train": ("Drivetrain", CG),
    "power train:manual transmission": ("Gearbox", CG),
    "power train:manual transmission:internal": ("Gearbox", CG),
    "power train:manual transmission:internal:gears": ("Gearbox", CG),
    "power train:manual transmission:internal:shaft": ("Gearbox", CG),
    "power train:manual transmission:seals/gaskets": ("Gearbox seal", CG),
    "power train:manual transmission:lubricant": ("Gearbox", CG),
    "power train:manual transmission:floor shift assembly": ("Gear lever and shift linkage", CG),
    "power train:manual transmission:column shift assembly": ("Gear lever and shift linkage", CG),
    "power train:manual transmission:shift pattern indicator": ("Gear indicator", ED),
    "power train:automatic transmission": ("Automatic or DCT gearbox", CG),
    "power train:automatic transmission:gear position indication (prndl)": ("Gear indicator", ED),
    "power train:automatic transmission:control module (tcm/pcm/tecm)": ("Automatic or DCT gearbox", CG),
    "power train:automatic transmission:lever and linkage": ("Gear lever and shift linkage", CG),
    "power train:automatic transmission:park/neutral start interlock switch": ("Clutch, neutral or sidestand switch", EL),
    "power train:clutch assembly": ("Clutch", CG),
    "power train:clutch assembly:pedal/hand lever(motorcycle)": ("Clutch lever", CG),
    "power train:clutch assembly:slave cylinder": ("Clutch slave cylinder", CG),
    "power train:clutch assembly:bell housing": ("Clutch", CG),
    "fuel system:kinetic:clutch": ("Clutch", CG),
    # ---- final drive
    "power train:driveline": ("Final drive", FD),
    "power train:driveline:chain/belt": ("Chain or belt", FD),
    "power train:driveline:chain/belt:sprokets/pulleys": ("Sprocket or pulley", FD),
    "power train:driveline:driveshaft": ("Driveshaft", FD),
    "power train:driveline:universal joint": ("Driveshaft", FD),
    "power train:driveline:center support bearing": ("Driveshaft", FD),
    "power train:driveline:differential unit": ("Final drive gear (shaft drive)", FD),
    "power train:axle assembly": ("Rear axle", FD),
    "power train:axle assembly:axle shaft": ("Rear axle", FD),
    "power train:axle assembly:axle shaft:seal": ("Rear axle", FD),
    "power train:axle assembly:banjo housing": ("Final drive gear (shaft drive)", FD),
    "power train:axle hubs": ("Rear axle", FD),
    "parking brake:driveline": ("Final drive", FD),
    # ---- brakes & ABS
    "service brakes": ("Brakes", BR),
    "service brakes:foundation components": ("Brakes", BR),
    "service brakes:foundation components:hoses, lines/piping, and fittings": ("Brake hose or line", BR),
    "service brakes:foundation components:master cylinder": ("Brake master cylinder", BR),
    "service brakes:foundation components:disc": ("Brakes", BR),
    "service brakes:disc": ("Brakes", BR),
    "service brakes:foundation components:disc:caliper": ("Brake caliper", BR),
    "service brakes:disc:caliper": ("Brake caliper", BR),
    "service brakes:foundation components:disc:pads": ("Brake pads", BR),
    "service brakes:disc:pads": ("Brake pads", BR),
    "service brakes:foundation components:disc:rotor": ("Brake disc", BR),
    "service brakes:disc:rotor": ("Brake disc", BR),
    "service brakes:foundation components:drum": ("Drum brake", BR),
    "service brakes:foundation components:differential proportional valve": ("Linked brake valve", BR),
    "service brakes:fluid": ("Brake fluid", BR),
    "service brakes:critical fasteners": ("Brake bolts", BR),
    "service brakes:pedals and linkages": ("Brake lever or pedal", BR),
    "service brakes:controls": ("Brake lever or pedal", BR),
    "service brakes:power assist": ("Brakes", BR),
    "service brakes:solenoid/actuator": ("Brakes", BR),
    "service brakes:software/programming": ("ABS", BR),
    "service brakes:brake fluid low warning": ("Brake fluid warning", BR),
    "service brakes:antilock/traction control/electronic limited slip": ("ABS", BR),
    "service brakes:antilock": ("ABS", BR),
    "service brakes:antilock/traction control/electronic limited slip:control unit/module": ("ABS unit", BR),
    "service brakes:antilock:control unit/module": ("ABS unit", BR),
    "service brakes:antilock/traction control/electronic limited slip:abs warning light": ("ABS warning light", BR),
    "service brakes:antilock:abs warning light": ("ABS warning light", BR),
    "service brakes:antilock/traction control/electronic limited slip:wheel speed sensor/tone ring": ("ABS wheel sensor", BR),
    "parking brake": ("Parking brake", BR),
    # ---- suspension & steering
    "suspension": ("Suspension", SS),
    "suspension:front": ("Front suspension (forks)", SS),
    "suspension:rear": ("Rear suspension", SS),
    "suspension:front:shock absorber": ("Front suspension (forks)", SS),
    "suspension:rear:shock absorber": ("Rear shock", SS),
    "suspension:rear:springs": ("Rear shock", SS),
    "suspension:front:springs": ("Front suspension (forks)", SS),
    "suspension:front:motorcycle fork/swingarm": ("Front suspension (forks)", SS),
    "suspension:rear:motorcycle fork/swingarm": ("Swingarm", SS),
    "suspension:rear:axle": ("Rear axle", FD),
    "suspension:front:control arm": ("Front suspension (three-wheeler)", SS),
    "suspension:front:stabilizer bar": ("Front suspension (three-wheeler)", SS),
    "suspension:multiple axle": ("Suspension", SS),
    "suspension:subframe/mounting bracket": ("Subframe", FB),
    "suspension:front:wheel bearing": ("Wheel bearing", WB),
    "suspension:front:hub": ("Wheel hub", WB),
    "steering": ("Steering", SS),
    "steering:steering wheel/handle bar": ("Handlebar", SS),
    "steering:steering wheel /handle bar": ("Handlebar", SS),
    "steering:critical fasteners": ("Handlebar or steering bolts", SS),
    "steering:column": ("Steering head", SS),
    "steering:column locking": ("Steering lock", SS),
    "steering:linkages": ("Steering linkage (three-wheeler)", SS),
    "steering:rack and pinion": ("Steering linkage (three-wheeler)", SS),
    "steering:gear box (other than rack and pinion)": ("Steering linkage (three-wheeler)", SS),
    "steering:hydraulic power assist": ("Power steering", SS),
    "steering:hydraulic power assist system": ("Power steering", SS),
    "steering:electric power assist system": ("Power steering", SS),
    # ---- wheels & bearings (tyres included: the form has no separate tyre category)
    "wheels": ("Wheel", WB),
    "wheels:rim": ("Wheel rim", WB),
    "wheels:hub": ("Wheel hub", WB),
    "wheels:hubcap/cover": ("Wheel cover", WB),
    "wheels:lugs/nuts/bolts/studs": ("Wheel bolts and axle nut", WB),
    "wheels:multi piece": ("Wheel rim", WB),
    "tires": ("Tyre", WB),
    "tires:tread/belt": ("Tyre", WB),
    "tires:sidewall": ("Tyre", WB),
    "tires:bead": ("Tyre", WB),
    "tires:valve": ("Tyre valve", WB),
    "tires:tube": ("Inner tube", WB),
    # ---- frame & bodywork
    "structure": ("Frame", FB),
    "structure:body": ("Bodywork, fairing and brackets", FB),
    "structure:body:bumpers": ("Crash bars and bumpers", FB),
    "structure:body:hood": ("Bodywork, fairing and brackets", FB),
    "structure:body:door": ("Bodywork, fairing and brackets", FB),
    "structure:body:trunk lid": ("Top box or trunk", FB),
    "structure:frame and members": ("Frame", FB),
    "structure:frame and members:underbody shields": ("Bash plate or underbody guard", FB),
    "structure:motorcycle:kickstand/center stand": ("Side or centre stand", FB),
    "structure:motorcycle:fairing/cowling/windscreen": ("Bodywork, fairing and brackets", FB),
    "latches/locks/linkages": ("Luggage lock", FB),
    "equipment:motorcycle:luggage/side/top cases": ("Luggage (panniers, top box)", FB),
    "equipment:mechanical:carrier/rack": ("Luggage rack", FB),
    "visibility": ("Mirrors and windscreen", FB),
    "visibility:rearview mirrors/devices": ("Mirror", FB),
    "visibility:windshield": ("Windscreen", FB),
    "visibility:defroster/defogger/hvac system": ("Heater (three-wheeler)", OTHER),
    "seats": ("Seat", FB),
    "seats:front assembly:seat heater/cooler": ("Heated seat", ED),
    # newer NHTSA complaint forms use broad codes only
    "engine": ("Engine", E),
    "fuel/propulsion system": ("Fuel system", FUEL),
    "visibility/wiper": ("Mirrors and windscreen", FB),
    "equipment adaptive/mobility": ("Accessories", OTHER),
    "trailer hitches": ("Trailer", OTHER),
    "other/i am not sure": ("Other", OTHER),
    "exterior lighting:lighting control module": ("Lights", EL),
    # ---- other
    "equipment": ("Accessories", OTHER),
    "equipment:other:labels": ("Labels and stickers", OTHER),
    "equipment:other:owners/service/other manual": ("Owner's manual", OTHER),
    "equipment:motorcycle:helmets": ("Helmet", OTHER),
    "equipment:recreational vehicle/trailer": ("Trailer", OTHER),
    "equipment:mechanical:slide-in camper": ("Trailer", OTHER),
    "air bags": ("Airbag", OTHER),
    "seat belts": ("Seat belt (three-wheeler)", OTHER),
    "child seat": ("Other", OTHER),
    "unknown or other": ("Other", OTHER),
}


def norm(code):
    c = (code or "").strip().lower()
    c = re.sub(r"\s*:\s*", ":", c)
    c = re.sub(r"^fuel system, (gasoline|diesel|other)", "fuel system", c)
    c = re.sub(r"^service brakes, (hydraulic|air|electric)", "service brakes", c)
    c = re.sub(r"^electronic stability control( \(esc\))?", "electronic stability control", c)
    return c


def lookup(code):
    """(part name, category) for an NHTSA component code."""
    parts = norm(code).split(":")
    for i in range(len(parts), 0, -1):
        hit = RULES.get(":".join(parts[:i]))
        if hit:
            return hit
    return ("Other", OTHER)


# broad names that say nothing beyond the category; left out of "parts named most often" lists
VAGUE = {"Other", "Electrical", "Brakes", "Fuel system", "Lights", "Drivetrain", "Suspension", "Steering",
         "Accessories", "Engine", "Final drive", "Wheel", "Frame", "Mirrors and windscreen", "Cooling system"}


def part_name(code):
    return lookup(code)[0]


def category(code):
    return lookup(code)[1]


def unknown_codes(codes):
    """Codes whose own path is not mapped (they fall back to a parent). For checking new data."""
    out = set()
    for c in codes:
        if norm(c) not in RULES:
            out.add(c)
    return out
