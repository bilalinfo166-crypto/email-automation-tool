import sqlite3, time
c = sqlite3.connect("warmwire.db", timeout=20)
last=None
for i in range(5):
    row = c.execute("SELECT done FROM scraper_jobs WHERE id=13").fetchone()
    d = row[0]
    change = "" if last is None else (" (+%d)" % (d-last))
    print(f"  t+{i*8}s  done={d}{change}")
    last = d
    time.sleep(8)
c.close()
