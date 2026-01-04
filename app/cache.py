"""
Simple in-memory LRU cache for FAQ retrieval results.
Cache key: tenant_id + hash(normalized_primary_query)
Cache value: FAQ answer payload + timestamp
TTL: 10 minutes
"""
import time
import hashlib
from typing import Optional, Dict, Tuple
from collections import OrderedDict


class LRUCache:
    """Simple LRU cache with TTL."""
    
    def __init__(self, max_size: int = 1000, ttl_seconds: int = 600):
        self.max_size = max_size
        self.ttl_seconds = ttl_seconds
        self.cache: OrderedDict[str, Tuple[Dict, float]] = OrderedDict()
    
    def _hash_query(self, query: str) -> str:
        """Generate hash for query (privacy-safe)."""
        if not query:
            return ""
        return hashlib.sha256(query.encode('utf-8')).hexdigest()[:16]
    
    def _is_expired(self, timestamp: float) -> bool:
        """Check if cache entry is expired."""
        return time.time() - timestamp > self.ttl_seconds
    
    def _cleanup_expired(self):
        """Remove expired entries."""
        now = time.time()
        expired_keys = [
            key for key, (_, ts) in self.cache.items()
            if now - ts > self.ttl_seconds
        ]
        for key in expired_keys:
            self.cache.pop(key, None)
    
    def get(self, tenant_id: str, normalized_query: str) -> Optional[Dict]:
        """
        Get cached result if available and not expired.
        Returns None if not found or expired.
        """
        self._cleanup_expired()
        
        query_hash = self._hash_query(normalized_query)
        key = f"{tenant_id}:{query_hash}"
        
        if key in self.cache:
            payload, timestamp = self.cache[key]
            if not self._is_expired(timestamp):
                # Move to end (most recently used)
                self.cache.move_to_end(key)
                return payload
        
        return None
    
    def put(self, tenant_id: str, normalized_query: str, payload: Dict):
        """
        Store result in cache.
        Evicts oldest entry if cache is full.
        """
        self._cleanup_expired()
        
        query_hash = self._hash_query(normalized_query)
        key = f"{tenant_id}:{query_hash}"
        
        # Remove if exists (will re-add at end)
        if key in self.cache:
            self.cache.pop(key)
        
        # Evict oldest if at capacity
        if len(self.cache) >= self.max_size:
            self.cache.popitem(last=False)  # Remove oldest
        
        # Add new entry
        self.cache[key] = (payload.copy(), time.time())
    
    def clear(self):
        """Clear all cache entries."""
        self.cache.clear()
    
    def stats(self) -> Dict:
        """Get cache statistics."""
        self._cleanup_expired()
        return {
            "size": len(self.cache),
            "max_size": self.max_size,
            "ttl_seconds": self.ttl_seconds
        }


# Global cache instance
_retrieval_cache = LRUCache(max_size=1000, ttl_seconds=600)


def get_cached_result(tenant_id: str, normalized_query: str) -> Optional[Dict]:
    """Get cached FAQ result."""
    return _retrieval_cache.get(tenant_id, normalized_query)


def cache_result(tenant_id: str, normalized_query: str, payload: Dict):
    """Cache FAQ result."""
    _retrieval_cache.put(tenant_id, normalized_query, payload)


def get_cache_stats() -> Dict:
    """Get cache statistics."""
    return _retrieval_cache.stats()


