"""
The organization logo convention (doc/logos.md): SVG on a 1000x1000 canvas
with a square viewBox, nothing active or external. logo_problems says what
breaks it (the logos check); svg_upload makes an uploaded SVG keep it, or
refuses one that cannot.
"""

import re
import xml.etree.ElementTree as ET

SVG_NS = "http://www.w3.org/2000/svg"


XLINK_NS = "http://www.w3.org/1999/xlink"


SVG_TYPE = "image/svg+xml"


LOGO_SIZE = "1000"


# elements that run code, pull in other content, or embed a bitmap
FORBIDDEN_ELEMENTS = ("script", "foreignObject", "image", "iframe", "object", "embed")


# @import, or url() of anything but a #fragment of the same file
OUTSIDE_STYLE = re.compile(r"@import|url\(\s*['\"]?(?!#)")


NUMBER = re.compile(r"[-+]?(\d+\.?\d*|\.\d+)([eE][-+]?\d+)?")


# a document type declaration can define entities that expand without end: an upload has none
DOCTYPE = re.compile(rb"<!DOCTYPE|<!ENTITY", re.IGNORECASE)


# the root <svg ...> start tag, and the attributes of it svg_upload sets
ROOT_TAG = re.compile(r"<svg\b[^>]*>")


CANVAS_ATTRIBUTE = re.compile(r"""\s(width|height|viewBox)\s*=\s*("[^"]*"|'[^']*')""")


class SvgError(ValueError):
    """ An upload that is no SVG, or one a logo may not be. """


def _local(tag: str) -> str:
    """ An element or attribute name without its {namespace}. """
    return tag.rsplit("}", 1)[-1]


def _numbers(value: str | None) -> list[float]:
    return [float(n.group(0)) for n in NUMBER.finditer(value or "")]


def _parsed(data: bytes) -> ET.Element:
    """ The root element of an SVG; SvgError when the data is not one. """
    if DOCTYPE.search(data):
        raise SvgError("has a document type declaration")
    try:
        root = ET.fromstring(data)
    except ET.ParseError as e:
        raise SvgError(f"not well-formed XML: {e}") from e
    if root.tag != f"{{{SVG_NS}}}svg":
        raise SvgError(f"the root element is {root.tag}, not an SVG <svg>")
    return root


def _content_problems(root: ET.Element) -> list[str]:
    """ What in an SVG runs code, embeds a bitmap or refers outside the file. """
    problems = []
    for element in root.iter():
        name = _local(element.tag) if isinstance(element.tag, str) else ""
        if name in FORBIDDEN_ELEMENTS:
            problems.append(f"has a <{name}> element")
        if name == "style" and element.text and OUTSIDE_STYLE.search(element.text):
            problems.append("<style> refers to something outside the file")
        for attribute, value in element.attrib.items():
            local = _local(attribute)
            if local.lower().startswith("on"):
                problems.append(f"<{name}> has an event handler, {local}")
            elif local == "href" and not value.startswith("#"):
                problems.append(f"<{name}> links to {value[:80]!r}")
            elif OUTSIDE_STYLE.search(value):
                problems.append(f"<{name}> {local} refers to something outside the file")
    # the same problem in many elements is said once
    return list(dict.fromkeys(problems))


def logo_problems(data: bytes) -> list[str]:
    """
    What is wrong with one SVG logo, by the convention in doc/logos.md: a
    1000x1000 canvas, a square viewBox, nothing active or external. The
    6% margin and the centering are not checked: they need the drawn
    bounding box, so a renderer.
    """
    try:
        root = _parsed(data)
    except SvgError as e:
        return [str(e)]
    problems = []
    width, height = root.get("width"), root.get("height")
    if (width, height) != (LOGO_SIZE, LOGO_SIZE):
        problems.append(f'width/height are {width!r}/{height!r}, not "{LOGO_SIZE}"/"{LOGO_SIZE}"')
    view_box = root.get("viewBox")
    if view_box is None:
        problems.append("no viewBox")
    else:
        numbers = _numbers(view_box)
        if len(numbers) != 4:
            problems.append(f"viewBox {view_box!r} is not four numbers")
        elif numbers[2] <= 0 or numbers[2] != numbers[3]:
            problems.append(f"viewBox {view_box!r} is not a square")
    return problems + _content_problems(root)


def is_svg(data: bytes) -> bool:
    """ Whether an upload claims to be SVG: its first tag, after any XML declaration and comments, is <svg. """
    head = data[:4096].lstrip(b"\xef\xbb\xbf \t\r\n")
    while head.startswith((b"<?", b"<!--", b"<!DOCTYPE")):
        if head.startswith(b"<!DOCTYPE"):
            # an SVG with a document type declaration: svg_upload refuses it, saying why
            return b"<svg" in head
        end = head.find(b"?>" if head.startswith(b"<?") else b"-->")
        if end < 0:
            return False
        head = head[end + (2 if head.startswith(b"<?") else 3):].lstrip()
    return head.startswith(b"<svg")


def svg_upload(data: bytes) -> bytes:
    """
    An uploaded SVG made to keep the logo convention: its viewBox squared
    (the shorter side widened, the artwork centered in it) and its canvas
    1000x1000. Only the root element changes. SvgError when it is no SVG,
    has nothing to size it by, or has anything active or external (doc/logos.md).
    """
    root = _parsed(data)
    problems = _content_problems(root)
    if problems:
        raise SvgError("; ".join(problems))
    box = _numbers(root.get("viewBox"))
    if root.get("viewBox") is None:
        width, height = _numbers(root.get("width")), _numbers(root.get("height"))
        if len(width) != 1 or len(height) != 1 or "%" in (root.get("width") or "") + (root.get("height") or ""):
            raise SvgError("has no viewBox and no width and height to make one from")
        box = [0.0, 0.0, width[0], height[0]]
    if len(box) != 4 or box[2] <= 0 or box[3] <= 0:
        raise SvgError(f"viewBox {root.get('viewBox')!r} is not four numbers with a size")
    x, y, w, h = box
    side = max(w, h)
    x, y = x - (side - w) / 2, y - (side - h) / 2
    try:
        text = data.decode("utf-8")
    except UnicodeDecodeError as e:
        raise SvgError("not UTF-8") from e
    tag = ROOT_TAG.search(text)
    if tag is None:
        raise SvgError("no <svg> start tag")
    canvas = f' width="{LOGO_SIZE}" height="{LOGO_SIZE}" viewBox="{x:g} {y:g} {side:g} {side:g}"'
    start = CANVAS_ATTRIBUTE.sub("", tag.group(0))
    # the canvas goes last, before the tag closes (">", or "/>" for an empty drawing)
    close = "/>" if start.endswith("/>") else ">"
    start = start[:-len(close)].rstrip() + canvas + close
    return (text[:tag.start()] + start + text[tag.end():]).encode("utf-8")
