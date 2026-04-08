"""
添加 products 表用于 quota 计费

手动运行此脚本来创建 products 表
"""
from sqlalchemy import create_engine, text
from app.config import settings

def create_products_table():
    """创建 products 表"""
    engine = create_engine(settings.database_url)

    sql = """
    CREATE TABLE IF NOT EXISTS products (
        id INT AUTO_INCREMENT PRIMARY KEY,
        code VARCHAR(50) NOT NULL UNIQUE COMMENT '商品编码',
        name VARCHAR(100) NOT NULL COMMENT '商品名称',
        price_cents INT NOT NULL COMMENT '价格（分）',
        currency VARCHAR(8) NOT NULL DEFAULT 'CNY' COMMENT '币种',
        quota_amount INT NOT NULL COMMENT '提供的提问次数',
        description VARCHAR(500) NULL COMMENT '商品描述',
        active BOOLEAN NOT NULL DEFAULT TRUE COMMENT '是否在售',
        created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP COMMENT '创建时间',
        updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP COMMENT '更新时间',
        INDEX idx_code (code),
        INDEX idx_active (active)
    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci COMMENT='商品表';
    """

    with engine.connect() as conn:
        conn.execute(text(sql))
        conn.commit()
        print("✓ products 表创建成功")

    # 插入初始商品数据
    insert_sql = """
    INSERT INTO products (code, name, price_cents, quota_amount, description, active)
    VALUES
        ('chat_5', '体验包', 990, 5, '5次提问，适合新用户体验', TRUE),
        ('chat_20', '标准包', 2990, 20, '20次提问，日常使用', TRUE),
        ('chat_50', '超值包', 5990, 50, '50次提问，深度探索', TRUE),
        ('chat_200', '年度包', 19900, 200, '200次提问，全年无忧', TRUE)
    ON DUPLICATE KEY UPDATE name=name;
    """

    with engine.connect() as conn:
        conn.execute(text(insert_sql))
        conn.commit()
        print("✓ 初始商品数据插入成功")

if __name__ == "__main__":
    create_products_table()
