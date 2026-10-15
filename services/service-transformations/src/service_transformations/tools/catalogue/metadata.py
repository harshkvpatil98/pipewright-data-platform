"""Metadata steps: what a recipe says about the dataset it makes (E1).

A metadata step changes no row. It records, in the recipe, a description,
tags, a classification or a personal-data marking for a column, a glossary
term, the dataset's owner or its description; when a run stores the recipe's
output, those are written to the dataset's catalogue entry, so the recipe is
where its output is documented and the documentation follows every run. A
person can still edit the entry; the next run writes the recipe's again.

The run applies them through `register_output_annotator`, which the
catalogue registers, so this package never imports it.
"""

from __future__ import annotations

from typing import Any, Callable


from shared_python.errors import BadRequestError

from service_transformations.ir.nodes import Node
from service_transformations.steps.flags import is_enabled, without_flags
from service_transformations.tools import register
from service_transformations.tools.builders import require_column
from service_transformations.tools.local import extension, handles
from service_transformations.tools.spec import Example, Param, ParamKind, ToolSpec

CATEGORY = "Metadata & documentation"
CLASSIFICATIONS = ("public", "internal", "confidential", "restricted")
PERSONAL = ("email address", "phone number", "name", "postal address", "date of birth", "government id",
            "financial account", "location", "online identifier", "other personal data")

#: Each registered annotator gets (db, project_id, dataset_id, notes, user_id) and returns warnings.
Annotator = Callable[..., list[str]]
_ANNOTATORS: list[Annotator] = []


def register_output_annotator(annotator: Annotator) -> None:
    if annotator not in _ANNOTATORS:
        _ANNOTATORS.append(annotator)


def notes_from(steps: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """What a recipe's metadata steps say, in order, from the steps that are on."""
    found = []
    for step in steps:
        config = step.get("config") or {}
        if step.get("step_type") == "tool" and str(config.get("tool", "")).startswith("meta.") and is_enabled(config):
            found.append(without_flags(config))
    return found


def apply_to_output(db: Any, *, project_id: Any, dataset_id: Any, steps: list[dict[str, Any]],
                    user_id: Any) -> list[str]:
    notes = notes_from(steps)
    if not notes:
        return []
    if not _ANNOTATORS:
        return ["This recipe's metadata steps were not written: the catalogue is not loaded on this server."]
    warnings: list[str] = []
    for annotator in _ANNOTATORS:
        warnings.extend(annotator(db, project_id=project_id, dataset_id=dataset_id, notes=notes, user_id=user_id))
    return warnings


def _declare(name: str, title: str, summary: str, keys: tuple[str, ...], example: Example, *,
             params: tuple[Param, ...], synonyms: tuple[str, ...], column: bool = True) -> ToolSpec:
    def build(node: Node, settings: dict[str, Any]) -> Node:
        if column:
            require_column(node, settings.get("column"))
        for key in keys:
            if key in ("column",):
                continue
            value = settings.get(key)
            if value in (None, "", []):
                raise BadRequestError(f"{title}: give the {key.replace('_', ' ')}.")
        return extension(node, name, {key: settings.get(key) for key in keys}, dict(node.schema()))

    handles(name)(lambda frame, config: frame.copy())
    return register(ToolSpec(
        name=name, title=title, category=CATEGORY, summary=summary, build=build, example=example, params=params,
        synonyms=synonyms, column_scoped=False, local_only=True, null_answer=True, warns_lost=False, row_wise=True,
    ))


_COLUMN = Param("column", "Column", ParamKind.COLUMN)
_ROWS = ({"email": "a@x.com"},)


def _shape(note: str, **params: Any) -> Example:
    return Example(rows=_ROWS, params={"column": "email", **params}, column="email", output="email",
                   expect=("a@x.com",), note=note)


_declare("meta.describe_column", "Describe a column", "Say what a column of the output means; each run writes it "
         "to the dataset's catalogue entry.", ("column", "description"),
         _shape("The rows pass through; the description goes on the output's catalogue entry.",
                description="Where to send receipts"),
         params=(_COLUMN, Param("description", "Description", ParamKind.TEXT)),
         synonyms=("set column description", "document column", "column comment", "describe field"))
_declare("meta.tag_column", "Tag a column", "Give a column of the output tags (finance, gdpr, kpi), written to its "
         "catalogue entry each run.", ("column", "tags"),
         _shape("The rows pass through; the tags go on the column in the catalogue.", tags=["contact"]),
         params=(_COLUMN, Param("tags", "Tags", ParamKind.LIST)),
         synonyms=("set column tags", "label column", "tag field"))
_declare("meta.classify_column", "Classify a column", "Say how sensitive a column of the output is: public, "
         "internal, confidential or restricted.", ("column", "level"),
         _shape("The rows pass through; the classification goes on the column in the catalogue.",
                level="confidential"),
         params=(_COLUMN, Param("level", "Classification", ParamKind.SELECT, default="internal",
                                options=CLASSIFICATIONS)),
         synonyms=("set column classification", "sensitivity", "data classification", "confidential"))
_declare("meta.mark_personal", "Mark personal data", "Say a column of the output holds personal data, and of what "
         "kind, for the catalogue, retention and erasure requests to find; who may see it is set by policies.",
         ("column", "kind"),
         _shape("The rows pass through; the marking goes on the column in the catalogue.", kind="email address"),
         params=(_COLUMN, Param("kind", "Kind", ParamKind.SELECT, default="email address", options=PERSONAL)),
         synonyms=("mark column pii", "pii", "gdpr", "personal data", "sensitive personal"))
_declare("meta.glossary_term", "Link a column to a glossary term", "Bind a column of the output to a term in the "
         "project's glossary (revenue, active customer), so the term knows where its data is.",
         ("column", "term"), _shape("The rows pass through; the term is bound to the output's column.",
                                     term="Customer email"),
         params=(_COLUMN, Param("term", "Glossary term", ParamKind.TEXT)),
         synonyms=("link to glossary term", "business glossary", "definition", "semantic term"))
_declare("meta.owner", "Set the dataset's owner", "Name the person who answers for the output dataset, by their "
         "username; written to its catalogue entry each run.", ("owner",),
         _shape("The rows pass through; the owner goes on the output's catalogue entry.", owner="ana"),
         params=(Param("owner", "Owner's username", ParamKind.TEXT),),
         synonyms=("set dataset owner", "data owner", "steward", "responsible person"), column=False)
_declare("meta.describe_dataset", "Describe the dataset", "Say what the output dataset is for; written to its "
         "catalogue entry each run.", ("description",),
         _shape("The rows pass through; the description goes on the output's catalogue entry.",
                description="Customers to email"),
         params=(Param("description", "Description", ParamKind.TEXT),),
         synonyms=("dataset description", "document dataset", "readme"), column=False)

