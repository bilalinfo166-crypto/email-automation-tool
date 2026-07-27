import sqlite3, time
c = sqlite3.connect("warmwire.db", timeout=20)
last=None
for i in range(5):
    r = c.execute("SELECT done, emails_found FROM scraper_jobs WHERE id=14").fetchone()
    ch = "" if last is None else " (+%d)"%(r[0]-last)
    print(f"  t+{i*10}s done={r[0]}{ch}  emails={r[1]}")
    last=r[0]; time.sleep(10)
c.close()
