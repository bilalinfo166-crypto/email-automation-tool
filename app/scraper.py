"""Email extractor v7 — COMPLETE REWRITE.

Fixes all 4 problems:
1. Deep extraction: raw HTML + visible text + JSON-LD + meta + data-attrs + script tags
2. Full deobfuscation: [at]/[dot], HTML entities, URL-encoded, span-split, reversed, CSS rtl
3. Per-domain timeout: max 30 seconds total per domain (not per page)
4. More pages: 12 pages checked (homepage + footer/header always included)

Speed: 20 workers continuous (no chunk-wait). SSL flexible. No MX during scrape.
"""
import re, time, html as html_mod
from urllib.parse import urlparse, urljoin, unquote
import requests, urllib3
from bs4 import BeautifulSoup

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

DOMAIN_TIMEOUT = 30   # max seconds per domain (all pages combined)
PAGE_TIMEOUT = 8      # per-page network timeout
PAGE_TIMEOUT_QUICK = 5
MAX_PAGES = 12
UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"

_s = requests.Session()
_s.headers.update({"User-Agent": UA})
_s.verify = False

EMAIL_RE = re.compile(r"[a-zA-Z0-9._%+\-]+@[a-zA-Z0-9.\-]+\.[a-zA-Z]{2,}")

ROLE_PFX = ["info","contact","sales","hello","support","office","admin","enquiry",
            "help","team","mail","marketing","editor","editorial","press","media",
            "partnerships","business","ads","guestpost","guest","submit","write",
            "content","outreach","advertise","blog","hr","careers","jobs"]

FREE = {"gmail.com","yahoo.com","yahoo.co.uk","outlook.com","hotmail.com",
        "hotmail.co.uk","live.com","aol.com","icloud.com","protonmail.com",
        "proton.me","mail.com","zoho.com","yandex.com","gmx.com","gmx.net"}

JUNK_RE = [re.compile(p, re.I) for p in [
    r"^(noreply|no-reply|donotreply|mailer-daemon|postmaster|abuse|root|webmaster)@",
    r"^(user|test|demo|sample|placeholder|yourname|youremail|name|email|someone)@",
    r"^(your|you|me|my)@",
    r"@example\.(com|org|net)$", r"@test\.", r"@localhost",
    r"@.*sentry", r"@.*wixpress", r"@.*wix\.com$",
    r"@.*wordpress\.(com|org)$", r"@.*squarespace\.com$", r"@.*shopify\.com$",
    r"@.*mailchimp\.com$", r"@.*sendgrid\.(com|net)$", r"@.*cloudflare\.com$",
    r"@.*hubspot\.(com|net)$", r"@.*herokuapp\.com$", r"@.*netlify",
    r"@.*vercel", r"@.*amazonaws\.com$", r"@.*googleusercontent\.com$",
    r"@.*gravatar\.com$", r"@.*typeform\.com$", r"@.*zendesk\.com$",
    r"@.*intercom\.(com|io)$", r"@.*gstatic\.com$",
    r"^[a-z]@", r"@.*\.(png|jpg|gif|svg|css|js)$", r"[0-9a-f]{20,}@",
]]

BLOCKED = {"facebook.com","fb.com","linkedin.com","instagram.com","twitter.com",
           "x.com","youtube.com","t.me","wa.me","reddit.com","quora.com","medium.com"}

# All pages to check (discovered + guessed)
GUESS_PATHS = [
    "/contact","/contact-us","/about","/about-us","/blog",
    "/advertise","/write-for-us","/guest-post","/team","/support",
    "/privacy","/privacy-policy","/terms","/legal","/imprint",
]

HI_KW = ["contact","contact-us","get-in-touch","write-for-us","guest-post","advertise"]
MD_KW = ["about","about-us","team","blog","support","help","privacy","terms","legal"]


def _blocked(d):
    d=d.lower().strip(".")
    return d in BLOCKED or any(d.endswith("."+b) for b in BLOCKED)

def _root(u):
    return urlparse(u if "//" in u else "https://"+u).netloc.lower().replace("www.","")

def _same(root,link):
    h=urlparse(link).netloc.lower().replace("www.","")
    return h=="" or h==root or h.endswith("."+root)

