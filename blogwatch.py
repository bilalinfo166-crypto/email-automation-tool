import sqlite3, time
c = sqlite3.connect("warmwire.db", timeout=20)
last=None
for i in range(3):
    r = c.execute("SELECT id, status, done_sites, total_sites, links_found, emails_found FROM blog_research_jobs ORDER BY id DESC LIMIT 1").fetchone()
    ch="" if last is None else " (links +%d)"%(r[4]-last)
    print(f"  job#{r[0]} {r[1]}  sites={r[2]}/{r[3]}  links={r[4]}{ch}  emails={r[5]}")
    last=r[4]; time.sleep(8)
c.close()
