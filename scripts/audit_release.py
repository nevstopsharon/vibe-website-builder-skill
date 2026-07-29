from __future__ import annotations

import argparse
import json
import re
import sys
from html.parser import HTMLParser
from pathlib import Path
from urllib.parse import unquote, urlsplit


# ==================== 用户配置区 ====================
TEXT_EXTENSIONS = {".html", ".htm", ".css", ".js", ".mjs", ".json", ".xml", ".txt", ".md"}
MAX_TEXT_BYTES = 5_000_000
CORRUPTION_MARKERS = ("tokens truncated", "\ufffd")
PLACEHOLDER_PATTERNS = (
    re.compile(r"\[\s*DEMO\s*\]", re.IGNORECASE),
    re.compile(r"\bdata-demo\s*=", re.IGNORECASE),
    re.compile(r">\s*\[?DEMO\]?(?:\s*[:：-][^<]*)?\s*<", re.IGNORECASE),
    re.compile(r"<!--[^>]*(?:pending|todo|tbd|待补充|待确认)[^>]*-->", re.IGNORECASE),
    re.compile(r">\s*(?:pending|todo|tbd|待补充|待确认)\s*<", re.IGNORECASE),
)
FORBIDDEN_NAME = re.compile(r"[^A-Za-z0-9._/-]")
SECRET_PATTERNS = (
    re.compile(r"-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----"),
    re.compile(r"\b(?:sk|ghp|github_pat)_[A-Za-z0-9_-]{20,}\b"),
    re.compile(r"\b(?:SUPABASE_SERVICE_ROLE_KEY|OPENAI_API_KEY)\s*[:=]\s*[\"']?[^\"'\s]+"),
)
# ====================================================


class PageParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.title = ""
        self._in_title = False
        self.links: list[str] = []
        self.description = False
        self.canonical = False
        self.noindex = False
        self.images_without_alt = 0
        self.images_without_dimensions = 0

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        values = {key.lower(): value or "" for key, value in attrs}
        if tag == "title":
            self._in_title = True
        if tag in {"a", "link"} and values.get("href"):
            self.links.append(values["href"])
        if tag in {"img", "script", "source"} and values.get("src"):
            self.links.append(values["src"])
        if tag == "meta" and values.get("name", "").lower() == "description" and values.get("content", "").strip():
            self.description = True
        if tag == "meta" and values.get("name", "").lower() == "robots":
            self.noindex = "noindex" in values.get("content", "").lower()
        if tag == "link" and values.get("rel", "").lower() == "canonical" and values.get("href"):
            self.canonical = True
        if tag == "img":
            if not values.get("alt", "").strip():
                self.images_without_alt += 1
            if not values.get("width") or not values.get("height"):
                self.images_without_dimensions += 1

    def handle_endtag(self, tag: str) -> None:
        if tag == "title":
            self._in_title = False

    def handle_data(self, data: str) -> None:
        if self._in_title:
            self.title += data


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="审计静态发布目录中的生产阻断项。")
    parser.add_argument("--site-root", type=Path, required=True)
    parser.add_argument("--allow-single-page", action="store_true")
    parser.add_argument("--report", type=Path)
    return parser.parse_args()


def local_target(site_root: Path, page: Path, href: str) -> Path | None:
    if not href or href.startswith(("#", "mailto:", "tel:", "data:", "javascript:")):
        return None
    parts = urlsplit(href)
    if parts.scheme or parts.netloc:
        return None
    clean = unquote(parts.path)
    if not clean:
        return None
    if clean.startswith("/"):
        target = site_root / clean.lstrip("/")
    else:
        target = page.parent / clean
    if clean.endswith("/"):
        target /= "index.html"
    return target.resolve()


def main() -> int:
    args = parse_args()
    root = args.site_root.resolve()
    if not root.is_dir():
        print(f"错误：发布目录不存在：{root}", file=sys.stderr)
        return 2

    blockers: list[str] = []
    warnings: list[str] = []
    files = sorted(path for path in root.rglob("*") if path.is_file())
    if not files:
        print(f"错误：发布目录为空：{root}", file=sys.stderr)
        return 2

    required = ["index.html"]
    if not args.allow_single_page:
        required += ["robots.txt", "sitemap.xml"]
        if not ((root / "404.html").is_file() or (root / "404" / "index.html").is_file()):
            blockers.append("缺少404.html或404/index.html")
    for name in required:
        if not (root / name).is_file():
            blockers.append(f"缺少{name}")

    for path in files:
        relative = path.relative_to(root).as_posix()
        if FORBIDDEN_NAME.search(relative):
            blockers.append(f"资源名含空格、中文或不安全字符：{relative}")
        if path.stat().st_size > MAX_TEXT_BYTES and path.suffix.lower() in TEXT_EXTENSIONS:
            warnings.append(f"跳过超大文本扫描：{relative}")
            continue
        if path.suffix.lower() not in TEXT_EXTENSIONS:
            continue
        try:
            text = path.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            blockers.append(f"文本不是UTF-8：{relative}")
            continue
        lowered = text.lower()
        for marker in CORRUPTION_MARKERS:
            if marker.lower() in lowered:
                blockers.append(f"{relative} 包含截断或乱码标记：{marker}")
        if path.suffix.lower() in {".html", ".htm", ".json", ".md"}:
            for pattern in PLACEHOLDER_PATTERNS:
                if pattern.search(text):
                    blockers.append(f"{relative} 包含未清理的DEMO或待处理标记")
                    break
        for pattern in SECRET_PATTERNS:
            if pattern.search(text):
                blockers.append(f"{relative} 疑似包含密钥")

        if path.suffix.lower() in {".html", ".htm"}:
            parser = PageParser()
            parser.feed(text)
            is_404 = relative in {"404.html", "404/index.html"}
            if not parser.title.strip():
                blockers.append(f"{relative} 缺少title")
            if not parser.description:
                blockers.append(f"{relative} 缺少description")
            if not parser.canonical and not is_404:
                blockers.append(f"{relative} 缺少canonical")
            if parser.noindex and not is_404:
                blockers.append(f"{relative} 含noindex")
            if parser.images_without_alt:
                blockers.append(f"{relative} 有{parser.images_without_alt}张图片缺少alt")
            if parser.images_without_dimensions:
                blockers.append(f"{relative} 有{parser.images_without_dimensions}张图片缺少width/height")
            for href in parser.links:
                target = local_target(root, path, href)
                if target is None:
                    continue
                try:
                    target.relative_to(root)
                except ValueError:
                    blockers.append(f"{relative} 链接越出发布目录：{href}")
                    continue
                if not target.exists():
                    blockers.append(f"{relative} 本地链接失效：{href}")

    blockers = sorted(set(blockers))
    warnings = sorted(set(warnings))
    report = {
        "site_root": str(root),
        "files_checked": len(files),
        "blockers": blockers,
        "warnings": warnings,
        "passed": not blockers,
    }
    if args.report:
        try:
            args.report.resolve().write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        except OSError as exc:
            print(f"错误：无法写报告：{exc}", file=sys.stderr)
            return 3

    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0 if not blockers else 1


if __name__ == "__main__":
    raise SystemExit(main())
