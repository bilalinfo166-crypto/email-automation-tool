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

    # A handful of huge aggregators genuinely can't be crawled (MSN, Yahoo...).
    # Everything else is fair game — we research whatever the user gives us.
    #
    # NOTE: _is_skip() is deliberately NOT used here. That list decides which
    # link TARGETS are worth pitching, and it also holds the sites currently
    # being researched — using it here made the tool refuse the user's own
    # research sites ("techbullion.com is a giant news portal").
    bare = root.replace("www.", "")
    if bare in NOT_BLOG_SITES:
        return {"ok": True, "reason": "large_portal",
                "hint": f"'{bare}' is a very large portal, so it may return few "
                        "guest-post prospects. We'll still crawl it."}

    # Can we even reach it? This is only a sanity check before the real run, so
    # it uses short timeouts and few requests — a slow check that makes the user
    # wait minutes is worse than no check at all.
    # Sites are checked in parallel, so a generous timeout costs nothing overall
    # — and it stops a merely-slow site being reported as dead.
    base = "https://" + root
    html = _fetch_check(base, timeout=10)
    if not html:
        html = _fetch_check("http://" + root, timeout=8)
    if not html:
        # Advisory only. Plenty of sites block a bare pre-check but crawl fine
        # during the real run, so this must never stop the job.
        return {"ok": True, "reason": "slow_or_protected",
                "hint": f"'{bare}' didn't respond to the quick check — it may be slow "
                        "or bot-protected. We'll still try it."}

    # Does it have a sitemap? (best signal it's a real, crawlable blog)
    # Two probes is enough here — the real run tries every variant.
    has_sitemap = False
    for sm in ["/sitemap.xml", "/post-sitemap.xml"]:
        if _fetch_check(base + sm, timeout=6):
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
# Pool must comfortably exceed the worker count, otherwise threads queue up
# waiting for a free connection instead of doing work.
_adapter = requests.adapters.HTTPAdapter(pool_connections=120, pool_maxsize=120, max_retries=1)
_session.mount("https://", _adapter)
_session.mount("http://", _adapter)

# A SEPARATE session for the pre-flight site check. Sharing the pool with a
# running research job meant the check sat waiting for a free connection —
# which looked like "Checking sites..." hanging for minutes.
_check_session = requests.Session()
_check_session.headers.update(HEADERS)
_check_adapter = requests.adapters.HTTPAdapter(pool_connections=20, pool_maxsize=20, max_retries=0)
_check_session.mount("https://", _check_adapter)
_check_session.mount("http://", _check_adapter)


def _fetch_check(url, timeout=8):
    """Fetch used only by check_site — never blocked by a running research job."""
    try:
        r = _check_session.get(url, timeout=timeout, allow_redirects=True)
        if r.status_code == 200:
            return _decode_body(r)
    except Exception:
        pass
    return None


def _root(url):
    try:
        return urlparse(url if "//" in url else "https://" + url).netloc.lower().replace("www.", "")
    except Exception:
        return ""


def _is_skip(domain):
    d = domain.lower().replace("www.", "")

    # A bare IP address is never a guest-post prospect — it's usually a tracking
    # pixel, a CDN node or a misparsed link.
    if re.match(r"^\d{1,3}(?:\.\d{1,3}){1,3}$", d):
        return True
    # Not a real hostname
    if "." not in d or d.endswith("."):
        return True
    # localhost / internal addresses
    if d in ("localhost", "127.0.0.1") or d.endswith(".local"):
        return True

    # Our own domains — the company site and every sender's domain. Linking to
    # ourselves is not a lead.
    for own in _OWN_DOMAINS:
        if d == own or d.endswith("." + own):
            return True
    # ...and anything built on one of our brand names, whatever the extension
    # (bradvertisers.com, bradvertisers.co.uk, blog.bradvertisers.net ...)
    labels = d.split(".")
    for brand in _OWN_BRANDS:
        if brand in labels:
            return True
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

