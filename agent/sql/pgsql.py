from psycopg import sql
from psycopg_pool import ConnectionPool
from psycopg.rows import dict_row

# 数据库连接参数
DB_CONFIG = {
    "dbname": "jr_znjp",
    "user": "postgres",
    "password": "P@ssw0rd",
    "host": "192.168.0.58",
    "port": "5432"
}

# 连接池参数
POOL_MIN_SIZE = 2    # 最小空闲连接
POOL_MAX_SIZE = 10   # 最大连接数
POOL_TIMEOUT = 5     # 获取连接超时秒数

pool = ConnectionPool(
    min_size=POOL_MIN_SIZE,
    max_size=POOL_MAX_SIZE,
    timeout=POOL_TIMEOUT,
    kwargs=DB_CONFIG
)

# 启动连接池（预创建最小连接）
pool.open()
print("数据库连接池初始化完成")

# CREATE TABLE runs (
#     run_id VARCHAR(255) NOT NULL,
#     session_id VARCHAR(255) NOT NULL,
#     status VARCHAR(100) NOT NULL,
#     user_id VARCHAR(255),
#     first_human_message TEXT,
#     last_ai_message TEXT,
#     created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
#     updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
# );
#
# CREATE INDEX idx_runs_session_id ON runs (session_id);

def execute_sql(query: sql.SQL, params: tuple = (), fetch: bool = False):
    """
    通用执行SQL
    :param query: psycopg.sql.SQL对象
    :param params: sql参数元组
    :param fetch: 是否返回查询结果
    :return: 结果/影响行数
    """
    with pool.connection() as conn:
        # with conn.cursor() as cur:
        with conn.cursor(row_factory=dict_row) as cur:
            cur.execute(query, params)
            if fetch:
                return cur.fetchall()
            res = cur.rowcount
        conn.commit()
    return res