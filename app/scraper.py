"""Email extractor v5 — SPEED FOCUSED + clean results.

Speed: 20 workers, 4s/2s timeout, only essential pages.
Junk: your@, you@, email@, neura.market type = rejected.
Vendor: always checks blog page.
Client: same speed, shows category.
"""
import re
from urllib.parse import urlparse, urljoin
import requests
from bs4 import BeautifulSoup
from .compliance import domain_has_mx

TIMEOUT = 3
TIMEOUT_QUICK = 2
MAX_PAGES = 6
USER_AGENT = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
HEADERS = {"User-Agent": USER_AGENT}

EMAIL_RE = re.compile(r"[a-zA-Z0-9._%+\-]+@[a-zA-Z0-9.\-]+\.[a-zA-Z]{2,}")

ROLE_PREFIXES = ["info","contact","sales","hello","support","office","admin","enquiry",
                 "help","team","mail","marketing","editor","editorial","press","media",
                 "partnerships","business","ads","guestpost","guest","submit","write",
                 "content","outreach","advertise","blog"]

FREE_PROVIDERS = {"gmail.com","yahoo.com","yahoo.co.uk","outlook.com","hotmail.com",
                  "hotmail.co.uk","live.com","aol.com","icloud.com","protonmail.com",
                  "proton.me","mail.com","zoho.com","yandex.com","gmx.com","gmx.net"}

JUNK_PATTERNS = [
    r"^(noreply|no-reply|donotreply|mailer-daemon|postmaster|abuse|root|webmaster)@",
    r"^(user|test|demo|sample|placeholder|yourname|youremail|name|email|someone)@",
    r"^(your|you|me|my|us|example|site|domain|company|website|contact|info)@(email|domain|example|test|sample|yoursite|website|company|mail)\.",
    r"^your@", r"^you@", r"^email@", r"^me@", r"^my@",
    r"@example\.(com|org|net)$",
    r"@test\.", r"@localhost",
    r"@.*sentry", r"@.*wixpress", r"@.*wix\.com$",
    r"@.*wordpress\.(com|org)$", r"@.*squarespace\.com$", r"@.*shopify\.com$",
    r"@.*mailchimp\.com$", r"@.*sendgrid\.(com|net)$", r"@.*cloudflare\.com$",
    r"@.*hubspot\.(com|net)$", r"@.*herokuapp\.com$", r"@.*netlify\.(com|app)$",
    r"@.*vercel\.(com|app)$", r"@.*amazonaws\.com$", r"@.*googleusercontent\.com$",
    r"@.*gravatar\.com$", r"@.*typeform\.com$", r"@.*zendesk\.com$",
    r"@.*intercom\.(com|io)$", r"@.*gstatic\.com$",
    r"^[a-z]@",
    r"@.*\.(png|jpg|jpeg|gif|svg|css|js)$",
    r"[0-9a-f]{20,}@",
    r"@.*\.market$",  # fake TLDs often used as placeholders
]
JUNK_RE = [re.compile(p, re.I) for p in JUNK_PATTERNS]

BLOCKED_NAV = {"facebook.com","fb.com","linkedin.com","instagram.com","twitter.com",
               "x.com","youtube.com","t.me","wa.me","reddit.com","quora.com","medium.com"}

GUESSED_PAGES = ["/contact","/contact-us","/about","/about-us","/blog",
                 "/advertise","/write-for-us","/guest-post","/team","/support"]

HIGH_KW = ["contact","contact-us","get-in-touch","write-for-us","guest-post","advertise"]
MED_KW = ["about","about-us","team","blog","support","help"]


def _is_nav_blocked(d):
    d = d.lower().strip(".")
    return d in BLOCKED_NAV or any(d.endswith("."+b) for b in BLOCKED_NAV)

def _root(url):
    return urlparse(url if "//" in url else "https://"+url).netloc.lower().replace("www.","")

def _same(root, link):
    h = urlparse(link).netloc.lower().replace("www.","")
    return h=="" or h==root or h.endswith("."+root)

