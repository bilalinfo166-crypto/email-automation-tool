"""Blog Research Engine — client-hunting via external link analysis.

LOGIC: A site publishing external (outbound) links is often running paid guest
posts. That site's owner is ACTIVE and spending money on SEO -> a hot potential
CLIENT for our guest-posting service.

FLOW:
1. User adds blog sites (techbullion.com, etc.)
2. User picks time range (24h / 3d / 1w / 1m / 2-6m / 1y) for "recent articles"
3. For each site: find recent articles within the time range
4. Open each article, extract EXTERNAL links only (skip internal)
5. Skip giant sites (YouTube, Facebook, Wikipedia, etc.)
6. Dedupe: same target domain -> keep 1 link; different domains -> keep all
7. Save: source site, source article, extracted link
8. The extracted link domains become client prospects -> scrape their emails
"""
import re
import time
import threading
from datetime import datetime, timedelta
from urllib.parse import urlparse, urljoin
from concurrent.futures import ThreadPoolExecutor, as_completed

import requests
from bs4 import BeautifulSoup

# Giant sites to skip — never useful as guest-post prospects
SKIP_DOMAINS = {
    "youtube.com", "youtu.be", "facebook.com", "fb.com", "instagram.com",
    "linkedin.com", "twitter.com", "x.com", "wikipedia.org", "quora.com",
    "medium.com", "reddit.com", "pinterest.com", "tiktok.com", "tumblr.com",
    "google.com", "goo.gl", "amazon.com", "apple.com", "microsoft.com",
    "github.com", "gravatar.com", "wordpress.com", "wordpress.org",
    "w3.org", "schema.org", "gstatic.com", "googleapis.com", "cloudflare.com",
    "bit.ly", "t.co", "buffer.com", "feedburner.com", "gmpg.org",
    "yahoo.com", "bing.com", "vimeo.com", "flickr.com", "soundcloud.com",
    "spotify.com", "paypal.com", "wa.me", "t.me", "whatsapp.com",
    "creativecommons.org", "mozilla.org", "adobe.com", "wix.com",
}

TIME_RANGES = {
    "24h": timedelta(hours=24), "3d": timedelta(days=3), "1w": timedelta(weeks=1),
    "1m": timedelta(days=30), "2m": timedelta(days=60), "3m": timedelta(days=90),
    "4m": timedelta(days=120), "5m": timedelta(days=150), "6m": timedelta(days=180),
    "1y": timedelta(days=365),
}

HEADERS = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                         "(KHTML, like Gecko) Chrome/120.0 Safari/537.36"}


def _root(url):
    try:
        return urlparse(url if "//" in url else "https://" + url).netloc.lower().replace("www.", "")
    except Exception:
        return ""


def _is_skip(domain):
    d = domain.lower().replace("www.", "")
    return any(d == s or d.endswith("." + s) for s in SKIP_DOMAINS)


def _fetch(url, timeout=10):
    try:
        r = requests.get(url, headers=HEADERS, timeout=timeout, allow_redirects=True)
        if r.status_code == 200:
            return r.text
    except Exception:
        pass
    return None


def _find_articles(site, max_articles=30):
    """Find recent article URLs from a blog site (homepage + sitemap)."""
    root = _root(site)
    base = "https://" + root
    articles = set()

    # Try homepage — collect internal links that look like articles
    html = _fetch(base)
    if html:
        soup = BeautifulSoup(html, "html.parser")
        for a in soup.find_all("a", href=True):
            href = a["href"]
            full = urljoin(base, href)
            if _root(full) == root:
                path = urlparse(full).path.strip("/")
                # Article-like: has a slug, not a category/tag/author page
                if path and "/" in path or (path and len(path) > 12 and "-" in path):
                    if not any(x in path.lower() for x in ["/tag/", "/category/", "/author/", "/page/", "/wp-", "/feed"]):
                        articles.add(full.split("#")[0].split("?")[0])
            if len(articles) >= max_articles:
                break

    # Also try sitemap for more articles
    if len(articles) < max_articles:
        for sm in ["/sitemap.xml", "/sitemap_index.xml", "/post-sitemap.xml"]:
            sm_html = _fetch(base + sm)
            if sm_html:
                for loc in re.findall(r"<loc>(.*?)</loc>", sm_html)[:max_articles]:
                    if _root(loc) == root:
                        articles.add(loc.strip())
                    if len(articles) >= max_articles:
                        break
                break

    return list(articles)[:max_articles]


def _extract_external_links(article_url):
    """Get external links from one article. Returns list of (target_domain, target_url)."""
    root = _root(article_url)
    html = _fetch(article_url)
    if not html:
        return []
    soup = BeautifulSoup(html, "html.parser")
    # Focus on article body if possible
    body = soup.find("article") or soup.find("main") or soup
    links = []
    seen_domains = set()
    for a in body.find_all("a", href=True):
        href = a["href"]
        if not href.startswith("http"):
            continue
        target_root = _root(href)
        if not target_root or target_root == root:
            continue  # internal link — skip
        if _is_skip(target_root):
            continue  # giant site — skip
        # Dedupe within THIS article: same domain -> keep only 1
        if target_root in seen_domains:
            continue
        seen_domains.add(target_root)
        links.append((target_root, href.split("#")[0]))
    return links


def research_site(site, time_range="1m", max_articles=30):
    """Research one blog site: find articles, extract external links.
    Returns list of dicts: {source_site, source_article, target_domain, target_url}."""
    results = []
    articles = _find_articles(site, max_articles)
    global_seen_domains = set()
    for article in articles:
        links = _extract_external_links(article)
        for target_domain, target_url in links:
            # Global dedupe across this site: same target domain once per site
            if target_domain in global_seen_domains:
                continue
            global_seen_domains.add(target_domain)
            results.append({
                "source_site": _root(site),
                "source_article": article,
                "target_domain": target_domain,
                "target_url": target_url,
            })
    return results


def research_sites(sites, time_range="1m", max_articles=30, workers=5, progress=None):
    """Research multiple sites in parallel. Returns all discovered links."""
    all_results = []
    seen_targets = set()  # global dedupe across ALL sites
    with ThreadPoolExecutor(max_workers=workers) as ex:
        futures = {ex.submit(research_site, s, time_range, max_articles): s for s in sites}
        for fut in as_completed(futures):
            site = futures[fut]
            try:
                site_results = fut.result()
                for r in site_results:
                    # Different sites may link to same target — keep first only
                    if r["target_domain"] in seen_targets:
                        continue
                    seen_targets.add(r["target_domain"])
                    all_results.append(r)
                if progress:
                    progress(site, len(site_results))
            except Exception as e:
                print(f"[BlogResearch] {site} failed: {e}")
    return all_results
