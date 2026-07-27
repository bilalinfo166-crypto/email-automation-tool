import sqlite3, time
c = sqlite3.connect("warmwire.db", timeout=20)
last=None
for i in range(3):
    r = c.execute("SELECT status, done, emails_found FROM scraper_jobs WHERE id=16").fetchone()
    ch="" if last is None else " (+%d)"%(r[1]-last)
    print(f"  #16 {r[0]}  done={r[1]}{ch}  emails={r[2]}"); last=r[1]; time.sleep(10)
c.close()
