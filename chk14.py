import sqlite3
c = sqlite3.connect("warmwire.db", timeout=20)
print("job 14 domain rows:", c.execute("SELECT count(*) FROM scraper_job_domains WHERE job_id=14").fetchone()[0])
print("by status:")
for st,cnt in c.execute("SELECT status,count(*) FROM scraper_job_domains WHERE job_id=14 GROUP BY status").fetchall():
    print("  ", st, cnt)
print("sample domains:", [r[0] for r in c.execute("SELECT domain FROM scraper_job_domains WHERE job_id=14 LIMIT 3").fetchall()])
c.close()
