from __future__ import annotations

import argparse
import subprocess
import sys
import winreg
from pathlib import Path


# ==================== 用户配置区 ====================
TASK_NAME = "Codex-Vibe-Website-Builder-AutoSync"
RUN_VALUE_NAME = "CodexVibeWebsiteBuilderAutoSync"
RUN_KEY_PATH = r"Software\Microsoft\Windows\CurrentVersion\Run"
SYNC_SCRIPT = Path(__file__).resolve().with_name("auto_sync.py")
# ====================================================


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="安装或移除Windows登录后自动同步任务。")
    parser.add_argument("--uninstall", action="store_true")
    parser.add_argument("--start-now", action="store_true")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    if sys.platform != "win32":
        print("错误：此安装器仅支持Windows。", file=sys.stderr)
        return 2
    if not SYNC_SCRIPT.is_file():
        print(f"错误：同步脚本不存在：{SYNC_SCRIPT}", file=sys.stderr)
        return 2

    if args.uninstall:
        subprocess.run(
            ["schtasks.exe", "/Delete", "/TN", TASK_NAME, "/F"],
            text=True,
            capture_output=True,
        )
        try:
            with winreg.OpenKey(winreg.HKEY_CURRENT_USER, RUN_KEY_PATH, 0, winreg.KEY_SET_VALUE) as key:
                winreg.DeleteValue(key, RUN_VALUE_NAME)
        except FileNotFoundError:
            pass
        print("已移除自动同步登录项。")
        return 0

    action = f'"{sys.executable}" "{SYNC_SCRIPT}" --watch'
    result = subprocess.run(
        [
            "schtasks.exe",
            "/Create",
            "/SC",
            "ONLOGON",
            "/TN",
            TASK_NAME,
            "/TR",
            action,
            "/RL",
            "LIMITED",
            "/F",
        ],
        text=True,
        capture_output=True,
    )
    if result.returncode == 0:
        print(f"已安装计划任务：{TASK_NAME}")
    else:
        try:
            with winreg.CreateKey(winreg.HKEY_CURRENT_USER, RUN_KEY_PATH) as key:
                winreg.SetValueEx(key, RUN_VALUE_NAME, 0, winreg.REG_SZ, action)
        except OSError as exc:
            print(f"错误：计划任务和当前用户登录项均无法创建：{exc}", file=sys.stderr)
            return 3
        print(f"计划任务不可用，已安装当前用户登录项：{RUN_VALUE_NAME}")
    print(f"同步脚本：{SYNC_SCRIPT}")
    if args.start_now:
        creation_flags = getattr(subprocess, "CREATE_NO_WINDOW", 0) | getattr(subprocess, "DETACHED_PROCESS", 0)
        subprocess.Popen(
            [sys.executable, str(SYNC_SCRIPT), "--watch"],
            cwd=SYNC_SCRIPT.parent.parent,
            creationflags=creation_flags,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            stdin=subprocess.DEVNULL,
        )
        print("已在后台启动同步监控。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
