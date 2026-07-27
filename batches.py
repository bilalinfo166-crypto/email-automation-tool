import sqlite3, time
c = sqlite3.connect("warmwire.db", timeout=20)
print("--- queued/running batches ---")
for r in c.execute("SELECT id, name, status, done, total FROM scraper_jobs WHERE source=\"split\" ORDER BY id").fetchall():
    print(f"  #{r[0]} {r[1][:30]:<30} {r[2]:<10} {r[3]}/{r[4]}")
c.close()