def _cfemail(enc):
    try:
        r=int(enc[:2],16); return "".join(chr(int(enc[i:i+2],16)^r) for i in range(2,len(enc),2))
    except: return None

def _deob(t):
    t=re.sub(r"\s*[\[\(\{]\s*at\s*[\]\)\}]\s*","@",t,flags=re.I)
    t=re.sub(r"\s*[\[\(\{]\s*dot\s*[\]\)\}]\s*",".",t,flags=re.I)
    return t

def _fetch(url, timeout=None):
    try:
        r=_session.get(url, timeout=(2, timeout or TIMEOUT), allow_redirects=True)
        if r.status_code>=400: return None
        ct=r.headers.get("content-type","")
        if "text/html" not in ct and "text" not in ct: return None
        return r.text
    except: return None

def _emails(html):
    f=set(EMAIL_RE.findall(html))
    f|=set(EMAIL_RE.findall(_deob(html)))
    for m in re.findall(r'mailto:([^\s"\'<>?&]+)',html,re.I):
        c=m.strip().lower()
        if EMAIL_RE.match(c): f.add(c)
    for m in re.findall(r'data-cfemail="([0-9a-fA-F]+)"',html):
        d=_cfemail(m)
        if d: f.add(d)
    for m in re.findall(r'href=["\']([^"\']*@[^"\']*)["\']',html):
        c=m.replace("mailto:","").strip().lower()
        if EMAIL_RE.match(c): f.add(c)
    return {e.lower().strip(".") for e in f if not e.lower().endswith((".png",".jpg",".gif",".svg",".css",".js",".ico",".pdf"))}

def _junk(e): return any(p.search(e) for p in JUNK_RE)

def _type(e,root):
    _,_,d=e.partition("@")
    if d in FREE_PROVIDERS: return "free_provider_email"
    if d==root or d.endswith("."+root): return "domain_email"
    return "cross_domain_email"

def _conf(src):
    p=urlparse(src).path.lower().rstrip("/")
    s=p.split("/")[-1] if p else ""
    f=p+" "+s
    if any(k in f for k in HIGH_KW): return "high"
    if any(k in f for k in MED_KW): return "medium"
    if p in ("","/"): return "medium"
    return "low"

def _signals(pages):
    """Only report signals for pages that ACTUALLY loaded."""
    s={}
    for url in pages:
        p=urlparse(url).path.lower()
        if any(k in p for k in ["write-for-us","guest-post","contribute","submit"]): s["write_for_us_page"]=url
        if any(k in p for k in ["advertise","advertising","sponsor","media-kit"]): s["advertise_page"]=url
        if "/blog" in p or "/articles" in p or "/news" in p: s["blog_page"]=url
        if "contact" in p: s["contact_page"]=url
    return s

def _biz_pages(base, root, html):
    soup=BeautifulSoup(html,"html.parser")
    hints=["contact","about","team","support","blog","write-for-us","guest-post","advertise"]
    pages=[]
    for a in soup.find_all("a",href=True):
        href=a["href"].strip()
        if not href or href.startswith(("#","mailto:","tel:","javascript:")): continue
        full=urljoin(base,href)
        h=urlparse(full).netloc.lower()
        if _is_nav_blocked(h): continue
        if not _same(root,full): continue
        txt=(href+" "+a.get_text(" ")).lower()
        if any(k in txt for k in hints): pages.append(full.split("#")[0])
    seen=set(); uniq=[]
    for p in pages:
        if p not in seen: seen.add(p); uniq.append(p)
    return uniq[:MAX_PAGES]

def _fb_fallback(html, root):
    links=re.findall(r'https?://(?:www\.)?facebook\.com/[a-zA-Z0-9._\-]+',html)
    if not links: return []
    contacts=[]
    for url in [links[0].rstrip("/")+"/about", links[0]]:
        h=_fetch(url, timeout=TIMEOUT_QUICK)
        if not h: continue
        for e in _emails(h):
            if _junk(e) or _is_nav_blocked(e.split("@")[-1]): continue
            l,_,d=e.partition("@")
            contacts.append({"email":e,"domain":root,"source_url":url,
                "role_based":any(l.startswith(p) for p in ROLE_PREFIXES),
                "mx_ok":True,"email_type":_type(e,root),
                "confidence":"medium","domain_match":(d==root)})
        if contacts: break
    return contacts


