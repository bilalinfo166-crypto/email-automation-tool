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
    # reference / big media / platforms — none of these buy guest posts
    "wikidata", "wikivoyage", "wikisource", "britannica", "dictionary",
    "investopedia", "healthline", "webmd", "mayoclinic", "medium",
    "substack", "blogspot", "tumblr", "github", "gitlab", "stackoverflow",
    "stackexchange", "mozilla", "w3schools", "cloudflare", "adobe", "canva",
    "zoom", "slack", "notion", "figma", "hubspot", "salesforce", "wix",
    "squarespace", "godaddy", "statista", "gartner", "mckinsey",
    "usatoday", "washingtonpost", "wsj", "cnbc", "foxnews", "nbcnews",
    "buzzfeed", "huffpost", "businessinsider", "techcrunch", "theverge",
    "wired", "engadget", "mashable", "vice", "vox", "msn",
}

# Whole TLDs that are never guest-post buyers
SKIP_TLDS = {"gov", "mil", "edu", "int"}

TIME_RANGES = {
    "24h": timedelta(hours=24), "3d": timedelta(days=3), "1w": timedelta(weeks=1),
    "1m": timedelta(days=30), "2m": timedelta(days=60), "3m": timedelta(days=90),
    "4m": timedelta(days=120), "5m": timedelta(days=150), "6m": timedelta(days=180),
    "1y": timedelta(days=365),
}

# Giant news portals / aggregators — these are NOT guest-post targets. They
# don't accept guest posts, are JavaScript-heavy, have no standard sitemap, and
# aggregate content from elsewhere. Warn the user instead of wasting time.
NOT_BLOG_SITES = {
    "msn.com", "yahoo.com", "news.yahoo.com", "google.com", "news.google.com",
    "bing.com", "duckduckgo.com", "apple.com", "news.apple.com",
    "facebook.com", "instagram.com", "twitter.com", "x.com", "linkedin.com",
    "reddit.com", "youtube.com", "tiktok.com", "pinterest.com", "quora.com",
    "medium.com", "substack.com", "wikipedia.org", "wikihow.com",
    "cnn.com", "bbc.com", "bbc.co.uk", "forbes.com", "reuters.com",
    "bloomberg.com", "nytimes.com", "washingtonpost.com", "theguardian.com",
    "wsj.com", "usatoday.com", "cnbc.com", "foxnews.com", "nbcnews.com",
    "abcnews.go.com", "buzzfeed.com", "huffpost.com", "businessinsider.com",
    "flipboard.com", "feedly.com", "pocket.com", "smartnews.com",
    "amazon.com", "ebay.com", "walmart.com", "etsy.com", "aliexpress.com",
}


def check_site(site):
    """Quick pre-check before researching. Returns a dict:
      {ok: bool, reason: str, hint: str}
    Tells the user upfront if a site won't work as a guest-post prospect."""
    root = _root(site)
    if not root or "." not in root:
        return {"ok": False, "reason": "invalid_url",
                "hint": "That doesn't look like a valid website. Enter a domain like 'techbullion.com'."}

    # Known non-blog / aggregator?
    bare = root.replace("www.", "")
    if bare in NOT_BLOG_SITES or _is_skip(root):
        return {"ok": False, "reason": "not_a_blog",
                "hint": f"'{bare}' is a giant news portal / aggregator, not a guest-post site. "
                        "It doesn't accept guest posts and has no standard sitemap. "
                        "Target smaller niche blogs instead (the kind that publish sponsored/guest articles)."}

    # Can we even reach it? This is only a sanity check before the real run, so
    # it uses short timeouts and few requests — a slow check that makes the user
    # wait minutes is worse than no check at all.
    # Sites are checked in parallel, so a generous timeout costs nothing overall
    # — and it stops a merely-slow site being reported as dead.
    base = "https://" + root
    html = _fetch(base, timeout=10)
    if not html:
        html = _fetch("http://" + root, timeout=8)
    if not html:
        return {"ok": False, "reason": "unreachable",
                "hint": f"Couldn't load '{bare}'. It may be down, blocking bots, or behind heavy protection."}

    # Does it have a sitemap? (best signal it's a real, crawlable blog)
    # Two probes is enough here — the real run tries every variant.
    has_sitemap = False
    for sm in ["/sitemap.xml", "/post-sitemap.xml"]:
        if _fetch(base + sm, timeout=6):
            has_sitemap = True
            break

    if not has_sitemap:
        return {"ok": True, "reason": "no_sitemap",
                "hint": f"'{bare}' has no standard sitemap — results may be limited. "
                        "It may be a JavaScript-heavy site. We'll try the homepage, but a "
                        "normal WordPress/blog site works best."}

    return {"ok": True, "reason": "looks_good",
            "hint": f"'{bare}' looks like a crawlable blog. Good to go."}


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
    # 3) Check EVERY label, not just the first — "en.wiktionary.org" was
    #    slipping through because only "en" was being tested.
    for label in parts[:-1]:
        if label in SKIP_BRANDS:
            return True
    # 4) Whole TLDs that never buy guest posts
    if parts and parts[-1] in SKIP_TLDS:
        return True
    if len(parts) >= 2 and parts[-2] == "gov":     # gov.uk, gov.au ...
        return True
    # 5) Never offer back a site we're currently researching — it's the source,
    #    not a client.
    for src in _SOURCE_SITES:
        if d == src or d.endswith("." + src):
            return True
    return False


