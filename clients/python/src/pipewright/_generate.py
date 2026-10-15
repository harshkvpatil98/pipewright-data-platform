"""Render `_operations.py` from Pipewright's OpenAPI document (A8, Y3).

One method per public operation (`/api/v1/...`), named after the route's own
function, with path parameters first, query parameters as keywords and the
request body as `body` (or `files` and `data` for an upload). Pure: give it
the document, get the module's source. `scripts/generate-client.py` writes
it; a test fails when the committed file is out of date.
"""

from __future__ import annotations

import keyword
import re
from typing import Any

HEADER = '''"""Every Pipewright API operation as a method. Generated; do not edit.

Made by `scripts/generate-client.py` from the gateway's OpenAPI document.
Each method calls `self._call`, which `pipewright.Client` provides.
"""

# ruff: noqa: E501

from __future__ import annotations

from typing import Any


class Operations:
    def _call(self, method: str, path: str, **kwargs: Any) -> Any:  # pragma: no cover - Client overrides
        raise NotImplementedError
'''

_PY_TYPES = {"string": "str", "integer": "int", "number": "float", "boolean": "bool", "array": "list[Any]", "object": "dict[str, Any]"}


def _method_name(operation_id: str, path: str, method: str) -> str:
    suffix = re.sub(r"\W", "_", path) + "_" + method  # the cleaned path starts with its own "_"
    name = operation_id[: -len(suffix)] if operation_id.endswith(suffix) else operation_id
    return re.sub(r"\W", "_", name).strip("_").lower()


def _param_name(name: str) -> str:
    clean = re.sub(r"\W", "_", name)
    return f"{clean}_" if keyword.iskeyword(clean) else clean


def _type_of(schema: dict[str, Any]) -> str:
    if "anyOf" in schema:
        kinds = [_type_of(option) for option in schema["anyOf"] if option.get("type") != "null"]
        return (kinds[0] if len(kinds) == 1 else "Any") + " | None"
    return _PY_TYPES.get(schema.get("type", ""), "Any")


def _summary(operation: dict[str, Any]) -> str:
    text = (operation.get("description") or operation.get("summary") or "").strip().split("\n\n")[0]
    return " ".join(text.split()).replace('"""', "'")


def render(spec: dict[str, Any]) -> str:
    lines = [HEADER]
    used: set[str] = set()
    for path in sorted(spec.get("paths", {})):
        if not path.startswith("/api/v1/"):
            continue  # internal and monitoring addresses are not for clients
        for method in ("get", "post", "put", "patch", "delete"):
            operation = spec["paths"][path].get(method)
            if not operation:
                continue
            name = _method_name(operation.get("operationId") or f"{method}_{path}", path, method)
            base, counter = name, 2
            while name in used:
                name, counter = f"{base}_{counter}", counter + 1
            used.add(name)

            params = operation.get("parameters") or []
            path_params = [p for p in params if p.get("in") == "path"]
            query_params = [p for p in params if p.get("in") == "query"]
            body = operation.get("requestBody") or {}
            content = body.get("content") or {}
            multipart = "multipart/form-data" in content

            signature = ["self"]
            signature += [f"{_param_name(p['name'])}: str" for p in path_params]
            keywords: list[str] = []
            for p in query_params:
                kind = _type_of(p.get("schema") or {})
                if p.get("required"):
                    keywords.append(f"{_param_name(p['name'])}: {kind}")
                else:
                    keywords.append(f"{_param_name(p['name'])}: {kind if kind.endswith('None') else kind + ' | None'} = None")
            if content and not multipart:
                keywords.append("body: Any" if body.get("required") else "body: Any = None")
            if multipart:
                keywords.append("files: dict[str, Any]")
                keywords.append("data: dict[str, Any] | None = None")
            if keywords:
                signature.append("*")
                signature += keywords

            url = path
            for p in path_params:
                url = url.replace("{" + p["name"] + "}", "{" + _param_name(p["name"]) + "}")
            call = [f'"{method.upper()}"', f'f"{url}"' if path_params else f'"{url}"']
            if query_params:
                pairs = ", ".join(f'"{p["name"]}": {_param_name(p["name"])}' for p in query_params)
                call.append(f"query={{{pairs}}}")
            if content and not multipart:
                call.append("body=body")
            if multipart:
                call.append("files=files")
                call.append("data=data")

            summary = _summary(operation)
            lines.append(f"    def {name}({', '.join(signature)}) -> Any:")
            lines.append(f'        """{summary}' if summary else '        """')
            lines.append("")
            lines.append(f"        {method.upper()} {path}")
            lines.append('        """')
            lines.append(f"        return self._call({', '.join(call)})")
            lines.append("")
    return "\n".join(lines).rstrip() + "\n"


def reference(spec: dict) -> str:
    """The OpenAPI document as committed in docs/api/openapi.json: sorted, so a
    change to the API shows as a readable diff."""
    import json

    return json.dumps(spec, indent=1, sort_keys=True, ensure_ascii=False) + "\n"
