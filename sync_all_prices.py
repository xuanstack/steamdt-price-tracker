import os
import time
import requests
import pymysql
from dotenv import load_dotenv

load_dotenv()

STEAMDT_API_KEY = os.getenv("STEAMDT_API_KEY")
if not STEAMDT_API_KEY:
    raise SystemExit("未找到 STEAMDT_API_KEY，请先在 .env 或环境变量中设置")

STEAMDT_BASE = "https://open.steamdt.com"

HEADERS = {
    "Authorization": f"Bearer {STEAMDT_API_KEY}",
    "Content-Type": "application/json"
}

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


def sync_all_prices(currency="23", sleep_seconds=0.5):
    """
    一次性抓取 items 表里所有饰品的 SteamDT 价格，并写入 prices 表。
    currency="23" 表示人民币。
    sleep_seconds 控制请求间隔，避免触发限流。
    """

    # 1. 读取所有饰品
    rconn = pymysql.connect(**DB_READER)
    rcur = rconn.cursor()
    rcur.execute("SELECT id, market_hash_name FROM items ORDER BY id")
    items = rcur.fetchall()
    rcur.close()
    rconn.close()

    total = len(items)
    print(f"共找到 {total} 个饰品，开始同步...")

    # 2. 连接写库
    wconn = pymysql.connect(**DB_WRITER)
    wcur = wconn.cursor()

    insert_sql = """
        INSERT INTO prices (item_id, platform, sell_price, buy_price, sell_num, buy_num)
        VALUES (%s, %s, %s, %s, %s, %s)
    """

    ok_items = 0
    fail_items = 0
    total_prices = 0

    for idx, it in enumerate(items, 1):
        item_id = it["id"]
        market_name = it["market_hash_name"]

        try:
            resp = requests.get(
                f"{STEAMDT_BASE}/open/cs2/v1/price/single",
                headers=HEADERS,
                params={
                    "marketHashName": market_name,
                    "currency": currency
                },
                timeout=15
            )
            resp.raise_for_status()
            data = resp.json()

            platforms = data.get("data") or []

            for p in platforms:
                wcur.execute(insert_sql, (
                    item_id,
                    p.get("platform"),
                    p.get("sellPrice"),
                    p.get("biddingPrice"),
                    p.get("sellCount"),
                    p.get("biddingCount")
                ))
                total_prices += 1

            wconn.commit()
            ok_items += 1
            print(f"[{idx}/{total}] OK  {market_name} -> {len(platforms)} 条平台价格")

        except Exception as e:
            wconn.rollback()
            fail_items += 1
            print(f"[{idx}/{total}] FAIL {market_name} -> {e}")

        time.sleep(sleep_seconds)

    wcur.close()
    wconn.close()

    print("\n同步完成")
    print(f"成功饰品: {ok_items}")
    print(f"失败饰品: {fail_items}")
    print(f"写入价格条数: {total_prices}")


if __name__ == "__main__":
    # 默认人民币，每次请求间隔 0.5 秒
    sync_all_prices(currency="23", sleep_seconds=0.5)