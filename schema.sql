-- SteamDT 饰品价格查询系统 —— 数据库结构
-- MySQL 8.0.19+ / 8.4

CREATE DATABASE IF NOT EXISTS steamdt_db
    DEFAULT CHARACTER SET utf8mb4
    COLLATE utf8mb4_0900_ai_ci;

USE steamdt_db;

CREATE TABLE IF NOT EXISTS items (
    id               INT           NOT NULL AUTO_INCREMENT,
    market_hash_name VARCHAR(255)  NOT NULL COMMENT '英文市场名，唯一标识',
    name_cn          VARCHAR(255)  DEFAULT NULL COMMENT '中文名称',
    name_en          VARCHAR(255)  DEFAULT NULL COMMENT '英文名称',
    image_url        VARCHAR(500)  DEFAULT NULL COMMENT '图片地址',
    created_at       DATETIME      DEFAULT CURRENT_TIMESTAMP,
    updated_at       DATETIME      DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    PRIMARY KEY (id),
    UNIQUE KEY uk_market_hash_name (market_hash_name),
    KEY idx_name_cn (name_cn)
) ENGINE = InnoDB DEFAULT CHARSET = utf8mb4 COMMENT = '饰品基础信息';

CREATE TABLE IF NOT EXISTS prices (
    id          BIGINT        NOT NULL AUTO_INCREMENT,
    item_id     INT           NOT NULL COMMENT '关联 items.id',
    platform    VARCHAR(50)   NOT NULL COMMENT '交易平台名称',
    sell_price  DECIMAL(10,2) DEFAULT NULL COMMENT '最低售价',
    buy_price   DECIMAL(10,2) DEFAULT NULL COMMENT '最高求购价',
    sell_num    INT           DEFAULT NULL COMMENT '在售数量',
    buy_num     INT           DEFAULT NULL COMMENT '求购数量',
    recorded_at DATETIME      DEFAULT CURRENT_TIMESTAMP COMMENT '采集时间',
    PRIMARY KEY (id),
    KEY idx_item_platform (item_id, platform),
    KEY idx_recorded_at (recorded_at),
    CONSTRAINT fk_prices_item FOREIGN KEY (item_id) REFERENCES items (id) ON DELETE CASCADE
) ENGINE = InnoDB DEFAULT CHARSET = utf8mb4 COMMENT = '价格快照';
