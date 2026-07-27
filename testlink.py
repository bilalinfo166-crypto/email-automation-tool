import sys; sys.path.insert(0, ".")
from app import blog_research as br
# yahan koi asli article URL daalo jismein bahar ki sites ke links hon
url = "https://techbullion.com/"   # <-- ise apne kisi blog article se badlo
links, reason = br._extract_external_links(url)
print("REASON:", reason)
print("LINKS FOUND:", len(links))
for d, u in links[:10]:
    print("  ", d, "->", u[:60])
# diagnostic: page par kitne anchors the
from bs4 import BeautifulSoup
html = br._fetch(url)
if html:
    soup = BeautifulSoup(html, "html.parser")
    alla = soup.find_all("a", href=True)
    ext = [a for a in alla if a["href"].startswith("http")]
    print(f"DIAG: total anchors={len(alla)}, http links={len(ext)}")
else:
    print("DIAG: page fetch FAILED (unreachable/blocked)")
