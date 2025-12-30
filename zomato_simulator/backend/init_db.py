import sqlite3
import os

DB_PATH = os.path.join(os.path.dirname(__file__), "gigworkers.db")
SCHEMA_PATH = os.path.join(os.path.dirname(__file__), "database_schema.sql")

def init_db():
    print(f"Initializing database at: {DB_PATH}")
    
    # ensure directory exists (should already)
    os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)

    # open connection
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()

    # read schema file
    with open(SCHEMA_PATH, "r", encoding="utf-8") as f:
        schema_sql = f.read()

    # execute the schema
    cursor.executescript(schema_sql)
    conn.commit()
    conn.close()

    print("Database initialized successfully!")

if __name__ == "__main__":
    init_db()
