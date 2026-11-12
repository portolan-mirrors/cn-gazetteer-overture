"""Measured class breaks for every style. Generated; do not edit.

Written by tools/make_breaks.py from the built data files. Rerun it
after any rebuild, then rerun tools/make_styles.py. The counts in the
comments are the features in each band at the time of generation, and
tools/distributions.sql reruns the same queries.
"""

# country.area_km2: bands [64, 32, 46, 44, 55, 31]
# country.name_langs: bands [25, 62, 31, 64, 54, 36]
# country.population: bands [44, 29, 62, 25, 26, 26]
# region.area_km2: bands [672, 863, 490, 856, 488, 560]
# region.name_langs: bands [558, 588, 1273, 1041, 67]
# region.country_units: bands [1575, 1484, 658, 212]
# region.population: bands [230, 269, 181, 205, 182, 137]
# county.area_km2: bands [8852, 9303, 5239, 5768, 5365, 4410]
# county.name_langs: bands [11091, 6426, 6760, 2001]
# county.country_units: bands [9146, 8107, 6191, 4401, 11092]
# county.population: bands [2523, 2286, 1264, 891, 1337]
# localadmin.area_km2: bands [6782, 3240, 2399, 2446, 3162, 3473]
# localadmin.name_langs: bands [3242, 4674, 2525, 1376]
# localadmin.population: bands [1496, 2017, 1364, 756, 829, 1061]
# locality.area_km2: bands [137293, 49483, 123412, 107686, 46874, 91346]
# locality.population: bands [45873, 73543, 34898, 27121, 41147, 27194]
# locality.name_langs: bands [82708, 68834, 61363, 46039, 11257]
# names.name_dupes: bands [3156802, 982760, 620804, 729861, 114186]
# names.name_lang_count: bands [5420570, 114379, 55009, 10516, 3804, 135]
# names.population: bands [298529, 331290, 143725, 192515, 194670, 204860]
# names.level: per level {0: 25620, 1: 89372, 2: 186018, 3: 72947, 4: 5230456}
# localadmin.country: 19 branch(es), counts [6257, 2927, 2853, 2173, 2119, 1959, 1132, 427, 401, 320, 275, 231, 143, 128, 89, 43, 15, 9, 1]
# locality.class: 4 branch(es), counts [255619, 134176, 45758, 7148, 113393]

BREAKS = {
    "country.area_km2": [
        500,
        5000,
        50000,
        200000,
        1000000
    ],
    "country.name_langs": [
        50,
        150,
        200,
        230,
        260
    ],
    "country.population": [
        100000,
        1000000,
        10000000,
        20000000,
        50000000
    ],
    "region.area_km2": [
        100,
        2000,
        5000,
        20000,
        50000
    ],
    "region.name_langs": [
        5,
        20,
        50,
        100
    ],
    "region.country_units": [
        20,
        50,
        100
    ],
    "region.population": [
        100000,
        500000,
        1000000,
        2000000,
        5000000
    ],
    "county.area_km2": [
        100,
        500,
        1000,
        2000,
        5000
    ],
    "county.name_langs": [
        2,
        10,
        20
    ],
    "county.country_units": [
        200,
        500,
        1000,
        2000
    ],
    "county.population": [
        20000,
        50000,
        100000,
        200000
    ],
    "localadmin.area_km2": [
        10,
        20,
        50,
        200,
        1000
    ],
    "localadmin.name_langs": [
        2,
        5,
        20
    ],
    "localadmin.population": [
        200,
        500,
        1000,
        2000,
        20000
    ],
    "locality.area_km2": [
        0.5,
        1,
        5,
        20,
        50
    ],
    "locality.population": [
        100,
        500,
        1000,
        2000,
        10000
    ],
    "locality.name_langs": [
        2,
        3,
        5,
        10
    ],
    "names.name_dupes": [
        2,
        4,
        10,
        100
    ],
    "names.name_lang_count": [
        2,
        3,
        5,
        10,
        50
    ],
    "names.population": [
        100,
        500,
        1000,
        5000,
        50000
    ],
    "names.level": [
        1,
        2,
        3,
        4
    ],
    "localadmin.country": [
        [
            "CZE",
            "#1f78b4"
        ],
        [
            "SVK",
            "#e31a1c"
        ],
        [
            "CHN",
            "#33a02c"
        ],
        [
            "IDN",
            "#ff7f00"
        ],
        [
            "CHE",
            "#6a3d9a"
        ],
        [
            "ARG",
            "#b15928"
        ],
        [
            "IRN",
            "#a6cee3"
        ],
        [
            "MAR",
            "#fb9a99"
        ],
        [
            "IRQ",
            "#b2df8a"
        ],
        [
            "FRA",
            "#fdbf6f"
        ],
        [
            "SYR",
            "#cab2d6"
        ],
        [
            "BFA",
            "#ffff99"
        ],
        [
            "HTI",
            "#17becf"
        ],
        [
            "SEN",
            "#d62728"
        ],
        [
            "JOR",
            "#2ca02c"
        ],
        [
            "BEL",
            "#9467bd"
        ],
        [
            "SLE",
            "#8c564b"
        ],
        [
            "CIV",
            "#e377c2"
        ],
        [
            "AUT",
            "#7f7f7f"
        ]
    ],
    "locality.class": [
        [
            "village",
            "#f8c2dd"
        ],
        [
            "hamlet",
            "#fdeaf3"
        ],
        [
            "town",
            "#d55a9b"
        ],
        [
            "city",
            "#6e1246"
        ]
    ]
}
