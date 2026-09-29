#!/usr/bin/env python3
"""Make a zed-gpui tree self-contained for downstream consumption.

Downstream projects consume this repository as a git submodule and reference its
crates through path dependencies. Cargo resolves workspace inheritance
(`dep.workspace = true`, `edition.workspace = true`, `lints.workspace = true`)
against the workspace root of the *build*, and that lookup walks up through path
dependencies into the consumer's own workspace. A crate that inherits therefore
cannot be pulled in from a submodule unless the consumer reconstructs this
repository's workspace table themselves.

This script removes that requirement: it copies the tree faithfully and then
rewrites every inheritable entry into its expanded form so each published crate
resolves on its own. The `gpui` branch keeps the original text, so merges with
upstream stay small; only the generated `lean` snapshot carries the expansion.

Usage:
    scripts/expand-workspace.py <source-dir> <target-dir>

`source-dir` is a checkout of the trimmed tree (normally the `gpui` branch
worktree) and `target-dir` receives the expanded copy.
"""
from __future__ import annotations

import os
import re
import shutil
import sys
import tomllib
from pathlib import Path

# Directories holding published packages, relative to the repository root.
PUBLISHED_ROOTS = ("crates", "tooling")

# Table names whose final segment is a dependency name.
DEPENDENCY_TABLES = ("dependencies", "dev-dependencies", "build-dependencies")

# Directories never carried into the published tree: build output and VCS
# metadata. Everything else is copied verbatim, so the snapshot stays a
# faithful representation of the source branch.
COPY_IGNORE = ("target", "cargo-target", ".git", ".direnv", "node_modules")

# Files the source branch carries that the snapshot should not: the lock file
# pins resolution for the *unexpanded* manifests, so it no longer describes the
# published tree. Consumers resolve their own lock against their build.
#
# Kept as an explicit list rather than a broad filter so that new files
# appearing upstream remain visible in code review instead of silently
# vanishing from the snapshot.
COPY_DROP_FILES = ("Cargo.lock",)

# The published root manifest. Standalone crates need only a member list to keep
# the repository buildable on its own; the dependency table is gone because
# every crate now carries full definitions.
ROOT_MANIFEST_TEMPLATE = """\
[workspace]
resolver = "2"
members = [
{members}
]
default-members = ["crates/gpui"]

[workspace.package]
publish = false
edition = "2024"
"""


def load_workspace(repo: Path) -> dict:
    """The workspace tables a crate can inherit from."""
    root = tomllib.loads((repo / "Cargo.toml").read_text())
    workspace = root["workspace"]
    return {
        "package": workspace.get("package", {}),
        "dependencies": workspace.get("dependencies", {}),
        "lints": workspace.get("lints", {}),
        "members": workspace.get("members", []),
    }


def is_package_manifest(path: Path) -> bool:
    try:
        return "package" in tomllib.loads(path.read_text())
    except (tomllib.TOMLDecodeError, OSError):
        return False


def package_manifests(repo: Path) -> list[Path]:
    found: list[Path] = []
    for top in PUBLISHED_ROOTS:
        base = repo / top
        if not base.is_dir():
            continue
        found.extend(p for p in sorted(base.rglob("Cargo.toml")) if is_package_manifest(p))
    return found


def render(value) -> str:
    """Render a value as inline TOML."""
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, str):
        return f'"{value}"'
    if isinstance(value, (int, float)):
        return str(value)
    if isinstance(value, list):
        return "[" + ", ".join(render(v) for v in value) + "]"
    if isinstance(value, dict):
        return "{ " + ", ".join(f"{k} = {render(v)}" for k, v in value.items()) + " }"
    raise TypeError(f"unsupported TOML value: {value!r}")


def merge_spec(base, extra: dict) -> dict:
    """Combine a workspace dependency spec with local overrides.

    A crate may write `{ workspace = true, optional = true }` or add features.
    Optional flags and features accumulate; every other key comes from the
    workspace entry unless the crate overrides it explicitly.
    """
    if isinstance(base, str):
        merged: dict = {"version": base}
    else:
        merged = {k: v for k, v in base.items() if k != "workspace"}

    for key, value in extra.items():
        if key == "workspace":
            continue
        if key == "features":
            existing = list(merged.get("features", []))
            for feature in value:
                if feature not in existing:
                    existing.append(feature)
            merged["features"] = existing
        elif key == "optional":
            merged["optional"] = True
        else:
            merged[key] = value

    return merged


