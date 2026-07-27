import sqlite3
c = sqlite3.connect("warmwire.db")
row = c.execute("SELECT status, done, total FROM scraper_jobs WHERE id=11").fetchone()
print("job 11 status/done/total:", row)
for st, cnt in c.execute("SELECT status, count(*) FROM scraper_job_domains WHERE job_id=11 GROUP BY status").fetchall():
    print("  ", st, cnt)
c.close()
