import sqlite3, time
c = sqlite3.connect("warmwire.db")
for i in range(4):
    row = c.execute("SELECT status, done FROM scraper_jobs WHERE id=11").fetchone()
    sc = c.execute("SELECT count(*) FROM scraper_job_domains WHERE job_id=11 AND status=\"scraping\"").fetchone()[0]
    print(f"  done={row[1]}  scraping={sc}")
    time.sleep(8)
c.close()
