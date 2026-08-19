import sqlite3
conn = sqlite3.connect('C:/Users/chuki/Desktop/N.A.L.L.Y/data/nally.db')
conn.execute("DELETE FROM mcp_oauth_state WHERE service='gmail'")
conn.commit()
conn.close()
print('Cleared OAuth state')