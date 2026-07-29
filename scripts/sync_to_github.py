from __future__ import annotations

import argparse
import re
import subprocess
import sys
from datetime import datetime
from pathlib import Path


# ==================== 用户配置区 ====================
DEFAULT_REPO_ROOT = Path(__file__).resolve().parent.parent
REMOTE_NAME = "origin"
BRANCH_NAME = "main"
MAX_FILE_BYTES = 20 * 1024 * 1024
SECRET_PATTERNS = (
    re.compile(rb"-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----"),
    re.compile(rb"\b(?:sk|ghp|github_pat)_[A-Za-z0-9_-]{20,}\b"),
    re.compile(rb"\b(?:OPENAI_API_KEY|SUPABASE_SERVICE_ROLE_KEY)\s*[:=]\s*[\"']?[^\"'\s]+"),
)
# ====================================================


def configure_console() -> None:
    for stream in (sys.stdout, sys.stderr):
        reconfigure = getattr(stream, "reconfigure", None)
        if reconfigure:
            reconfigure(encoding="utf-8", errors="replace")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="仅在用户明确下令时手动同步Skill到GitHub。")
    parser.add_argument("--repo-root", type=Path, default=DEFAULT_REPO_ROOT)
    parser.add_argument("--message", help="提交说明")
    parser.add_argument("--dry-run", action="store_true")
    return parser.parse_args()


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


def repository_files(repo: Path) -> list[Path]:
    result = git(repo, "ls-files", "-co", "--exclude-standard")
    return [repo / line for line in result.stdout.splitlines() if line.strip()]


def safety_scan(repo: Path) -> list[str]:
    problems: list[str] = []
    for path in repository_files(repo):
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


def remote_is_ahead(repo: Path) -> tuple[bool, str]:
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


def main() -> int:
    configure_console()
    args = parse_args()
    repo = args.repo_root.resolve()
    if not (repo / ".git").exists():
        print(f"错误：不是Git仓库：{repo}", file=sys.stderr)
        return 2

    status = git(repo, "status", "--porcelain", check=False)
    if status.returncode != 0:
        print(f"错误：无法读取Git状态：{status.stderr.strip()}", file=sys.stderr)
        return 2
    if not status.stdout.strip():
        print("没有需要同步的修改。")
        return 0

    problems = safety_scan(repo)
    if problems:
        print("安全扫描阻止同步：", file=sys.stderr)
        for problem in problems:
            print(f"  - {problem}", file=sys.stderr)
        return 1

    valid, validation_output = validate_skill(repo)
    if not valid:
        print(f"Skill校验失败，未同步：{validation_output}", file=sys.stderr)
        return 1

    if args.dry_run:
        print("Dry run通过；不会提交或推送。")
        return 0

    ahead, detail = remote_is_ahead(repo)
    if ahead:
        print(f"远端存在新提交或无法安全确认，未覆盖：{detail}", file=sys.stderr)
        return 1

    git(repo, "add", "-A")
    message = args.message or f"chore: manual sync {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}"
    commit = git(repo, "commit", "-m", message, check=False)
    if commit.returncode != 0:
        print(f"提交失败：{(commit.stdout + commit.stderr).strip()}", file=sys.stderr)
        return 1

    push = git(repo, "push", REMOTE_NAME, BRANCH_NAME, check=False)
    if push.returncode != 0:
        print(f"推送失败：{(push.stdout + push.stderr).strip()}", file=sys.stderr)
        return 1

    print(f"已按指令同步：{message}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
