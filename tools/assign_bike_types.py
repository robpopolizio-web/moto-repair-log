"""Assigns each model page a bike type (up to two), for the bike type hubs.

No data source records a bike's type, so this is a hand-written rule list: for each brand, model-name patterns in
order, first match wins. Engine size (from the catalogue) settles a few: a sportbike up to 800 cc is a supersport,
above that a superbike; every 50 cc bike is a moped first. What no rule covers is left blank for a person to fill.

Types (approved 2026-11-26): see TYPES in build_site_architecture.py.
Input:  the model pages (make, model, cc, url) from models_cc.tsv
Output: bike_types.csv  make, model, url, type_1, type_2, basis
Run:    python3 tools/assign_bike_types.py <models_cc.tsv> <out.csv>
"""
import csv, re, sys

DS, ADV, CR, TO, ST, SS, SB, NK, MU, SC = ("Dual sport", "Adventure", "Cruiser", "Touring", "Sport touring",
                                           "Supersport", "Superbike", "Naked", "Muscle", "Scrambler")
CF, MC, FT, BG, DB, TR, SM, MB, SCO = ("Café racer", "Modern classic", "Flat tracker", "Bagger", "Dirt bike",
                                       "Trials", "Supermoto", "Minibike", "Scooter")
MO, UB, TRI, EL, SI = "Moped (50 cc)", "Underbone", "Tricycle", "Electric", "Sidecar"
SPORT = "SPORT"          # supersport or superbike, by engine size
VINTAGE = "Classic"      # a bike built before about 1991 (checked against UK MOT first-use years, 2026-11-26)
NOTBIKE = "NOTBIKE"      # an ATV or a three-wheeled car
GUESS = "GUESS"          # typed from what the brand mostly makes, not from the model: a person should check

