"""Reference tables the value tools read: units, currencies, alphabets, languages, addresses.

Kept as data in one place so a test can check each table against itself (a
unit converts to its base and back; every currency symbol names a real
code), and so the reference says exactly what each tool knows.
"""

from __future__ import annotations

# ---------------------------------------------------------------- units
#
# Every unit as a multiple of its dimension's base unit (metre, kilogram,
# litre, square metre, metre per second, second, byte, joule, pascal).
# Temperature is not a multiple, so it has its own rule.

UNITS: dict[str, tuple[str, float]] = {
    # length (metre)
    "mm": ("length", 0.001), "cm": ("length", 0.01), "m": ("length", 1.0), "km": ("length", 1000.0),
    "in": ("length", 0.0254), "ft": ("length", 0.3048), "yd": ("length", 0.9144), "mi": ("length", 1609.344),
    "nmi": ("length", 1852.0),
    # mass (kilogram)
    "mg": ("mass", 1e-6), "g": ("mass", 0.001), "kg": ("mass", 1.0), "t": ("mass", 1000.0),
    "oz": ("mass", 0.028349523125), "lb": ("mass", 0.45359237), "st": ("mass", 6.35029318),
    # volume (litre)
    "ml": ("volume", 0.001), "cl": ("volume", 0.01), "l": ("volume", 1.0), "m3": ("volume", 1000.0),
    "tsp": ("volume", 0.00492892159375), "tbsp": ("volume", 0.01478676478125),
    "fl_oz_us": ("volume", 0.0295735295625), "fl_oz_uk": ("volume", 0.0284130625),
    "cup_us": ("volume", 0.2365882365), "pint_us": ("volume", 0.473176473), "pint_uk": ("volume", 0.56826125),
    "gal_us": ("volume", 3.785411784), "gal_uk": ("volume", 4.54609),
    # area (square metre)
    "mm2": ("area", 1e-6), "cm2": ("area", 1e-4), "m2": ("area", 1.0), "ha": ("area", 10_000.0),
    "km2": ("area", 1e6), "ft2": ("area", 0.09290304), "acre": ("area", 4046.8564224), "mi2": ("area", 2589988.110336),
    # speed (metre per second)
    "m/s": ("speed", 1.0), "km/h": ("speed", 1000 / 3600), "mph": ("speed", 0.44704), "kn": ("speed", 1852 / 3600),
    # time (second)
    "ms": ("time", 0.001), "s": ("time", 1.0), "min": ("time", 60.0), "h": ("time", 3600.0),
    "day": ("time", 86_400.0), "week": ("time", 604_800.0),
    # data (byte)
    "bit": ("data", 0.125), "B": ("data", 1.0), "KB": ("data", 1000.0), "MB": ("data", 1e6), "GB": ("data", 1e9),
    "TB": ("data", 1e12), "KiB": ("data", 1024.0), "MiB": ("data", 1024.0 ** 2), "GiB": ("data", 1024.0 ** 3),
    "TiB": ("data", 1024.0 ** 4),
    # energy (joule)
    "J": ("energy", 1.0), "kJ": ("energy", 1000.0), "cal": ("energy", 4.184), "kcal": ("energy", 4184.0),
    "Wh": ("energy", 3600.0), "kWh": ("energy", 3.6e6),
    # pressure (pascal)
    "Pa": ("pressure", 1.0), "kPa": ("pressure", 1000.0), "bar": ("pressure", 100_000.0),
    "psi": ("pressure", 6894.757293168), "atm": ("pressure", 101_325.0), "mmHg": ("pressure", 133.322387415),
}

#: Temperatures: (scale, offset) such that kelvin = value * scale + offset.
TEMPERATURES: dict[str, tuple[float, float]] = {"C": (1.0, 273.15), "F": (5 / 9, 273.15 - 32 * 5 / 9), "K": (1.0, 0.0)}

