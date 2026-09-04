"""Compact attribute ontology: canonical keys, synonyms (multi-lingual), units, tolerances, ranges.

Real deployment loads this from versioned YAML; the prototype keeps it inline.
"""
from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class AttrSpec:
    key: str
    section: str                       # core | attributes
    kind: str                          # number | string | bool | list | enum
    unit: str | None = None
    synonyms: tuple[str, ...] = ()
    tolerance: float = 0.0             # relative, for numbers
    range: tuple[float, float] | None = None
    variant_specific: bool = False
    weight: float = 1.0                # importance for hole-driven priority
    expected_in: tuple[str, ...] = ("retail", "datasheet")
    human: dict[str, str] = field(default_factory=dict)  # query words per lang


CORE: list[AttrSpec] = [
    AttrSpec("weight_g", "core", "number", "g", ("weight", "вага", "вес", "gewicht", "masa", "waga", "net weight", "product weight"),
             tolerance=0.03, range=(1, 500_000), weight=1.0, human={"en": "weight", "uk": "вага", "de": "Gewicht"}),
    AttrSpec("length_mm", "core", "number", "mm", ("length", "довжина", "länge", "długość"), tolerance=0.03, range=(1, 20_000)),
    AttrSpec("width_mm", "core", "number", "mm", ("width", "ширина", "breite", "szerokość"), tolerance=0.03, range=(1, 20_000)),
    AttrSpec("height_mm", "core", "number", "mm", ("height", "висота", "höhe", "wysokość"), tolerance=0.03, range=(1, 20_000)),
    AttrSpec("color", "core", "string", None, ("color", "colour", "колір", "цвет", "farbe", "kolor"), variant_specific=True, weight=0.6),
    AttrSpec("warranty_months", "core", "number", "months", ("warranty", "гарантія", "гарантия", "garantie", "gwarancja"),
             tolerance=0.0, range=(0, 240), weight=0.7, expected_in=("retail",), human={"en": "warranty", "uk": "гарантія", "de": "Garantie"}),
    AttrSpec("country_of_origin", "core", "string", None, ("country of origin", "made in", "країна виробник", "страна производитель", "herstellungsland"), weight=0.4),
    AttrSpec("in_the_box", "core", "list", None, ("in the box", "package contents", "комплектація", "комплектация", "lieferumfang", "scope of delivery"), weight=0.5, variant_specific=True),
]

POWER_TOOLS: list[AttrSpec] = [
    AttrSpec("voltage_v", "attributes", "number", "V", ("voltage", "battery voltage", "напруга", "напряжение", "spannung", "akkuspannung", "napięcie"),
             tolerance=0.0, range=(1, 1000), weight=1.0),
    AttrSpec("max_torque_hard_nm", "attributes", "number", "Nm", ("max torque hard", "max. torque (hard)", "torque hard", "max torque", "maximum torque", "max. torque", "hard torque", "крутний момент жорсткий", "крутящий момент жесткий", "drehmoment hart", "max. drehmoment"),
             tolerance=0.0, range=(0.1, 5000), weight=1.0, human={"en": "torque", "uk": "крутний момент", "de": "Drehmoment"}),
    AttrSpec("max_torque_soft_nm", "attributes", "number", "Nm", ("max torque soft", "max. torque (soft)", "torque soft", "soft torque", "крутний момент м'який", "drehmoment weich"),
             tolerance=0.0, range=(0.1, 5000), weight=0.7),
    AttrSpec("no_load_speed_rpm", "attributes", "number", "rpm", ("no-load speed", "no load speed", "rated speed", "швидкість холостого ходу", "число оборотов", "leerlaufdrehzahl", "obroty"),
             tolerance=0.02, range=(1, 100_000), weight=0.8, human={"en": "no-load speed", "uk": "обороти", "de": "Leerlaufdrehzahl"}),
    AttrSpec("chuck_capacity_mm", "attributes", "string", None, ("chuck capacity", "chuck range", "діаметр патрона", "патрон", "bohrfutterspannbereich"), weight=0.6),
    AttrSpec("chuck_type", "attributes", "string", None, ("chuck type", "chuck", "тип патрона", "bohrfutter"), weight=0.5),
    AttrSpec("battery_capacity_ah", "attributes", "number", "Ah", ("battery capacity", "ємність акумулятора", "емкость аккумулятора", "akkukapazität"),
             tolerance=0.0, range=(0.1, 100), weight=0.8, variant_specific=True),
    AttrSpec("motor_type", "attributes", "enum", None, ("motor type", "motor", "тип двигуна", "тип двигателя", "motortyp"), weight=0.6),
    AttrSpec("battery_included", "attributes", "bool", None, ("battery included", "batteries included", "акумулятор в комплекті", "akku im lieferumfang"), variant_specific=True, weight=0.5),
]

