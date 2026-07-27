import sqlite3
c = sqlite3.connect("warmwire.db")
def q(sql):
    try: return c.execute(sql).fetchall()
    except Exception as e: return [("ERROR", str(e))]

print("\n--- BLOG RESEARCH JOBS ---")
for r in q("SELECT id, name, status, sites, links_found, emails_found FROM blog_research_jobs ORDER BY id"):
    print("  ", r)

print("\n--- BLOG RESEARCH LINKS ---")
print("   total:", q("SELECT count(*) FROM blog_research_links")[0])
for r in q("SELECT email_status, count(*) FROM blog_research_links GROUP BY email_status"):
    print("   ", r)

print("\n--- OUTREACH ENTRIES (mode / type) ---")
for r in q("SELECT mode, email_type, count(*) FROM outreach_entries GROUP BY mode, email_type ORDER BY 3 DESC"):
    print("   ", r)

print("\n--- SCRAPER JOBS ---")
for r in q("SELECT mode, status, count(*), sum(emails_found) FROM scraper_jobs GROUP BY mode, status"):
    print("   ", r)
c.close()
