import sqlite3
c = sqlite3.connect("warmwire.db")
n = c.execute("UPDATE scraper_jobs SET status=\"stopped\" WHERE status IN (\"running\",\"queued\")").rowcount
c.commit(); print(n, "job(s) paused"); c.close()
