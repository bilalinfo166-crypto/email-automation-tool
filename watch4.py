import sqlite3, time
c = sqlite3.connect("warmwire.db")
for i in range(5):
    row = c.execute("SELECT status, done, emails_found FROM scraper_jobs WHERE id=11").fetchone()
    print(f"  status={row[0]:<10} done={row[1]}  emails={row[2]}")
    time.sleep(6)
c.close()
