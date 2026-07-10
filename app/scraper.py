"""Compliant business-contact extractor (v4).

AGGRESSIVE EMAIL EXTRACTION:
  - Accepts ALL emails found on public pages (domain-based, free-provider, cross-domain).
  - Does NOT require email domain to match the site domain.
  - Only rejects junk/platform/auto-generated emails.
  - Tries HARD: more pages, higher timeout, mailto+obfuscated+Cloudflare.
  - Vendor mode: detects guest-post/write-for-us/advertise/blog with clickable links.
"""
import re
from urllib.parse import urlparse, urljoin

import requests
from bs4 import BeautifulSoup

from .compliance import domain_has_mx

TIMEOUT = 6
TIMEOUT_QUICK = 3     # guessed pages — fast fail
MAX_PAGES = 8
USER_AGENT = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"

# Reusable session for connection pooling (much faster)
_session = requests.Session()
_session.headers.update({"User-Agent": USER_AGENT})

EMAIL_RE = re.compile(r"[a-zA-Z0-9._%+\-]+@[a-zA-Z0-9.\-]+\.[a-zA-Z]{2,}")
IGNORE_ENDINGS = (".png", ".jpg", ".jpeg", ".gif", ".webp", ".svg", ".css", ".js", ".ico", ".pdf")

BUSINESS_PAGE_HINTS = ["contact", "about", "team", "support", "legal", "privacy", "imprint",
                       "impressum", "write-for-us", "guest-post", "contribute", "advertise",
                       "advertising", "sponsor", "blog", "submit", "partnerships", "press",
                       "media", "editorial", "writers", "authors"]

HIGH_CONF_KW = ["contact", "contact-us", "get-in-touch", "kontakt", "contacto",
                "write-for-us", "guest-post", "contribute", "advertise"]
MED_HIGH_KW = ["about", "about-us", "team", "our-team", "advertising", "partnerships",
               "sponsor", "editorial", "press", "media", "writers", "authors", "submit"]
MED_KW = ["support", "help", "legal", "privacy", "imprint", "impressum", "blog", "footer"]

ROLE_PREFIXES = ["info", "contact", "sales", "hello", "support", "office", "admin",
                 "enquiry", "enquiries", "inquiries", "help", "team", "mail", "marketing",
                 "editor", "editorial", "press", "media", "partnerships", "business", "ads",
                 "guestpost", "guest", "submit", "write", "content", "outreach"]

FREE_PROVIDERS = {"gmail.com", "yahoo.com", "yahoo.co.uk", "outlook.com", "hotmail.com",
                  "hotmail.co.uk", "live.com", "aol.com", "icloud.com", "protonmail.com",
                  "proton.me", "mail.com", "zoho.com", "yandex.com", "gmx.com", "gmx.net"}

JUNK_PATTERNS = [
    r"^(noreply|no-reply|donotreply|mailer-daemon|postmaster|abuse|root|webmaster)@",
    r"^(user|test|demo|sample|placeholder|yourname|youremail|name|email|someone)@",
    r"^(info|contact|hello|support|sales|mail)@(example|test|domain|sample|yoursite|website)\.",
    r"@example\.(com|org|net)$",
    r"@test\.",
    r"@localhost",
    r"@.*sentry",
    r"@.*wixpress\.com$",
    r"@.*wix\.com$",
    r"@.*wordpress\.(com|org)$",
    r"@.*squarespace\.com$",
    r"@.*shopify\.com$",
    r"@.*mailchimp\.com$",
    r"@.*sendgrid\.(com|net)$",
    r"@.*cloudflare\.com$",
    r"@.*hubspot\.(com|net)$",
    r"@.*herokuapp\.com$",
    r"@.*netlify\.(com|app)$",
    r"@.*vercel\.(com|app)$",
    r"@.*amazonaws\.com$",
    r"@.*googleusercontent\.com$",
    r"@.*gstatic\.com$",
    r"@.*gravatar\.com$",
    r"@.*typeform\.com$",
    r"@.*zendesk\.com$",
    r"@.*intercom\.(com|io)$",
    r"^[a-z]@",
    r"@.*\.png$",
    r"@.*\.jpg$",
    r"[0-9a-f]{20,}@",
]
JUNK_RE = [re.compile(p, re.I) for p in JUNK_PATTERNS]

