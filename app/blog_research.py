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

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                  "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,"
              "image/webp,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9",
    # Only gzip/deflate — requests auto-decompresses these. Brotli (br) is NOT
    # auto-decompressed unless the brotli package is present, which turns sitemap
    # XML into garbage bytes. Leaving br out forces the server to send gzip/plain.
    "Accept-Encoding": "gzip, deflate",
    "Connection": "keep-alive",
    "Upgrade-Insecure-Requests": "1",
    "Sec-Fetch-Dest": "document",
    "Sec-Fetch-Mode": "navigate",
    "Sec-Fetch-Site": "none",
}

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


def _decode_body(r):
    """Return decoded text, handling gzip / brotli / .xml.gz even when requests
    didn't auto-decompress (e.g. brotli without the brotli package, or a
    mislabeled .gz sitemap). Falls back to r.text if content looks fine."""
    content = r.content
    if not content:
        return ""
    # gzip magic bytes: 1f 8b
    if content[:2] == b"\x1f\x8b":
        try:
            import gzip
            return gzip.decompress(content).decode("utf-8", "replace")
        except Exception:
            pass
    # brotli: no reliable magic number; try to decode if it doesn't look like text
    enc = (r.headers.get("Content-Encoding") or "").lower()
    if "br" in enc:
        try:
            import brotli
            return brotli.decompress(content).decode("utf-8", "replace")
        except Exception:
            # brotli package missing — try requests' own text as last resort
            pass
    # Normal path
    return r.text


def _fetch(url, timeout=8):
    try:
        r = _session.get(url, timeout=timeout, allow_redirects=True)
        # Rate-limited (Cloudflare 1015 usually comes as 429 or 503) — back off once
        if r.status_code in (429, 503):
            time.sleep(2)
            try:
                r = _session.get(url, timeout=timeout, allow_redirects=True)
            except Exception:
                return None
        if r.status_code == 200:
            text = _decode_body(r)
            # If it still looks like binary garbage (lots of non-text bytes),
            # bail so we don't feed junk into the parser.
            if text and text.count("\ufffd") > len(text) * 0.1:
                return None
            return text
    except Exception:
        pass
    return None


def _parse_sitemap_entries(xml):
    """Return [(url, lastmod)] from a sitemap or sitemap-index.
    Robust against namespaces, attributes, whitespace, and both <url> (page
    sitemap) and <sitemap> (index) block types."""
    if not xml:
        return []
    entries = []
    # Match BOTH <url>...</url> (page sitemap) and <sitemap>...</sitemap> (index).
    # [^>]* allows namespaced/attributed tags like <url xmlns="...">.
    block_re = re.compile(r"<(?:url|sitemap)\b[^>]*>(.*?)</(?:url|sitemap)>", re.S | re.I)
    loc_re = re.compile(r"<loc\b[^>]*>\s*(.*?)\s*</loc>", re.S | re.I)
    mod_re = re.compile(r"<lastmod\b[^>]*>\s*(.*?)\s*</lastmod>", re.S | re.I)
    for block in block_re.findall(xml):
        loc_m = loc_re.search(block)
        if not loc_m:
            continue
        mod_m = mod_re.search(block)
        url = loc_m.group(1).strip()
        # Strip CDATA wrappers and stray whitespace/newlines
        url = re.sub(r"^<!\[CDATA\[|\]\]>$", "", url).strip()
        if url:
            entries.append((url, mod_m.group(1).strip() if mod_m else ""))
    # Fallback: ANY <loc> anywhere (some sitemaps have no url/sitemap wrappers)
    if not entries:
        for loc in loc_re.findall(xml):
            u = re.sub(r"^<!\[CDATA\[|\]\]>$", "", loc.strip()).strip()
            if u:
                entries.append((u, ""))
    return entries


def _parse_date(s):
    """Parse a date string (sitemap lastmod is ISO-8601). Returns datetime or None."""
    if not s:
        return None
    s = s.strip()
    # Take just the date part (drop time/timezone): 2018-02-13T10:30:00+00:00
    m = re.match(r"(\d{4})-(\d{2})-(\d{2})", s)
    if m:
        try:
            return datetime(int(m.group(1)), int(m.group(2)), int(m.group(3)))
        except Exception:
            return None
    return None


def _date_from_url(url):
    """Many blogs put the publish date in the URL: /2018/02/13/slug or /2018/02/slug.
    Returns datetime or None."""
    # /YYYY/MM/DD/
    m = re.search(r"/(\d{4})/(\d{1,2})/(\d{1,2})/", url)
    if m:
        try:
            y, mo, d = int(m.group(1)), int(m.group(2)), int(m.group(3))
            if 2000 <= y <= 2100 and 1 <= mo <= 12 and 1 <= d <= 31:
                return datetime(y, mo, d)
        except Exception:
            pass
    # /YYYY/MM/
    m = re.search(r"/(\d{4})/(\d{1,2})/", url)
    if m:
        try:
            y, mo = int(m.group(1)), int(m.group(2))
            if 2000 <= y <= 2100 and 1 <= mo <= 12:
                return datetime(y, mo, 1)
        except Exception:
            pass
    return None