#: Words people write for units, to the unit.
UNIT_WORDS: dict[str, str] = {
    "millimetre": "mm", "millimetres": "mm", "millimeter": "mm", "millimeters": "mm",
    "centimetre": "cm", "centimetres": "cm", "centimeter": "cm", "centimeters": "cm",
    "metre": "m", "metres": "m", "meter": "m", "meters": "m", "kilometre": "km", "kilometres": "km",
    "kilometer": "km", "kilometers": "km", "inch": "in", "inches": "in", '"': "in", "foot": "ft", "feet": "ft",
    "'": "ft", "yard": "yd", "yards": "yd", "mile": "mi", "miles": "mi",
    "milligram": "mg", "milligrams": "mg", "gram": "g", "grams": "g", "gr": "g", "kilogram": "kg",
    "kilograms": "kg", "kilo": "kg", "kilos": "kg", "kgs": "kg", "tonne": "t", "tonnes": "t", "ounce": "oz",
    "ounces": "oz", "pound": "lb", "pounds": "lb", "lbs": "lb", "stone": "st",
    "millilitre": "ml", "millilitres": "ml", "milliliter": "ml", "milliliters": "ml", "litre": "l",
    "litres": "l", "liter": "l", "liters": "l", "ltr": "l", "gallon": "gal_uk", "gallons": "gal_uk",
    "hectare": "ha", "hectares": "ha", "acres": "acre", "sq m": "m2", "sqm": "m2", "sq ft": "ft2", "sqft": "ft2",
    "kph": "km/h", "kmh": "km/h", "knots": "kn", "knot": "kn",
    "second": "s", "seconds": "s", "sec": "s", "secs": "s", "minute": "min", "minutes": "min", "mins": "min",
    "hour": "h", "hours": "h", "hr": "h", "hrs": "h", "days": "day", "weeks": "week",
    "bytes": "B", "byte": "B", "kb": "KB", "mb": "MB", "gb": "GB", "tb": "TB",
    "°c": "C", "celsius": "C", "centigrade": "C", "°f": "F", "fahrenheit": "F", "kelvin": "K",
}


def unit_dimension(unit: str) -> str:
    if unit in TEMPERATURES:
        return "temperature"
    if unit not in UNITS:
        raise KeyError(unit)
    return UNITS[unit][0]


def unit_names() -> tuple[str, ...]:
    return (*UNITS, *TEMPERATURES)


# ----------------------------------------------------------- currencies

#: ISO 4217 codes this knows, with the symbols and names people write.
CURRENCIES: dict[str, tuple[str, ...]] = {
    "GBP": ("£", "pound", "pounds", "pound sterling", "sterling", "quid", "gbp"),
    "USD": ("$", "us$", "dollar", "dollars", "us dollar", "us dollars", "usd"),
    "EUR": ("€", "euro", "euros", "eur"),
    "JPY": ("¥", "yen", "jpy", "円"),
    "CNY": ("cny", "yuan", "renminbi", "rmb", "元"),
    "INR": ("₹", "rupee", "rupees", "indian rupee", "inr", "rs"),
    "CHF": ("chf", "swiss franc", "swiss francs", "fr."),
    "CAD": ("c$", "ca$", "canadian dollar", "canadian dollars", "cad"),
    "AUD": ("a$", "au$", "australian dollar", "australian dollars", "aud"),
    "NZD": ("nz$", "new zealand dollar", "nzd"),
    "SEK": ("sek", "swedish krona", "swedish kronor"),
    "NOK": ("nok", "norwegian krone", "norwegian kroner"),
    "DKK": ("dkk", "danish krone", "danish kroner"),
    "PLN": ("zł", "zloty", "złoty", "pln"),
    "CZK": ("kč", "koruna", "czk"),
    "HUF": ("ft", "forint", "huf"),
    "RUB": ("₽", "rouble", "roubles", "ruble", "rubles", "rub"),
    "TRY": ("₺", "lira", "turkish lira", "try"),
    "BRL": ("r$", "real", "reais", "brazilian real", "brl"),
    "MXN": ("mx$", "mexican peso", "mexican pesos", "mxn"),
    "ZAR": ("r", "rand", "zar"),
    "KRW": ("₩", "won", "krw"),
    "SGD": ("s$", "singapore dollar", "sgd"),
    "HKD": ("hk$", "hong kong dollar", "hkd"),
    "AED": ("aed", "dirham", "dirhams", "د.إ"),
    "SAR": ("sar", "riyal", "saudi riyal"),
    "ILS": ("₪", "shekel", "shekels", "ils"),
    "THB": ("฿", "baht", "thb"),
    "IDR": ("rp", "rupiah", "idr"),
    "NGN": ("₦", "naira", "ngn"),
    "UAH": ("₴", "hryvnia", "uah"),
    "PHP": ("₱", "peso", "philippine peso", "php"),
    "VND": ("₫", "dong", "vnd"),
}

# ------------------------------------------------------------ alphabets