# Sites currently being researched. Links pointing back at them are ignored.
_SOURCE_SITES = set()


def set_source_sites(sites):
    """Tell the extractor which domains are being researched."""
    _SOURCE_SITES.clear()
    for s in sites or []:
        r = _root(s).replace("www.", "").lower()
        if r:
            _SOURCE_SITES.add(r)


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
    # 3) <time> — but ONLY when the tag clearly marks the article's own publish
    #    date. Taking the first <time> on the page was a real bug: sidebars,
    #    "recent posts" widgets, comments and footers all contain <time> tags,
    #    usually with OLD dates. A fresh article next to a 2018 widget was being
    #    judged as 2018 and thrown away before its links were ever read.
    for pat in [
        r'<time[^>]*itemprop=["\']datePublished["\'][^>]*datetime=["\']([^"\']+)["\']',
        r'<time[^>]*datetime=["\']([^"\']+)["\'][^>]*itemprop=["\']datePublished["\']',
        r'<time[^>]*\bpubdate\b[^>]*datetime=["\']([^"\']+)["\']',
        r'<time[^>]*class=["\'][^"\']*(?:published|entry-date|post-date|posted-on)[^"\']*["\'][^>]*datetime=["\']([^"\']+)["\']',
    ]:
        m = re.search(pat, html, re.I)
        if m:
            d = _parse_date(m.group(1))
            if d:
                return d

    # No trustworthy date. Return None so the caller KEEPS the article and reads
    # its links — dropping a page on a guess is how good prospects get missed.
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


# Publish date read out of each article's own HTML, used when the sitemap
# didn't provide one.
_last_article_date = {}

# Which section each article was found under, filled by the most recent
# _find_articles() call and read by research_site().
_last_categories = {}


