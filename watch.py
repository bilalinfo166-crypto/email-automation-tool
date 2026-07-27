import sqlite3, time
c = sqlite3.connect("warmwire.db")
for i in range(3):
    row = c.execute("SELECT status, done FROM scraper_jobs WHERE id=11").fetchone()
    print(f"  status={row[0]:<10} done={row[1]}")
    time.sleep(4)
c.close()