# Our own domains: the company website plus every sender's domain. These turn
# up in email footers and signatures all the time, and they're never prospects.
_OWN_DOMAINS = set()


# Brand words taken from our own addresses (e.g. "bradvertisers" out of
# hira.bradvertisers@gmail.com). Any domain built on one of these is ours.
_OWN_BRANDS = set()


def set_own_domains(domains, brands=None):
    """Register what belongs to us, so it's never offered back as a prospect."""
    _OWN_DOMAINS.clear()
    _OWN_BRANDS.clear()
    token_counts = {}
    for d in domains or []:
        d = (d or "").strip().lower().replace("www.", "")
        if "@" in d:
            local, d = d.split("@")[0], d.split("@")[-1]
            # A free-mail address says nothing about the domain, but the local
            # part often carries the brand: hira.bradvertisers@gmail.com
            for tok in re.split(r"[.\-_+]", local):
                if len(tok) >= 5 and not tok.isdigit():
                    token_counts[tok] = token_counts.get(tok, 0) + 1
        d = re.sub(r"^https?://", "", d).split("/")[0]
        if d and "." in d:
            _OWN_DOMAINS.add(d)

    # Only a word shared by SEVERAL of our addresses is the company name.
    # A word used once is a person ("marita"), and blocking that could throw
    # away a real prospect with the same name.
    for tok, n in token_counts.items():
        if n >= 2:
            _OWN_BRANDS.add(tok)
    for b in brands or []:
        b = (b or "").strip().lower()
        if len(b) >= 4:
            _OWN_BRANDS.add(b)
    # Free providers are already skipped elsewhere; keep them out of "ours"
    _OWN_DOMAINS.discard("gmail.com")
    _OWN_DOMAINS.discard("googlemail.com")


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


# Cloudflare's "checking your browser" interstitial comes back as 200 OK with
# almost no content. Because it wasn't recognised, every one of those pages was
# counted as "an article with no links" — which is why a site could report
# hundreds of articles and zero links.
CHALLENGE_MARKERS = (
    "just a moment", "checking your browser", "cf-browser-verification",
    "cf_chl_opt", "cf_chl_jschl", "challenge-platform", "__cf_chl",
    "enable javascript and cookies to continue", "verifying you are human",
    "ddos protection by", "please turn javascript on",
    "attention required", "access denied", "error 1015", "error 1020",
    "you are being rate limited", "request blocked",
)


def _is_cloudflare_blocked(html):
    """True when the page is a bot check / block page rather than real content."""
    if not html:
        return False
    low = html[:6000].lower()          # markers always appear near the top
    if any(m in low for m in CHALLENGE_MARKERS):
        return True
    # A near-empty page that only ships scripts is a challenge shell too
    if len(html) < 2500 and "<script" in low and low.count("<a ") <= 1:
        return True
    return False


# Publish date read out of each article's own HTML, used when the sitemap
# didn't provide one.
_last_article_date = {}

# A few examples of articles that produced no links, with what was actually on
# the page. Used to explain a zero result instead of leaving it a mystery.
_no_link_samples = []

# Articles whose publish date was already confirmed IN-WINDOW at discovery time
# (from sitemap lastmod or a date in the URL). Used so the strict HTML-date
# check can still keep them even if the article page itself carries no date.
_confirmed_dates = {}

# Which section each article was found under, filled by the most recent
# _find_articles() call and read by research_site().
_last_categories = {}


