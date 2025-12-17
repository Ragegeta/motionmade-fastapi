import psycopg
from pgvector.psycopg import register_vector
from psycopg.rows import dict_row
from .settings import settings

def _connect(dsn, **kwargs):
    conn = _connect(dsn, **kwargs)
    register_vector(conn)
    return conn
def get_conn():
    return _connect(settings.DATABASE_URL, row_factory=dict_row)