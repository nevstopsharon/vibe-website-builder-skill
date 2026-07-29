from __future__ import annotations

import argparse
import json
import shutil
import sys
from datetime import datetime, timezone
from pathlib import Path


# ==================== 用户配置区 ====================
DEFAULT_OUTPUT_DIR = Path.cwd() / "website-project-kit"
DEFAULT_PROJECT_NAME = "未命名网站"
TEMPLATE_FILES = (
    "project-brief.md",
    "design-recipe.md",
    "motion-spec.md",
    "cost-table.md",
    "demo-content-register.json",
    "release-allowlist.json",
    "release-checklist.json",
)
# ====================================================


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="创建不含网站代码的项目规划文档包。")
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT_DIR)
    parser.add_argument("--project-name", default=DEFAULT_PROJECT_NAME)
    parser.add_argument("--overwrite", action="store_true")
    return parser.parse_args()


def write_json(path: Path, value: object) -> None:
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def main() -> int:
    args = parse_args()
    output = args.output.resolve()
    assets = Path(__file__).resolve().parent.parent / "assets"

    if not assets.is_dir():
        print(f"错误：模板目录不存在：{assets}", file=sys.stderr)
        return 2
    if output.exists() and not output.is_dir():
        print(f"错误：输出路径不是文件夹：{output}", file=sys.stderr)
        return 2

    try:
        output.mkdir(parents=True, exist_ok=True)
        written: list[Path] = []
        skipped: list[Path] = []
        for name in TEMPLATE_FILES:
            source = assets / name
            target = output / name
            if not source.is_file():
                raise FileNotFoundError(f"缺少模板：{source}")
            if target.exists() and not args.overwrite:
                skipped.append(target)
                continue
            shutil.copy2(source, target)
            written.append(target)

        state_path = output / "project-state.json"
        if args.overwrite or not state_path.exists():
            write_json(
                state_path,
                {
                    "project": args.project_name,
                    "created_at": datetime.now(timezone.utc).isoformat(),
                    "gates": {
                        "requirements": False,
                        "pages": False,
                        "ui": False,
                        "motion": False,
                        "technology": False,
                        "launch": False,
                    },
                    "confirmed_phrases": [],
                    "demo_items": [],
                    "decisions": [],
                    "change_requests": [],
                    "release_exceptions": [],
                },
            )
            written.append(state_path)
        else:
            skipped.append(state_path)
    except (OSError, PermissionError) as exc:
        print(f"错误：无法创建项目文档包：{exc}", file=sys.stderr)
        return 3

    print(f"项目文档目录：{output}")
    print(f"已写入：{len(written)} 个文件")
    for path in written:
        print(f"  + {path.resolve()}")
    if skipped:
        print(f"已保留现有文件：{len(skipped)} 个；使用 --overwrite 可覆盖。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
