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

# Giant / premium sites to skip — these are huge authority sites we can't pitch
# as guest-post clients (they don't buy our service). Only smaller business sites
# that are actively paying for guest posts are useful prospects.
SKIP_DOMAINS = {
    # Social / video / big platforms
    "youtube.com", "youtu.be", "facebook.com", "fb.com", "instagram.com",
    "linkedin.com", "twitter.com", "x.com", "wikipedia.org", "quora.com",
    "medium.com", "reddit.com", "pinterest.com", "tiktok.com", "tumblr.com",
    "vimeo.com", "flickr.com", "soundcloud.com", "spotify.com", "twitch.tv",
    "snapchat.com", "threads.net", "mastodon.social", "discord.com",
    # Big tech
    "google.com", "goo.gl", "amazon.com", "apple.com", "microsoft.com",
    "github.com", "gravatar.com", "wordpress.com", "wordpress.org",
    "adobe.com", "mozilla.org", "oracle.com", "ibm.com", "intel.com",
    "salesforce.com", "cloudflare.com", "googleapis.com", "gstatic.com",
    "googleusercontent.com", "play.google.com", "chrome.google.com",
    # Premium news / media (huge DA — never our clients)
    "forbes.com", "cnet.com", "techcrunch.com", "wired.com", "theverge.com",
    "nytimes.com", "wsj.com", "bloomberg.com", "reuters.com", "cnn.com",
    "bbc.com", "bbc.co.uk", "theguardian.com", "washingtonpost.com",
    "businessinsider.com", "entrepreneur.com", "inc.com", "mashable.com",
    "engadget.com", "gizmodo.com", "arstechnica.com", "venturebeat.com",
    "huffpost.com", "huffingtonpost.com", "usatoday.com", "time.com",
    "fortune.com", "economist.com", "ft.com", "forbes.com", "npr.org",
    "buzzfeed.com", "vox.com", "vice.com", "slate.com", "axios.com",
    "hbr.org", "fastcompany.com", "wikihow.com", "investopedia.com",
    # Data / stats / research portals (not clients)
    "statista.com", "similarweb.com", "semrush.com", "ahrefs.com",
    "atlas.media.mit.edu", "mit.edu", "harvard.edu", "stanford.edu",
    "researchgate.net", "sciencedirect.com", "springer.com", "jstor.org",
    "scholar.google.com", "arxiv.org", "ssrn.com", "nature.com",
    # Retail / marketplace giants
    "ebay.com", "walmart.com", "etsy.com", "alibaba.com", "shopify.com",
    "aliexpress.com", "target.com", "bestbuy.com", "shopify.com",
    # Utilities / infra / misc
    "w3.org", "schema.org", "bit.ly", "t.co", "buffer.com", "feedburner.com",
    "gmpg.org", "creativecommons.org", "wix.com", "squarespace.com",
    "yahoo.com", "bing.com", "paypal.com", "wa.me", "t.me", "whatsapp.com",
    "archive.org", "web.archive.org", "imdb.com", "yelp.com", "tripadvisor.com",
    "booking.com", "airbnb.com", "uber.com", "netflix.com", "cloudfront.net",
    "amazonaws.com", "herokuapp.com", "azurewebsites.net", "vercel.app",
    "netlify.app", "githubusercontent.com", "wp.com", "gstatic.com",
}

# Brand names to skip across ALL TLDs. amazon.co.uk, amazon.de, amazon.in,
# google.co.uk etc. all get skipped by matching the first label of the domain.
# This catches country variants that a plain domain list would miss.
SKIP_BRANDS = {
    "amazon", "google", "youtube", "facebook", "instagram", "linkedin",
    "twitter", "microsoft", "apple", "ebay", "walmart", "aliexpress",
    "alibaba", "yahoo", "bing", "paypal", "netflix", "spotify", "wikipedia",
    "booking", "tripadvisor", "airbnb", "uber", "pinterest", "reddit",
    "wordpress", "shopify", "etsy", "bbc", "cnn", "forbes", "reuters",
    "bloomberg", "theguardian", "nytimes", "wikihow", "indeed", "glassdoor",
    "flipkart", "target", "bestbuy", "wikimedia", "wiktionary", "quora",
}

TIME_RANGES = {
    "24h": timedelta(hours=24), "3d": timedelta(days=3), "1w": timedelta(weeks=1),
    "1m": timedelta(days=30), "2m": timedelta(days=60), "3m": timedelta(days=90),
    "4m": timedelta(days=120), "5m": timedelta(days=150), "6m": timedelta(days=180),
    "1y": timedelta(days=365),
}

HEADERS = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                         "(KHTML, like Gecko) Chrome/120.0 Safari/537.36"}