#: Letters to Latin, by the usual romanisation (ISO 9 simplified for
#: Cyrillic, ELOT 743 for Greek). Accented Latin letters are handled by
#: decomposition afterwards; these are the letters decomposition leaves alone.
TRANSLITERATION: dict[str, str] = {
    # Cyrillic
    "а": "a", "б": "b", "в": "v", "г": "g", "д": "d", "е": "e", "ё": "yo", "ж": "zh", "з": "z", "и": "i",
    "й": "y", "к": "k", "л": "l", "м": "m", "н": "n", "о": "o", "п": "p", "р": "r", "с": "s", "т": "t",
    "у": "u", "ф": "f", "х": "kh", "ц": "ts", "ч": "ch", "ш": "sh", "щ": "shch", "ъ": "", "ы": "y", "ь": "",
    "э": "e", "ю": "yu", "я": "ya", "є": "ye", "і": "i", "ї": "yi", "ґ": "g", "ў": "u", "ђ": "dj", "ј": "j",
    "љ": "lj", "њ": "nj", "ћ": "c", "џ": "dz",
    # Greek
    "α": "a", "β": "v", "γ": "g", "δ": "d", "ε": "e", "ζ": "z", "η": "i", "θ": "th", "ι": "i", "κ": "k",
    "λ": "l", "μ": "m", "ν": "n", "ξ": "x", "ο": "o", "π": "p", "ρ": "r", "σ": "s", "ς": "s", "τ": "t",
    "υ": "y", "φ": "f", "χ": "ch", "ψ": "ps", "ω": "o", "ά": "a", "έ": "e", "ή": "i", "ί": "i", "ό": "o",
    "ύ": "y", "ώ": "o", "ϊ": "i", "ϋ": "y", "ΐ": "i", "ΰ": "y",
    # Latin letters decomposition does not split
    "ß": "ss", "æ": "ae", "œ": "oe", "ø": "o", "đ": "d", "ð": "d", "þ": "th", "ł": "l", "ı": "i", "ħ": "h",
}

# ------------------------------------------------------------ languages

#: The commonest short words in each language, which carry its signature.
#: A text is scored by how many of its words each list holds.
LANGUAGE_WORDS: dict[str, frozenset[str]] = {
    "en": frozenset("the and of to in is it that for you was on are with as be this have from not at by".split()),
    "de": frozenset("der die und das ist nicht ein zu den von mit sich des auf für im dem eine auch es".split()),
    "fr": frozenset("le la les et des est un une du que pas pour dans en qui sur au avec il ne".split()),
    "es": frozenset("el la de que y los en un es se no las por una con para del al lo como".split()),
    "it": frozenset("il di che è la e non un per una sono gli del della le con mi si ma".split()),
    "pt": frozenset("o a de que e do da em um para é com não uma os no se na por mais".split()),
    "nl": frozenset("de het een en van is dat niet ik je zijn op te met voor er maar ook".split()),
    "sv": frozenset("och att det som en på är av för med till den har inte jag om ett var".split()),
    "da": frozenset("og at det en den til er som på de med han af for ikke der var jeg et".split()),
    "no": frozenset("og i det som en på er av for med til den har ikke jeg å at var et".split()),
    "fi": frozenset("ja on ei se että hän oli ole mutta kun niin myös tai jos vain sen".split()),
    "pl": frozenset("i w nie na się z jest to że do co jak ale tak o po za od".split()),
    "cs": frozenset("a se na je to že v s z do jsem o ale jak by tak pro".split()),
    "tr": frozenset("ve bir bu da de için ile çok ne o daha gibi ama ben var mı".split()),
    "ro": frozenset("și de în la cu nu pe că o un este se din care mai sunt".split()),
    "hu": frozenset("a az és hogy nem is egy meg van de csak már el ha volt".split()),
    "id": frozenset("yang dan di itu dengan untuk tidak ini dari dalam akan pada juga saya ke".split()),
}

#: Scripts that name their language (or a short list) on their own.
SCRIPTS: tuple[tuple[str, int, int], ...] = (
    ("el", 0x0370, 0x03FF), ("cyrillic", 0x0400, 0x04FF), ("he", 0x0590, 0x05FF), ("ar", 0x0600, 0x06FF),
    ("hi", 0x0900, 0x097F), ("th", 0x0E00, 0x0E7F), ("ka", 0x10A0, 0x10FF), ("ko", 0xAC00, 0xD7AF),
    ("ja", 0x3040, 0x30FF), ("zh", 0x4E00, 0x9FFF),
)

# ------------------------------------------------------------- addresses

#: Street and place words, long form to the usual abbreviation (UK and US).
STREET_WORDS: dict[str, str] = {
    "street": "St", "road": "Rd", "avenue": "Ave", "boulevard": "Blvd", "lane": "Ln", "drive": "Dr",
    "court": "Ct", "place": "Pl", "square": "Sq", "terrace": "Ter", "close": "Cl", "crescent": "Cres",
    "gardens": "Gdns", "parkway": "Pkwy", "highway": "Hwy", "mount": "Mt", "grove": "Gr", "park": "Pk",
    "way": "Way", "circle": "Cir", "trail": "Trl", "north": "N", "south": "S", "east": "E", "west": "W",
    "apartment": "Apt", "suite": "Ste", "building": "Bldg", "floor": "Fl", "unit": "Unit", "flat": "Flat",
}

US_STATES = frozenset((
    "AL AK AZ AR CA CO CT DE FL GA HI ID IL IN IA KS KY LA ME MD MA MI MN MS MO MT NE NV NH NJ NM NY NC ND OH OK "
    "OR PA RI SC SD TN TX UT VT VA WA WV WI WY DC").split())
