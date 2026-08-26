"""Validate the repository files required by the Poppy-Agent harness."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

REQUIRED_FILES = (
    "README.md",
    "CONTRIBUTING.md",
    "SECURITY.md",
    "CLAUDE.md",
    "AGENTS.md",
    "docs/git-workflow.md",
    "docs/commit-convention.md",
    "docs/ai-workflow.md",
    "docs/architecture.md",
    "docs/configuration.md",
    "docs/api-convention.md",
    "docs/testing.md",
    "docs/ci.md",
    "docs/pull-request-convention.md",
    ".github/pull_request_template.md",
    ".github/workflows/ci.yml",
)

TEXT_SUFFIXES = {
    ".example",
    ".md",
    ".ps1",
    ".py",
    ".sh",
    ".toml",
    ".yaml",
    ".yml",
}
TEXT_FILENAMES = {".gitattributes", ".gitignore"}


def tracked_files(repo_root: Path) -> list[str]:
    result = subprocess.run(
        ["git", "ls-files"],
        cwd=repo_root,
        check=True,
        capture_output=True,
        text=True,
    )
    return result.stdout.splitlines()


def is_text_file(relative_path: str) -> bool:
    path = Path(relative_path)
    return path.name in TEXT_FILENAMES or path.suffix in TEXT_SUFFIXES


def check_text_encoding(repo_root: Path, relative_paths: list[str]) -> list[str]:
    failures: list[str] = []
    for relative_path in relative_paths:
        if not is_text_file(relative_path):
            continue

        path = repo_root / relative_path
        raw = path.read_bytes()
        if raw.startswith(b"\xef\xbb\xbf"):
            failures.append(f"UTF-8 BOM NOT ALLOWED: {relative_path}")
        try:
            text = raw.decode("utf-8")
        except UnicodeDecodeError as error:
            failures.append(f"NOT UTF-8: {relative_path} ({error})")
            continue
        if "\ufffd" in text:
            failures.append(f"REPLACEMENT CHARACTER FOUND: {relative_path}")
    return failures


def main() -> int:
    repo_root = Path(__file__).resolve().parents[1]
    failures: list[str] = []

    for relative_path in REQUIRED_FILES:
        path = repo_root / relative_path
        if not path.is_file():
            failures.append(f"MISSING: {relative_path}")

    claude_path = repo_root / "CLAUDE.md"
    agents_path = repo_root / "AGENTS.md"
    if claude_path.is_file() and agents_path.is_file():
        if claude_path.read_bytes() != agents_path.read_bytes():
            failures.append("MISMATCH: CLAUDE.md and AGENTS.md are not byte-identical")
        for path in (claude_path, agents_path):
            if b"\r\n" in path.read_bytes():
                failures.append(f"NOT LF-ONLY: {path.relative_to(repo_root)}")

    tracked = tracked_files(repo_root)
    failures.extend(check_text_encoding(repo_root, tracked))

    for relative_path in tracked:
        if relative_path == ".env" or (
            relative_path.startswith(".env.") and relative_path != ".env.example"
        ):
            failures.append(f"SECRET FILE TRACKED: {relative_path}")

    if failures:
        print("harness-check FAILED")
        print("\n".join(failures))
        return 1

    print("harness-check PASSED")
    return 0


if __name__ == "__main__":
    sys.exit(main())
