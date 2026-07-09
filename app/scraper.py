"""Compliant business-contact extractor (v3).

Speed: 15 concurrent workers, 5s timeout, continuous pool (no batch-wait).
Extracts domain-based AND free-provider emails from public pages.
Smart selection: domain-match first, business role, high-confidence, then free.
Vendor mode: detects guest-post / write-for-us / advertise / blog signals.
Filters dummy/placeholder emails (user@domain, test@, example@, etc.).
"""
import re
from urllib.parse import urlparse, urljoin

import requests
from bs4 import BeautifulSoup

from .compliance import domain_has_mx

TIMEOUT = 5
MAX_PAGES = 8
USER_AGENT = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"

EMAIL_RE = re.compile(r"[a-zA-Z0-9._%+\-]+@[a-zA-Z0-9.\-]+\.[a-zA-Z]{2,}")
IGNORE_ENDINGS = (".png", ".jpg", ".jpeg", ".gif", ".webp", ".svg", ".css", ".js", ".ico", ".pdf")

BUSINESS_PAGE_HINTS = ["contact", "about", "team", "support", "legal", "privacy", "imprint",
                       "impressum", "write-for-us", "guest-post", "contribute", "advertise",
                       "advertising", "sponsor", "blog"]

HIGH_CONF_KW = ["contact", "contact-us", "get-in-touch", "kontakt", "contacto",
                "write-for-us", "guest-post", "contribute", "advertise"]
MED_HIGH_KW = ["about", "about-us", "team", "our-team", "advertising", "partnerships", "sponsor"]
MED_KW = ["support", "help", "legal", "privacy", "imprint", "impressum", "blog"]

ROLE_PREFIXES = ["info", "contact", "sales", "hello", "support", "office", "admin",
                 "enquiry", "enquiries", "inquiries", "help", "team", "mail", "marketing",
                 "editor", "editorial", "press", "media", "partnerships", "business", "ads"]

FREE_PROVIDERS = {"gmail.com", "yahoo.com", "yahoo.co.uk", "outlook.com", "hotmail.com",
                  "hotmail.co.uk", "live.com", "aol.com", "icloud.com", "protonmail.com",
                  "proton.me", "mail.com", "zoho.com", "yandex.com", "gmx.com", "gmx.net"}

# Junk/dummy patterns — NEVER real contacts
JUNK_PATTERNS = [
    r"^(noreply|no-reply|donotreply|mailer-daemon|postmaster|abuse|root|webmaster)@",
    r"^(user|test|admin|demo|sample|placeholder|yourname|youremail|name|email|someone)@",
    r"^(info|contact|hello|support|sales|mail|marketing|team)@(example|test|domain|sample|yoursite|website)\.",
    r"@example\.(com|org|net)$",
    r"@test\.",
    r"@localhost",
    r"@sentry\.",
    r"@wixpress\.com$",
    r"@wordpress\.(com|org)$",
    r"@squarespace\.com$",
    r"@shopify\.com$",
    r"@mailchimp\.com$",
    r"@sendgrid\.(com|net)$",
    r"@cloudflare\.com$",
    r"^[a-z]@",           # single-char local = junk
    r"@.*\.png$",
    r"@.*\.jpg$",
]
JUNK_RE = [re.compile(p, re.I) for p in JUNK_PATTERNS]

BLOCKED_NAV = {"facebook.com", "fb.com", "linkedin.com", "instagram.com", "twitter.com",
               "x.com", "youtube.com", "t.me", "wa.me", "reddit.com", "quora.com", "medium.com"}

# Vendor signals — keywords that indicate a site accepts guest content
VENDOR_KEYWORDS = {
    "guest_post": ["write for us", "guest post", "guest author", "guest blog", "become a contributor",
                   "submit a post", "submit article", "contribute", "guest writer", "submit guest"],
    "link_insertion": ["link insertion", "niche edit", "link placement", "contextual link",
                       "add a link", "insert link", "existing article"],
    "sponsored": ["sponsored post", "sponsored content", "sponsored article", "paid post",
                  "advertise with us", "advertising", "media kit", "press release", "paid content"],
    "blog": ["blog", "/blog", "articles", "news", "insights", "resources"],
}


