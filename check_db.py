import sqlite3
c = sqlite3.connect("data/nally.db")
tables = [r[0] for r in c.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()]
print("Tables:", tables)
for t in tables:
    count = c.execute(f"SELECT COUNT(*) FROM [{t}]").fetchone()[0]
    cols = [d[1] for d in c.execute(f"PRAGMA table_info([{t}])").fetchall()]
    print(f"  {t}: {count} rows, cols={cols}")
c.close()