def rebase_path(spec: dict, repo: Path, manifest_dir: Path) -> dict:
    """Rewrite a repository-relative `path` so it resolves from `manifest_dir`.

    The workspace table stores paths relative to the repository root, which only
    works for a crate sitting at that root. Published crates live one or more
    levels deep, so the path is recomputed against the crate's own directory.
    """
    if not isinstance(spec, dict) or "path" not in spec:
        return spec

    absolute = (repo / spec["path"]).resolve()
    rebased = os.path.relpath(absolute, manifest_dir.resolve())

    updated = dict(spec)
    updated["path"] = rebased.replace(os.sep, "/")
    return updated


def resolve_spec(base, extra: dict, repo: Path, manifest_dir: Path) -> dict:
    """Merge overrides and rebase any path onto the crate's own directory."""
    return rebase_path(merge_spec(base, extra), repo, manifest_dir)


def expand_package(text: str, ws_package: dict) -> str:
    """Expand `field.workspace = true` inside the `[package]` table."""
    for field, value in ws_package.items():
        pattern = re.compile(rf"^{re.escape(field)}\.workspace = true\s*$", re.MULTILINE)
        text = pattern.sub(f"{field} = {render(value)}", text)
    return text


def expand_lints(text: str, ws_lints: dict) -> str:
    """Expand a flat `[lints] workspace = true` into concrete lint tables.

    The workspace stores lints nested by tool (`[workspace.lints.rust]`) while a
    crate writes them flat (`[lints.rust]`), so the prefix is dropped.
    """
    if not re.search(r"^\[lints\]\s*\nworkspace = true\s*$", text, re.MULTILINE):
        return text

    blocks: list[str] = []
    for tool, entries in ws_lints.items():
        lines = [f"[lints.{tool}]"]
        for name, setting in entries.items():
            lines.append(f"{name} = {render(setting)}")
        blocks.append("\n".join(lines))

    return re.sub(
        r"^\[lints\]\s*\nworkspace = true\s*$",
        "\n\n".join(blocks),
        text,
        flags=re.MULTILINE,
    )


def expand_inline(
    text: str, ws_deps: dict, unresolved: list[str], repo: Path, manifest_dir: Path
) -> str:
    """Expand `name = { workspace = true, ... }` entries."""
    pattern = re.compile(
        r"^(\s*)([A-Za-z0-9_-]+)(\.[A-Za-z0-9_-]+)?\s*=\s*\{([^{}]*workspace\s*=\s*true[^{}]*)\}\s*$",
        re.MULTILINE,
    )

    def replace(match: re.Match) -> str:
        indent, name, subkey, body = (
            match.group(1),
            match.group(2),
            match.group(3),
            match.group(4),
        )
        extra = tomllib.loads(f"x = {{{body}}}")["x"]
        if name not in ws_deps:
            unresolved.append(name)
            return match.group(0)
        merged = resolve_spec(ws_deps[name], extra, repo, manifest_dir)
        target = f"{name}{subkey}" if subkey else name
        return f"{indent}{target} = {render(merged)}"

    return pattern.sub(replace, text)


def expand_bare(
    text: str, ws_deps: dict, unresolved: list[str], repo: Path, manifest_dir: Path
) -> str:
    """Expand the bare `name.workspace = true` form."""
    pattern = re.compile(r"^(\s*)([A-Za-z0-9_-]+)\.workspace = true\s*$", re.MULTILINE)

    def replace(match: re.Match) -> str:
        indent, name = match.group(1), match.group(2)
        if name not in ws_deps:
            unresolved.append(name)
            return match.group(0)
        spec = resolve_spec(ws_deps[name], {}, repo, manifest_dir)
        return f"{indent}{name} = {render(spec)}"

    return pattern.sub(replace, text)