def _is_nav_blocked(domain: str) -> bool:
    d = domain.lower().strip(".")
    return d in BLOCKED_NAV or any(d.endswith("." + b) for b in BLOCKED_NAV)


def _root_domain(url: str) -> str:
    return urlparse(url if "//" in url else "https://" + url).netloc.lower().replace("www.", "")


def _same_site(base_root: str, link: str) -> bool:
    host = urlparse(link).netloc.lower().replace("www.", "")
    return host == "" or host == base_root or host.endswith("." + base_root)


def _decode_cfemail(encoded: str):
    try:
        r = int(encoded[:2], 16)
        return "".join(chr(int(encoded[i:i + 2], 16) ^ r) for i in range(2, len(encoded), 2))
    except Exception:
        return None


def _deobfuscate(text: str) -> str:
    text = re.sub(r"\s*[\[\(\{]\s*at\s*[\]\)\}]\s*", "@", text, flags=re.I)
    text = re.sub(r"\s*[\[\(\{]\s*dot\s*[\]\)\}]\s*", ".", text, flags=re.I)
    return text


def _fetch(url: str):
    try:
        r = requests.get(url, timeout=TIMEOUT, allow_redirects=True,
                         headers={"User-Agent": USER_AGENT})
        ctype = r.headers.get("content-type", "")
        if "text/html" not in ctype and "text" not in ctype:
            return None
        return r.text
    except Exception:
        return None


def _emails_from_html(html: str) -> set[str]:
    found = set(EMAIL_RE.findall(html))
    found |= set(EMAIL_RE.findall(_deobfuscate(html)))
    for m in re.findall(r'mailto:([^\s"\'<>?&]+)', html, re.I):
        cleaned = m.strip().lower()
        if EMAIL_RE.match(cleaned):
            found.add(cleaned)
    for m in re.findall(r'data-cfemail="([0-9a-fA-F]+)"', html):
        d = _decode_cfemail(m)
        if d:
            found.add(d)
    out = set()
    for e in found:
        e = e.lower().strip(".")
        if not e.endswith(IGNORE_ENDINGS):
            out.add(e)
    return out


def _is_junk(email: str) -> bool:
    return any(p.search(email) for p in JUNK_RE)


def _classify_email(email: str) -> str:
    _, _, dom = email.partition("@")
    return "free_provider_email" if dom in FREE_PROVIDERS else "domain_email"


def _confidence(source_url: str) -> str:
    path = urlparse(source_url).path.lower().rstrip("/")
    slug = path.split("/")[-1] if path else ""
    full = path + " " + slug
    if any(k in full for k in HIGH_CONF_KW):
        return "high"
    if any(k in full for k in MED_HIGH_KW):
        return "high"
    if any(k in full for k in MED_KW):
        return "medium"
    if path in ("", "/"):
        return "medium"
    return "low"


def _detect_vendor_signals(all_html: str, all_pages: list[str]) -> dict:
    """Analyze site for guest-post/link-insertion/sponsored/blog signals."""
    combined = all_html.lower()
    urls_text = " ".join(all_pages).lower()
    signals = {}
    for sig, keywords in VENDOR_KEYWORDS.items():
        found = [kw for kw in keywords if kw in combined or kw in urls_text]
        if found:
            signals[sig] = True
    # detect specific pages
    for url in all_pages:
        p = urlparse(url).path.lower()
        if any(k in p for k in ["write-for-us", "guest-post", "contribute", "submit"]):
            signals["write_for_us_page"] = url
        if any(k in p for k in ["advertise", "advertising", "sponsor", "media-kit"]):
            signals["advertise_page"] = url
        if "/blog" in p or "/articles" in p or "/news" in p:
            signals["blog_page"] = url
    return signals


