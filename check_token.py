import sqlite3, json
from nally.mcp.oauth import _decrypt_token

conn = sqlite3.connect('C:/Users/chuki/Desktop/N.A.L.L.Y/data/nally.db')
row = conn.execute("SELECT tokens FROM mcp_oauth WHERE service='gmail'").fetchone()
raw = _decrypt_token(row[0])
data = json.loads(raw)
print("access_token_present:", bool(data.get("access_token")))
print("refresh_token_present:", bool(data.get("refresh_token")))
print("expires_in:", data.get("expires_in"))
conn.close()