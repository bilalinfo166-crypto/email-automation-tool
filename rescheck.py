import sqlite3, time
c = sqlite3.connect("warmwire.db", timeout=20)
last=None
for i in range(4):
    d = c.execute("SELECT done FROM scraper_jobs WHERE id=13").fetchone()[0]
    ch = "" if last is None else " (+%d)"%(d-last)
    print(f"  t+{i*7}s done={d}{ch}"); last=d
    time.sleep(7)
c.close()