def _find_articles(site, max_articles=30, time_range="1m"):
    """Find recent article URLs from a blog site within the time range.
    Prefers sitemap (real dated posts, newest-first). Filters out articles
    older than the cutoff using sitemap <lastmod> dates and URL-embedded dates."""
    root = _root(site)
    base = "https://" + root
    articles = []  # list of (url, date_str)
    seen = set()
    article_category = {}   # article url -> the section it was found under

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

    # 2. THE SITE ITSELF — homepage + blog/news sections.
    # Always done, not just as a fallback. A blog's newest posts are on its
    # front page by definition, so this catches anything the sitemap missed
    # (stale sitemap, no sitemap, or one that's blocked).
    # Whole path SEGMENTS that mean "this is a listing or utility page".
    # Matched as complete segments, never as substrings — otherwise a genuine
    # article like /what-you-should-know-about-seo would be thrown away just
    # for containing the word "about".
    NON_ARTICLE_SEGMENTS = {
        "tag", "tags", "category", "categories", "author", "authors", "page",
        "feed", "rss", "comments", "search", "contact", "contact-us", "about",
        "about-us", "privacy", "privacy-policy", "terms", "advertise",
        "sitemap", "disclaimer", "subscribe", "newsletter", "login", "signin",
        "register", "signup", "cart", "checkout", "account", "wp-admin",
        "wp-content", "wp-includes", "shop", "store", "pricing",
    }
    BAD_EXT = (".jpg", ".jpeg", ".png", ".gif", ".webp", ".svg", ".css", ".js",
               ".pdf", ".xml", ".zip", ".mp4", ".mp3")

    def _looks_like_article(path):
        """Is this URL a post rather than a listing page?"""
        low = path.lower().rstrip("/")
        if low.endswith(BAD_EXT):
            return False
        segments = [seg for seg in low.split("/") if seg]
        if any(seg in NON_ARTICLE_SEGMENTS for seg in segments):
            return False
        if any(seg.startswith("wp-") for seg in segments):
            return False
        last = path.rstrip("/").split("/")[-1]
        if not last or len(last) < 8:
            return False
        # /2026/07/16/some-story  — a date in the path is a strong signal
        if _date_from_url("/" + path):
            return True
        # descriptive slug: several words joined by hyphens
        if last.count("-") >= 2 and len(last) > 14:
            return True
        # deep path with a wordy last segment (e.g. /news/business/some-story)
        if path.count("/") >= 2 and last.count("-") >= 1 and len(last) > 12:
            return True
        return False

    def _harvest(page_url):
        """Pull article links out of one listing page."""
        html = _fetch(page_url, timeout=8)
        if not html:
            return 0
        got = 0
        try:
            soup = BeautifulSoup(html, "html.parser")
        except Exception:
            return 0
        for a in soup.find_all("a", href=True):
            full = urljoin(page_url, a["href"])
            if _root(full) != root:
                continue
            path = urlparse(full).path.strip("/")
            if not path or not _looks_like_article(path):
                continue
            before = len(articles)
            _add(full)          # date is checked inside _add
            if len(articles) > before:
                got += 1
            if len(articles) >= max_articles:
                break
        return got

    def _find_category_pages(page_url):
        """Read the site's own navigation and return its category/section pages.

        Rather than guessing which sections a site has, this takes them from the
        menu the site actually shows (CELEBRITY, TECH, BUSINESS, NEWS ...).
        """
        html = _fetch(page_url, timeout=8)
        if not html:
            return []
        try:
            soup = BeautifulSoup(html, "html.parser")
        except Exception:
            return []
        cats, seen_cat = [], set()
        # Prefer real navigation, fall back to the whole page
        areas = soup.find_all(["nav", "header"]) or [soup]
        for area in areas:
            for a in area.find_all("a", href=True):
                full = urljoin(page_url, a["href"]).split("#")[0].rstrip("/")
                if _root(full) != root:
                    continue
                path = urlparse(full).path.strip("/")
                if not path or full in seen_cat:
                    continue
                segs = [x for x in path.lower().split("/") if x]
                if not segs or len(segs) > 2:
                    continue
                # skip utility pages — they list no articles
                if segs[-1] in NON_ARTICLE_SEGMENTS and segs[0] != "category":
                    continue
                label = (a.get_text(strip=True) or segs[-1]).strip()
                if not label or len(label) > 30:
                    continue
                seen_cat.add(full)
                cats.append((full, label))
        return cats[:14]          # a sane cap

    if len(articles) < max_articles:
        # 1) the obvious listing pages
        listing_pages = [(base, ""), (base + "/blog", "Blog"), (base + "/news", "News"),
                         (base + "/articles", "Articles"), (base + "/insights", "Insights"),
                         (base + "/resources", "Resources"), (base + "/posts", "Posts")]
        # 2) plus every section the site lists in its own menu
        try:
            listing_pages += _find_category_pages(base)
        except Exception:
            pass

        for page_url, label in listing_pages:
            if len(articles) >= max_articles:
                break
            try:
                before = set(u for u, _ in articles)
                _harvest(page_url)
                # remember which section each new article came from
                for u, _d in articles:
                    if u not in before and u not in article_category:
                        article_category[u] = label or "Home"
            except Exception:
                continue

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

    _last_categories.clear()
    _last_categories.update(article_category)
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
        return [], "unreachable"

    # Cloudflare rate-limit / access-denied page — no real content, skip quietly
    if _is_cloudflare_blocked(html):
        return [], "blocked"

    # FINAL date safety net: if the article's HTML says it's older than the
    # cutoff, drop it — even if sitemap/URL gave no date.
    pub = _date_from_html(html)
    if cutoff is not None and pub is not None and pub < cutoff:
        return [], "too_old"
    # remembered so the caller can show a date even when the sitemap had none
    _last_article_date[article_url] = pub.strftime("%Y-%m-%d") if pub else ""
    soup = BeautifulSoup(html, "html.parser")

    # 1) Strip structural chrome — nav/header/footer/sidebar aren't article links
    for tag in soup.find_all(["nav", "header", "footer", "aside", "form",
                              "figure", "figcaption", "button"]):
        tag.decompose()

    # 2) Strip ad / sponsored / widget / related / promo containers by class or id.
    #    Uses WORD-BOUNDARY matching so it only kills real junk containers
    #    (e.g. "related-posts", "ad-slot") and NOT main content divs whose class
    #    merely contains a substring (e.g. "main-content", "advertise-content").
    JUNK_WORDS = ["sidebar", "navbar", "navmenu", "footer", "header-",
                  "related", "share", "sharing", "social", "comment",
                  "advert", "sponsor", "promoted", "promo-", "banner",
                  "affiliate", "taboola", "outbrain", "revcontent", "mgid",
                  "zergnet", "newsletter", "subscribe", "popup", "modal",
                  "read-more", "read-next", "more-from", "recommended",
                  "trending", "author-bio", "author-box", "about-author",
                  "bio-box", "breadcrumb", "pagination", "widget-"]
    def _is_junk_class(val):
        if not val:
            return False
        s = " ".join(val) if isinstance(val, list) else str(val)
        s = s.lower()
        return any(w in s for w in JUNK_WORDS)

    # NEVER strip these — they wrap the whole page. WordPress routinely puts
    # classes like "sidebar-right" or "comments-open" on <body>, and matching
    # those was deleting the entire document, so no links were ever found.
    STRUCTURAL = {"html", "body", "main", "article"}

    def _strip(attr):
        for tag in soup.find_all(attrs={attr: _is_junk_class}):
            if tag.name in STRUCTURAL:
                continue
            # A "junk" block that holds most of the page isn't junk — it's the
            # content wrapper with an unlucky class name.
            if len(tag.find_all("a", href=True)) > 0 and tag.find("article"):
                continue
            tag.decompose()
    _strip("class")
    _strip("id")
    # Also strip anything explicitly marked as an ad region
    for tag in soup.find_all(attrs={"data-ad": True}):
        tag.decompose()
    for tag in soup.find_all(attrs={"role": re.compile(r"^(banner|complementary|navigation)$", re.I)}):
        tag.decompose()

    # 3) Pick the real article-content container — try many patterns, widest net
    body = (soup.find("article")
            or soup.find(attrs={"class": re.compile(r"(entry-content|post-content|article-content|td-post-content|single-content|post-body|content-area|article-body|story-body|article__body|post__content|c-content|main-content|page-content|blog-content|story__content|rich-text|prose)", re.I)})
            or soup.find(attrs={"itemprop": "articleBody"})
            or soup.find("main")
            or soup.find("body")
            or soup)

    # Affiliate / tracking / redirect hosts that are never real prospect sites
    AFFILIATE_HOSTS = re.compile(
        r"(amzn\.to|amazon\.|bit\.ly|tinyurl|goo\.gl|ow\.ly|buff\.ly|"
        r"shareasale|clickbank|cj\.com|commission|impact\.com|awin|rakuten|"
        r"skimresources|viglink|linksynergy|go\.redirectingat|"
        r"doubleclick|googlesyndication|googleadservices|adservice|"
        r"utm_medium=affiliate|/ref=|/aff/|tag=|/go/|/out/|/click)", re.I)

    def _collect(container):
        found = []
        seen = set()
        for a in container.find_all("a", href=True):
            href = a["href"].strip()
            if not href.startswith("http"):
                continue
            rel = " ".join(a.get("rel", [])).lower() if a.get("rel") else ""
            if "sponsored" in rel:
                continue
            target_root = _root(href)
            if not target_root:
                continue
            if AFFILIATE_HOSTS.search(href):
                continue
            bare_root = root.replace("www.", "")
            bare_target = target_root.replace("www.", "")
            if (bare_target == bare_root or bare_root.endswith("." + bare_target)
                    or bare_target.endswith("." + bare_root)):
                continue
            if _is_skip(target_root):
                continue
            if bare_target in seen:
                continue
            seen.add(bare_target)
            found.append((bare_target, href.split("#")[0]))
        return found

    links = _collect(body)

    # FALLBACK 1: the chosen container gave nothing — re-scan the cleaned page.
    if not links and body is not soup:
        links = _collect(soup)

    # FALLBACK 2: cleaning removed too much (an unlucky class name on a wrapper).
    # Re-parse the ORIGINAL html, drop only obvious chrome, and look again. This
    # guarantees over-eager cleaning can never zero out a page that really does
    # have outbound links.
    if not links:
        raw = BeautifulSoup(html, "html.parser")
        for t in raw.find_all(["nav", "header", "footer", "aside", "form",
                               "script", "style", "button"]):
            t.decompose()
        links = _collect(raw)

    return links, ("ok" if links else "no_links")


