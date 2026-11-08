"""
scripts/geocode.py without the network: what it sends to Nominatim and
which matches it takes for the place itself.
"""

import importlib.util
from pathlib import Path
from types import ModuleType

import pytest


def load() -> ModuleType:
    path = Path(__file__).resolve().parent.parent / "scripts" / "geocode.py"
    spec = importlib.util.spec_from_file_location("geocode", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


geocode = load()


@pytest.mark.parametrize(("address", "parts"), [
    ("1000 Fifth Avenue, New York, NY 10028, USA", ["1000 Fifth Avenue", "New York", "NY", "USA"]),
    ("20 Deans Yard, London SW1P 3PA, United Kingdom", ["20 Deans Yard", "London", "United Kingdom"]),
    ("82 Yigal Alon St., 13th Floor, Tel Aviv 6789124, Israel", ["82 Yigal Alon St.", "Tel Aviv", "Israel"]),
    ("5 HaTzoref St., Holon, Israel (Mer Group, its parent)", ["5 HaTzoref St.", "Holon", "Israel"]),
    ("1730 S. El Camino Real, Suite 600, San Mateo, California, USA", ["1730 S. El Camino Real", "San Mateo", "California", "USA"]),
])
def test_address_parts(address: str, parts: list[str]) -> None:
    assert geocode.address_parts(address) == parts


@pytest.mark.parametrize(("matched", "name", "city", "wanted"), [
    ("Louvre Museum, Rue de Rivoli, Paris, France", "Louvre", "Paris, France", True),
    ("The Metropolitan Museum of Art, 1000, 5th Avenue, Manhattan", "The Metropolitan Museum of Art", "NY, USA", True),
    ("IBM Israel, Shlomo Shmeltzer, Petah Tikva, Israel", "IBM", "Petah Tikva, Israel", True),
    # another museum in the same city shares only "Museum" and the city's name
    ("Eretz Israel Museum, Chaim Levanon, Tel Aviv, Israel", "Tel Aviv Museum", "Tel Aviv, Israel", False),
    # the word must be in the matched object's own name, not further along the address
    ("Micro Focus M3, Altalef, Yehud, Israel", "HP", "Yehud, Israel", False),
])
def test_named(matched: str, name: str, city: str, wanted: bool) -> None:
    assert geocode.named({"display_name": matched}, name, city) is wanted
