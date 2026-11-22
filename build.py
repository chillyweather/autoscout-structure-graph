#!/usr/bin/env python3
"""Build docs/index.html from structure.json and an AutoScout checkout.

The stage order, the counts and the named constants come from the AutoScout
code at one Git ref. The wording comes from structure.json. The build fails
when the two disagree, so a page that builds describes the code it names.

Usage: ./build.py [--repo ../auto-scout] [--ref origin/main]
"""

from __future__ import annotations

import argparse
import ast
import glob
import json
import re
import subprocess
import sys
import tarfile
import tempfile
from pathlib import Path
from typing import Any

HERE = Path(__file__).resolve().parent
# Only these paths are read from the AutoScout ref.
PATHS = ["autoscout", "configs", "scripts", "deploy", "tests", "docs/agents", ".claude/skills", "AGENTS.md"]
WORKFLOW = "autoscout/weekly_workflow.py"
KINDS = {"code", "model", "agent"}
# The file names on the page open here. The repository is private: a visitor without access gets GitHub's 404.
REPO_URL = "https://github.com/chillyweather/auto-scout"


def git(repo: Path, *args: str) -> str:
    return subprocess.run(["git", "-C", str(repo), *args], check=True, capture_output=True, text=True).stdout.strip()


def export_ref(repo: Path, ref: str, target: Path) -> None:
    archive = subprocess.run(["git", "-C", str(repo), "archive", ref, *PATHS], check=True, capture_output=True).stdout
    tar_path = target / "ref.tar"
    tar_path.write_bytes(archive)
    with tarfile.open(tar_path) as tar:
        tar.extractall(target, filter="data")
    tar_path.unlink()


def stage_order(tree: Path) -> list[str]:
    """The method names in the tuple WeeklyWorkflow._stages() builds, in order."""
    module = ast.parse((tree / WORKFLOW).read_text())
    for node in ast.walk(module):
        if isinstance(node, ast.FunctionDef) and node.name == "_stages":
            for inner in ast.walk(node):
                if (
                    isinstance(inner, ast.Assign)
                    and isinstance(inner.targets[0], ast.Name)
                    and inner.targets[0].id == "stages"
                    and isinstance(inner.value, ast.Tuple)
                ):
                    return [element.attr for element in inner.value.elts if isinstance(element, ast.Attribute)]
    raise SystemExit(f"cannot find the stages tuple in {WORKFLOW}")


def constant(tree: Path, file: str, name: str) -> Any:
    for node in ast.parse((tree / file).read_text()).body:
        if isinstance(node, ast.Assign) and any(isinstance(t, ast.Name) and t.id == name for t in node.targets):
            return ast.literal_eval(node.value)
    raise KeyError(f"{file}: no constant {name}")


def resolve_fact(tree: Path, spec: dict[str, Any]) -> Any:
    if "json" in spec:
        value: Any = json.loads((tree / spec["file"]).read_text())
        for key in spec["json"].split("."):
            value = value[key]
        return value
    value = constant(tree, spec["file"], spec["const"])
    if spec.get("labels"):
        return [entry[0] for entry in value]
    if isinstance(value, float) and value.is_integer():
        return int(value)
    return value


def check_ref(tree: Path, ref: str) -> str | None:
    """A file reference is `path`, `path::symbol`, or a glob. Returns a problem or None."""
    path, _, symbol = ref.partition("::")
    if any(char in path for char in "*?"):
        return None if glob.glob(str(tree / path)) else f"no file matches {path}"
    target = tree / path
    if not target.exists():
        return f"missing file {path}"
    if symbol and not re.search(rf"^\s*(def|class)\s+{re.escape(symbol)}\b", target.read_text(), re.M):
        return f"{path} has no def or class {symbol}"
    return None


def link_for(tree: Path, ref: str) -> str:
    """Where a file reference opens in the AutoScout repository: the file (at the
    symbol's line), the folder, or for a glob the folder that holds the matches."""
    path, _, symbol = ref.partition("::")
    if any(char in path for char in "*?"):
        return f"{REPO_URL}/tree/main/{Path(path).parent.as_posix()}"
    target = tree / path
    if target.is_dir():
        return f"{REPO_URL}/tree/main/{path}"
    url = f"{REPO_URL}/blob/main/{path}"
    if symbol:
        for number, line in enumerate(target.read_text().splitlines(), 1):
            if re.match(rf"\s*(def|class)\s+{re.escape(symbol)}\b", line):
                return f"{url}#L{number}"
    return url