def expand_dotted_tables(
    text: str, ws_deps: dict, unresolved: list[str], repo: Path, manifest_dir: Path
) -> str:
    """Expand dependencies written as a dotted table.

    Cargo accepts both `dep = { workspace = true }` and a table form:

        [target.'cfg(windows)'.dependencies.scap]
        workspace = true
        optional = true

    The table carries overrides as sibling keys, so the workspace spec is merged
    with whatever else the body declares. The replacement is written inline
    under the enclosing table, emitted only when the manifest does not already
    declare it: repeating a header is a TOML error.
    """
    lines = text.splitlines(keepends=True)
    known_headers = {line.strip() for line in lines if line.startswith("[")}

    out: list[str] = []
    index = 0

    while index < len(lines):
        line = lines[index]
        header = re.match(r"^\[([^\]]*)\]\s*$", line)

        name = None
        if header:
            parts = split_dotted_key(header.group(1))
            if len(parts) >= 2 and parts[-2] in DEPENDENCY_TABLES:
                name = parts[-1]

        if name is None:
            out.append(line)
            index += 1
            continue

        body: list[str] = []
        cursor = index + 1
        while cursor < len(lines) and not lines[cursor].startswith("["):
            body.append(lines[cursor])
            cursor += 1

        if not any(re.match(r"^workspace\s*=\s*true\s*$", b) for b in body):
            out.append(line)
            index += 1
            continue

        if name not in ws_deps:
            unresolved.append(name)
            out.append(line)
            index += 1
            continue

        overrides: dict = {}
        for entry in body:
            parsed = re.match(r"^([A-Za-z0-9_-]+)\s*=\s*(.+?)\s*$", entry)
            if parsed and parsed.group(1) != "workspace":
                overrides[parsed.group(1)] = tomllib.loads(f"x = {parsed.group(2)}")["x"]

        merged = resolve_spec(ws_deps[name], overrides, repo, manifest_dir)

        parent = ".".join(split_dotted_key(header.group(1))[:-1])
        parent_header = f"[{parent}]"
        if parent and parent_header not in known_headers:
            out.append(f"{parent_header}\n")
            known_headers.add(parent_header)
        out.append(f"{name} = {render(merged)}\n")
        index = cursor

    return "".join(out)


def split_dotted_key(key: str) -> list[str]:
    """Split a TOML dotted key while respecting quoted segments."""
    parts: list[str] = []
    current = ""
    quote: str | None = None
    for char in key:
        if quote:
            current += char
            if char == quote:
                quote = None
            continue
        if char in "'\"":
            quote = char
            current += char
            continue
        if char == ".":
            parts.append(current.strip())
            current = ""
            continue
        current += char
    parts.append(current.strip())
    return parts


def rewrite_manifest(path: Path, workspace: dict, repo: Path) -> list[str]:
    """Rewrite one manifest in place; returns unresolved dependency names."""
    text = path.read_text()
    unresolved: list[str] = []
    manifest_dir = path.parent

    text = expand_package(text, workspace["package"])
    text = expand_lints(text, workspace["lints"])
    text = expand_inline(text, workspace["dependencies"], unresolved, repo, manifest_dir)
    text = expand_bare(text, workspace["dependencies"], unresolved, repo, manifest_dir)
    text = expand_dotted_tables(text, workspace["dependencies"], unresolved, repo, manifest_dir)

    path.write_text(text)
    return unresolved


def copy_tree(source: Path, target: Path) -> None:
    """Copy the source tree into `target`, preserving symlinks and layout.

    The snapshot is a faithful copy of the branch minus build output and VCS
    metadata; the only textual change applied afterwards is the workspace
    expansion. Keeping the copy faithful means `docs/` and `scripts/` still
    describe the snapshot, and any new top-level file shows up in review.
    """
    if target.exists():
        shutil.rmtree(target)
    target.mkdir(parents=True)

    ignore = shutil.ignore_patterns(*COPY_IGNORE)
    drop = {source / name for name in COPY_DROP_FILES}

    for entry in sorted(source.iterdir()):
        if entry.name == ".git" or entry.name in COPY_IGNORE:
            continue
        if entry in drop:
            continue
        dst = target / entry.name
        if entry.is_symlink():
            os.symlink(os.readlink(entry), dst)
        elif entry.is_dir():
            shutil.copytree(entry, dst, ignore=ignore, symlinks=True)
        else:
            shutil.copy2(entry, dst)


def write_root_manifest(target: Path, members: list[str]) -> None:
    """Write the member-only workspace root for the published tree."""
    body = "\n".join(f'    "{m}",' for m in members)
    (target / "Cargo.toml").write_text(ROOT_MANIFEST_TEMPLATE.format(members=body))


def main(argv: list[str]) -> int:
    if len(argv) != 3:
        print(__doc__.strip(), file=sys.stderr)
        return 2

    source, target = Path(argv[1]).resolve(), Path(argv[2]).resolve()
    if not (source / "Cargo.toml").is_file():
        print(f"error: {source} has no Cargo.toml", file=sys.stderr)
        return 1

    workspace = load_workspace(source)
    copy_tree(source, target)

    problems: list[tuple[str, str]] = []
    count = 0
    for manifest in package_manifests(target):
        for name in rewrite_manifest(manifest, workspace, target):
            problems.append((str(manifest.relative_to(target)), name))
        count += 1

    write_root_manifest(target, workspace["members"])

    print(f"expanded {count} manifests into {target}")
    if problems:
        print(f"\n{len(problems)} unresolved entries:", file=sys.stderr)
        for path, name in problems:
            print(f"  {path}: {name}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
