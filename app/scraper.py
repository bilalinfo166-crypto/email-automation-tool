"""Compliant business-contact extractor (v2).

Extracts BOTH:
  - Domain-based business emails (info@company.com, contact@brand.com)
  - Publicly listed free-provider emails (businessname@gmail.com, blog@outlook.com)

Rules baked in:
  - Only fetches the company's OWN website (same registrable domain for navigation).
  - Only visits public business pages: contact / about / team / support / legal / privacy.
  - Extracts ALL emails found on those pages (domain-based AND free-provider).
  - Does NOT guess/generate emails — only publicly visible ones.
  - No social platforms, no forums, no search engines, no JS-render harvesting.
  - Tags each email with email_type (domain_email / free_provider_email).
  - Tags each email with confidence (high/medium/low) based on source page.
  - Validates format, deduplicates, and checks MX.
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

# Public business pages to visit
BUSINESS_PAGE_HINTS = ["contact", "about", "team", "support", "legal", "privacy", "imprint", "impressum"]

# High-confidence page keywords (contact/about = most likely official email)
HIGH_CONFIDENCE_KEYWORDS = ["contact", "contact-us", "get-in-touch", "kontakt", "contacto"]
MEDIUM_HIGH_KEYWORDS = ["about", "about-us", "team", "our-team", "advertise", "advertising", "partnerships"]
MEDIUM_KEYWORDS = ["support", "help", "legal", "privacy", "imprint", "impressum"]

ROLE_PREFIXES = ["info", "contact", "sales", "hello", "support", "office", "admin",
                 "enquiry", "enquiries", "inquiries", "help", "team", "mail", "marketing"]

# Free email providers — emails from these are valid if publicly listed on a business page
FREE_PROVIDERS = {"gmail.com", "yahoo.com", "yahoo.co.uk", "outlook.com", "hotmail.com",
                  "hotmail.co.uk", "live.com", "aol.com", "icloud.com", "protonmail.com",
                  "proton.me", "mail.com", "zoho.com", "yandex.com", "gmx.com", "gmx.net"}

# Junk patterns — these are never real contact emails
JUNK_PATTERNS = [
    r"^(noreply|no-reply|donotreply|mailer-daemon|postmaster|abuse|root|webmaster)@",
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
]
JUNK_RE = [re.compile(p, re.I) for p in JUNK_PATTERNS]

# Sites we never navigate to (social/forums/mail providers — for LINK following, not email filtering)
BLOCKED_NAV_DOMAINS = {"facebook.com", "fb.com", "linkedin.com", "instagram.com", "twitter.com",
                       "x.com", "youtube.com", "t.me", "wa.me", "reddit.com", "quora.com", "medium.com"}


def _is_nav_blocked(domain: str) -> bool:
    """Block navigating TO social/forum sites (not for filtering emails)."""
    d = domain.lower().strip(".")
    return d in BLOCKED_NAV_DOMAINS or any(d.endswith("." + b) for b in BLOCKED_NAV_DOMAINS)


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
    # mailto: links
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


def _is_junk(email: str) -> bool:
    """Filter out system/platform/junk addresses that are never real contacts."""
    return any(p.search(email) for p in JUNK_RE)


def _classify_email(email: str, site_root: str) -> str:
    """Return 'domain_email' or 'free_provider_email'."""
    _, _, dom = email.partition("@")
    if dom in FREE_PROVIDERS:
        return "free_provider_email"
    return "domain_email"


def _confidence_from_url(source_url: str) -> str:
    """Score confidence based on which page the email was found on."""
    path = urlparse(source_url).path.lower().rstrip("/")
    slug = path.split("/")[-1] if path else ""
    full = path + " " + slug
    if any(k in full for k in HIGH_CONFIDENCE_KEYWORDS):
        return "high"
    if any(k in full for k in MEDIUM_HIGH_KEYWORDS):
        return "high"  # about/team pages are strong signals too
    if any(k in full for k in MEDIUM_KEYWORDS):
        return "medium"
    if path in ("", "/"):
        return "medium"  # homepage — decent signal
    return "low"


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
    return uniq[:MAX_PAGES - 1]


def extract_domain(domain: str) -> dict:
    """Scrape one website for its publicly listed contact emails.
    Returns both domain-based AND free-provider emails found on public pages."""
    root = _root_domain(domain)
    if not root or _is_nav_blocked(root):
        return {"domain": root, "contacts": [], "status": "skipped (not a company site)"}

    base = "https://" + root
    home = _fetch(base)
    if home is None:
        home = _fetch("http://" + root)
    if home is None:
        return {"domain": root, "contacts": [], "status": "site not reachable"}

    # Collect emails from all public pages, tracking which page each came from
    raw = _emails_from_html(home)
    source = {e: base for e in raw}

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

    # Build contacts — accept BOTH domain-based AND free-provider emails
    contacts = []
    seen = set()
    for e in sorted(raw):
        local, _, dom = e.partition("@")
        if not dom or not local:
            continue
        if e in seen:
            continue
        seen.add(e)

        # Skip junk/system emails
        if _is_junk(e):
            continue

        # Skip emails from platform domains (wix, wordpress, etc.) — already in JUNK_RE
        # but also skip if the email domain is a social/nav-blocked site
        if _is_nav_blocked(dom):
            continue

        email_type = _classify_email(e, root)
        src = source.get(e, base)
        confidence = _confidence_from_url(src)
        is_role = any(local.startswith(p) for p in ROLE_PREFIXES)
        mx = domain_has_mx(dom)

        contacts.append({
            "email": e,
            "domain": root,
            "source_url": src,
            "role_based": is_role,
            "mx_ok": mx,
            "email_type": email_type,
            "confidence": confidence,
        })

    # Sort: high-confidence first, then domain_email before free_provider, then role-based, then MX
    conf_order = {"high": 0, "medium": 1, "low": 2}
    type_order = {"domain_email": 0, "free_provider_email": 1}
    contacts.sort(key=lambda c: (
        conf_order.get(c["confidence"], 2),
        type_order.get(c["email_type"], 1),
        not c["mx_ok"],
        not c["role_based"],
        len(c["email"]),
    ))

    status = "scraped" if contacts else "no business email found"
    return {"domain": root, "contacts": contacts, "status": status}
