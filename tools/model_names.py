"""Display names for model pages: the catalogue's raw names, normalised.

Generic rules: codes upper case (Gs -> GS, Exc -> EXC), words title case (BULLET -> Bullet), Roman numerals
(Iii -> III), no repeated words (MT-03 MT-03), no brand inside the model name (Harley-Davidson Street 750 ->
Street 750), no stray words (None, and). OVERRIDES fix what no rule can: factory codes for a named model
(Fls 1690 -> Softail Slim, Klz 1000 -> Versys 1000), run-together names (890DUKER -> 890 Duke R), misspellings.
Two raw names that end up the same are one model page.
"""
import re

# real words that stay title case even when short
WORDS = {"Aero", "Area", "Bob", "Bolt", "Boy", "Bros", "City", "Code", "Cota", "Crox", "Cub", "Cup", "Dark", "Del", "Dual",
         "Duke", "Dyna", "Echo", "Euro", "Evo", "Fat", "Four", "Fury", "Gold", "Grom", "Hero", "Ibex", "Iron", "Isca", "Jet",
         "Jota", "King", "Lead", "Like", "Low", "Lo", "Mach", "Mana", "Mar", "Mask", "Moto", "Ness", "New", "Pan", "Pro",
         "Red", "Road", "Rod", "Sei", "Slim", "Soft", "Star", "Sum", "Tail", "Teo", "Tour", "Tri", "Twin", "Vino", "Vity",
         "Wide", "Wing", "Ace", "Wolf", "Worx", "Zing", "Zip", "Zuma", "Dax", "Glide", "Super", "Sport", "Ultra", "Classic"}
SPECIAL = {"Iii": "III", "Xii": "XII", "Ii": "II", "Vmax": "VMAX", "Tmax": "TMAX", "Xmax": "XMAX", "Smax": "SMAX",
           "Gsxs": "GSX-S", "Gsxr": "GSX-R", "Nrg": "NRG", "Pcx": "PCX", "Jog": "Jog", "JOG": "Jog", "Abs": "ABS", "Xevo": "X Evo"}

