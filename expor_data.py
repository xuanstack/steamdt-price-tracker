import pymysql
import requests
import time
from datetime import datetime

# ===== 数据库配置 =====
DB_READER = {
    'host': os.getenv("DB_HOST", "127.0.0.1"), 'port': 3306,
    'user': os.getenv("DB_USER_RO", "root"), 'password': os.getenv("DB_PASS_RO", ""),
    'database': 'steamdt_db', 'charset': 'utf8mb4',
    'cursorclass': pymysql.cursors.DictCursor
}
DB_WRITER = {
    'host': os.getenv("DB_HOST", "127.0.0.1"), 'port': 3306,
    'user': os.getenv("DB_USER_RW", "root"), 'password': os.getenv("DB_PASS_RW", ""),
    'database': 'steamdt_db', 'charset': 'utf8mb4',
    'cursorclass': pymysql.cursors.DictCursor
}

# ===== SteamDT 配置 =====
import os
from dotenv import load_dotenv
load_dotenv()
STEAMDT_KEY = os.getenv("STEAMDT_API_KEY")
BASE = "https://open.steamdt.com"
HEADERS = {"Authorization": f"Bearer {STEAMDT_KEY}"}

# ===== 限速配置 =====
# 官方限制 60 次/分钟，留点余量用 55 次/分钟
RATE_PER_MIN = 55
INTERVAL = 60.0 / RATE_PER_MIN   # 每次请求后 sleep 的秒数

# 每次运行最多抓多少条（避免一次跑太久中断）
MAX_PER_RUN = 5000


def get_items_without_price(limit):
    """获取还没有价格记录的饰品"""
    conn = pymysql.connect(**DB_READER)
    cursor = conn.cursor()
    cursor.execute("""
        SELECT i.id, i.market_hash_name
        FROM items i
        WHERE i.id NOT IN (SELECT DISTINCT item_id FROM prices)
        ORDER BY i.id
        LIMIT %s
    """, (limit,))
    items = cursor.fetchall()
    cursor.close()
    conn.close()
    return items


def get_total_remaining():
    conn = pymysql.connect(**DB_READER)
    cursor = conn.cursor()
    cursor.execute("""
        SELECT COUNT(*) AS c FROM items
        WHERE id NOT IN (SELECT DISTINCT item_id FROM prices)
    """)
    n = cursor.fetchone()['c']
    cursor.close()
    conn.close()
    return n


def fetch_price(market_hash_name):
    """调 SteamDT 查价格，返回 (platforms, error)"""
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
            msg = data.get("errorMsg", "unknown")
            # 4005 = 限流，需要等待
            if code == 4005:
                return None, "RATE_LIMIT"
            return None, f"{code}: {msg}"

        return data.get("data", []) or [], None
    except Exception as e:
        return None, str(e)[:80]


def save_prices(item_id, platforms):
    """把平台价格写入 prices 表"""
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
    remaining = get_total_remaining()
    print(f"[*] 全库还有 {remaining} 条饰品没有价格记录")

    if remaining == 0:
        print("[✓] 已全部抓取完成")
        return

    batch_size = min(MAX_PER_RUN, remaining)
    print(f"[*] 本次运行抓取 {batch_size} 条，预计耗时 {batch_size * INTERVAL / 60:.0f} 分钟")
    print(f"[*] 限速：{RATE_PER_MIN} 次/分钟\n")

    items = get_items_without_price(batch_size)
    total = len(items)

    success = 0
    fail = 0
    empty = 0
    start = time.time()

    for i, item in enumerate(items, 1):
        item_id = item['id']
        mhn = item['market_hash_name']

        platforms, err = fetch_price(mhn)

        # 处理限流：等待 60 秒再重试一次
        if err == "RATE_LIMIT":
            print(f"  [!] 被限流，等待 65 秒...")
            time.sleep(65)
            platforms, err = fetch_price(mhn)

        if err:
            fail += 1
            print(f"[{i}/{total}] ✗ {mhn[:45]} → {err}")
        elif not platforms:
            empty += 1
            print(f"[{i}/{total}] ○ {mhn[:45]} → 无平台数据")
        else:
            n = save_prices(item_id, platforms)
            success += 1
            print(f"[{i}/{total}] ✓ {mhn[:45]} → {n} 个平台")

        # 限速
        time.sleep(INTERVAL)

        # 每 50 条打印进度
        if i % 50 == 0:
            elapsed = time.time() - start
            speed = i / elapsed * 60
            eta = (total - i) / (i / elapsed)
            print(f"\n  === 进度 {i}/{total} | 成功 {success} 无数据 {empty} 失败 {fail} "
                  f"| 速度 {speed:.1f}/分钟 | 剩余 {eta/60:.0f} 分钟 ===\n")

    elapsed = time.time() - start
    print(f"\n[✓] 本次运行完成")
    print(f"[✓] 成功 {success} 条，无数据 {empty} 条，失败 {fail} 条")
    print(f"[✓] 耗时 {elapsed/60:.1f} 分钟")
    print(f"[✓] 剩余 {get_total_remaining()} 条未抓取")


if __name__ == "__main__":
    main()