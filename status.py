import sqlite3
c = sqlite3.connect("warmwire.db", timeout=20)
tot_e=0
for r in c.execute("SELECT id, status, done, total, emails_found FROM scraper_jobs WHERE id IN (14,15,16,17) ORDER BY id").fetchall():
    print(f"  #{r[0]}  {r[1]:<10} {r[2]}/{r[3]}  emails={r[4]}")
    tot_e+=r[4]
print(f"  TOTAL EMAILS SO FAR: {tot_e}")
c.close()
