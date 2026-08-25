import sqlite3
import os
import shutil
import time

print("=" * 60)
print("CLEARING ALL NALLY SESSIONS")
print("=" * 60)

# 1. Clear nally.db
db_path = "data/nally.db"
if os.path.exists(db_path):
    conn = sqlite3.connect(db_path)
    tables = conn.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()
    total = 0
    for table in tables:
        name = table[0]
        count = conn.execute(f"SELECT COUNT(*) FROM {name}").fetchone()[0]
        if count > 0 and name != "sqlite_sequence":
            conn.execute(f"DELETE FROM {name}")
            print(f"  nally.db.{name}: cleared {count} rows")
            total += count
    conn.commit()
    conn.close()
    sqlite3.connect(db_path).execute("VACUUM")
    print(f"  nally.db: total {total} rows cleared")

# 2. Clear nally_memory.db
mem_path = "data/nally_memory.db"
if os.path.exists(mem_path):
    conn = sqlite3.connect(mem_path)
    tables = conn.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()
    total = 0
    for table in tables:
        name = table[0]
        count = conn.execute(f"SELECT COUNT(*) FROM {name}").fetchone()[0]
        if count > 0 and name != "sqlite_sequence":
            conn.execute(f"DELETE FROM {name}")
            print(f"  nally_memory.db.{name}: cleared {count} rows")
            total += count
    conn.commit()
    conn.close()
    sqlite3.connect(mem_path).execute("VACUUM")
    print(f"  nally_memory.db: total {total} rows cleared")

# 3. Clear checkpoints.db
cp_path = "data/checkpoints.db"
if os.path.exists(cp_path):
    conn = sqlite3.connect(cp_path)
    tables = conn.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()
    total = 0
    for table in tables:
        name = table[0]
        try:
            count = conn.execute(f"SELECT COUNT(*) FROM [{name}]").fetchone()[0]
            if count > 0:
                conn.execute(f"DELETE FROM [{name}]")
                print(f"  checkpoints.db.{name}: cleared {count} rows")
                total += count
        except Exception as e:
            print(f"  checkpoints.db.{name}: skipped ({e})")
    conn.commit()
    conn.close()
    sqlite3.connect(cp_path).execute("VACUUM")
    print(f"  checkpoints.db: total {total} rows cleared")

# 4. Clear receipts
receipts_path = "data/receipts.jsonl"
if os.path.exists(receipts_path):
    size = os.path.getsize(receipts_path)
    open(receipts_path, "w").close()
    print(f"  receipts.jsonl: cleared ({size} bytes)")

# 5. Clear generated images
gen_dir = "data/generated"
if os.path.exists(gen_dir):
    files = os.listdir(gen_dir)
    for f in files:
        fp = os.path.join(gen_dir, f)
        if os.path.isfile(fp):
            os.remove(fp)
    print(f"  data/generated: cleared {len(files)} files")

# 6. Clear voice tmp
voice_dir = "data/voice_tmp"
if os.path.exists(voice_dir):
    files = os.listdir(voice_dir)
    for f in files:
        fp = os.path.join(voice_dir, f)
        if os.path.isfile(fp):
            os.remove(fp)
    print(f"  data/voice_tmp: cleared {len(files)} files")

# 7. Clear pending approvals
if os.path.exists(db_path):
    conn = sqlite3.connect(db_path)
    try:
        conn.execute("DELETE FROM pending_approvals")
        print("  pending_approvals: cleared")
    except:
        pass
    try:
        conn.execute("DELETE FROM stream_events")
        print("  stream_events: cleared")
    except:
        pass
    conn.commit()
    conn.close()

print("\n" + "=" * 60)
print("ALL SESSIONS CLEARED")
print("=" * 60)
