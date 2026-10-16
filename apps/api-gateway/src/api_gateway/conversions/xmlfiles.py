"""Reading an uploaded XML file safely (E2, X3).

Alteryx, Informatica, SSIS and Talend files are XML. An upload is read only
when it declares no ENTITY and no DOCTYPE with declarations of its own:
refusing them rules out entities that expand without end or reach for files
outside the upload. A DOCTYPE that only names its DTD (PowerCenter's exports
name powrmart.dtd) is allowed, and the DTD is never fetched: nothing in a
file is.
"""

from __future__ import annotations

import re
import xml.etree.ElementTree as ElementTree

from api_gateway.conversions.model import NotConverted

_ENTITY = re.compile(rb"<!\s*ENTITY", re.I)
_DOCTYPE = re.compile(rb"<!\s*DOCTYPE[^>]*\[", re.I)


def read_xml(data: bytes, what: str) -> ElementTree.Element:
    if _ENTITY.search(data) or _DOCTYPE.search(data):
        raise NotConverted(f"{what} declares a DOCTYPE or an ENTITY, which this does not read: the format has no "
                           "need of one.")
    try:
        return ElementTree.fromstring(data)
    except ElementTree.ParseError as exc:
        raise NotConverted(f"{what} is not XML this can read: {exc}.") from exc


def local(tag: str) -> str:
    """A tag without its namespace: {http://...}Executable is Executable."""
    return tag.rsplit("}", 1)[-1]


def attribute(element: ElementTree.Element, name: str, default: str | None = None) -> str | None:
    """An attribute by its local name, whatever namespace it is in."""
    for key, value in element.attrib.items():
        if local(key) == name:
            return value
    return default


def children(element: ElementTree.Element, name: str) -> list[ElementTree.Element]:
    return [child for child in element if local(child.tag) == name]


def child(element: ElementTree.Element | None, name: str) -> ElementTree.Element | None:
    if element is None:
        return None
    return next((item for item in element if local(item.tag) == name), None)


def descendants(element: ElementTree.Element, name: str) -> list[ElementTree.Element]:
    return [item for item in element.iter() if local(item.tag) == name]


def items(element: ElementTree.Element | None) -> list[ElementTree.Element]:
    """An element's children, or none when there is no element."""
    return list(element) if element is not None else []
