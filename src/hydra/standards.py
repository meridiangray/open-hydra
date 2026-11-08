"""standards.py — ISO code lists: what a country, currency, language or script code names.

The lists come from pycountry (the Debian iso-codes data), an optional dependency
(`pip install hydra[standards]`). Without it every lookup answers None and a label falls back to
the code as written, so nothing breaks, it only reads less well. `.hydra/rules/standards.yaml`
(the archive's own, else the one hydra ships) adds what ISO does not say: a label to use instead
of ISO's, the word for a national ("Saudi"), codes ISO lacks (Kosovo `xk`), and which string
properties hold a standard's codes (FtM types `country` and `language` are known already).

    ISO 3166-1    countries                 alpha-2 (FtM writes them lower case), alpha-3
    ISO 3166-3    former countries          alpha-4 (`suhh`) or their old alpha-2 (`su`)
    ISO 3166-2    subdivisions              `sa-01`
    ISO 4217      currencies                `SAR`
    ISO 639-3     languages                 `ara` (639-1 `ar` read too)
    ISO 15924     scripts                   `Arab`; script_of(text) tells the script a name is written in

    load(root)                       -> Standards for that archive
    Standards.label(kind, code)      -> a reader's name, the code itself when unknown
    Standards.valid(kind, code)      -> True / False, or None when pycountry is not installed
    Standards.kind_of(schema_prop)   -> which standard a property's values follow, or None
"""
from __future__ import annotations

import re
import unicodedata
from functools import lru_cache
from pathlib import Path

from hydra import layout, resources, yamlcache
from hydra.identity.types import norm_text

try:
    import pycountry
except ImportError:                       # optional: labels fall back to the codes
    pycountry = None

KINDS = ("country", "subdivision", "currency", "language", "script")
FTM_TYPES = {"country": "country", "language": "language"}    # FtM property types that hold ISO codes

# Reader-friendly short names where ISO 3166 uses a formal/inverted title, plus non-ISO codes
_NAMES = {
    "bn": "Brunei", "cd": "Democratic Republic of the Congo", "fk": "Falkland Islands",
    "fm": "Micronesia", "ir": "Iran", "kp": "North Korea", "kr": "South Korea", "la": "Laos",
    "ps": "Palestine", "ru": "Russia", "sy": "Syria", "tw": "Taiwan", "va": "Vatican City",
    "vg": "British Virgin Islands", "vi": "United States Virgin Islands",
    "xk": "Kosovo", "su": "Soviet Union", "suhh": "Soviet Union",
    "yu": "Yugoslavia", "yucs": "Yugoslavia", "dd": "East Germany", "ddde": "East Germany",
    "cs": "Czechoslovakia", "cshh": "Czechoslovakia", "csxx": "Serbia and Montenegro",
}

# Built-in demonyms by ISO alpha-2 (or historic) code; an archive's standards.yaml overrides any entry
_DEMONYMS = {
    "ae": "Emirati", "af": "Afghan", "al": "Albanian", "am": "Armenian", "ar": "Argentine",
    "at": "Austrian", "au": "Australian", "az": "Azerbaijani", "ba": "Bosnian", "bd": "Bangladeshi",
    "be": "Belgian", "bg": "Bulgarian", "bh": "Bahraini", "bn": "Bruneian", "bo": "Bolivian",
    "br": "Brazilian", "by": "Belarusian", "ca": "Canadian", "cd": "Congolese", "cg": "Congolese",
    "ch": "Swiss", "ci": "Ivorian", "cl": "Chilean", "cm": "Cameroonian", "cn": "Chinese",
    "co": "Colombian", "cr": "Costa Rican", "cu": "Cuban", "cy": "Cypriot", "cz": "Czech",
    "dd": "East German", "ddde": "East German", "de": "German", "dk": "Danish", "do": "Dominican",
    "dz": "Algerian", "ec": "Ecuadorian", "ee": "Estonian", "eg": "Egyptian", "es": "Spanish",
    "et": "Ethiopian", "fi": "Finnish", "fr": "French", "gb": "British", "ge": "Georgian",
    "gh": "Ghanaian", "gr": "Greek", "gt": "Guatemalan", "hk": "Hong Kong", "hn": "Honduran",
    "hr": "Croatian", "hu": "Hungarian", "id": "Indonesian", "ie": "Irish", "il": "Israeli",
    "in": "Indian", "iq": "Iraqi", "ir": "Iranian", "is": "Icelandic", "it": "Italian",
    "jm": "Jamaican", "jo": "Jordanian", "jp": "Japanese", "ke": "Kenyan", "kg": "Kyrgyz",
    "kh": "Cambodian", "kp": "North Korean", "kr": "South Korean", "kw": "Kuwaiti", "kz": "Kazakh",
    "la": "Lao", "lb": "Lebanese", "li": "Liechtensteiner", "lk": "Sri Lankan", "lt": "Lithuanian",
    "lu": "Luxembourgish", "lv": "Latvian", "ly": "Libyan", "ma": "Moroccan", "mc": "Monegasque",
    "md": "Moldovan", "me": "Montenegrin", "mk": "Macedonian", "mm": "Burmese", "mn": "Mongolian",
    "mt": "Maltese", "mx": "Mexican", "my": "Malaysian", "ng": "Nigerian", "ni": "Nicaraguan",
    "nl": "Dutch", "no": "Norwegian", "np": "Nepali", "nz": "New Zealand", "om": "Omani",
    "pa": "Panamanian", "pe": "Peruvian", "ph": "Filipino", "pk": "Pakistani", "pl": "Polish",
    "ps": "Palestinian", "pt": "Portuguese", "py": "Paraguayan", "qa": "Qatari", "ro": "Romanian",
    "rs": "Serbian", "ru": "Russian", "rw": "Rwandan", "sa": "Saudi", "sd": "Sudanese",
    "se": "Swedish", "sg": "Singaporean", "si": "Slovenian", "sk": "Slovak", "sn": "Senegalese",
    "so": "Somali", "su": "Soviet", "suhh": "Soviet", "sy": "Syrian", "th": "Thai",
    "tj": "Tajik", "tm": "Turkmen", "tn": "Tunisian", "tr": "Turkish", "tw": "Taiwanese",
    "tz": "Tanzanian", "ua": "Ukrainian", "ug": "Ugandan", "us": "American", "uy": "Uruguayan",
    "uz": "Uzbek", "ve": "Venezuelan", "vn": "Vietnamese", "xk": "Kosovar", "ye": "Yemeni",
    "yu": "Yugoslav", "yucs": "Yugoslav", "za": "South African", "zm": "Zambian", "zw": "Zimbabwean",
}

