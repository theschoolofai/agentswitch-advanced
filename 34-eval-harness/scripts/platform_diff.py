"""Compare two platform snapshots written by probe_access.py and say what changed.

A snapshot is one folder, data/platform/<system>/ (or its previous/ copy), holding:
  mcp-tools.json     our tool list: name, risk, read-only flag, input and output schemas
  rest-schemas.json  entity schemas: entity name and fields (name, type, required)
  probe.json         which reads were reachable
  version.json       the platform version, if the platform reports one

All functions here are pure: they take loaded data and return plain lists of change lines.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


@dataclass(frozen=True)
class Snapshot:
    """What one probe run saw on one system, reduced to the parts we compare."""

    tools: dict[str, dict[str, Any]] = field(default_factory=dict)
    entities: dict[str, dict[str, tuple[str, bool]]] = field(
        default_factory=dict
    )  # field -> (type, required)
    access: dict[str, bool] = field(default_factory=dict)  # "door:name" -> reachable
    version: str = "unknown"


def _read(path: Path) -> Any:
    return json.loads(path.read_text()) if path.exists() else None


def load_snapshot(folder: Path) -> Snapshot | None:
    """Load a snapshot folder. Returns None if the folder has no tool list (no snapshot there)."""
    tools_raw = _read(folder / "mcp-tools.json")
    if not isinstance(tools_raw, list):
        return None
    tools = {t["name"]: t for t in tools_raw if isinstance(t, dict) and "name" in t}
    schemas_raw = _read(folder / "rest-schemas.json") or {}
    entities: dict[str, dict[str, tuple[str, bool]]] = {}
    for schema in schemas_raw.get("schemas", []) if isinstance(schemas_raw, dict) else []:
        fields = schema.get("fields") or []
        entities[schema["entity"]] = {
            f["name"]: (str(f.get("type")), bool(f.get("required"))) for f in fields if "name" in f
        }
    probe = _read(folder / "probe.json") or {}
    access = {f"{c['door']}:{c['name']}": bool(c["ok"]) for c in probe.get("checks", [])}
    version = (_read(folder / "version.json") or {}).get("version", "unknown")
    return Snapshot(tools=tools, entities=entities, access=access, version=str(version))


def diff_tools(old: dict[str, dict[str, Any]], new: dict[str, dict[str, Any]]) -> list[str]:
    """Tools added or removed, and tools whose labels or schemas changed."""
    lines = [f"tool added: `{n}` (risk {new[n].get('risk')})" for n in sorted(new.keys() - old.keys())]
    lines += [f"tool removed: `{n}`" for n in sorted(old.keys() - new.keys())]
    for name in sorted(old.keys() & new.keys()):
        before, after = old[name], new[name]
        for key, label in (("risk", "risk"), ("read_only", "read-only flag")):
            if before.get(key) != after.get(key):
                lines.append(f"tool `{name}`: {label} {before.get(key)} -> {after.get(key)}")
        for key, label in (("input_schema", "input schema"), ("output_schema", "output schema")):
            if key in before and key in after and before[key] != after[key]:
                lines.append(f"tool `{name}`: {label} changed")
    return lines


def diff_entities(
    old: dict[str, dict[str, tuple[str, bool]]], new: dict[str, dict[str, tuple[str, bool]]]
) -> list[str]:
    """Entities added or removed, and fields added, removed or changed (type or required)."""
    lines = [f"entity added: `{e}`" for e in sorted(new.keys() - old.keys())]
    lines += [f"entity removed: `{e}`" for e in sorted(old.keys() - new.keys())]
    for entity in sorted(old.keys() & new.keys()):
        before, after = old[entity], new[entity]
        lines += [f"`{entity}`: field added `{f}`" for f in sorted(after.keys() - before.keys())]
        lines += [f"`{entity}`: field removed `{f}`" for f in sorted(before.keys() - after.keys())]
        for f in sorted(before.keys() & after.keys()):
            if before[f] != after[f]:
                (t0, r0), (t1, r1) = before[f], after[f]
                lines.append(f"`{entity}.{f}`: type {t0} -> {t1}, required {r0} -> {r1}")
    return lines


def diff_access(old: dict[str, bool], new: dict[str, bool]) -> list[str]:
    """Reads that became reachable or blocked."""
    word = {True: "reachable", False: "blocked"}
    return [
        f"access `{k}`: {word[old[k]]} -> {word[new[k]]}"
        for k in sorted(old.keys() & new.keys())
        if old[k] != new[k]
    ]


def compare_systems(a: Snapshot, b: Snapshot, name_a: str, name_b: str) -> list[str]:
    """Differences between the two systems in one run. They are meant to run the same software."""
    lines = [f"tool only on {name_a}: `{n}`" for n in sorted(a.tools.keys() - b.tools.keys())]
    lines += [f"tool only on {name_b}: `{n}`" for n in sorted(b.tools.keys() - a.tools.keys())]
    lines += [f"entity only on {name_a}: `{e}`" for e in sorted(a.entities.keys() - b.entities.keys())]
    lines += [f"entity only on {name_b}: `{e}`" for e in sorted(b.entities.keys() - a.entities.keys())]
    return lines


def diff_snapshots(old: Snapshot, new: Snapshot) -> list[str]:
    """Every change between two snapshots of the same system."""
    lines = [] if old.version == new.version else [f"version: {old.version} -> {new.version}"]
    return (
        lines
        + diff_tools(old.tools, new.tools)
        + diff_entities(old.entities, new.entities)
        + diff_access(old.access, new.access)
    )