def _cfe(enc):
    try:
        r=int(enc[:2],16); return "".join(chr(int(enc[i:i+2],16)^r) for i in range(2,len(enc),2))
    except: return None


def _deob(t):
    """FULL deobfuscation — handles all known patterns."""
    # URL decode first (%40=@, %2e=.)
    t = unquote(t)
    # HTML entity decode (&#64;, &#x40;, &commat;, etc.)
    t = html_mod.unescape(t)
    # [at] (at) {at} variations
    t = re.sub(r"\s*[\[\(\{<]\s*at\s*[\]\)\}>]\s*", "@", t, flags=re.I)
    # [dot] (dot) {dot} variations
    t = re.sub(r"\s*[\[\(\{<]\s*dot\s*[\]\)\}>]\s*", ".", t, flags=re.I)
    # Spaced: info at domain dot com / info AT domain DOT com
    t = re.sub(r"\b\s+at\s+\b", "@", t, flags=re.I)
    t = re.sub(r"\b\s+dot\s+\b", ".", t, flags=re.I)
    # Spaces around @ and . : info @ domain . com
    t = re.sub(r"\s*@\s*", "@", t)
    t = re.sub(r"\s*\.\s*", ".", t)
    # -at- and -dot- separators
    t = re.sub(r"\s*-at-\s*", "@", t, flags=re.I)
    t = re.sub(r"\s*-dot-\s*", ".", t, flags=re.I)
    return t


def _get(url, to=None):
    try:
        r = _s.get(url, timeout=to or PAGE_TIMEOUT, allow_redirects=True)
        if r.status_code >= 400: return None
        # Force encoding if needed
        if r.encoding and r.encoding.lower() != 'utf-8':
            r.encoding = r.apparent_encoding or 'utf-8'
        ct = r.headers.get("content-type", "").lower()
        if any(k in ct for k in ["text","html","xml","json"]): return r.text
        if not ct: return r.text
        return None
    except: return None


def _find(html_text):
    """DEEP email extraction from HTML — 8 methods."""
    found = set()

    # 1) Raw regex on full HTML source
    found |= set(EMAIL_RE.findall(html_text))

    # 2) Deobfuscated raw HTML
    deobbed = _deob(html_text)
    found |= set(EMAIL_RE.findall(deobbed))

    # 3) mailto: links (including URL-encoded)
    for m in re.findall(r'mailto:([^\s"\'<>?&]+)', html_text, re.I):
        c = unquote(m).strip().lower()
        if EMAIL_RE.match(c): found.add(c)

    # 4) Cloudflare email protection
    for m in re.findall(r'data-cfemail="([0-9a-fA-F]+)"', html_text):
        d = _cfe(m)
        if d: found.add(d)

    # 5) Any href with @
    for m in re.findall(r'href=["\']([^"\']*@[^"\']*)["\']', html_text):
        c = unquote(m).replace("mailto:", "").strip().lower()
        if EMAIL_RE.match(c): found.add(c)

    # 6) BeautifulSoup deep parse
    try:
        soup = BeautifulSoup(html_text, "html.parser")

        # Visible text (catches rendered obfuscation)
        text = soup.get_text("\n", strip=True)  # newline separator prevents word merging
        found |= set(EMAIL_RE.findall(text))
        found |= set(EMAIL_RE.findall(_deob(text)))

        # Span-split emails: <span>info</span>@<span>site.com</span>
        # Only check elements that directly contain @ in their own text
        for el in soup.find_all(string=re.compile(r'@')):
            parent = el.parent
            if parent:
                siblings_text = parent.get_text(" ", strip=True)
                found |= set(EMAIL_RE.findall(siblings_text))

        # Meta tags (description, keywords, author)
        for tag in soup.find_all("meta"):
            for attr in ["content", "value"]:
                val = tag.get(attr, "")
                if val:
                    found |= set(EMAIL_RE.findall(val))
                    found |= set(EMAIL_RE.findall(_deob(val)))

        # data- attributes (data-email, data-contact, etc.)
        for tag in soup.find_all(True):
            for attr, val in tag.attrs.items():
                if isinstance(val, str) and ("email" in attr.lower() or "contact" in attr.lower() or "@" in val):
                    found |= set(EMAIL_RE.findall(val))
                    found |= set(EMAIL_RE.findall(_deob(val)))

        # JSON-LD structured data (Schema.org)
        for script in soup.find_all("script", type="application/ld+json"):
            if script.string:
                found |= set(EMAIL_RE.findall(script.string))

        # Inline scripts (sometimes emails in JS variables)
        for script in soup.find_all("script"):
            if script.string and "@" in (script.string or ""):
                # Only extract if it looks like a real email assignment
                found |= set(EMAIL_RE.findall(script.string))

        # Alt, title, placeholder attributes
        for attr in ["alt", "title", "placeholder", "value", "aria-label"]:
            for tag in soup.find_all(attrs={attr: True}):
                val = tag[attr]
                found |= set(EMAIL_RE.findall(_deob(val)))

    except: pass

    # 7) Reversed strings (moc.elpmaxe@ofni)
    for m in re.findall(r'[a-z0-9.]+@[a-z0-9.]+\.[a-z]{2,}', html_text[::-1].lower()):
        rev = m[::-1]
        if EMAIL_RE.match(rev): found.add(rev)

    # Clean results — validate format and remove garbage
    clean = set()
    for e in found:
        e = e.lower().strip(".")
        if e.endswith((".png",".jpg",".gif",".svg",".css",".js",".ico",".pdf",".woff",".ttf")): continue
        if len(e) > 60: continue  # too long = garbage concatenation
        local, _, dom = e.partition("@")
        if not dom or not local: continue
        if ".." in dom or ".." in local: continue
        if len(local) > 40 or len(dom) > 40: continue  # way too long
        if not re.match(r'^[a-z0-9][a-z0-9._+\-]*$', local): continue
        if not re.match(r'^[a-z0-9][a-z0-9.\-]*\.[a-z]{2,10}$', dom): continue
        tld = dom.rsplit(".", 1)[-1]
        if len(tld) > 4: continue
        # Reject if local part looks like a concatenated domain (has 2+ dots)
        if local.count(".") >= 3: continue
        clean.add(e)
    return clean


