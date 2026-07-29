from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.parse import quote
from urllib.request import Request, urlopen


# ==================== 用户配置区 ====================
DEFAULT_TIMEOUT_SECONDS = 30
TEXT_EXTENSIONS = {".html", ".css", ".js", ".mjs", ".json", ".xml", ".txt"}
MOJIBAKE_MARKERS = (b"tokens truncated", "\ufffd".encode("utf-8"), b"\xc3\xa2\xc2")
USER_AGENT = "vibe-website-builder-deploy-verifier/1.0"
# ====================================================


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="逐字节比较本地发布文件与线上文件。")
    parser.add_argument("--site-root", type=Path, required=True)
    parser.add_argument("--base-url", required=True)
    parser.add_argument("--allowlist", type=Path, required=True)
    parser.add_argument("--timeout", type=int, default=DEFAULT_TIMEOUT_SECONDS)
    return parser.parse_args()


def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def load_allowlist(path: Path) -> list[str]:
    data = json.loads(path.read_text(encoding="utf-8"))
    files = data.get("files") if isinstance(data, dict) else data
    if not isinstance(files, list) or not files or not all(isinstance(item, str) and item for item in files):
        raise ValueError("allowlist必须包含非空字符串数组 files")
    if len(files) != len(set(files)):
        raise ValueError("allowlist含重复路径")
    return files


def remote_url(base_url: str, relative: str) -> str:
    encoded = "/".join(quote(part) for part in relative.replace("\\", "/").split("/"))
    return f"{base_url.rstrip('/')}/{encoded}"


def main() -> int:
    args = parse_args()
    root = args.site_root.resolve()
    allowlist_path = args.allowlist.resolve()
    if not root.is_dir():
        print(f"错误：发布目录不存在：{root}", file=sys.stderr)
        return 2
    if not allowlist_path.is_file():
        print(f"错误：允许列表不存在：{allowlist_path}", file=sys.stderr)
        return 2

    try:
        files = load_allowlist(allowlist_path)
    except (OSError, UnicodeDecodeError, json.JSONDecodeError, ValueError) as exc:
        print(f"错误：无法读取允许列表：{exc}", file=sys.stderr)
        return 2

    failures: list[str] = []
    results: list[dict[str, object]] = []
    for relative in files:
        local_path = (root / relative).resolve()
        try:
            local_path.relative_to(root)
        except ValueError:
            failures.append(f"路径越出发布目录：{relative}")
            continue
        if not local_path.is_file():
            failures.append(f"本地文件不存在：{relative}")
            continue
        local_bytes = local_path.read_bytes()
        url = remote_url(args.base_url, relative)
        request = Request(url, headers={"User-Agent": USER_AGENT, "Cache-Control": "no-cache"})
        try:
            with urlopen(request, timeout=args.timeout) as response:
                remote_bytes = response.read()
                status = getattr(response, "status", 200)
        except (HTTPError, URLError, TimeoutError, OSError) as exc:
            failures.append(f"下载失败 {url}：{exc}")
            continue

        local_hash = sha256(local_bytes)
        remote_hash = sha256(remote_bytes)
        matched = local_bytes == remote_bytes
        if not matched:
            failures.append(
                f"文件不一致：{relative}；本地{len(local_bytes)}字节/{local_hash}，"
                f"线上{len(remote_bytes)}字节/{remote_hash}"
            )
        if local_path.suffix.lower() in TEXT_EXTENSIONS:
            for marker in MOJIBAKE_MARKERS:
                if marker in remote_bytes:
                    failures.append(f"线上文本含截断或乱码标记：{relative}")
        results.append(
            {
                "file": relative,
                "url": url,
                "status": status,
                "local_bytes": len(local_bytes),
                "remote_bytes": len(remote_bytes),
                "sha256": local_hash,
                "matched": matched,
            }
        )

    report = {"base_url": args.base_url, "results": results, "failures": failures, "passed": not failures}
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0 if not failures else 1


if __name__ == "__main__":
    raise SystemExit(main())
