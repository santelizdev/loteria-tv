from __future__ import annotations

import unicodedata


VISIBLE_TRIPLE_GROUP_BASES = (
    "Triple Caliente",
    "Triple Caracas",
    "Triple Tachira",
    "Triple Zamorano",
    "Triple Zulia",
)

VISIBLE_TRIPLE_SINGLE_PROVIDERS = (
    "Chance Astral",
    "Trio Activo",
    "Triple Facil",
    "Triple Gana",
    "Super Gana",
    "Triple Centena",
)

TRIPLE_CARD_ORDER = (
    "Triple Caliente",
    "Triple Caracas",
    "Chance Astral",
    "Triple Tachira",
    "Trio Activo",
    "Triple Facil",
    "Triple Zamorano",
    "Triple Zulia",
    "Triple Gana",
    "Super Gana",
    "Triple Centena",
)

VISIBLE_ANIMALITO_PROVIDERS = (
    "Guacharito",
    "Guacharo",
    "Cazaloton",
    "La Granjita",
    "Loto Chaima",
    "Lotto Activo",
    "Lotto Activo Interl",
    "Lotto Rey",
    "Mega Animal",
    "SelvaPlus",
)

ACTIVE_SCRAPER_KEYS = (
    "lotoven_triples",
    "tuazar_triples",
    "lotoven_animalitos",
    # "condor_animalitos",  # Pausado por alcance comercial actual.
)


def _normalize_provider_key(value: str) -> str:
    raw = unicodedata.normalize("NFKD", str(value or ""))
    raw = "".join(char for char in raw if not unicodedata.combining(char))
    return "".join(char.lower() for char in raw if char.isalnum())


def _expand_triple_group_names(base_name: str) -> tuple[str, ...]:
    if base_name == "Triple Zamorano":
        return (f"{base_name} A", f"{base_name} C")
    return (f"{base_name} A", f"{base_name} B", f"{base_name} C")


def visible_triple_provider_names() -> tuple[str, ...]:
    names: list[str] = list(VISIBLE_TRIPLE_SINGLE_PROVIDERS)
    for base_name in VISIBLE_TRIPLE_GROUP_BASES:
        names.extend(_expand_triple_group_names(base_name))
    return tuple(names)


def visible_animalito_provider_keys() -> set[str]:
    return {_normalize_provider_key(name) for name in VISIBLE_ANIMALITO_PROVIDERS}


def is_visible_animalito_provider(name: str) -> bool:
    return _normalize_provider_key(name) in visible_animalito_provider_keys()