def research_site(site, time_range="1m", max_articles=30, workers=10,
                  on_article=None, on_link=None, should_stop=None, on_stats=None):
    """Research one blog site: find articles, extract external links.
    Articles processed in PARALLEL (10 workers). Live callbacks:
      on_article(article_url, count) — as each article is opened
      on_link(link_dict) — for each new external link found
      should_stop() — return True to abort immediately (checked per article)."""
    results = []
    if should_stop and should_stop():
        return results
    article_pairs = _find_articles(site, max_articles, time_range)
    categories = dict(_last_categories)   # snapshot before the next site runs  # list of (url, date)
    global_seen_domains = set()
    counter = [0]

    # Cutoff for the per-article date safety net (checks the article's own HTML)
    delta = TIME_RANGES.get(time_range, timedelta(days=30))
    cutoff = datetime.utcnow() - delta

    # Why articles produced nothing — so "0 links" can be explained
    stats = {"ok": 0, "no_links": 0, "too_old": 0, "unreachable": 0,
             "blocked": 0, "stopped": 0}

    def _do_article(pair):
        article, date_str = pair
        if should_stop and should_stop():
            return (article, date_str, [], "stopped")
        links, reason = _extract_external_links(article, cutoff)
        return (article, date_str, links, reason)

    with ThreadPoolExecutor(max_workers=workers) as ex:
        futures = [ex.submit(_do_article, p) for p in article_pairs]
        for fut in as_completed(futures):
            # Stop fast: as soon as the flag is set, stop collecting results
            if should_stop and should_stop():
                for f in futures:
                    f.cancel()
                break
            try:
                article, date_str, links, reason = fut.result()
            except Exception:
                continue
            stats[reason] = stats.get(reason, 0) + 1
            # An article outside the chosen time range was never really
            # "processed" — don't count it, or the numbers mislead.
            if reason == "too_old":
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
            if not pub_date:
                # no sitemap date — use the date printed in the article itself
                pub_date = _last_article_date.get(article, "")
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
                    "category": categories.get(article, ""),
                }
                results.append(link_data)
                if on_link:
                    try: on_link(link_data)
                    except Exception: pass

    print(f"[BlogResearch] {_root(site)}: {stats['ok']} article(s) with links, "
          f"{stats['no_links']} with none, {stats['too_old']} outside the time range, "
          f"{stats['unreachable']} unreachable, {stats['blocked']} blocked "
          f"-> {len(results)} prospect(s)")
    if isinstance(on_stats, dict):
        for k, v in stats.items():
            on_stats[k] = on_stats.get(k, 0) + v
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
