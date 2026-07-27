import sqlite3
c = sqlite3.connect("warmwire.db")
# job 11 ke no_email domains se ek chhota naya test-job banao (200 domains)
rows = c.execute("SELECT domain FROM scraper_job_domains WHERE job_id=11 AND status=\"no_email\" LIMIT 200").fetchall()
doms = [r[0] for r in rows]
print(len(doms), "no_email domains liye test ke liye")
open("retest_domains.txt","w").write("\n".join(doms))
c.close()
