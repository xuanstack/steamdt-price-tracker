"""SteamDT 饰品价格查询服务。

修复要点（2026-10-26）：
1. 搜索用 COALESCE(name_cn,'')，避免 NULL LIKE 被静默判假导致"搜不到"。
2. 所有数据库连接改用 try/finally，异常路径不再泄漏连接。
3. limit 参数安全解析并限制在 1..500。
4. 历史价格改为取最近 N 条（原来取的是最旧的 N 条，走势图会冻结）。
5. 校验 SteamDT 业务码（success/errorCode），上游故障不再伪装成"无在售数据"。
6. 关闭 debug，默认只监听 127.0.0.1。
"""

import os

import pymysql
import requests
from dotenv import load_dotenv
from flask import Flask, jsonify, render_template, request

load_dotenv()

app = Flask(__name__)

STEAMDT_API_KEY = os.getenv("STEAMDT_API_KEY")
STEAMDT_BASE = "https://open.steamdt.com"

if not STEAMDT_API_KEY:
    print("[warn] 未配置 STEAMDT_API_KEY，价格接口将返回配置错误")

HEADERS = {
    "Authorization": f"Bearer {STEAMDT_API_KEY}",
    "Content-Type": "application/json",
}

# TODO: 口令后续移入 .env（DB_HOST / DB_USER_RO / DB_PASS_RO / DB_USER_RW / DB_PASS_RW）
DB_READER = {
    "host": os.getenv("DB_HOST", "127.0.0.1"),
    "port": 3306,
    "user": os.getenv("DB_USER_RO", "root"),
    "password": os.getenv("DB_PASS_RO", ""),
    "database": "steamdt_db",
    "charset": "utf8mb4",
    "cursorclass": pymysql.cursors.DictCursor,
}

DB_WRITER = {
    "host": os.getenv("DB_HOST", "127.0.0.1"),
    "port": 3306,
    "user": os.getenv("DB_USER_RW", "root"),
    "password": os.getenv("DB_PASS_RW", ""),
    "database": "steamdt_db",
    "charset": "utf8mb4",
    "cursorclass": pymysql.cursors.DictCursor,
}


def parse_limit(raw, default=50, maximum=500):
    """把 limit 参数解析成 1..maximum 的整数，非法输入回落到默认值。"""
    try:
        value = int(raw)
    except (TypeError, ValueError):
        return default
    return max(1, min(value, maximum))


@app.route("/")
def index():
    return render_template("index.html")


@app.route("/api/search", methods=["GET"])
def search_items():
    keyword = request.args.get("keyword", "").strip()
    if not keyword:
        return jsonify({"error": "keyword is required"}), 400

    parts = [p for p in keyword.split() if p]

    # COALESCE 把 NULL 变成空串，避免 name_cn 为空时整行被 LIKE 判掉
    if len(parts) == 1:
        sql = """
            SELECT market_hash_name, name_cn
            FROM items
            WHERE COALESCE(name_cn, '') LIKE %s
               OR market_hash_name LIKE %s
            LIMIT 20
        """
        params = [f"%{parts[0]}%", f"%{parts[0]}%"]
    else:
        conditions = []
        params = []
        for p in parts:
            conditions.append(
                "(COALESCE(name_cn, '') LIKE %s OR market_hash_name LIKE %s)"
            )
            params.append(f"%{p}%")
            params.append(f"%{p}%")
        sql = """
            SELECT market_hash_name, name_cn
            FROM items
            WHERE %s
            LIMIT 20
        """ % " AND ".join(conditions)

    conn = None
    try:
        conn = pymysql.connect(**DB_READER)
        with conn.cursor() as cur:
            cur.execute(sql, params)
            rows = cur.fetchall()
    except Exception as e:
        return jsonify({"error": "database query failed: %s" % e}), 500
    finally:
        if conn:
            conn.close()

    return jsonify({"data": rows})