_ALIASES = {
    "uk": "gb", "great britain": "gb", "england": "gb", "scotland": "gb", "wales": "gb",
    "northern ireland": "gb", "channel islands": "gb", "alderney": "gb", "britain": "gb",
    "usa": "us", "u s a": "us", "u s": "us", "america": "us", "united states of america": "us",
    "uae": "ae", "ksa": "sa", "drc": "cd", "ussr": "su", "gdr": "dd",
    "burma": "mm", "swaziland": "sz", "ivory coast": "ci", "cape verde": "cv", "east timor": "tl",
}


def path(root) -> Path:
    own = Path(root) / layout.STANDARDS if root else None
    return own if own and yamlcache.is_file(own) else resources.TEMPLATE / layout.STANDARDS


def load(root=None) -> "Standards":
    f = path(root)
    doc = yamlcache.load(f) if yamlcache.is_file(f) else None
    return Standards(doc if isinstance(doc, dict) else {})


@lru_cache(maxsize=1)
def _country_index() -> dict[str, str]:
    """Normalized country code, alpha-3, name, common/official name, alias, or demonym -> alpha-2 code."""
    idx: dict[str, str] = {}
    if pycountry:
        for h in pycountry.historic_countries:
            code = (getattr(h, "alpha_2", None) or h.alpha_4).lower()
            for k in ("alpha_2", "alpha_3", "alpha_4", "name"):
                v = getattr(h, k, None)
                if v:
                    idx.setdefault(norm_text(v), code)
        for c in pycountry.countries:
            code = c.alpha_2.lower()
            for k in ("alpha_2", "alpha_3", "name", "common_name", "official_name"):
                v = getattr(c, k, None)
                if v:
                    idx[norm_text(v)] = code
                    if "," in v:
                        a, _, b = v.partition(",")
                        idx.setdefault(norm_text(f"{b} {a}"), code)
    for code, name in _NAMES.items():
        idx[code] = code
        idx[norm_text(name)] = code if len(code) == 2 or code not in idx else idx[code]
    for code, dem in _DEMONYMS.items():
        idx.setdefault(norm_text(dem), code)
    idx.update(_ALIASES)
    return idx


@lru_cache(maxsize=4096)
def country_code(value: str) -> str:
    """Any country code, name, or demonym -> canonical lower-case ISO code (or '' when unknown)."""
    n = norm_text(value)
    if not n:
        return ""
    compact = n.replace(" ", "")
    idx = _country_index()
    if compact in idx:
        return idx[compact]
    if n in idx:
        return idx[n]
    if re.fullmatch(r"[a-z]{2}", compact):
        return compact
    return ""


@lru_cache(maxsize=1024)
def language_code(value: str) -> str:
    """2-letter ISO 639-1, 3-letter ISO 639-3, or language name -> 3-letter ISO 639-3 code (or '' when unknown)."""
    c = str(value or "").strip()
    if not c or not pycountry:
        return ""
    hit = (pycountry.languages.get(alpha_3=c.lower()) if len(c) == 3 else
           pycountry.languages.get(alpha_2=c.lower()) if len(c) == 2 else
           pycountry.languages.get(name=c.title()))
    return getattr(hit, "alpha_3", "") if hit else ""


@lru_cache(maxsize=1024)
def currency_code(value: str) -> str:
    """Currency code or name -> 3-letter ISO 4217 code (or '' when unknown)."""
    c = str(value or "").strip()
    if not c or not pycountry:
        return ""
    hit = pycountry.currencies.get(alpha_3=c.upper()) if len(c) == 3 else pycountry.currencies.get(name=c.title())
    return getattr(hit, "alpha_3", "") if hit else ""


