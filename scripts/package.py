#!/usr/bin/env python3
"""Release only known source paths. Never archive runtime data or user profiles."""
from __future__ import annotations

import hashlib
from pathlib import Path
import re
import subprocess
import sys
import tarfile
from zipfile import ZipFile, ZipInfo, ZIP_DEFLATED

ROOT = Path(__file__).resolve().parents[1]
VERSION = "0.1.1"
TOP = f"duebridge-{VERSION}"
FIXED = ("pyproject.toml", "MANIFEST.in", ".gitignore", "README.md", "LICENSE", "AGENTS.md",
         "CONTRIBUTING.md", "VALIDATION.md", "install.sh", "duebridge", "homework", "scripts/package.py", ".github/workflows/tests.yml")


def sources() -> list[Path]:
    files = [ROOT / name for name in FIXED]
    for folder, extensions in (("src/homework_assistant", {".py", ".js", ".applescript", ".toml"}),
                               ("tests", {".py"}), ("examples", {".toml"})):
        files.extend(p for p in (ROOT / folder).rglob("*") if p.is_file() and p.suffix in extensions and "__pycache__" not in p.parts)
    return sorted(set(files))


def audit(name: str, content: bytes) -> None:
    if Path(name).is_absolute() or ".." in Path(name).parts or any(p in {".homework", ".venv", "materials", ".cache", ".git", "__pycache__"} for p in Path(name).parts):
        raise ValueError(f"Private or unsafe release path: {name}")
    if Path(name).name in {"homework.toml", "DUEDATES.md", "courses.json", "source-notes.json"}:
        raise ValueError(f"User data entered release: {name}")
    if str(ROOT.parent).encode() in content or str(Path.home()).encode() in content:
        raise ValueError(f"Private local path entered release: {name}")
    if re.search(rb"enrollmentID=\d{5,}", content):
        raise ValueError(f"Personal enrollment ID entered release: {name}")


def main() -> None:
    files = sources()
    for file in files:
        audit(str(file.relative_to(ROOT)), file.read_bytes())
    dist = ROOT / "dist"
    dist.mkdir(exist_ok=True)
    archive = dist / f"{TOP}-source.zip"
    with ZipFile(archive, "w", compression=ZIP_DEFLATED) as zipfile:
        for file in files:
            entry = ZipInfo(f"{TOP}/{file.relative_to(ROOT).as_posix()}")
            entry.compress_type = ZIP_DEFLATED
            executable = file.name in {"duebridge", "homework", "install.sh", "package.py"}
            entry.external_attr = (0o100755 if executable else 0o100644) << 16
            zipfile.writestr(entry, file.read_bytes())
    subprocess.run([sys.executable, "-m", "build", "--outdir", str(dist)], cwd=ROOT, check=True)
    outputs = [archive]
    for file in sorted(dist.glob(f"duebridge-{VERSION}-*.whl")):
        with ZipFile(file) as wheel:
            for name in wheel.namelist():
                audit(name, wheel.read(name))
        outputs.append(file)
    for file in sorted(dist.glob(f"duebridge-{VERSION}.tar.gz")):
        with tarfile.open(file) as source:
            for entry in source.getmembers():
                audit(entry.name, source.extractfile(entry).read() if entry.isfile() else b"")
        outputs.append(file)
    checksums = "\n".join(f"{hashlib.sha256(f.read_bytes()).hexdigest()}  {f.name}" for f in outputs) + "\n"
    (dist / "SHA256SUMS.txt").write_text(checksums, encoding="utf-8")
    for file in outputs:
        print(f"{file.name}: {file.stat().st_size:,} bytes")
    print("Release audit passed; no runtime data or personal enrollment IDs included.")


if __name__ == "__main__":
    main()