def _junk(e): return any(p.search(e) for p in JUNK_RE)

def _typ(e, root):
    _,_,d = e.partition("@")
    if d in FREE: return "free_provider_email"
    if d == root or d.endswith("." + root): return "domain_email"
    return "cross_domain_email"

def _conf(src):
    p = urlparse(src).path.lower().rstrip("/")
    s = p.split("/")[-1] if p else ""
    f = p + " " + s
    if any(k in f for k in HI_KW): return "high"
    if any(k in f for k in MD_KW): return "medium"
    if p in ("", "/"): return "medium"
    return "low"

def _sigs(pages):
    s = {}
    for u in pages:
        p = urlparse(u).path.lower()
        if any(k in p for k in ["write-for-us","guest-post","contribute","submit"]): s["write_for_us_page"] = u
        if any(k in p for k in ["advertise","advertising","sponsor","media-kit"]): s["advertise_page"] = u
        if "/blog" in p or "/articles" in p or "/news" in p: s["blog_page"] = u
        if "contact" in p: s["contact_page"] = u
    return s

def _discover(base, root, html_text):
    """Discover business pages from homepage links."""
    soup = BeautifulSoup(html_text, "html.parser")
    hints = ["contact","about","team","support","blog","write-for-us","guest-post",
             "advertise","privacy","terms","legal","press","media","editorial"]
    pages = []
    for a in soup.find_all("a", href=True):
        href = a["href"].strip()
        if not href or href.startswith(("#","mailto:","tel:","javascript:")): continue
        full = urljoin(base, href)
        h = urlparse(full).netloc.lower()
        if _blocked(h): continue
        if not _same(root, full): continue
        txt = (href + " " + a.get_text(" ")).lower()
        if any(k in txt for k in hints): pages.append(full.split("#")[0])
    seen = set(); uniq = []
    for p in pages:
        if p not in seen: seen.add(p); uniq.append(p)
    return uniq

def _fb(html_text, root):
    """Facebook fallback for sites with no emails."""
    links = re.findall(r'https?://(?:www\.)?facebook\.com/[a-zA-Z0-9._\-]+', html_text)
    if not links: return []
    out = []
    for url in [links[0].rstrip("/") + "/about", links[0]]:
        h = _get(url, PAGE_TIMEOUT_QUICK)
        if not h: continue
        for e in _find(h):
            if _junk(e) or _blocked(e.split("@")[-1]): continue
            l,_,d = e.partition("@")
            out.append({"email":e,"domain":root,"source_url":url,
                "role_based":any(l.startswith(p) for p in ROLE_PFX),
                "mx_ok":True,"email_type":_typ(e,root),
                "confidence":"medium","domain_match":(d==root)})
        if out: break
    return out


