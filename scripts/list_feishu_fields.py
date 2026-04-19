import os
import sys
from pathlib import Path

BASE_DIR = Path(__file__).parent.parent
sys.path.insert(0, str(BASE_DIR))

from dotenv import load_dotenv
from layers.syncer import FeishuClient


def main():
    load_dotenv(BASE_DIR / ".env")
    c = FeishuClient(
        os.getenv("FEISHU_APP_ID", ""),
        os.getenv("FEISHU_APP_SECRET", ""),
        os.getenv("FEISHU_BITABLE_APP_TOKEN", ""),
        os.getenv("FEISHU_BITABLE_TABLE_ID", ""),
    )
    path = f"/open-apis/bitable/v1/apps/{c.app_token}/tables/{c.table_id}/fields"
    data = c._request("GET", path, params={"page_size": 100})
    items = data.get("data", {}).get("items", [])
    print(f"字段数: {len(items)}", flush=True)
    for f in items:
        print(
            f"  type={f.get('type'):>3}  name={f.get('field_name')!r:<30}  id={f.get('field_id')}",
            flush=True,
        )


if __name__ == "__main__":
    main()