# Shared session with a big connection pool — reusing connections is dramatically
# faster than opening a new TCP+TLS handshake for every single article fetch.
_session = requests.Session()
_session.headers.update(HEADERS)
_adapter = requests.adapters.HTTPAdapter(pool_connections=50, pool_maxsize=50, max_retries=1)
_session.mount("https://", _adapter)
_session.mount("http://", _adapter)


def _root(url):
    try:
        return urlparse(url if "//" in url else "https://" + url).netloc.lower().replace("www.", "")
    except Exception:
        return ""


def _is_skip(domain):
    d = domain.lower().replace("www.", "")
    # 1) Exact domain or subdomain match against SKIP_DOMAINS
    if any(d == s or d.endswith("." + s) for s in SKIP_DOMAINS):
        return True
    # 2) Brand-name match across ALL TLDs (amazon.co.uk, amazon.de, google.in...)
    #    Take the first label of the registrable domain and compare to SKIP_BRANDS.
    parts = d.split(".")
    if parts:
        first = parts[0]
        if first in SKIP_BRANDS:
            return True
    return False


def _fetch(url, timeout=8):
    try:
        r = _session.get(url, timeout=timeout, allow_redirects=True)
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
    """Get ONLY organic editorial links from the article body.

    Excludes: ads, sponsored/promoted widgets (Taboola/Outbrain/etc), affiliate
    links, related-post widgets, share buttons, author bios, CTAs, image-only
    links, and rel=sponsored/nofollow links. Keeps only real in-content anchor
    links that a writer placed inside the article text."""
    root = _root(article_url)
    html = _fetch(article_url)
    if not html:
        return []
    soup = BeautifulSoup(html, "html.parser")

    # 1) Strip structural chrome — nav/header/footer/sidebar aren't article links
    for tag in soup.find_all(["nav", "header", "footer", "aside", "form",
                              "figure", "figcaption", "button"]):
        tag.decompose()

    # 2) Strip ad / sponsored / widget / related / promo containers by class or id.
    #    This is what removes "recommended for you", ad slots, affiliate boxes etc.
    JUNK_CONTAINER = re.compile(
        r"(menu|nav|sidebar|footer|header|widget|related|share|social|comment|"
        r"\bad\b|ads|advert|sponsor|promot|promo|banner|affiliate|partner|"
        r"taboola|outbrain|revcontent|mgid|zergnet|newsletter|subscribe|"
        r"popup|modal|cta|call-to-action|recommend|trending|popular|"
        r"author-bio|author-box|about-author|bio-box|post-meta|entry-meta|"
        r"tags|tag-list|breadcrumb|pagination|more-from|read-more|read-next)",
        re.I)
    for tag in soup.find_all(attrs={"class": JUNK_CONTAINER}):
        tag.decompose()
    for tag in soup.find_all(attrs={"id": JUNK_CONTAINER}):
        tag.decompose()
    # Also strip anything explicitly marked as an ad region
    for tag in soup.find_all(attrs={"data-ad": True}):
        tag.decompose()
    for tag in soup.find_all(attrs={"role": re.compile(r"(banner|complementary|navigation)", re.I)}):
        tag.decompose()

    # 3) Pick the real article-content container
    body = (soup.find("article")
            or soup.find("div", class_=re.compile(r"(entry-content|post-content|article-content|td-post-content|single-content|post-body|content-area|article-body|story-body)", re.I))
            or soup.find("main")
            or soup)

    # Affiliate / tracking / redirect hosts that are never real prospect sites
    AFFILIATE_HOSTS = re.compile(
        r"(amzn\.to|amazon\.|bit\.ly|tinyurl|goo\.gl|ow\.ly|buff\.ly|"
        r"shareasale|clickbank|cj\.com|commission|impact\.com|awin|rakuten|"
        r"skimresources|viglink|linksynergy|go\.redirectingat|"
        r"doubleclick|googlesyndication|googleadservices|adservice|"
        r"utm_medium=affiliate|/ref=|/aff/|tag=|/go/|/out/|/click)", re.I)

    links = []
    seen_domains = set()
    for a in body.find_all("a", href=True):
        href = a["href"].strip()
        if not href.startswith("http"):
            continue

        # Skip ONLY sponsored links (real paid ads). Do NOT skip nofollow —
        # guest-post / editorial links are very commonly nofollow, and that
        # domain owner is exactly the active prospect we want.
        rel = " ".join(a.get("rel", [])).lower() if a.get("rel") else ""
        if "sponsored" in rel:
            continue

        target_root = _root(href)
        if not target_root:
            continue

        # Skip affiliate / tracking / redirect links (these aren't real prospects)
        if AFFILIATE_HOSTS.search(href):
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
