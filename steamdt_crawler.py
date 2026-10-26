import os
import pymysql
import requests
import time
from dotenv import load_dotenv

load_dotenv()

# ===== 数据库配置 =====
DB_READER = {
    'host': os.getenv("DB_HOST", "127.0.0.1"),
    'port': 3306,
    'user': os.getenv("DB_USER_RO", "root"),
    'password': os.getenv("DB_PASS_RO", ""),
    'database': 'steamdt_db',
    'charset': 'utf8mb4',
    'cursorclass': pymysql.cursors.DictCursor
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

# ===== SteamDT 配置 =====
STEAMDT_KEY = os.getenv("STEAMDT_API_KEY")
BASE = "https://open.steamdt.com"
HEADERS = {"Authorization": f"Bearer {STEAMDT_KEY}"}

# ===== 抓取配置 =====
LIMIT = 100          # 本次抓取条数
INTERVAL = 1.2       # 每条间隔 1.2 秒


def get_items():
    """优先取热门饰品的 100 条（有中文名的优先）"""
    conn = pymysql.connect(**DB_READER)
    cursor = conn.cursor()

    # 用 f-string 拼 LIMIT，避免 % 转义问题
    sql = f"""
        SELECT i.id, i.market_hash_name, i.name_cn
        FROM items i
        WHERE i.id NOT IN (SELECT DISTINCT item_id FROM prices)
          AND i.name_cn IS NOT NULL
          AND i.name_cn != ''
        ORDER BY
          CASE
            WHEN i.name_cn LIKE '%AK-47%' THEN 1
            WHEN i.name_cn LIKE '%M4A4%' THEN 2
            WHEN i.name_cn LIKE '%AWP%' THEN 3
            WHEN i.name_cn LIKE '%蝴蝶刀%' THEN 4
            WHEN i.name_cn LIKE '%爪子刀%' THEN 5
            ELSE 99
          END,
          i.id ASC
        LIMIT {LIMIT}
    """
    cursor.execute(sql)
    items = cursor.fetchall()
    cursor.close()
    conn.close()
    return items


def fetch_price(market_hash_name):
    """调用 SteamDT 查询单个饰品价格"""
    try:
        r = requests.get(
            f"{BASE}/open/cs2/v1/price/single",
            headers=HEADERS,
            params={"marketHashName": market_hash_name, "currency": "23"},
            timeout=15
        )
        r.raise_for_status()
        data = r.json()

        if not data.get("success"):
            code = data.get("errorCode")
            msg = data.get("errorMsg", "")
            if code == 4005:
                return None, "RATE_LIMIT"
            return None, f"{code}: {msg}"

        return data.get("data", []) or [], None
    except Exception as e:
        return None, str(e)[:80]


def save_prices(item_id, platforms):
    """把价格数据写入 prices 表"""
    if not platforms:
        return 0

    conn = pymysql.connect(**DB_WRITER)
    cursor = conn.cursor()
    sql = """
        INSERT INTO prices (item_id, platform, sell_price, buy_price, sell_num, buy_num)
        VALUES (%s, %s, %s, %s, %s, %s)
    """
    count = 0
    for p in platforms:
        cursor.execute(sql, (
            item_id,
            p.get("platform"),
            p.get("sellPrice") or 0,
            p.get("biddingPrice") or 0,
            p.get("sellCount") or 0,
            p.get("biddingCount") or 0
        ))
        count += 1
    conn.commit()
    cursor.close()
    conn.close()
    return count


def main():
    items = get_items()
    total = len(items)

    if total == 0:
        print("[✓] 没有需要抓取的饰品")
        return

    print(f"[*] 本次抓取 {total} 条\n")

    ok = 0
    empty = 0
    fail = 0
    start = time.time()

    for i, item in enumerate(items, 1):
        mhn = item['market_hash_name']
        platforms, err = fetch_price(mhn)

        # 限流处理
        if err == "RATE_LIMIT":
            print(f"  [!] 限流，等待 60 秒...")
            time.sleep(60)
            platforms, err = fetch_price(mhn)

        if err:
            fail += 1
            print(f"[{i}/{total}] ✗ {mhn[:45]} → {err}")
        elif not platforms:
            empty += 1
            print(f"[{i}/{total}] ○ {mhn[:45]} → 无数据")
        else:
            n = save_prices(item['id'], platforms)
            ok += 1
            print(f"[{i}/{total}] ✓ {mhn[:45]} → {n} 个平台")

        time.sleep(INTERVAL)

    elapsed = time.time() - start
    print(f"\n[✓] 完成！成功 {ok}，无数据 {empty}，失败 {fail}")
    print(f"[✓] 耗时 {elapsed:.1f} 秒")


if __name__ == "__main__":
    main()