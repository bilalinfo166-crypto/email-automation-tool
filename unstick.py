import sqlite3
c = sqlite3.connect("warmwire.db")
n = c.execute("UPDATE scraper_job_domains SET status=\"pending\" WHERE job_id=11 AND status=\"scraping\"").rowcount
c.commit(); print(n, "atke domain wapas pending"); c.close()