def _obj(o, **extra) -> dict:
    return {k: getattr(o, k) for k in ("alpha_2", "alpha_3", "alpha_4", "name", "common_name", "official_name",
                                       "numeric", "code", "type") if getattr(o, k, None)} | extra


@lru_cache(maxsize=None)
def _country(code: str) -> dict | None:
    if not pycountry or not code:
        return None
    c = code.upper()
    hit = (pycountry.countries.get(alpha_2=c) if len(c) == 2 else
           pycountry.countries.get(alpha_3=c) if len(c) == 3 else None)
    if hit:
        return _obj(hit, former=False)
    old = (pycountry.historic_countries.get(alpha_4=c) if len(c) == 4 else
           next((h for h in pycountry.historic_countries if getattr(h, "alpha_2", None) == c), None) if len(c) == 2 else
           pycountry.historic_countries.get(alpha_3=c) if len(c) == 3 else None)
    return _obj(old, former=True) if old else None


@lru_cache(maxsize=None)
def _lookup(kind: str, code: str) -> dict | None:
    if not pycountry or not code:
        return None
    c = code.strip()
    if kind == "currency":
        hit = pycountry.currencies.get(alpha_3=c.upper())
    elif kind == "language":
        hit = (pycountry.languages.get(alpha_3=c.lower()) if len(c) == 3 else
               pycountry.languages.get(alpha_2=c.lower()) if len(c) == 2 else None)
    elif kind == "script":
        hit = pycountry.scripts.get(alpha_4=c.title())
    elif kind == "subdivision":
        hit = pycountry.subdivisions.get(code=c.upper())
    else:
        return None
    return _obj(hit) if hit else None


class Standards:
    def __init__(self, doc: dict):
        self.countries = {str(k).lower(): (v if isinstance(v, dict) else {}) for k, v in (doc.get("countries") or {}).items()}
        self.properties = {str(k): str(v) for k, v in (doc.get("properties") or {}).items()}
        self.available = pycountry is not None

    # -- one entry
    def country(self, code) -> dict | None:
        """{name, official_name, alpha_2, alpha_3, former, demonym}: ISO's, with the rules file's words over it."""
        raw = str(code or "").strip()
        low = raw.lower()
        c = low if (low in self.countries or low in _NAMES or _country(raw)) else (country_code(raw) or low)
        own = self.countries.get(c, {})
        iso = _country(c) or {}
        if not iso and not own and c not in _NAMES:
            return None
        name = own.get("name") or _NAMES.get(c) or iso.get("common_name") or iso.get("name")
        dem = own.get("demonym") or _DEMONYMS.get(c, "")
        return {**iso, "name": name, "demonym": dem, "former": iso.get("former", c in ("su", "suhh", "yu", "yucs", "dd", "ddde", "cs", "cshh", "csxx")),
                "iso": bool(iso)}

    def get(self, kind: str, code) -> dict | None:
        return self.country(code) if kind == "country" else _lookup(kind, str(code or ""))

    def label(self, kind: str, code) -> str:
        """A reader's name for a code; the code as written (upper case for a country) when unknown."""
        hit = self.get(kind, code)
        if hit:
            return hit.get("common_name") or hit["name"] if kind != "country" else hit["name"]
        return str(code or "").upper() if kind == "country" else str(code or "")

    def demonym(self, code) -> str:
        return (self.country(code) or {}).get("demonym", "")

    def valid(self, kind: str, code) -> bool | None:
        """Does the standard know the code? None when it cannot tell (pycountry not installed)."""
        raw = str(code or "").strip()
        low = raw.lower()
        if kind == "country" and (low in self.countries or low in _NAMES):
            return True
        if not self.available:
            return None
        if kind == "country":
            return _country(raw) is not None
        return _lookup(kind, raw) is not None

    # -- which properties hold codes
    def kind_of(self, schema_name: str, prop: str, ftm_type: str | None) -> str | None:
        """The standard a property's values follow: its FtM type (country, language), else the rules
        file's `properties` (`currency: currency`, or `Payment.currency: currency`), schema ancestry applied."""
        if ftm_type in FTM_TYPES:
            return FTM_TYPES[ftm_type]
        from hydra import schema as hschema
        for s in hschema.ancestors(schema_name) or (schema_name,):
            if f"{s}.{prop}" in self.properties:
                return self.properties[f"{s}.{prop}"]
        return self.properties.get(prop)


def script_of(text: str) -> str | None:
    """The ISO 15924 code of the script most of a name's letters are written in ("Arab", "Latn",
    "Cyrl"), from the Unicode names of its letters; None when it has no letters or pycountry is missing."""
    counts: dict[str, int] = {}
    for ch in str(text or ""):
        if ch.isalpha():
            word = unicodedata.name(ch, "").split(" ")[0]
            if word:
                counts[word] = counts.get(word, 0) + 1
    if not counts or not pycountry:
        return None
    word = max(counts, key=counts.get).title()
    hit = pycountry.scripts.get(name=word) or next((s for s in pycountry.scripts if s.name.split(" ")[0] == word), None)
    return hit.alpha_4 if hit else None