# (make, raw model) -> display name
OVERRIDES = {
 # Yamaha
 ("Yamaha", "MT-03 MT-03"): "MT-03", ("Yamaha", "Mt 120"): "MT-125", ("Yamaha", "MT125"): "MT-125", ("Yamaha", "Wr 120"): "WR125",
 ("Yamaha", "FZ1S"): "FZ1 Fazer", ("Yamaha", "FZ1N"): "FZ1", ("Yamaha", "Fazer FZS600"): "FZS600 Fazer",
 ("Yamaha", "Fazer FZS1000"): "FZS1000 Fazer", ("Yamaha", "YZFR125"): "YZF-R125", ("Yamaha", "YZF125"): "YZF-R125",
 ("Yamaha", "VMX17"): "VMAX 1700", ("Yamaha", "Vmax 1700"): "VMAX 1700", ("Yamaha", "Vmax 1200"): "VMAX 1200",
 ("Yamaha", "Serrow 225"): "Serow 225", ("Yamaha", "Dragstar 650"): "Drag Star 650", ("Yamaha", "535"): "Virago 535",
 ("Yamaha", "Tmax 500"): "TMAX 500", ("Yamaha", "JOG"): "Jog", ("Yamaha", "FJ09"): "FJ-09", ("Yamaha", "FZ8-N"): "FZ8",
 ("Yamaha", "XV1600AN"): "Road Star 1600", ("Yamaha", "XV1700P"): "Road Star Warrior", ("Yamaha", "Tracer 9 Gt"): "Tracer 9 GT",
 ("Yamaha", "YP400RA"): "Majesty 400", ("Yamaha", "X-Max 125"): "XMAX 125", ("Yamaha", "Xmax 250"): "XMAX 250",
 ("Yamaha", "Xmax 300"): "XMAX 300", ("Yamaha", "X-Max 400"): "XMAX 400", ("Yamaha", "Majesty YP250"): "Majesty 250",
 ("Yamaha", "Thunderace YZF1000R"): "YZF1000R Thunderace", ("Yamaha", "Thunderace 1000"): "YZF1000R Thunderace",
 ("Yamaha", "Diversion 600"): "XJ600 Diversion", ("Yamaha", "Diversion 900"): "XJ900 Diversion",
 # Honda
 ("Honda", "CBR1100XX"): "CBR1100XX Super Blackbird", ("Honda", "Blackbird 1100"): "CBR1100XX Super Blackbird",
 ("Honda", "VFR800 (Interceptor) 7820"): "VFR800 (Interceptor 800)", ("Honda", "Pcx 125"): "PCX125", ("Honda", "PCX150"): "PCX150",
 ("Honda", "Sh 125"): "SH125", ("Honda", "Sh 300"): "SH300", ("Honda", "Sh 50"): "SH50", ("Honda", "Mt 50"): "MT50",
 ("Honda", "CB1300 1380"): "CB1300", ("Honda", "CB250 250"): "CB250", ("Honda", "CD250U 250"): "CD250U",
 ("Honda", "Goldwing"): "Gold Wing", ("Honda", "Lead LEAD110"): "Lead 110", ("Honda", "Fireblade 900"): "CBR900RR Fireblade",
 ("Honda", "CBR900RR"): "CBR900RR Fireblade", ("Honda", "Deauville 650"): "Deauville NT650V", ("Honda", "Hornet 600"): "Hornet CB600F",
 ("Honda", "Firestorm 1000"): "VTR1000F Firestorm", ("Honda", "VTR1000F (Super Hawk)"): "VTR1000F Firestorm (Super Hawk)",
 ("Honda", "Silver Wing"): "Silver Wing FJS600", ("Honda", "NSS250 (Reflex)"): "Reflex NSS250", ("Honda", "NSS300 (Forza)"): "Forza 300",
 ("Honda", "Pan 1100"): "ST1100 Pan European", ("Honda", "ST1100"): "ST1100 Pan European", ("Honda", "ST1300"): "ST1300 Pan European",
 ("Honda", "Super Cub C125"): "Super Cub C125", ("Honda", "CUB90"): "C90 Cub", ("Honda", "C90"): "C90 Cub",
 ("Honda", "125"): "125 (unspecified)", ("Honda", "250"): "250 (unspecified)", ("Honda", "400"): "400 (unspecified)",
 ("Honda", "600"): "600 (unspecified)", ("Honda", "750"): "750 (unspecified)",
 ("Honda", "Rebel"): "Rebel (unspecified)",
 # Kawasaki
 ("Kawasaki", "and Ninja 400"): "Ninja 400", ("Kawasaki", "Klz 1000"): "Versys 1000", ("Kawasaki", "Zrx 1100"): "ZRX1100",
 ("Kawasaki", "Zrx 1200R"): "ZRX1200R", ("Kawasaki", "En 650"): "Vulcan S", ("Kawasaki", "Ej 770"): "W800",
 ("Kawasaki", "EJ800ABF"): "W800", ("Kawasaki", "Er 300"): "Z300", ("Kawasaki", "ER6"): "ER-6n", ("Kawasaki", "ER5"): "ER-5",
 ("Kawasaki", "ER500"): "ER-5", ("Kawasaki", "Sc 300"): "J300", ("Kawasaki", "KLE650CAF"): "Versys 650", ("Kawasaki", "KLE650CBF"): "Versys 650",
 ("Kawasaki", "EX650CAF"): "ER-6f", ("Kawasaki", "EX650CBF"): "ER-6f", ("Kawasaki", "EX650ECF"): "ER-6f", ("Kawasaki", "EX650KJF"): "Ninja 650",
 ("Kawasaki", "ZX1400J"): "Ninja ZX-14R", ("Kawasaki", "ZX1400DAF"): "Ninja ZX-14", ("Kawasaki", "ZX1400DBF"): "Ninja ZX-14",
 ("Kawasaki", "ZX1400FCF"): "Ninja ZX-14R", ("Kawasaki", "ZX1400FDF"): "Ninja ZX-14R", ("Kawasaki", "ZZR1400"): "Ninja ZX-14",
 ("Kawasaki", "ZG1400CAF"): "Concours 14", ("Kawasaki", "ZG1400CBF"): "Concours 14", ("Kawasaki", "ZG1400A8FL"): "Concours 14",
 ("Kawasaki", "ZG1400B8FL"): "Concours 14", ("Kawasaki", "GTR1400"): "Concours 14", ("Kawasaki", "1400GTR"): "Concours 14",
 ("Kawasaki", "ZX600RAF"): "Ninja ZX-6R", ("Kawasaki", "ZX600-J1"): "Ninja ZX-6R", ("Kawasaki", "ZX600-J2"): "Ninja ZX-6R",
 ("Kawasaki", "ZX636EDF"): "Ninja ZX-6R", ("Kawasaki", "ZX1000FAF"): "Ninja ZX-10R", ("Kawasaki", "ZX1002D"): "Ninja H2 SX",
 ("Kawasaki", "ZX1200-C1H"): "ZZR1200", ("Kawasaki", "ZX-10"): "Ninja ZX-10", ("Kawasaki", "ZX1100"): "ZZ-R1100",
 ("Kawasaki", "Ninja H2 Sx"): "Ninja H2 SX", ("Kawasaki", "Z H2"): "Z H2", ("Kawasaki", "EX500-A6"): "Ninja 500R",
 ("Kawasaki", "Vulcan 88"): "Vulcan 1500 (Vulcan 88)",
 # Suzuki
 ("Suzuki", "Gsxs 1000"): "GSX-S1000", ("Suzuki", "Gsxs 125"): "GSX-S125", ("Suzuki", "Gsxr 125"): "GSX-R125",
 ("Suzuki", "GSXR400"): "GSX-R400", ("Suzuki", "DRZ400SM"): "DR-Z400SM", ("Suzuki", "DRZ400E"): "DR-Z400E", ("Suzuki", "GSX1100 1130"): "GSX1100",
 ("Suzuki", "GSF650"): "Bandit 650", ("Suzuki", "VLR1800"): "Boulevard C109R", ("Suzuki", "Boulevard M109"): "Boulevard M109R",
 # BMW
 ("BMW", "R Series"): "R-series (unspecified)", ("BMW", "K Series"): "K-series (unspecified)", ("BMW", "Fseries 800"): "F 800 (unspecified)",
 ("BMW", "Fseries 650"): "F 650 (unspecified)", ("BMW", "Gseries 650"): "G 650 (unspecified)", ("BMW", "Gs 1200"): "R 1200 GS",
 ("BMW", "F750"): "F 750 GS", ("BMW", "F800 R"): "F 800 R", ("BMW", "K1300 R"): "K 1300 R", ("BMW", "F800 Gs Adventure"): "F 800 GS Adventure",
 ("BMW", "R1100"): "R 1100", ("BMW", "R 100 Gs"): "R 100 GS", ("BMW", "R100R"): "R 100 R", ("BMW", "R100RS"): "R 100 RS",
 ("BMW", "R90S"): "R 90 S", ("BMW", "K1"): "K1", ("BMW", "C1"): "C1", ("BMW", "C400"): "C 400", ("BMW", "C 600"): "C 600 Sport",
 ("BMW", "Ce 04"): "CE 04", ("BMW", "HP2 Megamoto"): "HP2 Megamoto", ("BMW", "G650X Country"): "G 650 Xcountry",
 ("BMW", "G650X Moto"): "G 650 Xmoto", ("BMW", "R65"): "R 65", ("BMW", "R75"): "R 75", ("BMW", "R80"): "R 80",
 ("BMW", "R100"): "R 100", ("BMW", "R60"): "R 60", ("BMW", "R45"): "R 45", ("BMW", "R850"): "R 850", ("BMW", "K75"): "K 75",
 ("BMW", "K100"): "K 100",
 # Triumph
 ("Triumph", "Rocket Iii"): "Rocket III", ("Triumph", "Rocket Iii Touring"): "Rocket III Touring", ("Triumph", "SpeedMaster"): "Speedmaster",
 ("Triumph", "Bonneville T100 790"): "Bonneville T100", ("Triumph", "Bonneville T100 860"): "Bonneville T100",
 ("Triumph", "T110"): "Tiger 110 (T110)", ("Triumph", "T110 T90"): "Tiger 90 (T90)", ("Triumph", "T110 T160"): "Trident T160",
 ("Triumph", "T110 T20"): "Tiger Cub (T20)", ("Triumph", "3TA"): "Twenty-One (3TA)", ("Triumph", "5TA"): "Speed Twin (5TA)",
 ("Triumph", "6T"): "Thunderbird (6T)", ("Triumph", "T120R"): "Bonneville T120R", ("Triumph", "T140"): "Bonneville T140",
 ("Triumph", "T140V"): "Bonneville T140V", ("Triumph", "T140E"): "Bonneville T140E", ("Triumph", "TR6"): "Trophy TR6",
 ("Triumph", "T100SS"): "Tiger 100SS (T100SS)", ("Triumph", "Thruxton Tfc"): "Thruxton TFC", ("Triumph", "Tiger 1200 Xca"): "Tiger 1200 XCA",
 ("Triumph", "Tiger 1200 Xrt"): "Tiger 1200 XRT", ("Triumph", "Speed Triple T509"): "Speed Triple T509", ("Triumph", "Sprint ST"): "Sprint ST",
 ("Triumph", "Daytona 955I"): "Daytona 955i", ("Triumph", "Speed Triple 1200 RS"): "Speed Triple 1200 RS",
 # KTM
 ("KTM", "890DUKER"): "890 Duke R", ("KTM", "1290SUPERDUKER"): "1290 Super Duke R", ("KTM", "1290SUPERDUKEGT"): "1290 Super Duke GT",
 ("KTM", "990SUPERDUKE"): "990 Super Duke", ("KTM", "990SUPERMOTOT"): "990 SMT", ("KTM", "Supermoto 990"): "990 Supermoto",
 ("KTM", "350EXC"): "350 EXC-F", ("KTM", "400EXC"): "400 EXC", ("KTM", "300EXC"): "300 EXC", ("KTM", "200EXC"): "200 EXC",
 ("KTM", "EXC300"): "300 EXC", ("KTM", "Exc 250"): "250 EXC", ("KTM", "Exc 450"): "450 EXC", ("KTM", "Exc 200"): "200 EXC",
 ("KTM", "520EXC"): "520 EXC", ("KTM", "250EXCTPI"): "250 EXC TPI", ("KTM", "450SX"): "450 SX-F", ("KTM", "250SX"): "250 SX",
 ("KTM", "350SX"): "350 SX-F", ("KTM", "450SMR"): "450 SMR", ("KTM", "525SMR"): "525 SMR", ("KTM", "625SMC"): "625 SMC",
 ("KTM", "250 Exc-f"): "250 EXC-F", ("KTM", "250 Xcf"): "250 XCF", ("KTM", "300 Xc"): "300 XC", ("KTM", "300 Xc-w"): "300 XC-W",
 ("KTM", "990 Adventure-s"): "990 Adventure S", ("KTM", "Rc 390"): "RC 390", ("KTM", "RC125"): "RC 125", ("KTM", "125"): "125 (unspecified)",
 ("KTM", "640"): "640 LC4", ("KTM", "10"): "Unknown model (catalogue code 10)", ("KTM", "LC8"): "LC8 (unspecified)", ("KTM", "Adventure"): "Adventure (unspecified)",
 ("KTM", "Duke"): "Duke (unspecified)", ("KTM", "LC4 Duke"): "Duke (LC4)", ("KTM", "Single Cylinder LC4 Duke"): "Duke (LC4)",
 ("KTM", "690 Smc"): "690 SMC", ("KTM", "390 Smc R"): "390 SMC R", ("KTM", "V-twin LC8 Supermoto"): "LC8 Supermoto (unspecified)",
 ("KTM", "V-twin LC8 Adventure"): "LC8 Adventure (unspecified)", ("KTM", "Super Adventure"): "Super Adventure (unspecified)",
 ("KTM", "Enduro Four-Stroke"): "EXC-F (unspecified)", ("KTM", "Enduro Two-Stroke"): "EXC (unspecified)",
 ("KTM", "Closed Course Competition"): "SX (unspecified)",
 # Harley-Davidson
 ("Harley-Davidson", "Harley-Davidson Street 750"): "Street 750", ("Harley-Davidson", "Harley-Davidson Street 500"): "Street 500",
 ("Harley-Davidson", "Xl 1200"): "Sportster 1200", ("Harley-Davidson", "XL"): "Sportster (XL)", ("Harley-Davidson", "XL883"): "Sportster 883",
 ("Harley-Davidson", "883"): "Sportster 883", ("Harley-Davidson", "XLH883"): "Sportster 883", ("Harley-Davidson", "XL883R"): "Sportster 883R",
 ("Harley-Davidson", "XL883L"): "Sportster 883 Low", ("Harley-Davidson", "XLH1000"): "Sportster 1000 (XLH)", ("Harley-Davidson", "XLH"): "Sportster (XLH)",
 ("Harley-Davidson", "XLS1000"): "Sportster Roadster 1000 (XLS)", ("Harley-Davidson", "XL1000"): "Sportster 1000",
 ("Harley-Davidson", "XLCH1000"): "Sportster XLCH 1000", ("Harley-Davidson", "1000"): "Sportster 1000",
 ("Harley-Davidson", "Fxdx 1450"): "Dyna Super Glide Sport", ("Harley-Davidson", "Fxdxi 1450"): "Dyna Super Glide Sport",
 ("Harley-Davidson", "Fxdxt 1450"): "Dyna Super Glide T-Sport", ("Harley-Davidson", "Fxds"): "Dyna Convertible",
 ("Harley-Davidson", "Fxdls 1801"): "Dyna Low Rider S", ("Harley-Davidson", "Flsts"): "Heritage Springer", ("Harley-Davidson", "Fxsts 1340"): "Springer Softail",
 ("Harley-Davidson", "Fxrs 1340"): "Low Rider (FXRS)", ("Harley-Davidson", "Flstfia 1550"): "Fat Boy", ("Harley-Davidson", "Flstsb 1580"): "Cross Bones",
 ("Harley-Davidson", "Flstsci 1450"): "Softail Springer Classic", ("Harley-Davidson", "Fls 1690"): "Softail Slim",
 ("Harley-Davidson", "Eglide 1690"): "Electra Glide", ("Harley-Davidson", "Flht"): "Electra Glide Standard",
 ("Harley-Davidson", "Flhs"): "Electra Glide Sport", ("Harley-Davidson", "Fltc"): "Tour Glide Classic",
 ("Harley-Davidson", "Flhrse"): "CVO Road King", ("Harley-Davidson", "Flhxse 1923"): "CVO Street Glide", ("Harley-Davidson", "Fltrxse"): "CVO Road Glide",
 ("Harley-Davidson", "Fxsbse"): "CVO Breakout", ("Harley-Davidson", "Flstnse"): "CVO Softail Deluxe", ("Harley-Davidson", "Flstfse 1690"): "CVO Fat Boy",
 ("Harley-Davidson", "Flhtcuse 1800"): "CVO Ultra Classic Electra Glide", ("Harley-Davidson", "FLHTCUSE6"): "CVO Ultra Classic Electra Glide",
 ("Harley-Davidson", "Flhtkse 1868"): "CVO Limited", ("Harley-Davidson", "Fxstsse 1800"): "CVO Softail Springer",
 ("Harley-Davidson", "Flhtcu Tc"): "Electra Glide Ultra Classic", ("Harley-Davidson", "Ultra Limited"): "Electra Glide Ultra Limited", ("Harley-Davidson", "Ultra Classic Electra Glide"): "Electra Glide Ultra Classic",
 ("Harley-Davidson", "Fxcwc 1580"): "Rocker C", ("Harley-Davidson", "Flhrxs"): "Road King Special", ("Harley-Davidson", "Vrscb 1130"): "V-Rod (VRSCB)",
 ("Harley-Davidson", "Vrscr 1130"): "Street Rod (VRSCR)", ("Harley-Davidson", "Fxst"): "Softail Standard", ("Harley-Davidson", "Flst"): "Heritage Softail",
 ("Harley-Davidson", "FX"): "Super Glide FX", ("Harley-Davidson", "FX1200"): "Super Glide FX", ("Harley-Davidson", "FXE1200"): "Super Glide (FXE)",
 ("Harley-Davidson", "FL"): "Electra Glide (FL)", ("Harley-Davidson", "FLH"): "Electra Glide (FLH)", ("Harley-Davidson", "FL1200"): "Electra Glide (FL)",
 ("Harley-Davidson", "FLH1200"): "Electra Glide (FLH)", ("Harley-Davidson", "1340"): "1340 Evolution (unspecified)",
 ("Harley-Davidson", "Custom 1340"): "1340 Evolution (unspecified)", ("Harley-Davidson", "FXR1340"): "FXR Super Glide",
 ("Harley-Davidson", "Fxrst"): "FXR Sport Glide", ("Harley-Davidson", "Soft Tail"): "Softail", ("Harley-Davidson", "Pro 1801"): "Dyna Street Bob (FXDB)",
 ("Harley-Davidson", "Dyna"): "Dyna (unspecified)", ("Harley-Davidson", "Softail"): "Softail (unspecified)",
 ("Harley-Davidson", "Touring"): "Touring (unspecified)", ("Harley-Davidson", "Deluxe"): "Softail Deluxe",
 ("Harley-Davidson", "Eagle"): "Eagle (unspecified)", ("Harley-Davidson", "MT350"): "MT350 (military)", ("Harley-Davidson", "MT500"): "MT500 (military)",
 # Indian, Victory
 ("Indian", "Indian Challenger Dark Horse"): "Challenger Dark Horse", ("Indian", "Indian Challenger Limited"): "Challenger Limited",
 ("Indian", "Indian Pursuit Dark Horse"): "Pursuit Dark Horse", ("Indian", "Indian Pursuit Limited"): "Pursuit Limited",
 ("Indian", "Chieftan"): "Chieftain", ("Indian", "FTR1200"): "FTR 1200", ("Indian", "Ftr 1200 S"): "FTR 1200 S",
 ("Indian", "Ftr 1200 R Carbon"): "FTR 1200 R Carbon", ("Indian", "Ftr 1200 Rally"): "FTR 1200 Rally",
 ("Indian", "Classic"): "Chief Classic", ("Indian", "Vintage"): "Chief Vintage", ("Indian", "Dark Horse"): "Dark Horse (unspecified)",
 ("Victory", "Anss Vegas"): "Ness Vegas", ("Victory", "Hard-ball"): "Hard-Ball", ("Victory", "High-Ball"): "High-Ball",
 ("Victory", "V92SC Sportcruiser"): "V92SC", ("Victory", "V92DC Deluxe Cruiser"): "V92DC",
 # Ducati
 ("Ducati", "Multistrada (MTS)"): "Multistrada", ("Ducati", "Streetfighter (SFT)"): "Streetfighter", ("Ducati", "Hypermotard (HYM)"): "Hypermotard",
 ("Ducati", "New Superbike (SBK)"): "Superbike (unspecified)", ("Ducati", "SuperBike"): "Superbike (unspecified)",
 ("Ducati", "M 1200"): "Monster 1200", ("Ducati", "M900"): "Monster 900", ("Ducati", "M600"): "Monster 600", ("Ducati", "M696"): "Monster 696",
 ("Ducati", "M821"): "Monster 821", ("Ducati", "M620IE"): "Monster 620", ("Ducati", "M750"): "Monster 750", ("Ducati", "M1100E"): "Monster 1100 Evo",
 ("Ducati", "M796"): "Monster 796", ("Ducati", "Monster 796"): "Monster 796", ("Ducati", "M695"): "Monster 695", ("Ducati", "M797"): "Monster 797",
 ("Ducati", "M800"): "Monster 800", ("Ducati", "M1000S"): "Monster S4 1000", ("Ducati", "M1100S"): "Monster 1100 S", ("Ducati", "S4R"): "Monster S4R",
 ("Ducati", "S2R"): "Monster S2R", ("Ducati", "Monster"): "Monster (unspecified)", ("Ducati", "749S"): "749 S",
 ("Ducati", "1199 Superleggera"): "1199 Superleggera", ("Ducati", "Desmosedici Rr"): "Desmosedici RR", ("Ducati", "Classic"): "SportClassic",
 ("Ducati", "Panigale 959"): "959 Panigale", ("Ducati", "959"): "959 Panigale", ("Ducati", "899"): "899 Panigale", ("Ducati", "1199"): "1199 Panigale",
 ("Ducati", "1299 Superleggera"): "1299 Panigale Superleggera", ("Ducati", "Scrambler 800"): "Scrambler", ("Ducati", "750"): "750 (unspecified)",
 ("Ducati", "600"): "600 (unspecified)", ("Ducati", "SuperSport"): "SuperSport", ("Ducati", "Standard"): "Standard (unspecified)",
 # Aprilia, Moto Guzzi, others
 ("Aprilia", "Rsv 1000 R"): "RSV 1000 R", ("Aprilia", "Rsv 1000"): "RSV Mille", ("Aprilia", "Mille"): "RSV Mille", ("Aprilia", "Sr 50"): "SR50",
 ("Aprilia", "Sr 120"): "SR125", ("Aprilia", "Sl 1000"): "SL1000 Falco", ("Aprilia", "Falco 1000"): "SL1000 Falco", ("Aprilia", "Rs 660"): "RS 660",
 ("Aprilia", "RS4"): "RS4 125", ("Aprilia", "RSV4 Rf"): "RSV4 RF", ("Aprilia", "ETV 1000 Caponord"): "ETV1000 Caponord", ("Aprilia", "Caponord"): "ETV1000 Caponord",
 ("Aprilia", "RST Futura"): "RST1000 Futura", ("Aprilia", "RST1000"): "RST1000 Futura", ("Aprilia", "Tuono 1000"): "Tuono 1000",
 ("Aprilia", "Tuono"): "Tuono (unspecified)", ("Aprilia", "Shiver"): "Shiver (unspecified)",
 ("Moto Guzzi", "Le 850"): "Le Mans 850", ("Moto Guzzi", "Le 1000"): "Le Mans 1000", ("Moto Guzzi", "V85 Tt"): "V85 TT",
 ("Moto Guzzi", "California Iii"): "California III", ("Moto Guzzi", "750"): "750 (unspecified)", ("Moto Guzzi", "850"): "850 T (unspecified)",
 ("Royal Enfield", "Bullt 500"): "Bullet 500", ("Royal Enfield", "Bullet"): "Bullet 500", ("Royal Enfield", "Int 650"): "Interceptor 650",
 ("Royal Enfield", "Continental 540"): "Continental GT 535", ("Royal Enfield", "Himalayan 411"): "Himalayan 411",
 ("Enfield", "350"): "Bullet 350", ("Enfield", "500"): "Bullet 500",
 ("Piaggio", "Bv 500"): "Beverly 500", ("Piaggio", "B500"): "Beverly 500", ("Piaggio", "B125"): "Beverly 125", ("Piaggio", "Nrg 50"): "NRG 50",
 ("Piaggio", "GTS300 280"): "Vespa GTS 300", ("Piaggio", "GTS300"): "Vespa GTS 300", ("Piaggio", "PX200E 120"): "Vespa PX200E",
 ("Piaggio", "PX200E"): "Vespa PX200E", ("Piaggio", "PX125"): "Vespa PX125", ("Piaggio", "PK125"): "Vespa PK125", ("Piaggio", "T5"): "Vespa T5",
 ("Piaggio", "ET2"): "Vespa ET2", ("Piaggio", "ET4"): "Vespa ET4", ("Piaggio", "GT125"): "Vespa GT125", ("Piaggio", "LX125"): "Vespa LX125",
 ("Piaggio", "ZIP125"): "Zip 125", ("Piaggio", "ZIP100"): "Zip 100", ("Piaggio", "FLY125"): "Fly 125", ("Piaggio", "FLY50"): "Fly 50", ("Piaggio", "FLY100"): "Fly 100",
 ("Vespa", "PX125"): "PX125", ("Vespa", "150SUPER"): "150 Super", ("Vespa", "Gts Rst Sei Giorni"): "GTS Sei Giorni", ("Vespa", "Gtv 300"): "GTV 300",
 ("Vespa", "125"): "125 (unspecified)", ("Gilera", "Skp 50"): "SKP 50", ("Gilera", "Rcr 50"): "RCR 50", ("Gilera", "Smt 50"): "SMT 50",
 ("Kymco", "People"): "People", ("Kymco", "Ck 125"): "CK 125", ("Kymco", "Agility"): "Agility",
 ("SYM", "JET50"): "Jet 50", ("SYM", "JET4 125"): "Jet 4 125", ("SYM", "JET4 50"): "Jet 4 50", ("SYM", "JET14"): "Jet 14", ("SYM", "MIO50"): "Mio 50",
 ("SYM", "MIO100"): "Mio 100", ("SYM", "Az 125"): "AZ 125", ("Zero", "DS & DS Police"): "DS", ("Zero", "Dsrp"): "DSR/P", ("Zero", "DSP"): "DS/P",
 ("Vmoto", "CPA None"): "CPA", ("Niu", "NQI None"): "NQi", ("Lexmoto", "Xtr 120"): "XTR 125", ("Lexmoto", "Xflm 125"): "XFLM 125",
 ("Lexmoto", "Zsf 125"): "ZSF 125", ("Lexmoto", "Fmr 50"): "FMR 50", ("Lexmoto", "Wy 120"): "WY 125", ("Lexmoto", "Zn 120"): "ZN 125",
 ("Jinlun", "Jl 120"): "JL125", ("Kymco", "Zing 120"): "Zing 125", ("Kymco", "Hipster 120"): "Hipster 125", ("Hyosung", "Cruise 120"): "Cruise 125",
 ("Rieju", "Rs 120"): "RS2 125", ("Scomadi", "Turismo 120"): "Turismo Technica 125", ("Scomadi", "Turismo 200"): "Turismo Technica 200",
 ("SYM", "Husky 120"): "Husky 125", ("Sinnis", "Js 125"): "JS125", ("Qingqi", "Qm 125"): "QM125", ("Ksr Moto", "Grs 125"): "GRS 125",
 ("Big Dog", "Chopper - DT"): "Chopper DT", ("Generic", "Code 125"): "Code 125", ("Morini", "35"): "3½ (350)",
 ("Ic", "Zhejiang Xingyue Vehicle Co"): "Zhejiang Xingyue (unspecified)", ("CCM", "Dual 644"): "644 Dual", ("Velocette", "Le 200"): "LE 200",
 ("BSA", "ROCKET3"): "Rocket 3", ("BSA", "Gold 500"): "Gold Star 500", ("BSA", "Gold 650"): "Gold Star 650", ("BSA", "Goldstar 500"): "Gold Star 500",
 ("Cagiva", "MITO-125"): "Mito 125", ("Cagiva", "Grand 900"): "Gran Canyon 900", ("Polaris", "Victory"): "Victory (unspecified)",
 ("Norton", "Commando"): "Commando 961", ("Ural", "Retro"): "Retro",
}
MAKE_NAMES = {"Ksr Moto": "KSR Moto", "Cpi": "CPI", "Ic": "IC", "Generic": "Generic", "Big Dog": "Big Dog"}


