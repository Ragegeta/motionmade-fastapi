#!/usr/bin/env python
"""Quick test script for debug endpoint."""
from app.settings import settings
from app.main import app
from fastapi.testclient import TestClient

# Test with DEBUG=False
print("=== Test 1: DEBUG=False (should 404) ===")
settings.DEBUG = False
client = TestClient(app)
r = client.get("/debug/routes")
print(f"Status: {r.status_code}")
print(f"Response: {r.json()}\n")

# Test with DEBUG=True
print("=== Test 2: DEBUG=True (should return routes) ===")
settings.DEBUG = True
client = TestClient(app)
r = client.get("/debug/routes")
print(f"Status: {r.status_code}")
routes = r.json()["routes"]
admin_routes = [x for x in routes if "/admin/tenant" in x["path"]]
print(f"Total routes: {len(routes)}")
print(f"Admin routes found: {len(admin_routes)}")
print("\nAdmin routes:")
for route in admin_routes:
    print(f"  {route['method']} {route['path']}")




