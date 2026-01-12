import psycopg
from contextlib import contextmanager
from pgvector.psycopg import register_vector
from .settings import settings

# Global connection pool (initialized on first use)
_pool = None
_pool_type = None  # Track which pooling method is active

def _init_pool():
    """Initialize the connection pool (lazy initialization).
    
    Uses psycopg_pool if available, otherwise falls back to thread-local connections.
    """
    global _pool, _pool_type
    if _pool is None:
        try:
            # Try to use psycopg_pool (separate package for psycopg3)
            from psycopg_pool import ConnectionPool
            _pool = ConnectionPool(
                settings.DATABASE_URL,
                min_size=2,
                max_size=10,
                open=True  # Open pool immediately
            )
            _pool_type = "psycopg_pool"
            print("[db] Using psycopg_pool for connection pooling")
        except ImportError:
            # Fallback: use thread-local connection reuse (simple pooling)
            from threading import local
            _thread_local = local()
            
            def _get_thread_conn():
                """Get or create a thread-local connection."""
                if not hasattr(_thread_local, 'conn') or _thread_local.conn.closed:
                    _thread_local.conn = psycopg.connect(settings.DATABASE_URL)
                    register_vector(_thread_local.conn)
                return _thread_local.conn
            
            _pool = {"type": "thread_local", "get_conn": _get_thread_conn, "local": _thread_local}
            _pool_type = "thread_local"
            print("[db] Using thread-local connection reuse (psycopg_pool not available)")
    return _pool

@contextmanager
def get_conn():
    """Get a database connection from the pool.
    
    Usage:
        with get_conn() as conn:
            conn.execute("SELECT ...")
    """
    pool = _init_pool()
    
    if isinstance(pool, dict) and pool.get("type") == "thread_local":
        # Thread-local fallback (simple pooling)
        conn = pool["get_conn"]()
        try:
            yield conn
        except Exception:
            # If connection is broken, close it so next call creates a new one
            try:
                conn.close()
            except:
                pass
            if hasattr(pool["local"], 'conn'):
                delattr(pool["local"], 'conn')
            raise
    else:
        # Use psycopg_pool ConnectionPool
        with pool.connection() as conn:
            register_vector(conn)
            yield conn

def get_pool_status():
    """Get connection pool status for debugging."""
    global _pool, _pool_type
    if _pool is None:
        return {"status": "not_initialized", "type": None}
    
    if _pool_type == "psycopg_pool":
        try:
            return {
                "status": "active",
                "type": "psycopg_pool",
                "min_size": _pool.min_size if hasattr(_pool, 'min_size') else None,
                "max_size": _pool.max_size if hasattr(_pool, 'max_size') else None,
            }
        except:
            return {"status": "active", "type": "psycopg_pool", "details": "unknown"}
    elif _pool_type == "thread_local":
        return {
            "status": "active",
            "type": "thread_local",
            "note": "Fallback mode - psycopg_pool not available"
        }
    else:
        return {"status": "unknown", "type": None}