# brand -> [(model regex, types...)]; matched case-insensitively against the model name, first match wins
R = {
 "Honda": [
  (r"^cbr500r|^cbr650|^cbr250rr", SS), (r"magna", CR), (r"^tlr", TR), (r"^mt 50", DS), (r"^cl250", SC), (r"^cd(?!125t)", NK),
  (r"^fx650", DS), (r"^fsh125", SCO), (r"^vfr400|^nc30|^rvf", SS),
  (r"gold ?wing", TO), (r"^(st1[13]00|pan 1100|pacific coast|deauville|ntv|nt1100|nt700)", ST),
  (r"^vfr1200x|crosstourer|africa twin|transalp|varadero|xrv|xl1000v|xl650v|xl700v|xl750|nc7[05]0x|cb500x|adv750|x-adv", ADV),
  (r"^nc7[05]0s|^nc700d|integra", NK), (r"^vfr|interceptor|^vf\d|^rvf|^nc30", ST),
  (r"^(cbr\d+r|cbr929|cbr954|cbr900|fireblade|rc51|cbr1000rr)", SPORT), (r"^cbr1100xx|blackbird|^cbr1000f", ST),
  (r"^cbr600f|^cbr650f|^cbr650r|^cbr500|^cbr400|^cbr250|^cbr300|^cbr125|^nsr|^ns400|^ns125|^vfr400|^cbr", SPORT),
  (r"vtr1000|super hawk|firestorm", SB),
  (r"valkyrie|f6c|^vtx1800|rune", MU), (r"^vtx|^vt\d|shadow|^fury|rebel|^ctx|^cmx|^cm\d|^cmx|^vt1300|interstate|magna|^ca125|^cd\d|^cn250", CR),
  (r"^xr650l|^xl\d|^xlr|^slr|^nx|^fmx|^dominator|^crf\d+l|^crm|^xl185|^xr250|^xr125|^xr400|^cl250|^tlr", DS),
  (r"^crf\d+[rxf]|^cr\d+|^xr600|^xr\d", DB), (r"^mtx", DS),
  (r"grom|^msx|monkey|^z50|^dax|^st70|^st50", MB),
  (r"^c90|^c70|^c50|^cub|super cub|innova|^anc|^afs|^nhx|wave|^h100|^ss50|^cd125t|^ps125|^nh80", UB),
  (r"^(pcx|sh |sh\d|vision|lead|forza|s-wing|silver wing|ses|pes|nes|fes|zoomer|ruckus|sfx|sgx|nps|szx|sj|x8r|city 50|express|camino|melody|pc50|elite|metropolitan|adv160|nss|^mt 50)", SCO),
  (r"^cbx1000|^cb750|^cb550|^cb450|^cb350|^cb360|^cb400|^cb200|^cb100|^cb125t|^cb250|^cb650z|^cx\d|^gl500|^xbr|^cd175|^cd185|^cd250|^cm200|^cb1$|^bros|^cb900|^nighthawk|^cb550", NK),
  (r"^cb1100", MC), (r"^cb|hornet|^919|^cbf|^cg|^cl|^125$|^250$|^400$|^600$|^750$", NK),
  (r"^nsa700|^ntv600|^nt650", ST), (r"^cb125f|^clr|^xr125", NK),
 ],
 "Yamaha": [
  (r"^tt250r", DS),
  (r"^yzf-?r1$|^yzf-r1|thunderace|^yzf1000|^fzr1000|^yzf750|^gts1000|^r1", SB),
  (r"^yzf-?r6|^yzf600|^yzf-r7|^fzr\d|^thundercat|^yzf-r3|^yzfr125|^yzf125|^tzr|^tdr|^rd\d|^fz750|^fzx|^fzr750", SPORT),
  (r"^fjr|^fj\d|^tracer|^tdm|^fj09|^gts|^diversion 900|^xj900", ST),
  (r"super tenere|^xtz|tenere 700|^xt1200", ADV),
  (r"^xt\d|^serow|^serrow|^tw\d|^xg250|^wr\d+r|^wr125|^wr250r|^dt\d|^xt660", DS), (r"^wr250x|^wr125x", SM), (r"^xt660x", SM),
  (r"^wr|^yz|^tt-?r|^ttr|^tt600|^wr4", DB),
  (r"vmax|^vmx", MU), (r"^mt-01", MU), (r"roadliner|stratoliner|star venture|royal star venture|royal star tour|road warrior", TO),
  (r"road star|v star|^xv|^xvs|virago|bolt|raider|royal star|dragstar|drag star|^535|^xv1600|^xv1700|^xv1000", CR),
  (r"^xsr|^xs650|^sr400|^sr500|^sr250|^srx|^sr125", MC),
  (r"^mt-|^mt\d|^mt |^fz\d|^fz1|^fz8|^fazer|^xj6|^xj\d|^xjr|^fz6|^ybr|^ys125|^yb100|^rxs|^szr|^trx|^bt1100|^xs\d|^xj650|^xj550|^xj750|^diversion|^fz600|^xt350", NK),
  (r"^xsr125", MC),
  (r"tmax|^xp|majesty|^yp|x-max|xmax|^xc|^nxc|^gpd|^cw|^cs50|jog|^yq|^yn|aerox|^bws|^ew50|^ns50|^ovetto|^xq|^vity|^teo|^delight|^x-city|^zuma|^smax|^vino|^morphous|^c3|^mws|^qt50|^hw125|^yh50|^fs1", SCO),
  (r"^t80|^mt 50", UB), (r"^tzr50|^dt50", MO),
 ],
 "Kawasaki": [
  (r"^ninja$", "SKIP"), (r"ninja 500", SS), (r"z900rs|^w\d|^zephyr", MC), (r"^z125", MB), (r"^kmx|^klx650", DS),
  (r"ninja zx-12|^zx1200-c1h|^zx1200", SB), (r"zz-?r1100", ST),
  (r"ninja zx-14|zzr1400|^zx1400|^zx14|ninja zx-12|^zx1200|zzr1200|zz-?r1100|^zx1100|^gpz1100|^gpz1000|^gpx750|^gpz900|^gpz750|^gpz600|^gpx600|^zzr600|^zzr400|^gpz550|^gpz305|^gpx250|^gpz500|^ex500|ninja 500r|^gpz", None),
  (r"ninja zx-10|^zx-10|^zx1000|ninja zx-9|ninja h2$|^zx1002", SB), (r"ninja zx-6|^zx600|^zx636|^zx-7r|^zxr\d|^zx600", SS),
  (r"ninja h2 sx|concours|^gtr|^1400gtr|^zg1400|ninja 1000|^zzr1200|^zx1100", ST),
  (r"^zx1400|zzr1400|ninja zx-14|zx-14r", ST),
  (r"ninja (250|300|400|500|650)|^ninja$|^ex650|^er-?6f|^zzr600|^zzr400|^gpz|^gpx|^ex500|^kr1s|^zxr", SPORT),
  (r"versys|^klz|^kle650|^kle500|^klv1000", ADV),
  (r"klr|^kl\d|^klx\d+s|super sherpa|^kdx|^ke100|^klx230|^klx300|^klx250|^klr", DS), (r"^klx650|^kmx|^kx", DB),
  (r"vulcan 2000|^vn2000|vulcan 1700|voyager|vulcan 1600|^vn1600", CR), (r"voyager", TO),
  (r"vulcan|^vn\d|^en\d|^en |^el250|eliminator|^zl\d|^vn750", CR),
  (r"^w\d|z900rs|^zephyr|^zrx|^z1$|^kz|^z1100|^z1000$|^z1300|^z550|^z650$|^z750$|^z750s|^z900$|^z400$", NK),
  (r"^z\d|^z h2|^er-?\d|^er\d|^er5|^er 300|^er500|^zr-7|^zr550|^gt\d|^h1|^kh\d|^z125|^z200|^z250|^br125|^ar\d|^bx125|^ej", NK),
  (r"^sc ?300|^j300|^j125", SCO),
 ],
 "Suzuki": [
  (r"drz?-?400sm|dr-z400sm", SM), (r"^tu250", MC), (r"^fl125", UB),
  (r"^tl1000s", SB),
  (r"gsx-?r ?1000|^gsxr1000|hayabusa|gsx1300r|^tl1000r|^gsx-?r ?1100", SB), (r"^gsx-?r|^gsxr|^rgv|^rg\d|^rf600|^gsxf|^katana|^gsx250r|^gsxr400|^gsx-?r", SPORT),
  (r"^rf900", ST), (r"^gsx650f|^bandit 1250f|^gsx1250f|^gsx-?s ?1000gt", ST),
  (r"v-?strom|^dl\d|^xf650", ADV),
  (r"dr-?z400s$|^dr-?z?400s|^dr\d|^ts\d|^dr650|^dr350|^dr200|^dr250|^dr125|^dr600|^dr800|^djebel|^tu250|vanvan|^drz400e", DS),
  (r"drz?-?400sm|^dr-z400sm", SM), (r"^rm\d|^rmz", DB),
  (r"m109|m90|vzr|b-king|^vlr1800|intruder m1800", MU),
  (r"boulevard|intruder|marauder|^vl\d|^vs\d|^vz\d|savage|^gz|^gn\d|^en125|^volusia|^c50|^c90|^s83|^m50", CR),
  (r"burgman|^an\d|^uh\d|^ux\d|^uk110|^uc125|^ay50|^ap50|^ae50|^uf50|^fz50|^tr50|^address|^katana 50|^epicuro|^fl125", SCO),
  (r"^fl125s", UB),
  (r"bandit|^gsf|^sv|gladius|^gs\d|^gsx\d|^gsx-?s|^gsxs|^gsr|^gw250|^gt\d|^t500|^gs500|^gs ", NK),
  (r"^rv\d|^tu250", DS), (r"^gp100|^gs125|^en125|^gn125", NK), (r"^ts50|^tr50s", MO),
 ],
 "BMW": [
  (r"^k ?1600 ?b", BG), (r"^r 18", CR), (r"^f 650$", ADV),
  (r"^k ?1600|^k ?1200 ?lt|^k ?100 ?lt|^k ?1100 ?lt|^r ?1[12][05]0 ?rt|^r ?1200 ?rt|^r ?100 ?rt|^r ?1100 ?rt|^r ?1250 ?rt|^r 18", TO),
  (r"^k ?1600 ?b", BG),
  (r"^r ?1[0-3][05]0 ?gs|^r ?1200 ?gs|^gs 1200|^r ?100 ?gs|^f ?[789][05]0 ?gs|^f ?[67]00 ?gs|^f ?650 ?gs|^g ?310 ?gs|^f 850|^f 750 ?gs|^f800 ?gs|^hp2 enduro|^r 1300 gs|^g ?650 ?gs|^gseries|^fseries 800|^fseries 650", ADV),
  (r"^g650x country|^g ?650 ?x|^g650x|^g ?650$", DS), (r"^g650x moto|^hp2 megamoto", SM),
  (r"^k ?1[23]00 ?gt|^k ?1200 ?rs|^k ?1100 ?rs|^k ?100 ?rs|^r ?1[12][05]0 ?rs|^r ?1250 ?rs|^r ?1200 ?st|^f ?800 ?st|^f ?800 ?gt|^r100rs|^k75|^k1$|^k100$|^k series|^f ?900 ?xr|^s ?1000 ?xr|^m 1000 xr|^r 1250 rs", ST),
  (r"^s ?1000 ?rr|^hp4|^m 1000 rr|^k ?1[23]00 ?s|^k ?1200 ?s|^r ?1100 ?s|^r ?1200 ?s|^hp2 sport", SB),
  (r"r ?ninet|^r ?1[0-3]00 ?r|^r ?1[0-3][05]0 ?r|^r1100|^s ?1000 ?r|^m 1000 r|^k ?1[23]00 ?r|^k1300 r|^f ?[89]00 ?r|^f800 r|^g ?310 ?r|^f ?650 ?cs|^f ?650|^f ?800 ?s|^r ?850|^r series|^f750", NK),
  (r"^r ?1200 ?c|^r ?1200 ?cl", CR),
  (r"^c ?[46]\d0|^c1$|^c400|^c evolution|^ce 04|^c 400 x", SCO),
  (r"^r\d\d|^r ?90s|^r100r|^r45|^r65|^r75|^r80|^r60|^r100$", NK),
 ],
 "Triumph": [
  (r"^tiger 1050", ST),
  (r"rocket", MU), (r"^tiger 800|^tiger 900|^tiger 1050|^tiger 1200|^tiger$|^tiger 1200|^tiger 900", ADV), (r"tiger sport", ST),
  (r"^trophy|^sprint", ST), (r"^daytona 6[06]|^tt600|^daytona 675|^daytona 600|^daytona 660", SS),
  (r"^daytona", SB), (r"^speed four", SS),
  (r"thruxton|street cup", CF), (r"scrambler", SC), (r"bonneville|^t100$|street twin|speed twin|^speed 400|^t120", MC),
  (r"thunderbird|^america|speedmaster|^legend|^adventurer|bobber", CR),
  (r"street triple|speed triple|^trident 660|^trident$|^trident 880|^trident 750", NK),
  (r"^tr6|^t110|^t140|^3ta|^5ta|^6t|^t100ss|^t120r|^t140v|^t140e", VINTAGE),
 ],
 "Ducati": [
  (r"^900ss|^750$|^600$", SS), (r"^sport 1000|^gt1000", MC),
  (r"panigale v4|^1299|^1199|^1198|^1098|^999|^998|^996|^916|^888|^851|desmosedici|superbike|^sbk|new superbike|^955sp", SB),
  (r"^749|^748|^848|^panigale 959|^959|^899|^f848", SS),
  (r"multistrada|^mts|desertx", ADV), (r"^st\d|supersport|^sport 1000|^gt1000|^900ss|^750$|^600$", ST),
  (r"^supersport", ST), (r"hypermotard|hyperstrada", SM), (r"diavel|xdiavel", MU),
  (r"scrambler", SC), (r"^sport 1000|^gt1000|^classic", MC),
  (r"monster|^m\d|^m ?1200|streetfighter|^sft|^s2r|^s4r", NK),
  (r"^standard$", None),
 ],
 "KTM": [
  (r"1290superdukegt", ST),
  (r"super ?duke|^1290superduker|^990superduke|^990 duke|^890duker|^790 duke|^690 duke|^390 duke|^250 duke|^125$|^duke|lc4 duke|^single cylinder lc4 duke|^lc4 duke", NK),
  (r"adventure|^lc8$|^v-twin lc8 adventure|superenduro|^950 superenduro", ADV), (r"1290superdukegt", ST),
  (r"smc|supermoto|^450smr|^525smr|^625smc|^990supermotot|^v-twin lc8 supermoto", SM),
  (r"^rc ?\d|^rc8|^rc125", SPORT),
  (r"690 enduro|^640$|^640 ", DS),
  (r"exc|^xc|xc-w|xcf|^\d+sx|freeride|enduro|closed course|^\d+ xc", DB),
  (r"^10$", ADV),
 ],
 "Harley-Davidson": [
  (r"tri glide|freewheeler|trike", TRI), (r"sidecar", SI), (r"pan america", ADV),
  (r"street glide|road glide|^fltr|^flhx|^cvo street glide|^cvo road glide|road glide custom|^fltrxse|^flhxse", BG),
  (r"electra|ultra|road king|^flht|^flhr|^police|^fl\d|^flh|^fltc|touring|^eglide|^flhs|^cvo limited|^fl$|^flh1200|^cvo road king|^flhtcu|^flhtk", TO),
  (r"v-?rod|night rod|^vrsc|muscle|^cvo v-rod", MU),
  (r"sportster|^xl|iron|forty-eight|nightster|^883|superlow|^xlh|^xlch|^xls|^1000$|roadster|^xr1200", CR),
  (r"^street ?750|^street ?500|street rod|harley-davidson street", CR),
  (r"^mt350|^mt500", DS),
  (r".", CR),
 ],
 "Indian": [
  (r"^chief", CR),
  (r"ftr", FT), (r"roadmaster|^chief roadmaster", TO), (r"chieftain|chieftan|challenger|pursuit|springfield|dark horse$", BG),
  (r"^dark horse|^indian challenger", BG), (r"scout bobber|chief bobber|bomber", CR), (r".", CR),
 ],
 "Victory": [(r"^vision", TO), (r"magnum|hard-?ball", BG), (r"cross country|cross roads|touring cruiser", BG), (r".", CR)],
 "Aprilia": [
  (r"rsv4|^rsv|^mille|^rs ?660|^tuono v4 1100|falco|^rst1000|^rst futura", None),
  (r"^rsv|^mille|^rsv4", SB), (r"tuono", NK), (r"^rs ?660|^rs250|^rs125|^rs4|^rs50|^rs 50", SPORT),
  (r"caponord|pegaso|^etv", ADV), (r"^rst|futura|falco|^sl ?1000", ST), (r"dorsoduro|^sx\d|^mx125|^rx\d", SM),
  (r"^sl ?750|shiver|mana", NK),
  (r"^sr|^sonic|^rally|^area 51|^sportcity|^atlantic|^scarabeo|^leonardo|^habana|^mojito|^sport 125|^sport 300", SCO),
 ],
 "Moto Guzzi": [
  (r"^750$", "SKIP"), (r"^t3|^850$|^v50|^v65", VINTAGE), (r"^le ", CF),
  (r"stelvio|v85|^v85", ADV), (r"norge|california 1400 touring|^spada", ST), (r"griso|^sport 1100|^1000s|^v11 sport|^le|centauro|^v10", NK),
  (r"^v7|^v9 roamer|^v65|^v50|^breva|^v11$|^750$|^850$|^t3|^v100", MC), (r"california|^nevada|eldorado|audace|^v9 bobber|^v12", CR),
 ],
 "Buell": [(r"ulysses|^xb12x", ADV), (r"^1125r|firebolt|^xb9r|^xb12r", SS), (r"^1125cr|lightning|^xb\d+s|^x1|^m2|^s1|^s2|^s3|cyclone|thunderbolt|^classic", NK), (r"blast", NK)],
 "Husqvarna": [(r"svartpilen", FT), (r"vitpilen", CF), (r"701 supermoto|^sm\d", SM), (r"701 enduro|^te610|^g 650|^tr650", DS), (r".", DB)],
 "Royal Enfield": [(r"himalayan", ADV), (r"continental", CF), (r"meteor|crusader", CR), (r"int ?650|bullet|bullt", MC)],
 "Enfield": [(r".", MC)],
 "Can-Am": [(r".", TRI)], "Arcimoto": [(r".", TRI, EL)], "Vanderhall": [(r".", NOTBIKE)], "Polaris": [(r"^victory", CR), (r".", NOTBIKE)],
 "Zap": [(r".", NOTBIKE)], "Taotao": [(r".", NOTBIKE)],
 "Zero": [(r"^ds|^dsr|^x$|^fx|^mx|^xu", DS, EL), (r"^s$|^sr$", NK, EL)], "LiveWire": [(r".", NK, EL)], "Brammo": [(r".", NK, EL)],
 "Niu": [(r".", SCO, EL)], "Sondors": [(r".", NK, EL)],
 "Ural": [(r".", SI)],
 "Big Dog": [(r".", CR)], "American IronHorse": [(r".", CR)], "Excelsior-Henderson": [(r".", CR)], "Independence": [(r".", CR)],
 "MV Agusta": [(r"^f4|^f3", SS), (r"^f4", SB), (r"brutale|dragster", NK), (r"^f6", None)],
 "Cagiva": [(r"mito", SS), (r"raptor|v-raptor|planet", NK), (r"grand", ADV)],
 "Benelli": [(r"trk", ADV), (r"tornado 900", SS), (r"tornado 125|bn125", NK), (r"^k2", MO)],
 "CFMoto": [(r"ibex", ADV), (r"450ss", SS), (r"300nk", NK), (r"700cl-x", MC), (r"cf700", NK)],
 "CCM": [(r"r30|604r|604e|404ds|dual 644|644ds", DS)],
 "Beta": [(r"alp", DS), (r"xtrainer|^rr", DB)],
 "GasGas": [(r"pampera", TR), (r"^ec|^es", DB)], "Montesa": [(r".", TR)], "Sherco": [(r".", DB)], "Husaberg": [(r".", DB)],
 "Hyosung": [(r"^gt\d", NK), (r"^gv|^cruise", CR), (r"^rx", DS)],
 "Laverda": [(r"^750s", SS), (r".", VINTAGE)], "Vincent": [(r".", VINTAGE)], "Velocette": [(r".", VINTAGE)], "BSA": [(r".", VINTAGE)],
 "Matchless": [(r".", VINTAGE)], "Sunbeam": [(r".", VINTAGE)], "Ariel": [(r".", VINTAGE)], "Jawa": [(r".", VINTAGE)],
 "Morini": [(r".", VINTAGE)], "Armstrong": [(r".", DB)], "Puch": [(r".", MO)],
 "Norton": [(r"commando 961|^commando$", MC), (r".", VINTAGE)],
 "MZ": [(r"baghira", SM), (r"skorpion", NK), (r".", VINTAGE)],
 "Lambretta": [(r".", SCO)], "Vespa": [(r".", SCO)], "Scomadi": [(r".", SCO)], "Italjet": [(r".", SCO)],
 "Kymco": [(r"pulsar|zing|hipster|k-pipe|ck 125", NK), (r".", SCO)], "Peugeot": [(r".", SCO)], "Gilera": [(r"smt|rcr", SM), (r"fuoco", SCO, TRI), (r".", SCO)],
 "Piaggio": [(r"mp3", SCO, TRI), (r".", SCO)], "SYM": [(r"husky|xs125|wolf|^az|^red 50|^dd50|^vs125", NK), (r".", SCO)],
 "MBK": [(r".", SCO)], "TGB": [(r".", SCO)], "Baotian": [(r".", SCO)], "Longjia": [(r".", SCO)], "Direct Bikes": [(r".", SCO)],
 "Easy Rider": [(r".", SCO)], "Sukida": [(r"sk50qt", SCO), (r".", NK, GUESS)], "Znen": [(r".", SCO)], "Beeline": [(r".", SCO)],
 "Cpi": [(r".", SCO)], "Malaguti": [(r".", SCO)], "Royal Alloy": [(r".", SCO)], "Chunfeng": [(r".", SCO)], "Vmoto": [(r".", SCO, EL)],
 "Generic": [(r"trigger", DS), (r".", SCO, GUESS)], "Derbi": [(r"senda|terra", DS), (r"gpr|gp1", SS), (r".", SCO)],
 "AJS": [(r"16ms", VINTAGE), (r"cadwell", CF), (r"dd125e", DS), (r"modena|jsm|js125", NK), (r".", SCO)],
 "Lexmoto": [(r"^ht125", NK), (r"echo|hunter|milano|isca|diablo|titan|fmr|viper|tommy|venom|valiant|zsx|xflm|wy|zn|dfe|enigma", None),
             (r"echo|milano|tommy|fmr 50|hunter|titan|diablo|viper|isca|zn|wy|valiant", SCO),
             (r"michigan|arizona|gladiator", CR), (r"xtr|assault|adrenaline|venom|enigma|lxr|zsb|fmr125|zsx|xflm|zsf|arrow|dfe|fmx", NK)],
 "Keeway": [(r"superlight", CR), (r"tx125", DS), (r"rk|rkf|rks", NK), (r"hurricane|k-light", SCO)],
 "Rieju": [(r"mrt|marathon", DS), (r"rs", SS)], "Sinnis": [(r"shuttle", SCO), (r"xf125gy", DS), (r".", NK, GUESS)],
 "Pulse": [(r"xf125gy", DS), (r".", SCO)], "Herald": [(r"xf125gy", DS), (r"classic", MC)], "Pioneer": [(r".", DS)],
 "Shineray": [(r".", DS)], "Lifan": [(r"gy", DS), (r".", NK, GUESS)], "Jinlun": [(r".", NK, GUESS)], "Haotian": [(r".", NK, GUESS)], "Huoniao": [(r".", NK, GUESS)],
 "Qingqi": [(r".", NK, GUESS)], "Zongshen": [(r".", NK, GUESS)], "Zontes": [(r".", NK, GUESS)], "Hartford": [(r".", NK, GUESS)], "Better": [(r".", NK, GUESS)],
 "Skyjet": [(r".", NK, GUESS)], "Superbyke": [(r".", SS)], "Mutt": [(r".", MC)], "Tamoretti": [(r".", CF)], "Ksr Moto": [(r"grs", NK), (r"worx", SM)],
 "Bullit": [(r".", MC)], "Mondial": [(r".", NK)], "Daelim": [(r".", CR)], "Sachs": [(r"roadster", NK), (r"xtc", SS)],
 "White Knuckle": [(r".", NK, GUESS)], "Ic": [(r".", NOTBIKE)], "LML": [(r".", SCO)],
}

