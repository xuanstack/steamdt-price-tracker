import os
import json
import requests
import pymysql
from dotenv import load_dotenv

load_dotenv()

STEAMDT_API_KEY = os.getenv("STEAMDT_API_KEY")
STEAMDT_BASE = "https://open.steamdt.com"

HEADERS = {
    "Authorization": f"Bearer {STEAMDT_API_KEY}",
    "Content-Type": "application/json"
}

DB_WRITER = {
    'host': os.getenv("DB_HOST", "127.0.0.1"),
    'port': 3306,
    'user': os.getenv("DB_USER_RW", "root"),
    'password': os.getenv("DB_PASS_RW", ""),
    'database': 'steamdt_db',
    'charset': 'utf8mb4',
    'cursorclass': pymysql.cursors.DictCursor
}

CACHE_FILE = "steam_items_base.json"


def fetch_and_save():
    """请求 API，把原始数据完整保存到本地，不做任何字段解析"""
    print("正在请求 /open/cs2/v1/base ...")
    resp = requests.get(f"{STEAMDT_BASE}/open/cs2/v1/base", headers=HEADERS, timeout=30)
    print("状态码:", resp.status_code)

    raw = resp.json()
    if not raw.get("success"):
        print("请求失败:", raw)
        return

    data = raw.get("data") or []
    with open(CACHE_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)

    print(f"已保存 {len(data)} 条到 {CACHE_FILE}")
    if data:
        print("\n=== 第一条数据的字段名 ===")
        print(list(data[0].keys()))
        print("\n=== 第一条数据完整内容 ===")
        print(json.dumps(data[0], ensure_ascii=False, indent=2))


if __name__ == "__main__":
    fetch_and_save()