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


def _parse_sitemap_entries(xml):
    """Return [(url, lastmod)] from a sitemap, so we can sort recent-first."""
    entries = []
    # Match <url>...<loc>X</loc>...<lastmod>Y</lastmod>...</url> blocks
    for block in re.findall(r"<url>(.*?)</url>", xml, re.S):
        loc_m = re.search(r"<loc>\s*(.*?)\s*</loc>", block)
        mod_m = re.search(r"<lastmod>\s*(.*?)\s*</lastmod>", block)
        if loc_m:
            entries.append((loc_m.group(1).strip(), mod_m.group(1).strip() if mod_m else ""))
    # Fallback: plain <loc> list with no <url> wrapper
    if not entries:
        for loc in re.findall(r"<loc>\s*(.*?)\s*</loc>", xml):
            entries.append((loc.strip(), ""))
    return entries


def _find_articles(site, max_articles=30):
    """Find recent article URLs from a blog site. Prefers sitemap (real posts,
    sorted newest-first) over homepage links (often category pages)."""
    root = _root(site)
    base = "https://" + root
    articles = []
    seen = set()

    def _add(url):
        u = url.split("#")[0].split("?")[0].rstrip("/")
        if u not in seen and _root(u) == root and not u.endswith(".xml"):
            seen.add(u)
            articles.append(u)

    # 1. SITEMAP FIRST — real dated posts, newest-first
    sitemap_urls = ["/post-sitemap.xml", "/post-sitemap1.xml", "/sitemap-posts.xml",
                    "/wp-sitemap-posts-post-1.xml", "/sitemap_index.xml",
                    "/sitemap.xml", "/wp-sitemap.xml", "/news-sitemap.xml"]
    for sm in sitemap_urls:
        sm_html = _fetch(base + sm)
        if not sm_html:
            continue
        entries = _parse_sitemap_entries(sm_html)
        if not entries:
            continue
        # Sitemap index? follow post/news sub-sitemaps
        sub_sitemaps = [u for u, _ in entries if u.endswith(".xml")]
        if sub_sitemaps:
            all_entries = []
            for sub in sub_sitemaps:
                if any(k in sub.lower() for k in ["post", "article", "news", "blog"]):
                    sub_html = _fetch(sub)
                    if sub_html:
                        all_entries.extend(_parse_sitemap_entries(sub_html))
                if len(all_entries) >= max_articles * 2:
                    break
            entries = all_entries or entries
        # Sort newest-first by lastmod (empty dates go last)
        entries.sort(key=lambda x: x[1] or "0", reverse=True)
        for url, _mod in entries:
            _add(url)
            if len(articles) >= max_articles:
                break
        if len(articles) >= max_articles:
            break

    # 2. HOMEPAGE FALLBACK — only if sitemap gave little
    if len(articles) < 5:
        html = _fetch(base) or _fetch("http://" + root)
        if html:
            soup = BeautifulSoup(html, "html.parser")
            for a in soup.find_all("a", href=True):
                full = urljoin(base, a["href"])
                if _root(full) != root:
                    continue
                path = urlparse(full).path.strip("/")
                if not path:
                    continue
                low = path.lower()
                if any(x in low for x in ["/tag/", "/category/", "/author/", "/page/",
                                          "/wp-", "/feed", "contact", "about", "privacy",
                                          "terms", ".jpg", ".png", ".css", ".js"]):
                    continue
                last = path.split("/")[-1]
                looks_like_article = (last.count("-") >= 2 and len(last) > 15) or path.count("/") >= 2
                if looks_like_article:
                    _add(full)
                if len(articles) >= max_articles:
                    break

    return articles[:max_articles]


def _extract_external_links(article_url):
    """Get external links from one article. Returns list of (target_domain, target_url)."""
    root = _root(article_url)
    html = _fetch(article_url)
    if not html:
        return []
    soup = BeautifulSoup(html, "html.parser")

    # Remove nav, header, footer, sidebar, menus — links there aren't guest-post links
    for tag in soup.find_all(["nav", "header", "footer", "aside"]):
        tag.decompose()
    for tag in soup.find_all(class_=re.compile(r"(menu|nav|sidebar|footer|header|widget|related|share|social|comment)", re.I)):
        tag.decompose()

    # Prefer the article content container; fall back to whole cleaned page
    body = (soup.find("article")
            or soup.find("div", class_=re.compile(r"(entry-content|post-content|article-content|td-post-content|single-content|post-body|content-area)", re.I))
            or soup.find("main")
            or soup)

    links = []
    seen_domains = set()
    for a in body.find_all("a", href=True):
        href = a["href"].strip()
        if not href.startswith("http"):
            continue
        target_root = _root(href)
        if not target_root:
            continue
        # Skip internal links (same root, ignoring www / subdomain)
        bare_root = root.replace("www.", "")
        bare_target = target_root.replace("www.", "")
        if bare_target == bare_root or bare_root.endswith("." + bare_target) or bare_target.endswith("." + bare_root):
            continue
        if _is_skip(target_root):
            continue  # giant site — skip
        # Dedupe within THIS article: same domain -> keep only 1
        if bare_target in seen_domains:
            continue
        seen_domains.add(bare_target)
        links.append((bare_target, href.split("#")[0]))
    return links


def research_site(site, time_range="1m", max_articles=30, workers=10,
                  on_article=None, on_link=None):
    """Research one blog site: find articles, extract external links.
    Articles processed in PARALLEL (10 workers). Live callbacks:
      on_article(article_url, count) — as each article is opened
      on_link(link_dict) — for each new external link found."""
    results = []
    articles = _find_articles(site, max_articles)
    global_seen_domains = set()
    counter = [0]

    def _do_article(article):
        return (article, _extract_external_links(article))

    with ThreadPoolExecutor(max_workers=workers) as ex:
        futures = [ex.submit(_do_article, a) for a in articles]
        for fut in as_completed(futures):
            try:
                article, links = fut.result()
            except Exception:
                continue
            counter[0] += 1
            if on_article:
                try: on_article(article, counter[0])
                except Exception: pass
            for target_domain, target_url in links:
                if target_domain in global_seen_domains:
                    continue
                global_seen_domains.add(target_domain)
                link_data = {
                    "source_site": _root(site),
                    "source_article": article,
                    "target_domain": target_domain,
                    "target_url": target_url,
                }
                results.append(link_data)
                if on_link:
                    try: on_link(link_data)
                    except Exception: pass
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
