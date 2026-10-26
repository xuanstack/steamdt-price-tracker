"""从 SteamDT 拉取饰品基础信息，写入 items 表。

修复要点（2026-10-26）：
1. 字段映射修正：接口返回的是 name（中文） / marketHashName，不是 nameCn / nameEn。
2. 防覆盖：ON DUPLICATE KEY UPDATE 使用 COALESCE，新值为空时保留库里已有的中文名。
3. 接口一次返回全量数据，不再做无效的分页循环。
4. 写库前做字段自检，接口字段一变立刻中止，避免再把 NULL 写进去。
"""

import os
import sys

import pymysql
import requests
from dotenv import load_dotenv

load_dotenv()

STEAMDT_API_KEY = os.getenv("STEAMDT_API_KEY")
STEAMDT_BASE = "https://open.steamdt.com"
API_URL = f"{STEAMDT_BASE}/open/cs2/v1/base"

HEADERS = {
    "Authorization": f"Bearer {STEAMDT_API_KEY}",
    "Content-Type": "application/json",
}

# TODO: 口令后续移入 .env（DB_HOST / DB_USER_RW / DB_PASS_RW），此处暂保持原配置
DB_WRITER = {
    "host": os.getenv("DB_HOST", "127.0.0.1"),
    "port": 3306,
    "user": os.getenv("DB_USER_RW", "root"),
    "password": os.getenv("DB_PASS_RW", ""),
    "database": "steamdt_db",
    "charset": "utf8mb4",
    "cursorclass": pymysql.cursors.DictCursor,
}

# 接口必须提供的字段，缺任何一个就中止
REQUIRED_KEYS = {"marketHashName", "name"}

UPSERT_SQL = """
    INSERT INTO items (market_hash_name, name_cn, created_at, updated_at)
    VALUES (%s, %s, NOW(), NOW()) AS new
    ON DUPLICATE KEY UPDATE
        name_cn = COALESCE(new.name_cn, items.name_cn),
        updated_at = NOW()
"""


def fetch_base():
    """拉取饰品基础数据（该接口一次返回全量，不支持分页）。"""
    resp = requests.get(API_URL, headers=HEADERS, timeout=90)
    resp.raise_for_status()
    body = resp.json()

    if not body.get("success"):
        raise RuntimeError(
            "接口返回失败: errorCode=%s errorMsg=%s"
            % (body.get("errorCode"), body.get("errorMsg"))
        )
    return body.get("data") or []


def main():
    if not STEAMDT_API_KEY:
        sys.exit("[!] 未找到 STEAMDT_API_KEY，请先在 .env 中配置")

    try:
        data = fetch_base()
    except Exception as e:
        sys.exit("[!] 拉取接口失败：%s" % e)

    if not data:
        sys.exit("[!] 接口返回 0 条数据，未做任何写入")

    # 字段自检：接口改了字段名就停下，宁可不写也不写坏
    missing = REQUIRED_KEYS - set(data[0].keys())
    if missing:
        sys.exit(
            "[!] 接口字段发生变化，缺少 %s；当前字段为 %s。已中止，未写库。"
            % (sorted(missing), list(data[0].keys()))
        )

    rows = []
    skipped = 0
    for item in data:
        mhn = (item.get("marketHashName") or "").strip()
        cn = (item.get("name") or "").strip()
        if not mhn or not cn:
            skipped += 1
            continue
        rows.append((mhn, cn))

    if not rows:
        sys.exit("[!] 没有可写入的有效数据（marketHashName 或 name 为空）")

    print("[*] 接口返回 %d 条，有效 %d 条，跳过 %d 条" % (len(data), len(rows), skipped))

    conn = pymysql.connect(**DB_WRITER)
    try:
        with conn.cursor() as cur:
            cur.executemany(UPSERT_SQL, rows)
        conn.commit()
    except Exception as e:
        conn.rollback()
        sys.exit("[!] 写库失败，已回滚：%s" % e)
    finally:
        conn.close()

    # 写后自检：中文名非空率太低就报警
    try:
        conn = pymysql.connect(**DB_WRITER)
        with conn.cursor() as cur:
            cur.execute(
                "SELECT COUNT(*) AS total, "
                "SUM(name_cn IS NOT NULL AND name_cn <> '') AS filled FROM items"
            )
            stat = cur.fetchone()
        conn.close()
        total = stat["total"] or 0
        filled = stat["filled"] or 0
        rate = (filled * 100.0 / total) if total else 0
        print("[✓] items 共 %d 条，中文名已填充 %d 条（%.1f%%）" % (total, filled, rate))
        if rate < 50:
            print("[!] 中文名覆盖率偏低，请检查接口字段是否又变了")
    except Exception as e:
        print("[warn] 写后自检失败：%s" % e)


if __name__ == "__main__":
    main()