def _find_articles(site, max_articles=30, time_range="1m", workers=50):
    """Find recent article URLs from a blog site within the time range.
    Prefers sitemap (real dated posts, newest-first). Filters out articles
    older than the cutoff using sitemap <lastmod> dates and URL-embedded dates."""
    root = _root(site)
    base = "https://" + root
    articles = []  # list of (url, date_str)
    seen = set()
    _confirmed_dates.clear()   # fresh per site — no stale confirmations
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
        # If discovery gave a real date (sitemap lastmod or a date in the URL)
        # AND it's inside the window, remember that — the strict HTML-date check
        # in extraction will trust it even if the page itself has no date.
        d = _parse_date(lastmod) or _date_from_url(u)
        if d is not None and d >= cutoff:
            _confirmed_dates[u] = True
        seen.add(u)
        articles.append((u, lastmod))

    # 1. SITEMAP FIRST. Big WordPress sites split posts across MANY numbered
    # sitemaps (post-sitemap.xml, post-sitemap2.xml, post-sitemap3.xml...).
    # In Yoast, HIGHER numbers usually hold the NEWEST posts. We gather from the
    # sitemap index if present, PLUS follow numbered sitemaps until they run out.
    # Index files and the numbered sitemaps are probed in the SAME batch.
    # Waiting for the index first, then starting the numbered probe, then the
    # listing pages, meant three sequential waits per site — most of the time
    # was spent waiting rather than working.
    index_urls = ["/sitemap_index.xml", "/sitemap.xml", "/wp-sitemap.xml"]
    post_sitemaps = []

    # Always probe the numbered sitemaps as well — cheap now that everything
    # runs together, and it covers sites whose index is missing or stale.
    if True:
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

    # Fetch the candidate sitemaps IN PARALLEL. Probing up to forty of them one
    # after another was the single slowest step — on a site with no numbered
    # sitemaps it burned minutes before a single article was read.
    # index files first, then the numbered guesses
    post_sitemaps = [base + ix for ix in index_urls] + post_sitemaps
    # de-dupe while keeping order
    seen_sm = set()
    post_sitemaps = [u for u in post_sitemaps
                     if not (u in seen_sm or seen_sm.add(u))][:45]
    all_entries = []

    def _grab_sitemap(url):
        html = _fetch(url, timeout=7)
        if not html:
            return []
        ents = _parse_sitemap_entries(html)
        arts = [(u, m) for u, m in ents if not u.endswith(".xml")]
        if arts:
            return arts
        # It's an index — follow the post/news sub-sitemaps it points at.
        subs = [u for u, _ in ents if u.endswith(".xml")
                and any(k in u.lower() for k in ["post", "article", "news", "blog"])]

        # Take the HIGHEST-numbered ones first. Big WordPress sites split posts
        # across post-sitemap1..40, and the LOW numbers hold the OLDEST posts.
        # Reading them in document order meant loading 2016 archives and then
        # discarding them all as "outside the time window".
        def _num(u):
            m = re.search(r"(\d+)\.xml", u)
            return int(m.group(1)) if m else 0
        subs.sort(key=_num, reverse=True)
        subs = subs[:12]

        out = []
        for sub in subs:
            sub_html = _fetch(sub, timeout=7)
            if sub_html:
                out.extend((u, m) for u, m in _parse_sitemap_entries(sub_html)
                           if not u.endswith(".xml"))
        return out

    # NOTE: no `with` block here on purpose. Exiting a ThreadPoolExecutor
    # context waits for EVERY submitted task, so one hanging site could stall
    # the whole run even though we set a timeout. Shutting down without waiting
    # keeps things moving.
    # Kick off the listing pages (homepage, /blog, /news ...) in the SAME batch
    # as the sitemaps, so the two no longer wait for each other.
    early_listing = [(base, "Home"), (base + "/blog", "Blog"), (base + "/news", "News"),
                     (base + "/articles", "Articles"), (base + "/insights", "Insights"),
                     (base + "/resources", "Resources"), (base + "/posts", "Posts")]
    ex = ThreadPoolExecutor(max_workers=min(workers, len(post_sitemaps) + len(early_listing)))
    early_pages = []
    try:
        listing_futs = {ex.submit(_fetch, url, 6): (url, label)
                        for url, label in early_listing}
        futs = [ex.submit(_grab_sitemap, sm) for sm in post_sitemaps]
        for f in as_completed(futs, timeout=20):
            try:
                all_entries.extend(f.result())
            except Exception:
                continue
    except Exception:
        pass   # take whatever came back in time
        # collect whatever the listing fetches produced
        for f, (url, label) in listing_futs.items():
            try:
                early_pages.append((url, label, f.result(timeout=1)))
            except Exception:
                continue
    finally:
        ex.shutdown(wait=False, cancel_futures=True)
    print(f"[BlogResearch] {root}: sitemaps gave {len(all_entries)} url(s)")

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

    def _find_category_pages(page_url, html=None):
        """Read the site's own navigation and return its category/section pages.

        Rather than guessing which sections a site has, this takes them from the
        menu the site actually shows (CELEBRITY, TECH, BUSINESS, NEWS ...).
        """
        if html is None:
            html = _fetch(page_url, timeout=6)
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
        # The homepage and the obvious listing pages were already fetched
        # alongside the sitemaps — reuse them instead of downloading again.
        pages = [p for p in early_pages if p[2]]
        home_html = next((h for (u, l, h) in early_pages if u == base and h), None)

        # Sections the site lists in its own menu (read from the homepage we
        # already have, so this costs no extra request).
        listing_pages = []
        try:
            listing_pages = _find_category_pages(base, html=home_html)[:20]
        except Exception:
            pass

        # Fetch every listing page AT ONCE. Doing this one at a time meant ~20
        # sequential page loads per site before a single article was read — on
        # several sites that alone took many minutes.
        def _grab(item):
            page_url, label = item
            html = _fetch(page_url, timeout=6)
            return (page_url, label, html)

        ex2 = ThreadPoolExecutor(max_workers=max(1, min(workers, len(listing_pages))))
        try:
            if not listing_pages:
                raise StopIteration
            futs = [ex2.submit(_grab, it) for it in listing_pages]
            for f in as_completed(futs, timeout=20):
                try:
                    pages.append(f.result())
                except Exception:
                    continue
        except Exception:
            pass  # whatever arrived in time is enough
        finally:
            ex2.shutdown(wait=False, cancel_futures=True)

        for page_url, label, html in pages:
            if len(articles) >= max_articles:
                break
            if not html:
                continue
            try:
                soup = BeautifulSoup(html, "html.parser")
            except Exception:
                continue
            for a in soup.find_all("a", href=True):
                full = urljoin(page_url, a["href"])
                if _root(full) != root:
                    continue
                path = urlparse(full).path.strip("/")
                if not path or not _looks_like_article(path):
                    continue
                before = len(articles)
                _add(full)
                if len(articles) > before:
                    article_category[articles[-1][0]] = label
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

    # STRICT date enforcement. The user wants only articles inside the selected
    # window — nothing older, and nothing whose date we can't confirm.
    #   - HTML date present and older than cutoff  -> skip ("too_old")
    #   - HTML date present and within window       -> keep
    #   - no HTML date, but the sitemap/URL already gave a confirmed in-window
    #     date (recorded in _confirmed_dates)       -> keep
    #   - no date anywhere                           -> skip ("no_date"), because
    #     we can't prove it's inside the window
    pub = _date_from_html(html)
    if cutoff is not None:
        if pub is not None:
            if pub < cutoff:
                return [], "too_old"
        else:
            # HTML had no date — only keep if a date was already confirmed
            # in-window at the discovery stage (sitemap lastmod / URL date).
            if not _confirmed_dates.get(article_url):
                return [], "no_date"
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

    # 3) Pick the real article-content container — try many patterns, widest net.
    #    Covers WordPress, Ghost, Medium, Substack, Drupal, Joomla, Webflow, and
    #    common hand-rolled themes. Order matters: most-specific first.
    body = (soup.find("article")
            or soup.find(attrs={"class": re.compile(r"(entry-content|post-content|article-content|td-post-content|single-content|post-body|content-area|article-body|story-body|article__body|post__content|c-content|main-content|page-content|blog-content|story__content|rich-text|prose|gh-content|kg-canvas|post-full-content|node__content|field--name-body|com-content|item-page|blog-post-content|post-text|articletext|article-text|content__body|body-content|entry|postbody|the-content|content-body)", re.I)})
            or soup.find(attrs={"itemprop": "articleBody"})
            or soup.find(attrs={"role": "article"})
            or soup.find("main")
            or soup.find("body")
            or soup)

    # If we picked a broad <article>/<main> but it CONTAINS a specific content
    # div, drill into that div — <article> tags often wrap related-posts and
    # author boxes too, and those aren't part of the editorial content.
    if body is not soup and body.name in ("article", "main"):
        inner = body.find(attrs={"class": re.compile(
            r"(entry-content|post-content|td-post-content|article__body|post__content|"
            r"gh-content|post-full-content|the-content|content-body|article-body)", re.I)})
        if inner is not None and len(inner.find_all("a", href=True)) > 0:
            body = inner

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

    # Diagnostics for the "no links" case — recorded so the run can explain
    # itself instead of silently reporting zero.
    try:
        _all_a = soup.find_all("a", href=True)
        _ext = [a for a in _all_a if a["href"].startswith("http")
                and _root(a["href"]) and _root(a["href"]).replace("www.", "")
                != root.replace("www.", "")]
        _diag = {"anchors": len(_all_a), "external": len(_ext),
                 "container": (body.name if body is not soup else "whole-page"),
                 "samples": [a["href"][:70] for a in _ext[:4]]}
    except Exception:
        _diag = {}

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

    if not links:
        # remember the first few so the summary can show what was on the page
        if len(_no_link_samples) < 3:
            _no_link_samples.append({"url": article_url, **_diag})
        return links, "no_links"
    return links, "ok"


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
    article_pairs = _find_articles(site, max_articles, time_range, workers=workers)
    categories = dict(_last_categories)   # snapshot before the next site runs  # list of (url, date)
    global_seen_domains = set()
    counter = [0]

    # Cutoff for the per-article date safety net (checks the article's own HTML)
    delta = TIME_RANGES.get(time_range, timedelta(days=30))
    cutoff = datetime.utcnow() - delta

    # Why articles produced nothing — so "0 links" can be explained
    stats = {"ok": 0, "no_links": 0, "too_old": 0, "unreachable": 0,
             "blocked": 0, "stopped": 0, "no_date": 0}
    _no_link_samples.clear()

    def _do_article(pair):
        article, date_str = pair
        if should_stop and should_stop():
            return (article, date_str, [], "stopped")
        links, reason = _extract_external_links(article, cutoff)
        return (article, date_str, links, reason)

    print(f"[BlogResearch] {_root(site)}: reading {len(article_pairs)} article(s) "
          f"with {workers} workers")
    # Hard ceiling per site so one slow site can never stall the whole job.
    ARTICLE_BUDGET = 180  # seconds
    ex = ThreadPoolExecutor(max_workers=workers)
    try:
        futures = [ex.submit(_do_article, p) for p in article_pairs]
        for fut in as_completed(futures, timeout=ARTICLE_BUDGET):
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
    except Exception as e:
        print(f"[BlogResearch] {_root(site)}: stopped reading early ({type(e).__name__}) "
              f"— moving on with what was collected")
    finally:
        # Don't wait on stragglers — a single unresponsive article shouldn't
        # hold up the rest of the run.
        ex.shutdown(wait=False, cancel_futures=True)

    for smp in _no_link_samples:
        print(f"[BlogResearch]   no-links example: {smp.get('url','')}")
        print(f"[BlogResearch]     anchors={smp.get('anchors')} external={smp.get('external')} "
              f"container={smp.get('container')}")
        for ex in smp.get("samples", []):
            print(f"[BlogResearch]     saw: {ex}")
    if _no_link_samples and isinstance(on_stats, dict):
        on_stats["no_link_examples"] = list(_no_link_samples)

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
