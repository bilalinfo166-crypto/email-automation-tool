import sqlite3
c = sqlite3.connect("warmwire.db", timeout=25)
print("checkpoint:", c.execute("PRAGMA wal_checkpoint(TRUNCATE)").fetchone())
c.execute("UPDATE scraper_jobs SET status=\"stopped\" WHERE status IN (\"running\",\"queued\")")
c.execute("UPDATE scraper_job_domains SET status=\"pending\" WHERE status=\"scraping\"")
c.commit(); print("ready"); c.close()
