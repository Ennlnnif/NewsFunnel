"""
一次性脚本：把 8 个板块选项预填到飞书表格的"板块"字段。

用法:
    python scripts/init_feishu_options.py

预填选项：
    AI Agent / AI视频 / AI游戏 / AI社交 /
    AI通用技术/模型 / AI行业动态 / 其他值得关注的产品 / 行业观点

跑完可删除（.env 凭证读取复用 syncer 模块）。
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

BASE_DIR = Path(__file__).parent.parent
sys.path.insert(0, str(BASE_DIR))

from dotenv import load_dotenv  # noqa: E402
from layers.syncer import FeishuClient  # noqa: E402

SECTIONS = [
    "AI Agent",
    "AI视频",
    "AI游戏",
    "AI社交",
    "AI通用技术/模型",
    "AI行业动态",
    "其他值得关注的产品",
    "行业观点",
]

FIELD_NAME = "板块"


def main() -> int:
    load_dotenv(BASE_DIR / ".env")
    client = FeishuClient(
        app_id=os.getenv("FEISHU_APP_ID", ""),
        app_secret=os.getenv("FEISHU_APP_SECRET", ""),
        app_token=os.getenv("FEISHU_BITABLE_APP_TOKEN", ""),
        table_id=os.getenv("FEISHU_BITABLE_TABLE_ID", ""),
    )

    # 1. 列字段，定位"板块"字段的 field_id 和类型
    path = f"/open-apis/bitable/v1/apps/{client.app_token}/tables/{client.table_id}/fields"
    data = client._request("GET", path, params={"page_size": 100})
    fields = data.get("data", {}).get("items", [])

    target = None
    for f in fields:
        if f.get("field_name") == FIELD_NAME:
            target = f
            break

    if not target:
        print(f"❌ 未找到字段: {FIELD_NAME}")
        return 1

    field_id = target["field_id"]
    ftype = target.get("type")
    # 飞书：3=单选, 4=多选
    if ftype not in (3, 4):
        print(f"❌ 字段 {FIELD_NAME} 类型={ftype}，不是单选/多选")
        return 1

    existing_opts = (target.get("property") or {}).get("options", []) or []
    existing_names = {o["name"] for o in existing_opts}
    print(f"已有选项: {sorted(existing_names)}")

    # 2. 合并新选项（保留旧的，追加缺失的）
    to_add = [s for s in SECTIONS if s not in existing_names]
    if not to_add:
        print("✅ 所有目标选项已存在，无需补充")
        return 0

    print(f"待补选项: {to_add}")
    new_options = list(existing_opts) + [{"name": n} for n in to_add]

    # 3. 更新字段
    update_path = (
        f"/open-apis/bitable/v1/apps/{client.app_token}"
        f"/tables/{client.table_id}/fields/{field_id}"
    )
    body = {
        "field_name": FIELD_NAME,
        "type": ftype,
        "property": {"options": new_options},
    }
    client._request("PUT", update_path, json=body)
    print(f"✅ 已补充 {len(to_add)} 个选项")
    return 0


if __name__ == "__main__":
    sys.exit(main())
