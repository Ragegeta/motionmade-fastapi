import psycopg
from pgvector.psycopg import register_vector
from .settings import settings

def get_conn():
    conn = psycopg.connect(settings.DATABASE_URL)
    register_vector(conn)
    return conn