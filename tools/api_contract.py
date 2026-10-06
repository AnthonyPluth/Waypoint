from __future__ import annotations

import argparse
import ast
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import feature_map

ROOT = feature_map.ROOT
CONTRACT = ROOT / "waypoint/server/contract.py"
OPENAPI_OUT = ROOT / "docs/openapi.json"
TS_OUT = ROOT / "frontend/src/lib/api-types.ts"

SCALARS = {"str": {"type": "string"}, "int": {"type": "integer"}, "float": {"type": "number"},
           "bool": {"type": "boolean"}, "None": {"type": "null"}, "Any": {}}
ERROR = {"description": "Refused (4xx) or failed (5xx): what went wrong, to show as it is.",
         "content": {"application/json": {"schema": {
             "type": "object", "properties": {"error": {"type": "string"}}, "required": ["error"]}}}}
CSRF = {"name": "X-Waypoint", "in": "header", "required": True, "schema": {"const": "1"},
        "description": "Sent with every request that isn't a GET; Waypoint refuses one without it (CSRF)."}


class ContractError(Exception):
    pass


def typeddicts() -> dict[str, dict]:
    out: dict[str, dict] = {}
    for node in ast.parse(CONTRACT.read_text()).body:
        if not isinstance(node, ast.ClassDef):
            continue
        fields: list[tuple[str, ast.expr, bool]] = []
        for base in node.bases:
            name = getattr(base, "id", None)
            if name == "TypedDict":
                continue
            if name not in out:
                raise ContractError(f"contract.py: {node.name}'s base {ast.unparse(base)} isn't a TypedDict defined above it")
            fields += out[name]["fields"]
        total = all(not (k.arg == "total" and isinstance(k.value, ast.Constant) and k.value.value is False)
                    for k in node.keywords)
        for stmt in node.body:
            if isinstance(stmt, ast.AnnAssign) and isinstance(stmt.target, ast.Name):
                ann, required = stmt.annotation, total
                if isinstance(ann, ast.Subscript) and getattr(ann.value, "id", None) in ("NotRequired", "Required"):
                    required = ann.value.id == "Required"   # type: ignore[attr-defined]
                    ann = ann.slice
                fields = [f for f in fields if f[0] != stmt.target.id] + [(stmt.target.id, ann, required)]
        out[node.name] = {"doc": ast.get_docstring(node), "fields": fields}
    return out


def schema(ann: ast.expr, types: dict[str, dict], used: set[str], where: str) -> dict:
    if isinstance(ann, ast.Constant) and isinstance(ann.value, str):
        return schema(ast.parse(ann.value, mode="eval").body, types, used, where)
    if isinstance(ann, ast.Constant) and ann.value is None:
        return {"type": "null"}
    if isinstance(ann, ast.Name):
        if ann.id in SCALARS:
            return dict(SCALARS[ann.id])
        if ann.id in types:
            used.add(ann.id)
            return {"$ref": f"#/components/schemas/{ann.id}"}
    if isinstance(ann, ast.BinOp) and isinstance(ann.op, ast.BitOr):
        return union([schema(ann.left, types, used, where), schema(ann.right, types, used, where)])
    if isinstance(ann, ast.Subscript) and isinstance(ann.value, ast.Name):
        args = list(ann.slice.elts) if isinstance(ann.slice, ast.Tuple) else [ann.slice]
        if ann.value.id == "list" and len(args) == 1:
            return {"type": "array", "items": schema(args[0], types, used, where)}
        if ann.value.id == "dict" and len(args) == 2 and getattr(args[0], "id", None) == "str":
            return {"type": "object", "additionalProperties": schema(args[1], types, used, where)}
        if ann.value.id == "Literal" and all(isinstance(a, ast.Constant) for a in args):
            values = [a.value for a in args]   # type: ignore[attr-defined]
            return {"const": values[0]} if len(values) == 1 else {"enum": values}
    raise ContractError(f"{where}: can't describe the type {ast.unparse(ann)} (see waypoint/server/contract.py)")


def union(members: list[dict]) -> dict:
    flat: list[dict] = []
    for m in members:
        flat += m["anyOf"] if set(m) == {"anyOf"} else [m]
    if all(set(m) == {"type"} for m in flat):
        kinds = [k for m in flat for k in (m["type"] if isinstance(m["type"], list) else [m["type"]])]
        return {"type": list(dict.fromkeys(kinds))}
    if all(set(m) <= {"enum", "const"} or m == {"type": "null"} for m in flat):
        values = [v for m in flat for v in (m["enum"] if "enum" in m else [m.get("const")])]
        return {"enum": list(dict.fromkeys(values))}
    return {"anyOf": flat}


def object_schema(name: str, types: dict[str, dict], used: set[str]) -> dict:
    td = types[name]
    out: dict = {"type": "object"}
    if td["doc"]:
        out["description"] = td["doc"]
    out["properties"] = {f: schema(ann, types, used, f"{name}.{f}") for f, ann, _ in td["fields"]}
    out["required"] = [f for f, _, required in td["fields"] if required]
    out["additionalProperties"] = False
    return out


def handler_annotations(route: dict, trees: dict[str, ast.Module]) -> tuple[ast.expr | None, ast.expr | None]:
    tree = trees.setdefault(route["file"], ast.parse((ROOT / route["file"]).read_text()))
    for node in tree.body:
        if isinstance(node, ast.FunctionDef) and node.name == route["handler"]:
            params = node.args.posonlyargs + node.args.args
            return (params[2].annotation if len(params) > 2 else None), node.returns
    raise ContractError(f"{route['file']}: no function {route['handler']} (named in ROUTES)")


