from __future__ import annotations

import argparse
import os
import re
import subprocess
import sys
import tempfile
import time
from datetime import datetime
from pathlib import Path


# ==================== 用户配置区 ====================
DEFAULT_REPO_ROOT = Path(__file__).resolve().parent.parent
REMOTE_NAME = "origin"
BRANCH_NAME = "main"
POLL_SECONDS = 10
QUIET_SECONDS = 20
MAX_FILE_BYTES = 20 * 1024 * 1024
LOG_FILE = Path(os.environ.get("LOCALAPPDATA", Path.home())) / "Codex" / "vibe-website-builder-sync.log"
FALLBACK_LOG_FILE = Path(tempfile.gettempdir()) / "vibe-website-builder-sync.log"
SECRET_PATTERNS = (
    re.compile(rb"-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----"),
    re.compile(rb"\b(?:sk|ghp|github_pat)_[A-Za-z0-9_-]{20,}\b"),
    re.compile(rb"\b(?:OPENAI_API_KEY|SUPABASE_SERVICE_ROLE_KEY)\s*[:=]\s*[\"']?[^\"'\s]+"),
)
# ====================================================


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="安全地自动提交并推送此Skill目录。")
    parser.add_argument("--repo-root", type=Path, default=DEFAULT_REPO_ROOT)
    parser.add_argument("--once", action="store_true")
    parser.add_argument("--watch", action="store_true")
    parser.add_argument("--dry-run", action="store_true")
    return parser.parse_args()


def log(message: str) -> None:
    line = f"[{datetime.now().isoformat(timespec='seconds')}] {message}"
    print(line)
    for path in (LOG_FILE, FALLBACK_LOG_FILE):
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            with path.open("a", encoding="utf-8") as handle:
                handle.write(line + "\n")
            return
        except OSError:
            continue


def run(repo: Path, *args: str, check: bool = True) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [*args],
        cwd=repo,
        text=True,
        encoding="utf-8",
        errors="replace",
        capture_output=True,
        check=check,
    )


def git(repo: Path, *args: str, check: bool = True) -> subprocess.CompletedProcess[str]:
    return run(repo, "git", *args, check=check)


def changed_files(repo: Path) -> list[Path]:
    result = git(repo, "ls-files", "-co", "--exclude-standard")
    return [repo / line for line in result.stdout.splitlines() if line.strip()]


def safety_scan(repo: Path) -> list[str]:
    problems: list[str] = []
    for path in changed_files(repo):
        if not path.is_file():
            continue
        relative = path.relative_to(repo).as_posix()
        size = path.stat().st_size
        if size > MAX_FILE_BYTES:
            problems.append(f"{relative} 超过 {MAX_FILE_BYTES} 字节")
            continue
        data = path.read_bytes()
        for pattern in SECRET_PATTERNS:
            if pattern.search(data):
                problems.append(f"{relative} 疑似包含密钥")
                break
    return problems


def validate_skill(repo: Path) -> tuple[bool, str]:
    validator = Path.home() / ".codex" / "skills" / ".system" / "skill-creator" / "scripts" / "quick_validate.py"
    if not validator.is_file():
        return False, f"找不到校验器：{validator}"
    result = run(repo, sys.executable, str(validator), str(repo), check=False)
    return result.returncode == 0, (result.stdout + result.stderr).strip()


def remote_ahead(repo: Path) -> tuple[bool, str]:
    fetch = git(repo, "fetch", REMOTE_NAME, BRANCH_NAME, check=False)
    if fetch.returncode != 0:
        return True, (fetch.stdout + fetch.stderr).strip()
    count = git(repo, "rev-list", "--left-right", "--count", f"HEAD...{REMOTE_NAME}/{BRANCH_NAME}", check=False)
    if count.returncode != 0:
        return True, (count.stdout + count.stderr).strip()
    parts = count.stdout.split()
    if len(parts) != 2:
        return True, f"无法解析分叉状态：{count.stdout!r}"
    return int(parts[1]) > 0, count.stdout.strip()


def sync_once(repo: Path, dry_run: bool) -> int:
    status = git(repo, "status", "--porcelain", check=False)
    if status.returncode != 0:
        log(f"Git状态失败：{status.stderr.strip()}")
        return 2
    if not status.stdout.strip():
        log("没有需要同步的修改。")
        return 0

    problems = safety_scan(repo)
    if problems:
        log("安全扫描阻止同步：" + "；".join(problems))
        return 1
    valid, output = validate_skill(repo)
    if not valid:
        log(f"Skill校验失败，未同步：{output}")
        return 1
    if dry_run:
        log("Dry run通过；不会提交或推送。")
        return 0

    ahead, detail = remote_ahead(repo)
    if ahead:
        log(f"远端存在新提交或无法安全确认，未自动覆盖：{detail}")
        return 1

    git(repo, "add", "-A")
    message = f"chore: auto-sync {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}"
    commit = git(repo, "commit", "-m", message, check=False)
    if commit.returncode != 0:
        log(f"提交失败：{(commit.stdout + commit.stderr).strip()}")
        return 1
    push = git(repo, "push", REMOTE_NAME, BRANCH_NAME, check=False)
    if push.returncode != 0:
        log(f"推送失败：{(push.stdout + push.stderr).strip()}")
        return 1
    log(f"已同步：{message}")
    return 0


def watch(repo: Path, dry_run: bool) -> int:
    log(f"开始监控：{repo}")
    last_status = ""
    changed_at: float | None = None
    while True:
        result = git(repo, "status", "--porcelain", check=False)
        current = result.stdout if result.returncode == 0 else ""
        if current != last_status:
            last_status = current
            changed_at = time.monotonic() if current.strip() else None
        if current.strip() and changed_at is not None and time.monotonic() - changed_at >= QUIET_SECONDS:
            sync_once(repo, dry_run)
            last_status = git(repo, "status", "--porcelain", check=False).stdout
            changed_at = time.monotonic() if last_status.strip() else None
        time.sleep(POLL_SECONDS)


def main() -> int:
    args = parse_args()
    repo = args.repo_root.resolve()
    if not (repo / ".git").exists():
        print(f"错误：不是Git仓库：{repo}", file=sys.stderr)
        return 2
    if not args.once and not args.watch:
        args.once = True
    try:
        return watch(repo, args.dry_run) if args.watch else sync_once(repo, args.dry_run)
    except KeyboardInterrupt:
        log("监控已停止。")
        return 0
    except (OSError, subprocess.SubprocessError) as exc:
        log(f"同步异常：{exc}")
        return 3


if __name__ == "__main__":
    raise SystemExit(main())
