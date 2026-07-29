from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from typing import Any


# ==================== 用户配置区 ====================
SUPPORTED_EXTENSIONS = {".json"}
VALID_STATUSES = {"draft", "review", "published", "archived"}
STABLE_ID_PATTERN = re.compile(r"^[a-z0-9][a-z0-9-]*$")
PENDING_MARKERS = {"pending", "todo", "tbd", "待补充", "待确认"}
SKIP_FILES = {"demo-content-register.json", "release-checklist.json", "release-allowlist.json"}
# ====================================================


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="校验网站结构化内容和DEMO状态。")
    parser.add_argument("--content-root", type=Path, required=True)
    parser.add_argument("--production", action="store_true", help="将DEMO和pending作为阻断项")
    return parser.parse_args()


def is_blank(value: Any) -> bool:
    return value is None or (isinstance(value, str) and not value.strip())


def validate_image(image: Any, where: str, errors: list[str]) -> None:
    if not isinstance(image, dict):
        errors.append(f"{where}：图片必须是对象")
        return
    for key in ("src", "width", "height", "alt", "source"):
        if key not in image or is_blank(image[key]):
            errors.append(f"{where}：图片缺少 {key}")
    for key in ("width", "height"):
        if key in image and (not isinstance(image[key], int) or image[key] <= 0):
            errors.append(f"{where}：{key} 必须是正整数")
    if image.get("width") and image.get("height") and not image.get("ratio"):
        errors.append(f"{where}：图片缺少 ratio")


def validate_item(item: dict[str, Any], where: str, production: bool, errors: list[str]) -> None:
    required = ("id", "status", "archived", "demo", "title", "slug", "seo")
    for key in required:
        if key not in item or is_blank(item[key]):
            errors.append(f"{where}：缺少必填字段 {key}")

    item_id = item.get("id")
    if isinstance(item_id, str) and not STABLE_ID_PATTERN.fullmatch(item_id):
        errors.append(f"{where}：id 必须使用小写英文、数字和连字符")
    if item.get("status") not in VALID_STATUSES:
        errors.append(f"{where}：status 必须是 {sorted(VALID_STATUSES)}")
    if "archived" in item and not isinstance(item["archived"], bool):
        errors.append(f"{where}：archived 必须是布尔值")
    if "demo" in item and not isinstance(item["demo"], bool):
        errors.append(f"{where}：demo 必须是布尔值")
    if production and item.get("demo") is True:
        errors.append(f"{where}：生产内容仍标记为 DEMO")

    seo = item.get("seo")
    if not isinstance(seo, dict):
        errors.append(f"{where}：seo 必须是对象")
    else:
        for key in ("title", "description", "noindex"):
            if key not in seo or is_blank(seo[key]):
                errors.append(f"{where}.seo：缺少 {key}")
        if production and seo.get("noindex") is True:
            errors.append(f"{where}.seo：生产内容仍为 noindex")

    images = item.get("images", [])
    if not isinstance(images, list):
        errors.append(f"{where}：images 必须是数组")
    else:
        for index, image in enumerate(images):
            validate_image(image, f"{where}.images[{index}]", errors)

    if production:
        for key, value in item.items():
            if isinstance(value, str) and value.strip().lower() in PENDING_MARKERS:
                errors.append(f"{where}.{key}：包含待处理标记 {value!r}")


def validate_file(path: Path, production: bool) -> list[str]:
    errors: list[str] = []
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except UnicodeDecodeError:
        return [f"{path}：不是UTF-8文本"]
    except json.JSONDecodeError as exc:
        return [f"{path}:{exc.lineno}:{exc.colno}：JSON格式错误：{exc.msg}"]

    items: list[Any]
    if isinstance(data, list):
        items = data
    elif isinstance(data, dict) and isinstance(data.get("items"), list):
        items = data["items"]
    elif isinstance(data, dict) and "id" in data:
        items = [data]
    else:
        return errors

    ids: set[str] = set()
    for index, item in enumerate(items):
        where = f"{path}[{index}]"
        if not isinstance(item, dict):
            errors.append(f"{where}：内容项必须是对象")
            continue
        validate_item(item, where, production, errors)
        item_id = item.get("id")
        if isinstance(item_id, str):
            if item_id in ids:
                errors.append(f"{where}：重复id {item_id}")
            ids.add(item_id)
    return errors


def main() -> int:
    args = parse_args()
    root = args.content_root.resolve()
    if not root.is_dir():
        print(f"错误：内容目录不存在：{root}", file=sys.stderr)
        return 2

    files = sorted(
        path for path in root.rglob("*")
        if path.is_file() and path.suffix.lower() in SUPPORTED_EXTENSIONS and path.name not in SKIP_FILES
    )
    if not files:
        print(f"错误：未找到支持的内容文件：{root}", file=sys.stderr)
        return 2

    errors: list[str] = []
    for path in files:
        errors.extend(validate_file(path, args.production))

    print(f"内容目录：{root}")
    print(f"已检查：{len(files)} 个JSON文件")
    if errors:
        print(f"发现：{len(errors)} 个阻断问题")
        for error in errors:
            print(f"  - {error}")
        return 1
    print("结果：通过")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
