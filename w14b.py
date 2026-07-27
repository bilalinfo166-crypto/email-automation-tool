import sqlite3, time
c = sqlite3.connect("warmwire.db", timeout=20)
for i in range(5):
    d = c.execute("SELECT done, emails_found FROM scraper_jobs WHERE id=14").fetchone()
    sc = c.execute("SELECT count(*) FROM scraper_job_domains WHERE job_id=14 AND status=\"scraping\"").fetchone()[0]
    cp = c.execute("SELECT count(*) FROM scraper_job_domains WHERE job_id=14 AND status IN (\"completed\",\"no_email\",\"failed\")").fetchone()[0]
    print(f"  t+{i*8}s  done={d[0]}  processed={cp}  scraping={sc}  emails={d[1]}")
    time.sleep(8)
c.close()
