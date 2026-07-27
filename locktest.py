import sqlite3, time
# Ek write lock lene ki koshish, sirf 3 second ke liye. Agar milta hai = koi aur nahi pakde.
# Agar "locked" aata hai = pakka koi process DB ko write ke liye roke hue hai.
c = sqlite3.connect("warmwire.db", timeout=3)
try:
    c.execute("BEGIN IMMEDIATE")
    print("WRITE LOCK MILA — DB free hai. Masla kahin aur hai.")
    c.execute("ROLLBACK")
except Exception as e:
    print("WRITE LOCK NAHI MILA:", type(e).__name__, "-", e)
    print(">> Koi process DB ko pakde baitha hai.")
c.close()