@app.route("/api/price", methods=["GET"])
def get_price():
    market_name = request.args.get("marketHashName", "").strip()
    currency = request.args.get("currency", "23")  # 23=人民币, 1=美元

    if not market_name:
        return jsonify({"error": "marketHashName is required"}), 400

    conn = None
    try:
        conn = pymysql.connect(**DB_READER)
        with conn.cursor() as cur:
            cur.execute(
                "SELECT id FROM items WHERE market_hash_name = %s", (market_name,)
            )
            row = cur.fetchone()
    except Exception as e:
        return jsonify({"error": "database query failed: %s" % e}), 500
    finally:
        if conn:
            conn.close()

    if not row:
        return jsonify({"error": "item not found in local database"}), 404
    item_id = row["id"]

    try:
        resp = requests.get(
            f"{STEAMDT_BASE}/open/cs2/v1/price/single",
            headers=HEADERS,
            params={"marketHashName": market_name, "currency": currency},
            timeout=15,
        )
        resp.raise_for_status()
        data = resp.json()
    except Exception as e:
        return jsonify({"error": "SteamDT request failed: %s" % e}), 502

    # 上游业务码：success=false 或 errorCode!=0 都算失败
    if not data.get("success") or data.get("errorCode") not in (0, None):
        return (
            jsonify(
                {
                    "error": "SteamDT returned an error",
                    "errorCode": data.get("errorCode"),
                    "errorMsg": data.get("errorMsg"),
                }
            ),
            502,
        )

    # 只在人民币查询时写入历史，避免多币种混淆
    if currency == "23":
        platforms = data.get("data") or []
        if platforms:
            wconn = None
            try:
                wconn = pymysql.connect(**DB_WRITER)
                with wconn.cursor() as wcur:
                    wcur.executemany(
                        """
                        INSERT INTO prices
                            (item_id, platform, sell_price, buy_price, sell_num, buy_num)
                        VALUES (%s, %s, %s, %s, %s, %s)
                        """,
                        [
                            (
                                item_id,
                                p.get("platform"),
                                p.get("sellPrice") or 0,
                                p.get("biddingPrice") or 0,
                                p.get("sellCount") or 0,
                                p.get("biddingCount") or 0,
                            )
                            for p in platforms
                        ],
                    )
                wconn.commit()
                print("[ok] stored %d platform prices for item_id=%s"
                      % (len(platforms), item_id))
            except Exception as e:
                if wconn:
                    wconn.rollback()
                print("[warn] failed to store price: %s" % e)
            finally:
                if wconn:
                    wconn.close()

    return jsonify(data)


@app.route("/api/history", methods=["GET"])
def get_history():
    """从 prices 表读取最近 N 条历史价格（按时间正序返回）。"""
    market_name = request.args.get("marketHashName", "").strip()
    platform = request.args.get("platform", "").strip()
    limit = parse_limit(request.args.get("limit", 50), default=50, maximum=500)

    if not market_name:
        return jsonify({"error": "marketHashName is required"}), 400

    conn = None
    try:
        conn = pymysql.connect(**DB_READER)
        with conn.cursor() as cur:
            cur.execute(
                "SELECT id FROM items WHERE market_hash_name = %s", (market_name,)
            )
            row = cur.fetchone()
            if not row:
                return jsonify({"error": "item not found"}), 404
            item_id = row["id"]

            if platform:
                sql = """
                    SELECT * FROM (
                        SELECT platform, sell_price, buy_price, recorded_at
                        FROM prices
                        WHERE item_id = %s AND platform = %s AND sell_price > 0
                        ORDER BY recorded_at DESC
                        LIMIT %s
                    ) t ORDER BY recorded_at ASC
                """
                cur.execute(sql, (item_id, platform, limit))
            else:
                sql = """
                    SELECT * FROM (
                        SELECT platform, sell_price, buy_price, recorded_at
                        FROM prices
                        WHERE item_id = %s AND sell_price > 0
                        ORDER BY recorded_at DESC
                        LIMIT %s
                    ) t ORDER BY recorded_at ASC
                """
                cur.execute(sql, (item_id, limit))
            rows = cur.fetchall()
    except Exception as e:
        return jsonify({"error": "database query failed: %s" % e}), 500
    finally:
        if conn:
            conn.close()

    for r in rows:
        if r.get("recorded_at") and hasattr(r["recorded_at"], "strftime"):
            r["recorded_at"] = r["recorded_at"].strftime("%m-%d %H:%M")

    return jsonify({"data": rows})


if __name__ == "__main__":
    host = os.getenv("APP_HOST", "127.0.0.1")
    port = int(os.getenv("APP_PORT", "5000"))
    app.run(host=host, port=port, debug=False)
