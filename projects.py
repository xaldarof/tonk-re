"""Multi-APK project container model.

A project used to map 1:1 to a single decompiled APK: `WORKSPACE/<name>/` held that
APK's `jadx/`, `apktool/` and `meta.json` directly. To analyse several related APKs
together (a base + its splits, or successive versions) under one shared context, a
project can instead be a *container* of **members**, each member keeping its own
decompiled tree and metadata.

Layout (backward compatible):

    WORKSPACE/<name>/            # container root == the PRIMARY member's decompiled tree
      jadx/  apktool/  meta.json #   (unchanged single-APK layout)
      project.json               # present only once a 2nd APK is attached
      attached/<member>/         # each extra member: its own jadx/ apktool/ meta.json
        jadx/  apktool/  meta.json

Because the primary member stays at the container root (`dir == "."`), a legacy
single-APK project *is* a one-member container with no `project.json`, and every tool
that resolves the project root keeps pointing at the primary member unchanged.

This is a pure leaf module (stdlib only, no server/gui import — same rule as
native.py / patches.py / report.py / apis.py): it owns only the `project.json`
document shape and manipulation. All filesystem work — resolving member directories,
running scanners per member, writing the file — stays in the facade (server.py), which
passes data in and takes documents back out. That keeps member resolution next to the
other path/safety helpers and this module trivially unit-testable.
"""
from __future__ import annotations

import json
import re

MANIFEST = "project.json"  # container descriptor, at the project root
ATTACHED = "attached"      # subdir holding non-primary members
VERSION = 1


def new_doc(primary: str) -> dict:
    """An empty container whose primary member is `primary` (add it with add_member)."""
    return {"version": VERSION, "primary": primary, "members": []}


def member_dirname(name: str) -> str:
    """Container-relative directory for a (non-primary) member, named after the member.

    Sanitised to the same safe charset decompile() uses for project names, so it can be
    joined under the container with the facade's `_safe_join`."""
    safe = re.sub(r"[^A-Za-z0-9_.-]", "_", name).strip("._") or "member"
    return f"{ATTACHED}/{safe}"


def add_member(doc: dict, name: str, dirpath: str, apk: str | None,
               sha256: str | None, label: str | None = None) -> dict:
    """Register a member (idempotent on `name`). Returns the same doc for chaining."""
    doc.setdefault("members", [])
    if not any(m["name"] == name for m in doc["members"]):
        doc["members"].append({
            "name": name, "dir": dirpath, "apk": apk, "sha256": sha256,
            "label": label or name,
        })
    return doc


def load(text: str) -> dict:
    """Parse + normalise a project.json document (fills defaults, validates shape)."""
    doc = json.loads(text)
    if not isinstance(doc, dict) or "members" not in doc:
        raise ValueError("invalid project.json: missing 'members'")
    doc.setdefault("version", VERSION)
    for m in doc["members"]:
        m.setdefault("label", m.get("name"))
        m.setdefault("dir", ".")
    if not doc.get("primary") and doc["members"]:
        doc["primary"] = doc["members"][0]["name"]
    return doc


def dumps(doc: dict) -> str:
    return json.dumps(doc, indent=2)


def is_primary(doc: dict, name: str) -> bool:
    return doc.get("primary") == name
