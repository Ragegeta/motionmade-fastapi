from dotenv import load_dotenv
load_dotenv()

import os
import psycopg

db = os.environ["DATABASE_URL"]
tenant_id = "motionmade"
tenant_name = "MotionMade"

with psycopg.connect(db) as conn:
    conn.execute(
        "INSERT INTO tenants (id, name) VALUES (%s, %s) ON CONFLICT (id) DO UPDATE SET name=EXCLUDED.name",
        (tenant_id, tenant_name),
    )
    conn.commit()

print("Tenant OK:", tenant_id)