# 50 cc and under: a moped first, its style second
STYLE_50 = {SCO: SCO, SS: SS, DS: DS, DB: DB, NK: NK, SM: SM, UB: UB, MB: MB}


def assign(make, model, cc):
    for rx, *types in R.get(make, []):
        if not re.search(rx, model, re.I):
            continue
        guess = GUESS in types
        types = [t for t in types if t and t != GUESS]
        if not types:
            continue          # a pattern listed only to fall through to the next rule
        if types == ["SKIP"]:
            return [], "unassigned"     # too vague a name to type (Kawasaki "Ninja")
        if not cc:
            m = re.search(r"(\d{3,4})", model)
            cc = int(m.group(1)) if m else None
        out = []
        for t in types:
            if t == SPORT:
                t = SS if (cc and cc <= 800) else SB
            out.append(t)
        if cc and cc <= 50 and out and out[0] not in (VINTAGE, NOTBIKE, MO) and out[0] not in (EL,):
            out = [MO] + [o for o in out if o != MO][:1]
        # a second hub where the bike honestly belongs to two: a bagger is a tourer too, a retro-styled
        # scrambler or café racer is a modern classic too
        if out == [BG]:
            out.append(TO)
        if out[0] in (SC, CF) and make in ("Triumph", "Ducati", "Royal Enfield"):
            out.append(MC)
        return out, ("guessed from brand (check)" if guess else "rule")
    if cc and cc <= 50:
        return [MO], "engine size only (check)"
    return [], "unassigned"


def main(src, dst):
    rows = list(csv.reader(open(src), delimiter="\t"))
    n = {"rule": 0}
    with open(dst, "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["make", "model", "url", "type_1", "type_2", "basis"])
        for make, model, cc, url in rows:
            types, basis = assign(make, model, int(cc) if cc.strip().isdigit() else None)
            note = basis
            if types and types[0] == NOTBIKE:
                types, note = [], "not a motorcycle (ATV or three-wheeled car)"
            w.writerow([make, model, url, types[0] if types else "", types[1] if len(types) > 1 else "", note])
            n[note] = n.get(note, 0) + 1
    print(n)


if __name__ == "__main__":
    main(sys.argv[1], sys.argv[2])