def _date_from_html(html):
    """Extract an article's published date from its HTML. Checks meta tags,
    JSON-LD, and <time> elements. Returns datetime or None."""
    if not html:
        return None
    # 1) Open Graph / article meta tags
    for pat in [
        r'property=["\']article:published_time["\'][^>]*content=["\']([^"\']+)["\']',
        r'content=["\']([^"\']+)["\'][^>]*property=["\']article:published_time["\']',
        r'name=["\']publish[-_]?date["\'][^>]*content=["\']([^"\']+)["\']',
        r'name=["\']date["\'][^>]*content=["\']([^"\']+)["\']',
        r'property=["\']og:updated_time["\'][^>]*content=["\']([^"\']+)["\']',
        r'itemprop=["\']datePublished["\'][^>]*content=["\']([^"\']+)["\']',
    ]:
        m = re.search(pat, html, re.I)
        if m:
            d = _parse_date(m.group(1))
            if d:
                return d
    # 2) JSON-LD "datePublished":"2020-..."
    m = re.search(r'"datePublished"\s*:\s*"([^"]+)"', html)
    if m:
        d = _parse_date(m.group(1))
        if d:
            return d
    # 3) <time datetime="2020-...">
    m = re.search(r'<time[^>]*datetime=["\']([^"\']+)["\']', html, re.I)
    if m:
        d = _parse_date(m.group(1))
        if d:
            return d
    return None


def _is_cloudflare_blocked(html):
    """Detect Cloudflare access-denied / rate-limit (error 1015, 1020 etc.)."""
    if not html:
        return False
    low = html.lower()
    return ("cloudflare" in low and
            ("error 1015" in low or "error 1020" in low or "access denied" in low
             or "rate limited" in low or "you are being rate limited" in low
             or "attention required" in low))


def _find_articles(site, max_articles=30, time_range="1m"):
    """Find recent article URLs from a blog site within the time range.
    Prefers sitemap (real dated posts, newest-first). Filters out articles
    older than the cutoff using sitemap <lastmod> dates and URL-embedded dates."""
    root = _root(site)
    base = "https://" + root
    articles = []  # list of (url, date_str)
    seen = set()

    # Date cutoff: articles older than this are skipped
    delta = TIME_RANGES.get(time_range, timedelta(days=30))
    cutoff = datetime.utcnow() - delta

    def _too_old(url, lastmod):
        """True if the article is older than the cutoff."""
        d = _parse_date(lastmod) or _date_from_url(url)
        if d is None:
            return False  # no date info — keep
        return d < cutoff

    def _add(url, lastmod=""):
        u = url.split("#")[0].split("?")[0].rstrip("/")
        if u in seen or _root(u) != root or u.endswith(".xml"):
            return
        if _too_old(u, lastmod):
            return
        seen.add(u)
        articles.append((u, lastmod))

    # 1. SITEMAP FIRST. Big WordPress sites split posts across MANY numbered
    # sitemaps (post-sitemap.xml, post-sitemap2.xml, post-sitemap3.xml...).
    # In Yoast, HIGHER numbers usually hold the NEWEST posts. We gather from the
    # sitemap index if present, PLUS follow numbered sitemaps until they run out.
    index_urls = ["/sitemap_index.xml", "/sitemap.xml", "/wp-sitemap.xml"]
    post_sitemaps = []
    for ix in index_urls:
        ix_html = _fetch(base + ix)
        if not ix_html:
            continue
        ix_entries = _parse_sitemap_entries(ix_html)
        subs = [u for u, _ in ix_entries if u.endswith(".xml")
                and any(k in u.lower() for k in ["post", "article", "news", "blog"])]
        if subs:
            post_sitemaps = subs
            break

    # If the index didn't list post sitemaps, probe numbered ones directly.
    if not post_sitemaps:
        # Probe forward: post-sitemap.xml, post-sitemap2..post-sitemap40.
        # Collect ALL that exist (don't stop at first gap — some sites skip numbers).
        candidates = [base + "/post-sitemap.xml"]
        for n in range(2, 41):
            candidates.append(f"{base}/post-sitemap{n}.xml")
        post_sitemaps = candidates

    # Fallbacks for non-Yoast sites
    extra = ["/sitemap-posts.xml", "/wp-sitemap-posts-post-1.xml",
             "/wp-sitemap-posts-post-2.xml", "/news-sitemap.xml"]
    for e in extra:
        post_sitemaps.append(base + e)

    # Read highest-numbered first (newest posts usually there), but DON'T stop
    # early on gaps — gather from every sitemap that actually returns entries.
    def _sm_sort_key(u):
        m = re.search(r"post-sitemap(\d+)\.xml", u)
        return int(m.group(1)) if m else (1 if "post-sitemap.xml" in u else 0)
    post_sitemaps = sorted(set(post_sitemaps), key=_sm_sort_key, reverse=True)

    all_entries = []
    fetched_ok = 0
    for sm in post_sitemaps:
        sm_html = _fetch(sm)
        if not sm_html:
            continue
        ents = _parse_sitemap_entries(sm_html)
        ents = [(u, m) for u, m in ents if not u.endswith(".xml")]
        if ents:
            all_entries.extend(ents)
            fetched_ok += 1
        # Once we have plenty AND have read a few sitemaps, stop (enough to sort)
        if len(all_entries) >= max_articles * 30 and fetched_ok >= 2:
            break

    if all_entries:
        all_entries.sort(key=lambda x: x[1] or "0", reverse=True)
        for url, mod in all_entries:
            _add(url, mod)
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
                # Reject non-article pages: categories, tags, homepage sections,
                # advertise/press/about pages etc.
                if any(x in low for x in ["/tag/", "tag/", "/category/", "category/",
                                          "/author/", "author/", "/page/", "page/",
                                          "/wp-", "/feed", "feed/", "contact", "about",
                                          "privacy", "terms", "advertise", "press-release",
                                          "press-releases", "sitemap", "disclaimer",
                                          "subscribe", "newsletter", "login", "register",
                                          ".jpg", ".png", ".css", ".js", ".pdf"]):
                    continue
                last = path.split("/")[-1]
                # Real articles have descriptive slugs (multiple hyphens, longer text)
                looks_like_article = (last.count("-") >= 3 and len(last) > 25)
                if looks_like_article:
                    _add(full)  # homepage links have no lastmod; URL date checked inside
                if len(articles) >= max_articles:
                    break

    # 3. SAFETY NET — if the date filter dropped EVERYTHING but the sitemap did
    # have posts, take the newest ones anyway (better to show recent posts than
    # nothing). This handles sites whose dates are all outside the window or
    # whose sitemap lacks lastmod entirely. Reuses the already-gathered,
    # newest-first all_entries.
    if not articles and all_entries:
        for url, mod in all_entries:  # already sorted newest-first
            u = url.split("#")[0].split("?")[0].rstrip("/")
            if u in seen or _root(u) != root or u.endswith(".xml"):
                continue
            seen.add(u)
            articles.append((u, mod))
            if len(articles) >= max_articles:
                break

    return articles[:max_articles]


