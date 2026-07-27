import sqlite3
c = sqlite3.connect("warmwire.db", timeout=20)
for r in c.execute("SELECT id, status, done, total, emails_found FROM scraper_jobs WHERE id IN (14,15,16,17) ORDER BY id").fetchall():
    print(f"  #{r[0]}  {r[1]:<10} {r[2]}/{r[3]}  emails={r[4]}")
run = c.execute("SELECT id FROM scraper_jobs WHERE status=\"running\"").fetchall()
print("RUNNING:", [x[0] for x in run] if run else "NONE")
c.close()
