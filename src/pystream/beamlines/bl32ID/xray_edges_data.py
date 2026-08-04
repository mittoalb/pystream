"""
X-ray Absorption Edge Data for bl32ID X-ray Tools plugin.

Copied verbatim from /home/beams/AMITTONE/Software/xraytr/xray_edges.py so
this plugin is self-contained. Format per row:
  [Z, Element_Name, Symbol, K_edge, L1_edge, L2_edge, L3_edge]  (energies in eV)
None marks edges not commonly measured / unavailable.
"""

XRAY_EDGES = [
    [1, "Hydrogen", "H", 13.6, None, None, None],
    [2, "Helium", "He", 24.6, None, None, None],
    [3, "Lithium", "Li", 54.7, None, None, None],
    [4, "Beryllium", "Be", 111.5, None, None, None],
    [5, "Boron", "B", 188, None, None, None],
    [6, "Carbon", "C", 284.2, None, None, None],
    [7, "Nitrogen", "N", 399.6, None, None, None],
    [8, "Oxygen", "O", 543.1, None, None, None],
    [9, "Fluorine", "F", 696.7, None, None, None],
    [10, "Neon", "Ne", 870.2, 48.5, 21.7, 21.6],
    [11, "Sodium", "Na", 1070.8, 63.5, 30.4, 30.5],
    [12, "Magnesium", "Mg", 1303.0, 88.6, 49.6, 49.2],
    [13, "Aluminum", "Al", 1559.6, 117.8, 72.9, 72.5],
    [14, "Silicon", "Si", 1839.0, 149.7, 99.8, 99.2],
    [15, "Phosphorus", "P", 2145.5, 189.0, 132.2, 131.2],
    [16, "Sulfur", "S", 2472.0, 230.9, 163.6, 162.5],
    [17, "Chlorine", "Cl", 2822.4, 270.0, 202.0, 200.0],
    [18, "Argon", "Ar", 3205.9, 326.3, 250.6, 248.4],
    [19, "Potassium", "K", 3608.4, 378.6, 297.3, 294.6],
    [20, "Calcium", "Ca", 4038.5, 438.4, 349.7, 346.2],
    [21, "Scandium", "Sc", 4492.8, 498.0, 403.6, 398.7],
    [22, "Titanium", "Ti", 4966.4, 563.4, 460.2, 455.0],
    [23, "Vanadium", "V", 5465.1, 626.7, 519.8, 512.1],
    [24, "Chromium", "Cr", 5989.0, 696.0, 583.8, 574.1],
    [25, "Manganese", "Mn", 6539.0, 769.1, 649.9, 638.7],
    [26, "Iron", "Fe", 7112.0, 844.6, 719.9, 706.8],
    [27, "Cobalt", "Co", 7709.0, 925.1, 793.2, 778.1],
    [28, "Nickel", "Ni", 8333.0, 1008.6, 870.0, 852.7],
    [29, "Copper", "Cu", 8979.0, 1096.7, 952.3, 932.7],
    [30, "Zinc", "Zn", 9659.0, 1196.2, 1044.9, 1021.8],
    [31, "Gallium", "Ga", 10367, 1299.0, 1143.2, 1116.4],
    [32, "Germanium", "Ge", 11103, 1414.6, 1248.1, 1217.0],
    [33, "Arsenic", "As", 11867, 1527.0, 1359.1, 1323.6],
    [34, "Selenium", "Se", 12658, 1652.0, 1474.3, 1433.9],
    [35, "Bromine", "Br", 13474, 1782.0, 1596.0, 1550.0],
    [36, "Krypton", "Kr", 14326, 1921.0, 1730.9, 1678.4],
    [37, "Rubidium", "Rb", 15200, 2065.0, 1864.9, 1804.4],
    [38, "Strontium", "Sr", 16105, 2216.0, 2007.0, 1940.0],
    [39, "Yttrium", "Y", 17038, 2373.0, 2156.0, 2080.0],
    [40, "Zirconium", "Zr", 17998, 2532.0, 2307.0, 2223.0],
    [41, "Niobium", "Nb", 18986, 2698.0, 2465.0, 2371.0],
    [42, "Molybdenum", "Mo", 20000, 2866.0, 2625.0, 2520.0],
    [43, "Technetium", "Tc", 21044, 3043.0, 2793.0, 2677.0],
    [44, "Ruthenium", "Ru", 22117, 3224.0, 2967.0, 2838.0],
    [45, "Rhodium", "Rh", 23220, 3412.0, 3146.0, 3004.0],
    [46, "Palladium", "Pd", 24350, 3604.0, 3330.0, 3173.0],
    [47, "Silver", "Ag", 25514, 3806.0, 3524.0, 3351.0],
    [48, "Cadmium", "Cd", 26711, 4018.0, 3727.0, 3538.0],
    [49, "Indium", "In", 27940, 4238.0, 3938.0, 3730.0],
    [50, "Tin", "Sn", 29200, 4465.0, 4156.0, 3929.0],
    [51, "Antimony", "Sb", 30491, 4698.0, 4380.0, 4132.0],
    [52, "Tellurium", "Te", 31814, 4939.0, 4612.0, 4341.0],
    [53, "Iodine", "I", 33169, 5188.0, 4852.0, 4557.0],
    [54, "Xenon", "Xe", 34561, 5453.0, 5107.0, 4786.0],
    [55, "Cesium", "Cs", 35985, 5714.0, 5359.0, 5012.0],
    [56, "Barium", "Ba", 37441, 5989.0, 5624.0, 5247.0],
    [57, "Lanthanum", "La", 38925, 6266.0, 5891.0, 5483.0],
    [58, "Cerium", "Ce", 40443, 6549.0, 6164.0, 5723.0],
    [59, "Praseodymium", "Pr", 41991, 6835.0, 6440.0, 5964.0],
    [60, "Neodymium", "Nd", 43569, 7126.0, 6722.0, 6208.0],
    [61, "Promethium", "Pm", 45184, 7428.0, 7013.0, 6459.0],
    [62, "Samarium", "Sm", 46834, 7737.0, 7312.0, 6716.0],
    [63, "Europium", "Eu", 48519, 8052.0, 7617.0, 6977.0],
    [64, "Gadolinium", "Gd", 50239, 8376.0, 7930.0, 7243.0],
    [65, "Terbium", "Tb", 51996, 8708.0, 8252.0, 7514.0],
    [66, "Dysprosium", "Dy", 53789, 9046.0, 8581.0, 7790.0],
    [67, "Holmium", "Ho", 55618, 9394.0, 8918.0, 8071.0],
    [68, "Erbium", "Er", 57486, 9751.0, 9264.0, 8358.0],
    [69, "Thulium", "Tm", 59390, 10116, 9617.0, 8648.0],
    [70, "Ytterbium", "Yb", 61332, 10486, 9978.0, 8944.0],
    [71, "Lutetium", "Lu", 63314, 10870, 10349, 9244.0],
    [72, "Hafnium", "Hf", 65351, 11271, 10739, 9561.0],
    [73, "Tantalum", "Ta", 67416, 11682, 11136, 9881.0],
    [74, "Tungsten", "W", 69525, 12100, 11544, 10207],
    [75, "Rhenium", "Re", 71676, 12527, 11959, 10535],
    [76, "Osmium", "Os", 73871, 12968, 12385, 10871],
    [77, "Iridium", "Ir", 76111, 13419, 12824, 11215],
    [78, "Platinum", "Pt", 78395, 13880, 13273, 11564],
    [79, "Gold", "Au", 80725, 14353, 13734, 11919],
    [80, "Mercury", "Hg", 83102, 14839, 14209, 12284],
    [81, "Thallium", "Tl", 85530, 15347, 14698, 12658],
    [82, "Lead", "Pb", 88005, 15861, 15200, 13035],
    [83, "Bismuth", "Bi", 90524, 16388, 15711, 13419],
    [84, "Polonium", "Po", 93105, 16939, 16244, 13814],
    [85, "Astatine", "At", 95730, 17493, 16785, 14214],
    [86, "Radon", "Rn", 98404, 18049, 17337, 14619],
    [87, "Francium", "Fr", 101137, 18639, 17907, 15031],
    [88, "Radium", "Ra", 103922, 19237, 18484, 15444],
    [89, "Actinium", "Ac", 106755, 19840, 19083, 15871],
    [90, "Thorium", "Th", 109651, 20472, 19693, 16300],
    [91, "Protactinium", "Pa", 112601, 21105, 20314, 16733],
    [92, "Uranium", "U", 115606, 21757, 20948, 17166],
    [93, "Neptunium", "Np", 118678, 22427, 21600, 17610],
    [94, "Plutonium", "Pu", 121818, 23097, 22266, 18056],
    [95, "Americium", "Am", 125027, 23773, 22944, 18504],
    [96, "Curium", "Cm", 128220, 24460, 23779, 18930],
    [97, "Berkelium", "Bk", 131590, 25275, 24385, 19452],
    [98, "Californium", "Cf", 135960, 26110, 25250, 19930],
    [99, "Einsteinium", "Es", 139490, 26900, 26020, 20410],
    [100, "Fermium", "Fm", 143090, 27700, 26810, 20900],
    [101, "Mendelevium", "Md", 146780, 28530, 27610, 21390],
    [102, "Nobelium", "No", 150540, 29380, 28440, 21880],
    [103, "Lawrencium", "Lr", 154380, 30240, 29280, 22360],
]


EDGE_COLUMN_INDEX = {"K": 3, "L1": 4, "L2": 5, "L3": 6}


def search_elements(term):
    """Return rows whose name or symbol contains `term` (case-insensitive).
    Empty/None term returns the full table."""
    if not term:
        return list(XRAY_EDGES)
    t = term.lower()
    return [r for r in XRAY_EDGES
            if t in r[1].lower() or t in r[2].lower()]


def filter_by_energy_range(rows, min_energy=None, max_energy=None, edge_type="K"):
    """Keep rows where the chosen edge is within [min, max]. Rows lacking
    that edge are dropped."""
    idx = EDGE_COLUMN_INDEX.get(edge_type)
    if idx is None:
        return list(rows)
    out = []
    for r in rows:
        e = r[idx]
        if e is None:
            continue
        if min_energy is not None and e < min_energy:
            continue
        if max_energy is not None and e > max_energy:
            continue
        out.append(r)
    return out