def _extract_external_links(article_url, cutoff=None):
    """Get ONLY organic editorial links from the article body.

    If cutoff is given, the article's own published date (from its HTML) is
    checked — articles older than cutoff return [] (final date safety net for
    when sitemap lastmod / URL date were missing).

    Excludes: ads, sponsored/promoted widgets (Taboola/Outbrain/etc), affiliate
    links, related-post widgets, share buttons, author bios, CTAs, image-only
    links, and rel=sponsored links. Keeps only real in-content anchor links."""
    root = _root(article_url)
    html = _fetch(article_url)
    if not html:
        return []

    # Cloudflare rate-limit / access-denied page — no real content, skip quietly
    if _is_cloudflare_blocked(html):
        print(f"[BlogResearch]   (cloudflare blocked) {article_url}")
        return []

    # FINAL date safety net: if the article's HTML says it's older than the
    # cutoff, drop it — even if sitemap/URL gave no date.
    if cutoff is not None:
        pub = _date_from_html(html)
        if pub is not None and pub < cutoff:
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
                  on_article=None, on_link=None, should_stop=None):
    """Research one blog site: find articles, extract external links.
    Articles processed in PARALLEL (10 workers). Live callbacks:
      on_article(article_url, count) — as each article is opened
      on_link(link_dict) — for each new external link found
      should_stop() — return True to abort immediately (checked per article)."""
    results = []
    if should_stop and should_stop():
        return results
    article_pairs = _find_articles(site, max_articles, time_range)  # list of (url, date)
    global_seen_domains = set()
    counter = [0]

    # Cutoff for the per-article date safety net (checks the article's own HTML)
    delta = TIME_RANGES.get(time_range, timedelta(days=30))
    cutoff = datetime.utcnow() - delta

    def _do_article(pair):
        article, date_str = pair
        if should_stop and should_stop():
            return (article, date_str, [])
        return (article, date_str, _extract_external_links(article, cutoff))

    with ThreadPoolExecutor(max_workers=workers) as ex:
        futures = [ex.submit(_do_article, p) for p in article_pairs]
        for fut in as_completed(futures):
            # Stop fast: as soon as the flag is set, stop collecting results
            if should_stop and should_stop():
                for f in futures:
                    f.cancel()
                break
            try:
                article, date_str, links = fut.result()
            except Exception:
                continue
            counter[0] += 1
            if on_article:
                try: on_article(article, counter[0])
                except Exception: pass
            # Clean the date to just YYYY-MM-DD for display
            pub_date = ""
            if date_str:
                d = _parse_date(date_str)
                if d:
                    pub_date = d.strftime("%Y-%m-%d")
            for target_domain, target_url in links:
                if target_domain in global_seen_domains:
                    continue
                global_seen_domains.add(target_domain)
                link_data = {
                    "source_site": _root(site),
                    "source_article": article,
                    "target_domain": target_domain,
                    "target_url": target_url,
                    "published_date": pub_date,
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
