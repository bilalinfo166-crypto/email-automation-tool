import sqlite3
c = sqlite3.connect("warmwire.db", timeout=20)
# is job ke articles jinme links the — inko dekhen
r = c.execute("SELECT id, name, sites, articles_found, links_found FROM blog_research_jobs ORDER BY id DESC LIMIT 1").fetchone()
print("Latest job:", r[1], "| articles:", r[3], "| links:", r[4])
print("sites:", r[2][:100])
c.close()
