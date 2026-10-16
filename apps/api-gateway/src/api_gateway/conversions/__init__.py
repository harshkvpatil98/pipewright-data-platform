"""Converting work from another tool into recipes, checks and workflows (E2, X3).

One converter per format, each reading the format as its maker publishes it
and saying, part by part, what it became or why it did not; nothing is
converted approximately. ``model.py`` is what a conversion is, ``sql.py``
turns SQL into recipes for the formats that hold SQL, ``apply.py`` makes the
result through each service's ordinary create function, and ``router.py``
serves both: a preview that changes nothing, and the import.

The fixtures the tests read are written here from each maker's published
format, not taken from their examples; the help says so.
"""

from __future__ import annotations

import posixpath
import re
from dataclasses import dataclass
from typing import Callable

from api_gateway.conversions.model import Conversion, NotConverted


@dataclass(frozen=True)
class Format:
    key: str
    #: What it is, in words: "a dbt project".
    title: str
    #: What to upload.
    upload: str
    extensions: tuple[str, ...]
    #: (files by path, lookup) -> the conversion.
    convert: Callable[..., Conversion]


def _formats() -> dict[str, Format]:
    from api_gateway.conversions.airflow import convert_airflow
    from api_gateway.conversions.alteryx import convert_alteryx
    from api_gateway.conversions.dbt import convert_dbt
    from api_gateway.conversions.informatica import convert_informatica
    from api_gateway.conversions.power_query import convert_power_query
    from api_gateway.conversions.ssis import convert_ssis
    from api_gateway.conversions.talend import convert_talend

    found = [
        Format("dbt", "a dbt project", "A .zip of the project's folder, with its dbt_project.yml.", (".zip",),
               convert_dbt),
        Format("airflow", "an Airflow workflow", "The workflow's .py file.", (".py",), convert_airflow),
        Format("alteryx", "an Alteryx workflow", "The workflow's .yxmd file.", (".yxmd",), convert_alteryx),
        Format("informatica", "an Informatica PowerCenter mapping", "The mapping's XML export.", (".xml",),
               convert_informatica),
        Format("ssis", "an SSIS package", "The package's .dtsx file.", (".dtsx",), convert_ssis),
        Format("talend", "a Talend job", "The job's .item file (in its process folder).", (".item",), convert_talend),
        Format("power_query", "a Power Query", "The query's M, as a .pq or .m file (or .txt).", (".pq", ".m", ".txt"),
               convert_power_query),
    ]
    return {item.key: item for item in found}


def formats() -> dict[str, Format]:
    return _formats()


def read_upload(file_name: str, data: bytes, wanted: str | None = None) -> tuple[Format, dict[str, bytes]]:
    """Which format an upload is, and its files by path."""
    from api_gateway.conversions.dbt import is_dbt_project, read_zip

    known = formats()
    if wanted:
        if wanted not in known:
            raise NotConverted(f"{wanted} is not a format this converts. It converts "
                               f"{', '.join(item.title for item in known.values())}.")
        chosen = known[wanted]
    else:
        chosen = detect(file_name, data, known)
    if file_name.lower().endswith(".zip"):
        files = read_zip(data)
        if chosen.key == "dbt" and not is_dbt_project(files):
            raise NotConverted("The .zip has no dbt_project.yml, so it is not a dbt project.")
        return chosen, files
    return chosen, {posixpath.basename(file_name.replace("\\", "/")) or "upload": data}


def detect(file_name: str, data: bytes, known: dict[str, Format]) -> Format:
    lowered = file_name.lower()
    head = data[:4096].decode("utf-8", errors="replace")
    for item in known.values():
        if item.key == "dbt" and lowered.endswith(".zip"):
            return item
        if any(lowered.endswith(extension) for extension in item.extensions) and _looks_like(item.key, head):
            return item
    raise NotConverted(f"This file is not one this converts. It converts "
                       f"{', '.join(f'{item.title} ({item.upload})' for item in known.values())}")


def _looks_like(key: str, head: str) -> bool:
    """Whether the start of a file is the format its extension claims."""
    if key == "airflow":
        return "airflow" in head or "DAG(" in head or "@dag" in head
    if key == "talend":
        return "ProcessType" in head
    if key == "ssis":
        return "SqlServer/Dts" in head
    if key == "informatica":
        return "POWERMART" in head
    if key == "power_query":
        return bool(re.search(r"\blet\b", head)) or head.lstrip("\ufeff ").startswith("section")
    return True
