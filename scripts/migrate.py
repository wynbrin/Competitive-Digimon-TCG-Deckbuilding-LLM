# scripts/migrate.py
import sys, os
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.append(ROOT)

import os
import psycopg2
from app.db.connection import get_connection

SCHEMA_DIR = "schema"

def apply_sql_file(conn, path):
    print(f"Applying {path}...")
    with open(path, "r", encoding="utf-8") as f:
        sql = f.read()
    with conn.cursor() as cur:
        cur.execute(sql)
    conn.commit()
    print(f"✓ Applied {path}")

def main():
    conn = get_connection()

    sql_files = sorted(
        f for f in os.listdir(SCHEMA_DIR)
        if f.endswith(".sql")
    )

    if not sql_files:
        print("No SQL files found in schema/")
        return

    for filename in sql_files:
        apply_sql_file(conn, os.path.join(SCHEMA_DIR, filename))

    conn.close()
    print("All migrations applied.")

if __name__ == "__main__":
    main()
