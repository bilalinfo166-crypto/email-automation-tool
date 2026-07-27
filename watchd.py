import sqlite3, time
c = sqlite3.connect("warmwire.db", timeout=15)
for i in range(3):
    row = c.execute("SELECT status, done, total, emails_found FROM scraper_jobs WHERE id=13").fetchone()
    sc = c.execute("SELECT count(*) FROM scraper_job_domains WHERE job_id=13 AND status=\"scraping\"").fetchone()[0]
    print(f"  done={row[1]}/{row[2]}  emails={row[3]}  scraping={sc}  status={row[0]}")
    time.sleep(6)
c.close()