BLOCKED_NAV = {"facebook.com", "fb.com", "linkedin.com", "instagram.com", "twitter.com",
               "x.com", "youtube.com", "t.me", "wa.me", "reddit.com", "quora.com", "medium.com"}

VENDOR_KEYWORDS = {
    "guest_post": ["write for us", "guest post", "guest author", "guest blog", "become a contributor",
                   "submit a post", "submit article", "contribute", "guest writer", "submit guest"],
    "link_insertion": ["link insertion", "niche edit", "link placement", "contextual link"],
    "sponsored": ["sponsored post", "sponsored content", "sponsored article", "paid post",
                  "advertise with us", "advertising", "media kit", "press release", "paid content"],
    "blog": ["blog", "/blog", "articles", "news", "insights", "resources"],
}

GUESSED_PAGES = [
    "/contact", "/contact-us", "/about", "/about-us",
    "/advertise", "/write-for-us", "/guest-post",
    "/blog", "/team", "/support",
]


def _is_nav_blocked(domain):
    d = domain.lower().strip(".")
    return d in BLOCKED_NAV or any(d.endswith("." + b) for b in BLOCKED_NAV)


def _root_domain(url):
    return urlparse(url if "//" in url else "https://" + url).netloc.lower().replace("www.", "")


def _same_site(base_root, link):
    host = urlparse(link).netloc.lower().replace("www.", "")
    return host == "" or host == base_root or host.endswith("." + base_root)


def _decode_cfemail(encoded):
    try:
        r = int(encoded[:2], 16)
        return "".join(chr(int(encoded[i:i+2], 16) ^ r) for i in range(2, len(encoded), 2))
    except Exception:
        return None


def _deobfuscate(text):
    text = re.sub(r"\s*[\[\(\{]\s*at\s*[\]\)\}]\s*", "@", text, flags=re.I)
    text = re.sub(r"\s*[\[\(\{]\s*dot\s*[\]\)\}]\s*", ".", text, flags=re.I)
    return text


def _fetch(url, timeout=None):
    try:
        r = _session.get(url, timeout=timeout or TIMEOUT, allow_redirects=True)
        if r.status_code >= 400:
            return None
        ctype = r.headers.get("content-type", "")
        if "text/html" not in ctype and "text" not in ctype:
            return None
        return r.text
    except Exception:
        return None


def _emails_from_html(html):
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
    # also check href attributes for obfuscated emails
    for m in re.findall(r'href=["\']([^"\']*@[^"\']*)["\']', html):
        cleaned = m.replace("mailto:", "").strip().lower()
        if EMAIL_RE.match(cleaned):
            found.add(cleaned)
    out = set()
    for e in found:
        e = e.lower().strip(".")
        if not e.endswith(IGNORE_ENDINGS):
            out.add(e)
    return out


def _is_junk(email):
    return any(p.search(email) for p in JUNK_RE)


def _classify_email(email, site_root):
    _, _, dom = email.partition("@")
    if dom in FREE_PROVIDERS:
        return "free_provider_email"
    if dom == site_root or dom.endswith("." + site_root):
        return "domain_email"
    return "cross_domain_email"


def _confidence(source_url):
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


def _detect_vendor_signals(all_html, all_pages):
    """Only report signals for pages that ACTUALLY LOADED (not 404).
    all_pages only contains URLs that _fetch returned successfully."""
    signals = {}
    for url in all_pages:
        p = urlparse(url).path.lower()
        if any(k in p for k in ["write-for-us", "guest-post", "contribute", "submit"]):
            signals["write_for_us_page"] = url
        if any(k in p for k in ["advertise", "advertising", "sponsor", "media-kit"]):
            signals["advertise_page"] = url
        if "/blog" in p or "/articles" in p or "/news" in p:
            signals["blog_page"] = url
        if "contact" in p:
            signals["contact_page"] = url
    return signals


