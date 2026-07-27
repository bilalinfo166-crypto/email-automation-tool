import sqlite3, time
c = sqlite3.connect("warmwire.db", timeout=20)
last=None
for i in range(4):
    r = c.execute("SELECT status, done, emails_found FROM scraper_jobs WHERE id=14").fetchone()
    sc = c.execute("SELECT count(*) FROM scraper_job_domains WHERE job_id=14 AND status=\"scraping\"").fetchone()[0]
    ch = "" if last is None else " (+%d)"%(r[1]-last)
    print(f"  #14 {r[0]}  done={r[1]}{ch}  emails={r[2]}  scraping={sc}")
    last=r[1]; time.sleep(12)
c.close()
