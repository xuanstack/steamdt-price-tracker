# SteamDT 饰品价格查询系统

一个基于 **Flask + MySQL** 的 CS2 饰品价格聚合工具：对接 SteamDT 开放平台，把同一件饰品在多个交易平台的售价、求购价与挂单量聚到一起，并沉淀历史价格用于走势查询。

![Python](https://img.shields.io/badge/Python-3.12-3776AB?logo=python&logoColor=white)
![Flask](https://img.shields.io/badge/Flask-3.x-000000?logo=flask&logoColor=white)
![MySQL](https://img.shields.io/badge/MySQL-8.4-4479A1?logo=mysql&logoColor=white)

## 功能

- **关键词搜索**：支持中英文名称模糊匹配，空格分隔多个关键词时按「同时包含」处理（AND 语义），最多返回 20 条。
- **实时价格**：调用 SteamDT `/open/cs2/v1/price/single`，一次取回该饰品在各平台的售价、求购价、在售量与求购量。
- **历史价格**：每次人民币查询会落库一条快照，前端按平台拉取最近 N 条绘制走势。
- **批量同步**：脚本按固定间隔抓取，遇到限流码自动退避重试，已入库的记录自动跳过，支持断点续抓。
- **数据导出**：把价格快照导出为 CSV / TXT，便于离线核对。

## 技术栈

| 层次 | 选型 |
|---|---|
| Web 框架 | Flask |
| 数据库 | MySQL 8.4 + PyMySQL，读写账号分离 |
| 外部接口 | SteamDT 开放平台（Bearer Token 鉴权） |
| 前端 | 原生 HTML / CSS / JavaScript（无框架，约 780 行） |
| 配置 | python-dotenv |

## 目录结构

```
.
├── app.py                 # Flask 服务：搜索 / 实时价格 / 历史价格三个接口
├── templates/index.html   # 单页前端
├── static/                # 静态资源
├── update_items.py        # 拉取饰品基础信息，写入 items 表
├── steamdt_crawler.py     # 按需批量抓取价格
├── sync_all_prices.py     # 全量同步已有饰品的价格
├── expor_price.py         # 导出价格快照
├── expor_data.py          # 导出饰品基础数据
├── check.py               # 调试脚本：打印接口原始字段
├── env.example            # 环境变量示例
└── requirements.txt
```

## 快速开始

```bash
# 1. 安装依赖
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt

# 2. 配置环境变量
copy env.example .env
# 编辑 .env，填入 SteamDT API Key 与数据库账号

# 3. 建表（首次运行）
mysql -u root -p steamdt_db < schema.sql

# 4. 启动服务
python app.py
# 浏览器打开 http://127.0.0.1:5000
```

## 数据模型

```sql
items(
  id INT PK AUTO_INCREMENT,
  market_hash_name VARCHAR(255) NOT NULL UNIQUE,  -- 英文市场名，唯一键
  name_cn VARCHAR(255),                            -- 中文名
  name_en VARCHAR(255),
  image_url VARCHAR(500),
  created_at DATETIME,
  updated_at DATETIME
)

prices(
  id BIGINT PK AUTO_INCREMENT,
  item_id INT NOT NULL,          -- 关联 items.id
  platform VARCHAR(50) NOT NULL, -- 平台名，如 BUFF / C5
  sell_price DECIMAL(10,2),
  buy_price DECIMAL(10,2),
  sell_num INT,
  buy_num INT,
  recorded_at DATETIME
)
```

## 接口

| 方法 | 路径 | 参数 | 说明 |
|---|---|---|---|
| GET | `/` | — | 前端页面 |
| GET | `/api/search` | `keyword` | 关键词搜索，返回 `market_hash_name` 与 `name_cn` |
| GET | `/api/price` | `marketHashName`、`currency` | 实时多平台价格，人民币查询会写入历史 |
| GET | `/api/history` | `marketHashName`、`platform`、`limit` | 最近 N 条历史价格，按时间正序返回 |

## 注意事项

- SteamDT 开放平台对 `/base` 与 `/price/single` 有调用频次限制，超限返回 `errorCode=4005`。同步脚本已内置退避，但批量抓取仍需控制节奏。
- 饰品基础接口一次返回全量数据（4 万余条），不要做无意义的分页循环。
- `items.name_cn` 由接口的 `name` 字段写入，更新时使用 `COALESCE` 保护，避免接口字段变更时把已有中文名覆盖为空。
- 生产部署请关闭 Flask 调试模式，并使用 waitress / gunicorn 等 WSGI 服务器。

## License

MIT
