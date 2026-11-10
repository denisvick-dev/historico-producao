"""Executa as mesmas verificações usadas no CI, individualmente ou em conjunto."""

from __future__ import annotations

import argparse
import py_compile
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def run_command(*args: str) -> None:
    print("+", " ".join(args), flush=True)
    subprocess.run([sys.executable, "-m", *args], cwd=ROOT, check=True)


def lint() -> None:
    # E402 é intencional: structlog é configurado antes dos módulos do app.
    run_command("ruff", "check", ".", "--select", "E4,E7,E9,F", "--ignore", "E402")
    run_command("ruff", "format", "--check", ".")


def types() -> None:
    run_command(
        "mypy",
        "--follow-imports=silent",
        "--disable-error-code=type-arg",
        "--disable-error-code=no-any-return",
        "--disable-error-code=unused-ignore",
        ".",
    )


def tests() -> None:
    run_command("unittest", "discover", "-s", "tests", "-v")


def compile_sources() -> None:
    files = [
        ROOT / name for name in ("streamlit_app.py", "production.py", "drive_import.py")
    ]
    for folder in ("components", "config", "scripts", "tests"):
        files.extend(sorted((ROOT / folder).rglob("*.py")))
    for path in files:
        py_compile.compile(str(path), doraise=True)
    print(f"Compilação concluída: {len(files)} arquivos.", flush=True)


def main() -> None:
    checks = {"lint": lint, "types": types, "tests": tests, "compile": compile_sources}
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("check", nargs="?", choices=["all", *checks], default="all")
    args = parser.parse_args()
    if args.check == "all":
        for check in checks.values():
            check()
    else:
        checks[args.check]()


if __name__ == "__main__":
    main()
