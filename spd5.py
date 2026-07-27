import sqlite3, time
c = sqlite3.connect("warmwire.db", timeout=20)
last=None
for i in range(4):
    r = c.execute("SELECT done, emails_found FROM scraper_jobs WHERE id=15").fetchone()
    sc = c.execute("SELECT count(*) FROM scraper_job_domains WHERE job_id=15 AND status=\"scraping\"").fetchone()[0]
    ch="" if last is None else " (+%d)"%(r[0]-last)
    print(f"  t+{i*12}s done={r[0]}{ch} emails={r[1]} scraping={sc}"); last=r[0]; time.sleep(12)
c.close()