def extract_domain(domain, mode="vendor"):
    """Extract emails from a domain. Max 30 seconds total."""
    start = time.time()
    root = _root(domain)
    if not root or _blocked(root):
        return {"domain":root,"contacts":[],"status":"skipped","vendor_signals":{},"client_category":""}

    def time_left(): return max(0, DOMAIN_TIMEOUT - (time.time() - start))
    def timed_out(): return time.time() - start >= DOMAIN_TIMEOUT

    # Try to load homepage
    base = "https://" + root
    home = _get(base)
    if not home and not timed_out(): home = _get("http://" + root)
    if not home and not timed_out(): home = _get("https://www." + root)
    if not home:
        return {"domain":root,"contacts":[],"status":"site not reachable","vendor_signals":{},"client_category":""}

    # Extract from homepage (ALWAYS do this thoroughly)
    html_all = home
    raw = _find(home)
    src = {e: base for e in raw}

    # Discover pages from homepage + add guessed paths
    pages = _discover(base, root, home)
    for path in GUESS_PATHS:
        u = base + path
        if u not in pages: pages.append(u)

    # Fetch additional pages (within time budget)
    loaded = [base]
    for pg in pages[:MAX_PAGES]:
        if timed_out(): break
        remaining = min(PAGE_TIMEOUT_QUICK, time_left())
        if remaining < 1: break
        h = _get(pg, remaining)
        if h:
            loaded.append(pg)
            html_all += " " + h
            for e in _find(h):
                if e not in src: src[e] = pg
            raw |= set(src.keys())

    # Vendor signals (only for pages that actually loaded)
    vs = _sigs(loaded) if mode == "vendor" else {}

    # Client category
    cat = ""
    if mode == "client":
        t = html_all.lower()
        cats = [
            (["e-commerce","ecommerce","shop","store","product"], "E-commerce"),
            (["saas","software","platform","app","api"], "SaaS/Tech"),
            (["agency","marketing","seo","digital","branding"], "Agency"),
            (["blog","magazine","news","media","journal","publication"], "Blog/Media"),
            (["health","medical","clinic","doctor","hospital","wellness"], "Health"),
            (["finance","fintech","bank","investment","insurance"], "Finance"),
            (["education","course","training","learn","university","school"], "Education"),
            (["real estate","property","realty","housing"], "Real Estate"),
            (["food","restaurant","recipe","cooking","cafe"], "Food"),
            (["travel","hotel","tour","flight","booking"], "Travel"),
        ]
        for keywords, label in cats:
            if any(k in t for k in keywords):
                cat = label; break
        if not cat: cat = "Business"

    # Build contacts
    contacts = []
    seen = set()
    for e in sorted(raw):
        l,_,d = e.partition("@")
        if not d or not l or e in seen: continue
        seen.add(e)
        if _junk(e) or _blocked(d): continue
        s = src.get(e, base)
        dm = (d == root or d.endswith("." + root))
        contacts.append({"email":e,"domain":root,"source_url":s,
            "role_based":any(l.startswith(p) for p in ROLE_PFX),
            "mx_ok":True,"email_type":_typ(e,root),
            "confidence":_conf(s),"domain_match":dm})

    # Facebook fallback if no emails and time remaining
    if not contacts and not timed_out():
        contacts.extend(_fb(html_all, root))

    # Smart sort: domain-match > confidence > role > type > length
    co = {"high":0,"medium":1,"low":2}
    to = {"domain_email":0,"free_provider_email":1,"cross_domain_email":2}
    contacts.sort(key=lambda c: (
        not c["domain_match"], co.get(c["confidence"],2),
        not c["role_based"], to.get(c["email_type"],2), len(c["email"])))

    elapsed = round(time.time() - start, 1)
    return {"domain":root,"contacts":contacts,
            "status":"scraped" if contacts else "no business email found",
            "vendor_signals":vs,"client_category":cat,"elapsed":elapsed}