def _word(w):
    if w in SPECIAL:
        return SPECIAL[w]
    core = w.strip("()")
    if not core:
        return w
    if re.fullmatch(r"[IVX]+", core.upper()) and core.upper() in ("II", "III", "IV", "XII") and core != core.upper():
        return w.replace(core, core.upper())
    if core.isalpha():
        if core in WORDS or core.capitalize() in WORDS:
            return w.replace(core, core.capitalize())
        if len(core) <= 4 and not core.islower():
            return w.replace(core, core.upper())        # Gs -> GS, Exc -> EXC, Rr -> RR
        if core.isupper() and len(core) > 4:
            return w.replace(core, core.capitalize())   # BULLET -> Bullet
        return w
    # letters and digits: codes stay upper case (Fe -> FE in "FE 350" is handled above)
    if re.fullmatch(r"[A-Za-z]+\d+[A-Za-z]*|\d+[A-Za-z]+", core) and core[0].islower():
        return w.replace(core, core.upper())
    return w


def display(make, model):
    """The page name for a catalogue model."""
    if (make, model) in OVERRIDES:
        return OVERRIDES[(make, model)]
    m = model.strip()
    for prefix in (make + " ", make.split()[0] + " "):
        if m.startswith(prefix) and len(m) > len(prefix):
            m = m[len(prefix):]
    m = re.sub(r"\bNone\b", "", m)
    m = re.sub(r"^and\s+", "", m)
    words = [_word(w) for w in m.split()]
    out = []
    for w in words:                                       # MT-03 MT-03 -> MT-03
        if not out or w.lower() != out[-1].lower():
            out.append(w)
    return " ".join(out).strip()


def make_display(make):
    return MAKE_NAMES.get(make, make)
