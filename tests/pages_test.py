"""
The library page against the scripts that run on it: every page of WORLDS
(static/js/worlds.js) has its dialog form in html/library.html, under the id
setupWorldForm looks for (slug(view) + "-form", the slug being the page's
singular name, lowercase, spaces as dashes), and in DIALOG_FORMS. A page
renamed without its form left the whole site not loading ("Cannot set
properties of null (setting 'onsubmit')").
"""

import re
from pathlib import Path

SRC = Path(__file__).resolve().parent.parent / "src" / "myworld"
WORLDS_JS = (SRC / "static" / "js" / "worlds.js").read_text(encoding="utf-8")
DIALOG_JS = (SRC / "static" / "js" / "dialog.js").read_text(encoding="utf-8")
LIBRARY = (SRC / "html" / "library.html").read_text(encoding="utf-8")


def _worlds() -> dict[str, str]:
    """ Each page of WORLDS and its singular name. """
    start = WORLDS_JS.index("export const WORLDS = {")
    block = WORLDS_JS[start:WORLDS_JS.index("\n};", start)]
    found = dict(re.findall(r'^\t"?([\w-]+)"?: \["[^"]*", "[^"]*", "([^"]*)"', block, re.MULTILINE))
    assert len(found) > 20
    return found


def test_every_page_has_its_form() -> None:
    dialog_forms = re.search(r"DIALOG_FORMS = \[(.*?)\]", DIALOG_JS)
    assert dialog_forms is not None
    listed = set(re.findall(r'"([\w-]+)"', dialog_forms.group(1)))
    for view, singular in _worlds().items():
        form = singular.lower().replace(" ", "-") + "-form"
        assert f'<form id="{form}"' in LIBRARY, f"{view}: no {form} in library.html"
        assert form in listed, f"{view}: {form} is not in DIALOG_FORMS"