def _business_pages(base_url, root, html):
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


def _find_facebook_email(home_html, root):
    """FALLBACK: if no email found on the site, try the site's Facebook page.
    Find the FB link from the site, fetch the FB page, extract any email."""
    fb_links = re.findall(r'https?://(?:www\.)?facebook\.com/[a-zA-Z0-9._\-]+', home_html)
    if not fb_links:
        return []
    fb_url = fb_links[0]
    # Try the /about page on Facebook (more likely to show contact info)
    about_url = fb_url.rstrip("/") + "/about"
    contacts = []
    for url in [about_url, fb_url]:
        html = _fetch(url, timeout=TIMEOUT_QUICK)
        if not html:
            continue
        for e in _emails_from_html(html):
            e = e.lower().strip(".")
            if _is_junk(e):
                continue
            if _is_nav_blocked(e.split("@")[-1]):
                continue
            contacts.append({
                "email": e, "domain": root, "source_url": url,
                "role_based": any(e.split("@")[0].startswith(p) for p in ROLE_PREFIXES),
                "mx_ok": domain_has_mx(e.split("@")[-1]),
                "email_type": _classify_email(e, root),
                "confidence": "medium",
                "domain_match": (e.split("@")[-1] == root),
            })
        if contacts:
            break
    return contacts


def extract_domain(domain, mode="vendor"):
    root = _root_domain(domain)
    if not root or _is_nav_blocked(root):
        return {"domain": root, "contacts": [], "status": "skipped (not a company site)", "vendor_signals": {}}

    base = "https://" + root
    home = _fetch(base)
    if home is None:
        home = _fetch("http://" + root)
    if home is None:
        home = _fetch("https://www." + root)
    if home is None:
        return {"domain": root, "contacts": [], "status": "site not reachable", "vendor_signals": {}}

    all_html = home
    raw = _emails_from_html(home)
    source = {e: base for e in raw}

    pages = _business_pages(base, root, home)
    for path in GUESSED_PAGES:
        u = base + path
        if u not in pages:
            pages.append(u)

    all_pages = [base]
    for page in pages[:MAX_PAGES]:
        html = _fetch(page, timeout=TIMEOUT_QUICK)
        if html:
            all_pages.append(page)
            all_html += " " + html
            for e in _emails_from_html(html):
                if e not in source:
                    source[e] = page
            raw |= set(source.keys())

    vendor_signals = _detect_vendor_signals(all_html, all_pages) if mode == "vendor" else {}

    # Build contacts
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

        email_type = _classify_email(e, root)
        src = source.get(e, base)
        conf = _confidence(src)
        is_role = any(local.startswith(p) for p in ROLE_PREFIXES)
        mx = domain_has_mx(dom)
        domain_match = (dom == root or dom.endswith("." + root))

        contacts.append({
            "email": e, "domain": root, "source_url": src,
            "role_based": is_role, "mx_ok": mx, "email_type": email_type,
            "confidence": conf, "domain_match": domain_match,
        })

    # FALLBACK: if no emails found, try the site's Facebook page
    if not contacts:
        fb_contacts = _find_facebook_email(all_html, root)
        contacts.extend(fb_contacts)

    # SMART SORT
    conf_order = {"high": 0, "medium": 1, "low": 2}
    type_order = {"domain_email": 0, "free_provider_email": 1, "cross_domain_email": 2}
    contacts.sort(key=lambda c: (
        not c["domain_match"],
        conf_order.get(c["confidence"], 2),
        not c["role_based"],
        type_order.get(c["email_type"], 2),
        not c["mx_ok"],
        len(c["email"]),
    ))

    status = "scraped" if contacts else "no business email found"
    return {"domain": root, "contacts": contacts, "status": status, "vendor_signals": vendor_signals}
