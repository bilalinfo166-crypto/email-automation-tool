import sys; sys.path.insert(0, ".")
from app import blog_research as br
from bs4 import BeautifulSoup
from urllib.parse import urlparse
url = r'''https://techbullion.com/engineering-trust-how-novakid-pairs-clean-design-with-authentic-insights-on-learning-english-for-kids/'''
html = br._fetch(url)
if not html:
    print('FETCH FAILED - site blocked/unreachable:', url)
else:
    soup = BeautifulSoup(html, 'html.parser')
    ext = [a['href'] for a in soup.find_all('a', href=True) if a['href'].startswith('http')]
    doms = {}
    for u in ext:
        d = urlparse(u).netloc.replace('www.','')
        doms[d] = doms.get(d,0)+1
    print(f'Total external links: {len(ext)}, unique domains: {len(doms)}')
    print('Top linked domains:')
    for d,c in sorted(doms.items(), key=lambda x:-x[1])[:15]:
        print(f'  {c:3}x  {d}  (skip={br._is_skip(d)})')
    links, reason = br._extract_external_links(url)
    print(f'PROSPECTS EXTRACTED: {len(links)}  reason={reason}')