SMARTPHONES: list[AttrSpec] = [
    AttrSpec("display_in", "attributes", "number", "in", ("display size", "screen size", "діагональ", "диагональ", "displaygröße"), tolerance=0.02, range=(2, 15), weight=1.0),
    AttrSpec("storage_gb", "attributes", "number", "GB", ("storage", "internal storage", "вбудована пам'ять", "встроенная память", "speicher"), tolerance=0.0, range=(1, 4096), variant_specific=True, weight=1.0),
    AttrSpec("ram_gb", "attributes", "number", "GB", ("ram", "memory", "оперативна пам'ять", "оперативная память", "arbeitsspeicher"), tolerance=0.0, range=(0.5, 64), weight=0.9),
    AttrSpec("battery_mah", "attributes", "number", "mAh", ("battery", "battery capacity", "акумулятор", "аккумулятор", "akku"), tolerance=0.02, range=(500, 30000), weight=0.9),
    AttrSpec("chipset", "attributes", "string", None, ("chipset", "processor", "soc", "процесор", "процессор", "prozessor"), weight=0.9),
]

CATEGORIES: dict[str, dict] = {
    "generic": {"path": ["generic"], "attrs": [], "keywords": []},
    "tools/power_tools": {"path": ["tools", "power_tools"], "attrs": POWER_TOOLS,
                          "keywords": ["drill", "driver", "screwdriver", "шуруповерт", "шуруповёрт", "дриль", "дрель", "akkuschrauber", "bohrschrauber", "grinder", "болгарка", "gsr", "gsb", "gdr", "dhp", "dga", "dtd", "impact"]},
    "electronics/smartphones": {"path": ["electronics", "smartphones"], "attrs": SMARTPHONES,
                                "keywords": ["iphone", "galaxy", "smartphone", "смартфон", "pixel", "xiaomi", "redmi", "телефон"]},
}

VARIANT_AXES: dict[str, list[str]] = {
    "tools/power_tools": ["kit", "battery_capacity_ah", "color"],
    "electronics/smartphones": ["color", "storage_gb", "region"],
    "generic": ["color"],
}

BRAND_LEXICON = {
    "bosch": {"aliases": ["bosch", "bosch professional"], "langs": ["en", "de", "uk"]},
    "makita": {"aliases": ["makita"], "langs": ["en", "ja", "uk"]},
    "dewalt": {"aliases": ["dewalt", "de walt"], "langs": ["en", "uk"]},
    "apple": {"aliases": ["apple", "iphone"], "langs": ["en"]},
    "samsung": {"aliases": ["samsung", "galaxy"], "langs": ["en", "ko"]},
    "xiaomi": {"aliases": ["xiaomi", "redmi", "poco"], "langs": ["en", "zh"]},
    "fluke": {"aliases": ["fluke"], "langs": ["en"]},
    "siemens": {"aliases": ["siemens"], "langs": ["en", "de"]},
    "skf": {"aliases": ["skf"], "langs": ["en", "de"]},
}


def specs_for(category: str) -> list[AttrSpec]:
    return CORE + CATEGORIES.get(category, CATEGORIES["generic"])["attrs"]


def spec_index(category: str) -> dict[str, AttrSpec]:
    return {s.key: s for s in specs_for(category)}


def synonym_index(category: str) -> list[tuple[str, AttrSpec]]:
    """Longest-synonym-first list for greedy key matching."""
    pairs = [(syn.lower(), s) for s in specs_for(category) for syn in (s.key.replace("_", " "),) + s.synonyms]
    return sorted(pairs, key=lambda p: -len(p[0]))


def category_path(category: str) -> list[str]:
    return CATEGORIES.get(category, CATEGORIES["generic"])["path"]
