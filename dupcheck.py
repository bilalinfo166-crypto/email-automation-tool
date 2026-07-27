import sqlite3
c = sqlite3.connect("warmwire.db", timeout=20)
# outreach entries — total vs unique emails
tot = c.execute("SELECT count(*) FROM outreach_entries").fetchone()[0]
uniq = c.execute("SELECT count(DISTINCT email) FROM outreach_entries").fetchone()[0]
print(f"outreach_entries: {tot} total rows, {uniq} unique emails")
print(f"  -> {tot-uniq} duplicate rows" if tot>uniq else "  -> NO duplicates")
print()
# by mode
print("by mode:")
for m,cnt,u in c.execute("SELECT mode, count(*), count(DISTINCT email) FROM outreach_entries GROUP BY mode").fetchall():
    print(f"  {m}: {cnt} rows, {u} unique")
print()
# worst repeated emails
print("most-repeated emails (if any):")
for em,cnt in c.execute("SELECT email, count(*) c FROM outreach_entries GROUP BY email HAVING c>1 ORDER BY c DESC LIMIT 8").fetchall():
    print(f"  {cnt}x  {em}")
c.close()
