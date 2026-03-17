import sqlite3

conn = sqlite3.connect("app.db")
cur = conn.cursor()

cur.execute("PRAGMA table_info(orders)")
columns = [row[1] for row in cur.fetchall()]

if "created_at" not in columns:
    cur.execute("ALTER TABLE orders ADD COLUMN created_at TEXT")
    print("Coloana created_at a fost adăugată în orders.")
else:
    print("Coloana created_at există deja.")

conn.commit()
conn.close()