def names(ann: ast.expr | None) -> set[str]:
    if ann is None:
        return set()
    if isinstance(ann, ast.Constant) and isinstance(ann.value, str):
        return names(ast.parse(ann.value, mode="eval").body)
    return {n.id for n in ast.walk(ann) if isinstance(n, ast.Name)}


def openapi_path(path: str) -> tuple[str, list[str]]:
    names: list[str] = []
    parts = []
    for seg in path.split("/"):
        if seg == "{id}":
            names.append("id" if not names else f"id{len(names) + 1}")
            seg = "{" + names[-1] + "}"
        parts.append(seg)
    return "/".join(parts), names


def build() -> dict:
    types = typeddicts()
    used: set[str] = set()
    paths: dict[str, dict] = {}
    trees: dict[str, ast.Module] = {}
    for r in feature_map.routes():
        body, reply = handler_annotations(r, trees)
        body = body if names(body) & set(types) else None
        if not names(reply) & set(types):
            if body is not None:
                raise ContractError(f"{r['handler']}: its body is typed but not its reply; type both, or neither")
            continue
        where = f"{r['file']}:{r['handler']}"
        address, ids = openapi_path(r["path"])
        op: dict = {"operationId": r["handler"], "x-handler": where}
        params = [{"name": n, "in": "path", "required": True, "schema": {"type": "string"}} for n in ids]
        if r["method"] != "GET":
            params.append(CSRF)
        if params:
            op["parameters"] = params
        if body is not None:
            op["requestBody"] = {"required": True, "content": {"application/json": {"schema": schema(body, types, used, where)}}}
        op["responses"] = {"200": {"description": "OK", "content": {"application/json": {"schema": schema(reply, types, used, where)}}},
                           "default": {"$ref": "#/components/responses/Error"}}
        paths.setdefault(address, {})[r["method"].lower()] = op
    done: dict[str, dict] = {}
    while missing := sorted(used - set(done)):
        for name in missing:
            done[name] = object_schema(name, types, used)
    return {
        "openapi": "3.1.0",
        "info": {"title": "Waypoint", "version": "0",
                 "description": "The routes of Waypoint's API that the contract covers (waypoint/server/contract.py). "
                                "Generated by tools/api_contract.py (`make api-contract`); don't edit by hand."},
        "paths": paths,
        "components": {"schemas": dict(sorted(done.items())), "responses": {"Error": ERROR}},
    }


def ts_type(s: dict) -> str:
    if "$ref" in s:
        return s["$ref"].rsplit("/", 1)[1]
    if "enum" in s or "const" in s:
        return " | ".join(json.dumps(v, ensure_ascii=False) for v in (s["enum"] if "enum" in s else [s["const"]]))
    if "anyOf" in s:
        return " | ".join(ts_type(m) for m in s["anyOf"])
    kinds = s.get("type")
    if isinstance(kinds, list):
        return " | ".join(dict.fromkeys(ts_type({**s, "type": k}) for k in kinds))
    if kinds == "array":
        item = ts_type(s["items"])
        return f"({item})[]" if " | " in item else f"{item}[]"
    if kinds == "object":
        if "properties" in s:
            return "{ " + "; ".join(field(k, v, k in s.get("required", [])) for k, v in s["properties"].items()) + " }"
        return f"Record<string, {ts_type(s.get('additionalProperties', {}))}>"
    return {"string": "string", "integer": "number", "number": "number", "boolean": "boolean", "null": "null"}.get(kinds or "", "unknown")


def field(name: str, s: dict, required: bool) -> str:
    return f"{name}{'' if required else '?'}: {ts_type(s)}"


def render_ts(doc: dict) -> str:
    out: list[str] = []
    for name, s in doc["components"]["schemas"].items():
        out.append(f"export interface {name} {{")
        out += [f"  {field(k, v, k in s['required'])};" for k, v in s["properties"].items()]
        out += ["}", ""]
    out.append("export interface Endpoints {")
    for address, ops in doc["paths"].items():
        for method, op in ops.items():
            path = "/".join("{id}" if seg.startswith("{") else seg for seg in address.split("/"))
            body = op.get("requestBody", {}).get("content", {}).get("application/json", {}).get("schema")
            reply = op["responses"]["200"]["content"]["application/json"]["schema"]
            out.append(f"  \"{method.upper()} {path}\": {{ body: {ts_type(body) if body else 'never'}; reply: {ts_type(reply)} }};")
    out.append("}")
    return "\n".join(out) + "\n"


def render_json(doc: dict) -> str:
    return json.dumps(doc, indent=2, ensure_ascii=False) + "\n"


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--check", action="store_true", help="write nothing; fail if the generated files are out of date")
    args = ap.parse_args()
    try:
        doc = build()
    except ContractError as e:
        print(f"tools/api_contract.py: {e}", file=sys.stderr)
        return 1
    want = {OPENAPI_OUT: render_json(doc), TS_OUT: render_ts(doc)}
    if not args.check:
        for f, text in want.items():
            f.write_text(text)
        return 0
    stale = [f for f, text in want.items() if not f.exists() or f.read_text() != text]
    for f in stale:
        print(f"{f.relative_to(ROOT)} is out of date: run `make api-contract`", file=sys.stderr)
    return 1 if stale else 0


if __name__ == "__main__":
    sys.exit(main())