def _business_pages(base_url: str, root: str, html: str) -> list[str]:
    soup = BeautifulSoup(html, "html.parser")
    pages = []
    for a in soup.find_all("a", href=True):
        href = a["href"].strip()
        if not href or href.startswith(("#", "mailto:", "tel:", "javascript:")):
            continue
        full = urljoin(base_url, href)
        host = urlparse(full).netloc.lower()
        if _is_nav_blocked(host):
            continue
        if not _same_site(root, full):
            continue
        text = (href + " " + a.get_text(" ")).lower()
        if any(k in text for k in BUSINESS_PAGE_HINTS):
            pages.append(full.split("#")[0])
    seen, uniq = set(), []
    for p in pages:
        if p not in seen:
            seen.add(p)
            uniq.append(p)
    return uniq[:MAX_PAGES]


def extract_domain(domain: str, mode: str = "vendor") -> dict:
    """Scrape one website for publicly listed contact emails + vendor signals."""
    root = _root_domain(domain)
    if not root or _is_nav_blocked(root):
        return {"domain": root, "contacts": [], "status": "skipped (not a company site)", "vendor_signals": {}}

    base = "https://" + root
    home = _fetch(base)
    if home is None:
        home = _fetch("http://" + root)
    if home is None:
        return {"domain": root, "contacts": [], "status": "site not reachable", "vendor_signals": {}}

    all_html = home
    raw = _emails_from_html(home)
    source = {e: base for e in raw}

    pages = _business_pages(base, root, home)
    for path in ("/contact", "/contact-us", "/about", "/about-us", "/get-in-touch",
                 "/contacto", "/kontakt", "/impressum", "/advertise", "/advertising",
                 "/partnerships", "/team", "/our-team", "/support", "/help",
                 "/write-for-us", "/guest-post", "/contribute", "/submit-article",
                 "/blog", "/sponsor"):
        u = base + path
        if u not in pages:
            pages.append(u)

    all_pages = [base]
    for page in pages[:MAX_PAGES + 6]:
        html = _fetch(page)
        if html:
            all_pages.append(page)
            all_html += " " + html
            for e in _emails_from_html(html):
                if e not in source:
                    source[e] = page
            raw |= set(source.keys())

    # Vendor signals (only computed if mode == vendor)
    vendor_signals = _detect_vendor_signals(all_html, all_pages) if mode == "vendor" else {}

    # Build contacts — accept BOTH domain-based AND free-provider
    contacts = []
    seen = set()
    for e in sorted(raw):
        local, _, dom = e.partition("@")
        if not dom or not local:
            continue
        if e in seen:
            continue
        seen.add(e)
        if _is_junk(e):
            continue
        if _is_nav_blocked(dom):
            continue

        email_type = _classify_email(e)
        src = source.get(e, base)
        conf = _confidence(src)
        is_role = any(local.startswith(p) for p in ROLE_PREFIXES)
        mx = domain_has_mx(dom)
        # domain match = email domain matches the site being scraped
        domain_match = (dom == root or dom.endswith("." + root))

        contacts.append({
            "email": e,
            "domain": root,
            "source_url": src,
            "role_based": is_role,
            "mx_ok": mx,
            "email_type": email_type,
            "confidence": conf,
            "domain_match": domain_match,
        })

    # SMART SORT: domain-match first > business role > high-confidence > domain_email > free
    conf_order = {"high": 0, "medium": 1, "low": 2}
    type_order = {"domain_email": 0, "free_provider_email": 1}
    contacts.sort(key=lambda c: (
        not c["domain_match"],                    # site's own email first
        conf_order.get(c["confidence"], 2),       # high confidence first
        not c["role_based"],                      # role-based (info@, contact@) first
        type_order.get(c["email_type"], 1),        # domain email before free
        not c["mx_ok"],                           # deliverable first
        len(c["email"]),                          # shorter = cleaner
    ))

    status = "scraped" if contacts else "no business email found"
    return {"domain": root, "contacts": contacts, "status": status, "vendor_signals": vendor_signals}
