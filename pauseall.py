import sqlite3
c = sqlite3.connect("warmwire.db")
n1 = c.execute("UPDATE scraper_jobs SET status=\"stopped\" WHERE status IN (\"running\",\"queued\")").rowcount
# blog jobs bhi pause — ye bhi background mein DB par kaam karte hain
try:
    n2 = c.execute("UPDATE blog_research_jobs SET status=\"stopped\" WHERE status IN (\"running\",\"queued\")").rowcount
except Exception:
    n2 = 0
c.execute("UPDATE scraper_job_domains SET status=\"pending\" WHERE job_id=11 AND status=\"scraping\"")
c.commit()
print(n1, "scraper +", n2, "blog job(s) paused")
print("WAL checkpoint:", c.execute("PRAGMA wal_checkpoint(TRUNCATE)").fetchone())
c.close()
