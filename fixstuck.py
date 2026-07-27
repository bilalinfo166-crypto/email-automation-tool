import sqlite3
c = sqlite3.connect("warmwire.db")
n = c.execute("UPDATE scraper_job_domains SET status='pending' WHERE job_id=11 AND status='scraping'").rowcount
c.commit()
print(n, "atke hue domain wapas pending kar diye")
print("ab pending:", c.execute("SELECT count(*) FROM scraper_job_domains WHERE job_id=11 AND status='pending'").fetchone()[0])
c.close()
