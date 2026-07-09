"""Compliant business-contact extractor.

Rules baked in:
  - Only fetches the company's OWN website (same registrable domain).
  - Only visits public business pages: contact / about / team / support / legal / privacy.
  - Keeps ONLY addresses on the site's own domain (its published business contacts).
    This naturally excludes personal gmail/yahoo addresses and third-party emails.
  - No social platforms, no forums, no search engines, no JS-render harvesting.
  - Skips role-less personal-looking harvesting; prefers role addresses (info@, contact@ ...).
"""
import re
from urllib.parse import urlparse, urljoin

import requests
from bs4 import BeautifulSoup

from .compliance import domain_has_mx

TIMEOUT = 8
MAX_PAGES = 6
USER_AGENT = "Mozilla/5.0 (compatible; WarmWireCRM/1.0; +contact-page-only)"

EMAIL_RE = re.compile(r"[a-zA-Z0-9._%+\-]+@[a-zA-Z0-9.\-]+\.[a-zA-Z]{2,}")
IGNORE_ENDINGS = (".png", ".jpg", ".jpeg", ".gif", ".webp", ".svg", ".css", ".js", ".ico", ".pdf")

# Only these public business pages are visited.
BUSINESS_PAGE_HINTS = ["contact", "about", "team", "support", "legal", "privacy", "imprint", "impressum"]

ROLE_PREFIXES = ["info", "contact", "sales", "hello", "support", "office", "admin",
                 "enquiry", "enquiries", "inquiries", "help", "team", "mail", "marketing"]

# Never treated as the company's own site.
BLOCKED_DOMAINS = {"facebook.com", "fb.com", "linkedin.com", "instagram.com", "twitter.com",
                   "x.com", "youtube.com", "t.me", "wa.me", "reddit.com", "quora.com",
                   "medium.com", "gmail.com", "yahoo.com", "outlook.com", "hotmail.com"}


def _is_blocked(domain: str) -> bool:
    """Proper domain match — finix.com won't match x.com anymore."""
    d = domain.lower().strip(".")
    return d in BLOCKED_DOMAINS or any(d.endswith("." + b) for b in BLOCKED_DOMAINS)


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
    # mailto: links (many sites hide email behind mailto only)
    for m in re.findall(r'mailto:([^\s"\'<>?&]+)', html, re.I):
        cleaned = m.strip().lower()
        if EMAIL_RE.match(cleaned):
            found.add(cleaned)
    # Cloudflare email protection
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


def _business_pages(base_url: str, root: str, html: str) -> list[str]:
    soup = BeautifulSoup(html, "html.parser")
    pages = []
    for a in soup.find_all("a", href=True):
        href = a["href"].strip()
        if not href or href.startswith(("#", "mailto:", "tel:", "javascript:")):
            continue
        full = urljoin(base_url, href)
        host = urlparse(full).netloc.lower()
        if _is_blocked(host):                           # never follow social/forums/mail hosts
            continue
        if not _same_site(root, full):                 # stay on the company's own site
            continue
        text = (href + " " + a.get_text(" ")).lower()
        if any(k in text for k in BUSINESS_PAGE_HINTS):
            pages.append(full.split("#")[0])
    # de-dup, keep order, cap
    seen, uniq = set(), []
    for p in pages:
        if p not in seen:
            seen.add(p)
            uniq.append(p)
    return uniq[:MAX_PAGES - 1]


def extract_domain(domain: str) -> dict:
    """Scrape one company's own website for its published business contact addresses."""
    root = _root_domain(domain)
    if not root or _is_blocked(root):
        return {"domain": root, "contacts": [], "status": "skipped (not a company site)"}

    base = "https://" + root
    home = _fetch(base)
    if home is None:
        home = _fetch("http://" + root)
    if home is None:
        return {"domain": root, "contacts": [], "status": "site not reachable"}

    raw = _emails_from_html(home)
    source = {e: base for e in raw}

    # pages discovered from the homepage + a few common guessed paths (better recall)
    pages = _business_pages(base, root, home)
    for path in ("/contact", "/contact-us", "/about", "/about-us", "/get-in-touch",
                 "/contacto", "/kontakt", "/impressum", "/advertise", "/advertising",
                 "/partnerships", "/team", "/our-team", "/support", "/help"):
        u = base + path
        if u not in pages:
            pages.append(u)
    for page in pages[:MAX_PAGES + 4]:
        html = _fetch(page)
        if html:
            for e in _emails_from_html(html):
                if e not in source:
                    source[e] = page
            raw |= set(source.keys())

    # KEEP ONLY the company's own published addresses (same domain as the site).
    contacts = []
    for e in sorted(raw):
        local, _, dom = e.partition("@")
        if not dom:
            continue
        if not (dom == root or dom.endswith("." + root)):
            continue  # drop third-party / personal addresses that happen to appear on the page
        contacts.append({
            "email": e,
            "domain": root,
            "source_url": source.get(e, base),
            "role_based": any(local.startswith(p) for p in ROLE_PREFIXES),
            "mx_ok": domain_has_mx(dom),
        })

    # best first: deliverable (MX) + role-based + shorter/cleaner address
    contacts.sort(key=lambda c: (not c["mx_ok"], not c["role_based"], len(c["email"]), c["email"]))
    status = "scraped" if contacts else "no business email found"
    return {"domain": root, "contacts": contacts, "status": status}
