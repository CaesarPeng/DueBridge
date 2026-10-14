from __future__ import annotations

import hashlib
from html.parser import HTMLParser
import json
import os
from pathlib import Path
import re
from urllib.parse import quote
import xml.etree.ElementTree as ET
from zipfile import ZipFile

from .config import Config
from .storage import stamp, write_json, write_text

CUE = re.compile(r"\bdue\b(?!\s+(?:to|east|west|north|south)\b)|deadline|截止|最晚", re.I)
SUPPORTED = {".pdf", ".docx", ".html", ".htm", ".md", ".txt", ".ipynb"}
SKIP = {".homework", ".git", ".venv", "node_modules", "__pycache__", "build", "dist", ".ipynb_checkpoints"}


class HTMLText(HTMLParser):
    def __init__(self):
        super().__init__()
        self.parts = []
        self.hidden = 0

    def handle_starttag(self, tag, attrs):
        if tag in {"script", "style"}:
            self.hidden += 1
        elif tag in {"p", "div", "br", "li", "tr", "h1", "h2", "h3"}:
            self.parts.append("\n")

    def handle_endtag(self, tag):
        if tag in {"script", "style"}:
            self.hidden = max(0, self.hidden - 1)
        elif tag in {"p", "div", "li", "tr"}:
            self.parts.append("\n")

    def handle_data(self, data):
        if not self.hidden:
            self.parts.append(data)


def extract(path: Path) -> str:
    suffix = path.suffix.lower()
    if suffix == ".pdf":
        try:
            from pypdf import PdfReader
        except ImportError:
            raise ValueError("PDF 读取需要 pypdf；请完成项目安装") from None
        reader = PdfReader(path)
        if len(reader.pages) > 150:
            raise ValueError("PDF 超过 150 页，跳过长教材")
        return "\n".join(page.extract_text() or "" for page in reader.pages)
    if suffix == ".docx":
        with ZipFile(path) as archive:
            member = archive.getinfo("word/document.xml")
            if member.file_size > 20_000_000:
                raise ValueError("DOCX 解压文字超过 20 MB")
            tree = ET.fromstring(archive.read(member))
        ns = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"
        return "\n".join("".join(t.text or "" for t in p.iter(ns + "t")) for p in tree.iter(ns + "p"))
    text = path.read_text(encoding="utf-8", errors="replace")
    if suffix == ".ipynb":
        return "\n".join("".join(c.get("source", [])) for c in json.loads(text).get("cells", []) if c.get("cell_type") == "markdown")
    if suffix in {".html", ".htm"}:
        parser = HTMLText()
        parser.feed(text)
        return "".join(parser.parts)
    return text


def scan(config: Config) -> dict:
    files, entries, failures = set(), [], []
    for relative in config.local_paths:
        directory = config.root / relative
        if not directory.exists():
            failures.append({"path": relative, "reason": "配置路径不存在"})
            continue
        candidates = [directory] if directory.is_file() else directory.rglob("*")
        for path in candidates:
            if path.is_file() and path.suffix.lower() in SUPPORTED and not any(p in SKIP for p in path.relative_to(config.root).parts):
                if path.is_symlink() or not path.resolve().is_relative_to(config.root.resolve()):
                    failures.append({"path": str(path.relative_to(config.root)), "reason": "跳过符号链接或项目外文件"})
                elif path.name not in {"AGENTS.md", "homework.toml"} and path != config.root / config.output:
                    files.add(path)
    scanned = 0
    for path in sorted(files):
        relative = str(path.relative_to(config.root))
        try:
            if path.stat().st_size > 20_000_000:
                raise ValueError("文件超过 20 MB")
            text = extract(path)
            if not text.strip():
                raise ValueError("没有可提取文字，可能需要 OCR")
            scanned += 1
            match = CUE.search(text)
            if match is None:
                continue
            name = hashlib.sha256(relative.encode()).hexdigest()[:20] + ".md"
            target = config.state / "text" / name
            link = quote(os.path.relpath(path, target.parent), safe="/")
            header = f"# {relative}\n\n[原文件]({link})\n\n读取时间：{stamp(config)}\n\n"
            write_text(target, header + text + "\n", private=True)
            sample = re.sub(r"\s+", " ", text[max(0, match.start() - 80):match.end() + 350]).strip()
            entries.append({"path": relative, "text": str(target.relative_to(config.root)), "sample": sample})
        except Exception as error:
            failures.append({"path": relative, "reason": f"{type(error).__name__}: {error}"})
    data = {"scanned": scanned, "entries": entries, "failures": failures, "fetched_at": stamp(config)}
    write_json(config.state / "local.json", data)
    return data
