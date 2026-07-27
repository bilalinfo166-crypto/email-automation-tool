import sqlite3
c = sqlite3.connect("warmwire.db")
row = c.execute("SELECT status, done, total, emails_found FROM scraper_jobs WHERE id=11").fetchone()
print("JOB:", row[0], "| done", row[1], "/", row[2], "| emails", row[3])
print("--- domain outcomes ---")
tot = 0
for st, cnt in c.execute("SELECT status, count(*) FROM scraper_job_domains WHERE job_id=11 GROUP BY status ORDER BY 2 DESC").fetchall():
    print(f"   {st:<14} {cnt}")
    tot += cnt
print("--- of the FAILED ones, how many timed out? ---")
for err, cnt in c.execute("SELECT error, count(*) FROM scraper_job_domains WHERE job_id=11 AND status=\"failed\" GROUP BY error ORDER BY 2 DESC LIMIT 8").fetchall():
    print(f"   {cnt:>5}  {err[:60]}")
c.close()