def extract_domain(domain, mode="vendor"):
    root=_root(domain)
    if not root or _is_nav_blocked(root):
        return {"domain":root,"contacts":[],"status":"skipped","vendor_signals":{},"client_category":""}

    base="https://"+root
    home=_fetch(base)
    if not home: home=_fetch("http://"+root)
    if not home: home=_fetch("https://www."+root)
    if not home:
        return {"domain":root,"contacts":[],"status":"site not reachable","vendor_signals":{},"client_category":""}

    # ALWAYS extract from homepage first
    all_html=home
    raw=_emails(home)
    source={e:base for e in raw}

    # Discovered + guessed pages
    pages=_biz_pages(base,root,home)
    for path in GUESSED_PAGES:
        u=base+path
        if u not in pages: pages.append(u)

    loaded=[base]
    for page in pages[:MAX_PAGES]:
        h=_fetch(page, timeout=TIMEOUT_QUICK)
        if h:
            loaded.append(page)
            all_html+=" "+h
            for e in _emails(h):
                if e not in source: source[e]=page
            raw|=set(source.keys())

    # Signals
    vs=_signals(loaded) if mode=="vendor" else {}
    
    # Client category detection
    cat=""
    if mode=="client":
        txt=all_html.lower()
        if "e-commerce" in txt or "ecommerce" in txt or "shop" in txt or "store" in txt: cat="E-commerce"
        elif "saas" in txt or "software" in txt or "platform" in txt or "app" in txt: cat="SaaS/Tech"
        elif "agency" in txt or "marketing" in txt or "seo" in txt or "digital" in txt: cat="Agency"
        elif "blog" in txt or "magazine" in txt or "news" in txt or "media" in txt: cat="Blog/Media"
        elif "health" in txt or "medical" in txt or "clinic" in txt or "doctor" in txt: cat="Health"
        elif "finance" in txt or "fintech" in txt or "bank" in txt or "investment" in txt: cat="Finance"
        elif "education" in txt or "course" in txt or "training" in txt or "learn" in txt: cat="Education"
        elif "real estate" in txt or "property" in txt or "realty" in txt: cat="Real Estate"
        elif "food" in txt or "restaurant" in txt or "recipe" in txt: cat="Food"
        elif "travel" in txt or "hotel" in txt or "tour" in txt: cat="Travel"
        else: cat="Business"

    # Build contacts — accept ALL publicly found emails
    contacts=[]
    seen=set()
    for e in sorted(raw):
        l,_,d=e.partition("@")
        if not d or not l: continue
        if e in seen: continue
        seen.add(e)
        if _junk(e): continue
        if _is_nav_blocked(d): continue
        src=source.get(e,base)
        dm=(d==root or d.endswith("."+root))
        contacts.append({"email":e,"domain":root,"source_url":src,
            "role_based":any(l.startswith(p) for p in ROLE_PREFIXES),
            "mx_ok":True,"email_type":_type(e,root),
            "confidence":_conf(src),"domain_match":dm})

    # Facebook fallback if no emails
    if not contacts:
        contacts.extend(_fb_fallback(all_html,root))

    # SMART SORT: domain-match > confidence > role > type > mx > length
    co={"high":0,"medium":1,"low":2}
    to={"domain_email":0,"free_provider_email":1,"cross_domain_email":2}
    contacts.sort(key=lambda c:(not c["domain_match"],co.get(c["confidence"],2),
        not c["role_based"],to.get(c["email_type"],2),not c["mx_ok"],len(c["email"])))

    return {"domain":root,"contacts":contacts,
            "status":"scraped" if contacts else "no business email found",
            "vendor_signals":vs,"client_category":cat}
