import sqlite3
c = sqlite3.connect("warmwire.db", timeout=20)
print("checkpoint:", c.execute("PRAGMA wal_checkpoint(TRUNCATE)").fetchone())
c.execute("UPDATE scraper_job_domains SET status=\"pending\" WHERE status=\"scraping\"")
c.execute("UPDATE scraper_jobs SET status=\"queued\" WHERE id IN (15,16,17) AND status!=\"completed\"")
c.commit(); print("reset done"); c.close()
