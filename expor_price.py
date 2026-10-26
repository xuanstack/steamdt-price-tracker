import os
import pymysql
import csv
from datetime import datetime

# ===== 数据库配置 =====
DB_CONFIG = {
    'host': os.getenv("DB_HOST", "127.0.0.1"),
    'port': 3306,
    'user': os.getenv("DB_USER_RO", "root"),
    'password': os.getenv("DB_PASS_RO", ""),
    'database': 'steamdt_db',
    'charset': 'utf8mb4',
    'cursorclass': pymysql.cursors.DictCursor
}

TXT_FILE = 'steamdt_priced_report.txt'
CSV_FILE = 'steamdt_priced_report.csv'

# 列宽
W_ID = 6
W_NAME = 42
W_PRICE = 12
W_PLATFORM = 12


def truncate(s, n):
    if not s:
        return ''
    return s if len(s) <= n else s[:n - 3] + '...'


def row_txt(id_str, name, price, platform):
    return f"|{id_str:>{W_ID}}|{name:<{W_NAME}}|{price:>{W_PRICE}}|{platform:<{W_PLATFORM}}|"


def sep_txt(char='-'):
    return f"|{char * W_ID}|{char * W_NAME}|{char * W_PRICE}|{char * W_PLATFORM}|"


def export():
    conn = pymysql.connect(**DB_CONFIG)
    cursor = conn.cursor()

    sql = """
        SELECT
            i.id AS item_id,
            i.name_cn AS name_cn,
            i.market_hash_name AS market_hash_name,
            p.platform AS platform,
            p.sell_price AS sell_price,
            p.buy_price AS buy_price,
            p.sell_num AS sell_num,
            p.buy_num AS buy_num,
            p.recorded_at AS recorded_at
        FROM prices p
        INNER JOIN items i ON p.item_id = i.id
        WHERE p.sell_price > 0
        ORDER BY i.id ASC, p.sell_price ASC
    """
    cursor.execute(sql)
    rows = cursor.fetchall()

    if not rows:
        print("[!] prices 表里没有数据，请先运行 steamdt_crawler.py 抓取")
        cursor.close()
        conn.close()
        return

    total_items = len({r['item_id'] for r in rows})
    total_rows = len(rows)

    # ===== 写 TXT =====
    with open(TXT_FILE, 'w', encoding='utf-8') as f:
        f.write("=" * 80 + "\n")
        f.write("  CS2 饰品价格导出报告\n")
        f.write(f"  导出时间：{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n")
        f.write(f"  饰品数量：{total_items} 款\n")
        f.write(f"  价格记录：{total_rows} 条\n")
        f.write("=" * 80 + "\n\n")

        f.write(sep_txt('=') + "\n")
        f.write(row_txt('ID', '名称', '价格', '平台') + "\n")
        f.write(sep_txt('=') + "\n")

        for r in rows:
            id_str = str(r['item_id'])
            name = r['name_cn'] or r['market_hash_name'] or '未知'
            name = truncate(name, W_NAME)
            price_str = f"¥{r['sell_price']:.2f}"
            platform = r['platform'] or '-'

            f.write(row_txt(id_str, name, price_str, platform) + "\n")

        f.write(sep_txt('=') + "\n")
        f.write(f"\n合计：{total_items} 款饰品，{total_rows} 条价格记录\n")

        # 热门饰品汇总
        f.write("\n")
        f.write("=" * 80 + "\n")
        f.write("  各饰品最低价汇总\n")
        f.write("=" * 80 + "\n\n")

        grouped = {}
        for r in rows:
            iid = r['item_id']
            if iid not in grouped:
                grouped[iid] = {
                    'id': iid,
                    'name': r['name_cn'] or r['market_hash_name'] or '未知',
                    'lowest': r['sell_price'],
                    'platform': r['platform'],
                    'count': 1
                }
            else:
                grouped[iid]['count'] += 1
                if r['sell_price'] < grouped[iid]['lowest']:
                    grouped[iid]['lowest'] = r['sell_price']
                    grouped[iid]['platform'] = r['platform']

        sorted_g = sorted(grouped.values(), key=lambda x: x['lowest'])

        f.write(sep_txt('=') + "\n")
        f.write(row_txt('ID', '饰品名称', '最低价', '平台') + "\n")
        f.write(sep_txt('=') + "\n")
        for g in sorted_g:
            f.write(row_txt(
                str(g['id']),
                truncate(g['name'], W_NAME),
                f"¥{g['lowest']:.2f}",
                g['platform']
            ) + "\n")
        f.write(sep_txt('=') + "\n")

    print(f"[✓] TXT 导出成功：{TXT_FILE}")

    # ===== 写 CSV =====
    with open(CSV_FILE, 'w', newline='', encoding='utf-8-sig') as f:
        writer = csv.writer(f)
        writer.writerow(['饰品ID', '中文名称', '市场英文名', '平台', '在售最低价',
                         '求购最高价', '在售数量', '求购数量', '记录时间'])
        for r in rows:
            writer.writerow([
                r['item_id'],
                r['name_cn'] or '',
                r['market_hash_name'] or '',
                r['platform'] or '',
                f"{r['sell_price']:.2f}" if r['sell_price'] else '',
                f"{r['buy_price']:.2f}" if r['buy_price'] else '',
                r['sell_num'] or 0,
                r['buy_num'] or 0,
                r['recorded_at'].strftime('%Y-%m-%d %H:%M:%S') if r['recorded_at'] else ''
            ])

    print(f"[✓] CSV 导出成功：{CSV_FILE}")
    print(f"\n[✓] 饰品 {total_items} 款，价格记录 {total_rows} 条")

    cursor.close()
    conn.close()


if __name__ == "__main__":
    export()