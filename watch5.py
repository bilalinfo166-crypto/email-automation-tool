import sqlite3, time
c = sqlite3.connect("warmwire.db")
for i in range(3):
    rows = dict(c.execute("SELECT status, count(*) FROM scraper_job_domains WHERE job_id=11 GROUP BY status").fetchall())
    print(f"  scraping={rows.get('scraping',0)}  pending={rows.get('pending',0)}  completed={rows.get('completed',0)}  no_email={rows.get('no_email',0)}  failed={rows.get('failed',0)}")
    time.sleep(6)
c.close()