def substitute(value: Any, facts: dict[str, Any]) -> Any:
    if isinstance(value, str):
        return re.sub(r"\{\{(\w+)\}\}", lambda m: str(facts[m.group(1)]), value)
    if isinstance(value, list):
        return [substitute(item, facts) for item in value]
    if isinstance(value, dict):
        return {key: substitute(item, facts) for key, item in value.items()}
    return value


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("--repo", type=Path, default=HERE.parent / "auto-scout")
    parser.add_argument("--ref", default="origin/main")
    args = parser.parse_args()

    manifest = json.loads((HERE / "structure.json").read_text())
    problems: list[str] = []

    with tempfile.TemporaryDirectory() as tmp:
        tree = Path(tmp)
        export_ref(args.repo, args.ref, tree)

        # Stages: the code gives the order, the manifest gives the words.
        order = stage_order(tree)
        described = manifest["stages"]
        phase_of = {stage: phase["title"] for phase in manifest["phases"] for stage in phase["stages"]}
        for stage in order:
            if stage not in described:
                problems.append(f"stage {stage} is in the code and has no entry in structure.json")
            elif stage not in phase_of:
                problems.append(f"stage {stage} belongs to no phase in structure.json")
        for stage in described:
            if stage not in order:
                problems.append(f"stage {stage} is in structure.json and no longer in the code")

        facts: dict[str, Any] = {}
        for name, spec in manifest["facts"].items():
            try:
                facts[name] = resolve_fact(tree, spec)
            except (KeyError, OSError, ValueError, SyntaxError) as exc:
                problems.append(f"fact {name}: {exc}")

        rows = [described[s] for s in order if s in described]
        for section in manifest["sections"]:
            rows += section["rows"]
        for row in rows:
            if row["kind"] not in KINDS:
                problems.append(f"{row['name']}: unknown kind {row['kind']}")
            for ref in row.get("files", []):
                problem = check_ref(tree, ref)
                if problem:
                    problems.append(f"{row['name']}: {problem}")

        links = {ref: link_for(tree, ref) for row in rows for ref in row.get("files", []) if not check_ref(tree, ref)}

        if problems:
            print("structure.json disagrees with the code:", file=sys.stderr)
            for problem in problems:
                print(f"  - {problem}", file=sys.stderr)
            return 1

        phases: list[dict[str, Any]] = []
        for stage in order:
            title = phase_of[stage]
            if not phases or phases[-1]["title"] != title:
                if any(phase["title"] == title for phase in phases):
                    print(f"phase {title} is not contiguous in the code order (at {stage})", file=sys.stderr)
                    return 1
                phases.append({"title": title, "stages": []})
            phases[-1]["stages"].append({"id": stage, **described[stage]})

        modules = sorted((tree / "autoscout").rglob("*.py"))
        stats = {
            "stages": len(order),
            "model_stages": sum(1 for s in order if described[s]["kind"] == "model"),
            "modules": len(modules),
            "lines": sum(len(m.read_text().splitlines()) for m in modules),
            "test_files": len(list((tree / "tests").glob("test_*.py"))),
            "launchers": sum(1 for p in (tree / "scripts").iterdir() if p.is_file()),
        }

    data = substitute(
        {
            "meta": {
                "commit": git(args.repo, "rev-parse", "--short", args.ref),
                "commit_date": git(args.repo, "log", "-1", "--format=%cs", args.ref),
                "stats": stats,
            },
            "facts": facts,
            "phases": phases,
            "sections": manifest["sections"],
            "questions": manifest["questions"],
        },
        facts,
    )
    data["links"] = links
    for question in data["questions"]:
        question["options"] = facts[question.pop("options_fact")]

    template = substitute((HERE / "template.html").read_text(), facts)
    payload = json.dumps(data, ensure_ascii=False).replace("</", "<\\/")
    out = HERE / "docs" / "index.html"
    out.parent.mkdir(exist_ok=True)
    out.write_text(template.replace("/*DATA*/null", payload))
    print(f"built {out.relative_to(HERE)} from {args.ref} @ {data['meta']['commit']}: "
          f"{stats['stages']} stages, {stats['model_stages']} with a model call")
    return 0


if __name__ == "__main__":
    sys.exit(main())
