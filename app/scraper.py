"""Email extractor v6 — FINAL: reliable + fast + clean.

Timeout: 8s connect+read (reliable for all countries).
Workers: 20 parallel. No MX during scrape. SSL flexible.
Vendor: blog/write-for-us/advertise clickable links.
Client: category + source page link.
"""
import re, warnings
from urllib.parse import urlparse, urljoin
import requests, urllib3
from bs4 import BeautifulSoup

# Suppress SSL warnings for sites with bad certs
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

TIMEOUT = 8
TIMEOUT_QUICK = 5
MAX_PAGES = 6
UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"

_s = requests.Session()
_s.headers.update({"User-Agent": UA})
_s.verify = False  # handle sites with expired/bad SSL

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

GUESS = ["/contact","/contact-us","/about","/about-us","/blog",
         "/advertise","/write-for-us","/guest-post","/team","/support"]

HI = ["contact","contact-us","get-in-touch","write-for-us","guest-post","advertise"]
MD = ["about","about-us","team","blog","support","help"]


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
    # [at] (at) {at} variations
    t=re.sub(r"\s*[\[\(\{]\s*at\s*[\]\)\}]\s*","@",t,flags=re.I)
    # [dot] (dot) {dot} variations
    t=re.sub(r"\s*[\[\(\{]\s*dot\s*[\]\)\}]\s*",".",t,flags=re.I)
    # "at" as word between spaces: info at domain dot com
    t=re.sub(r"\s+at\s+","@",t,flags=re.I)
    t=re.sub(r"\s+dot\s+",".",t,flags=re.I)
    # HTML entities: &#64; = @ and &#46; = .
    t=t.replace("&#64;","@").replace("&#46;",".").replace("&#x40;","@").replace("&#x2e;",".")
    # (at) without brackets sometimes written as " AT "
    t=re.sub(r"\sAT\s","@",t)
    t=re.sub(r"\sDOT\s",".",t)
    return t

def _get(url, to=None):
    try:
        r=_s.get(url, timeout=to or TIMEOUT, allow_redirects=True)
        if r.status_code>=400: return None
        # Accept any text-like content (html, xhtml, xml, plain text)
        ct=r.headers.get("content-type","").lower()
        if any(k in ct for k in ["text","html","xml","json"]): return r.text
        if not ct: return r.text  # no content-type header = try anyway
        return None
    except: return None

def _find(html):
    # 1) Raw regex on full HTML source
    f=set(EMAIL_RE.findall(html))
    # 2) Deobfuscated text
    deobbed=_deob(html)
    f|=set(EMAIL_RE.findall(deobbed))
    # 3) mailto: links
    for m in re.findall(r'mailto:([^\s"\'<>?&]+)',html,re.I):
        c=m.strip().lower()
        if EMAIL_RE.match(c): f.add(c)
    # 4) Cloudflare protected
    for m in re.findall(r'data-cfemail="([0-9a-fA-F]+)"',html):
        d=_cfe(m)
        if d: f.add(d)
    # 5) href attributes with @
    for m in re.findall(r'href=["\']([^"\']*@[^"\']*)["\']',html):
        c=m.replace("mailto:","").strip().lower()
        if EMAIL_RE.match(c): f.add(c)
    # 6) Parse with BeautifulSoup for visible text (catches rendered obfuscation)
    try:
        soup=BeautifulSoup(html,"html.parser")
        # Get ALL visible text
        text=soup.get_text(" ",strip=True)
        f|=set(EMAIL_RE.findall(text))
        f|=set(EMAIL_RE.findall(_deob(text)))
        # Check title, meta description, alt tags
        for tag in soup.find_all("meta"):
            content=tag.get("content","")
            if content:
                f|=set(EMAIL_RE.findall(content))
                f|=set(EMAIL_RE.findall(_deob(content)))
        for tag in soup.find_all(attrs={"alt":True}):
            f|=set(EMAIL_RE.findall(_deob(tag["alt"])))
    except: pass
    return {e.lower().strip(".") for e in f if not e.lower().endswith((".png",".jpg",".gif",".svg",".css",".js",".ico",".pdf"))}

def _junk(e): return any(p.search(e) for p in JUNK_RE)

def _typ(e,root):
    _,_,d=e.partition("@")
    if d in FREE: return "free_provider_email"
    if d==root or d.endswith("."+root): return "domain_email"
    return "cross_domain_email"

def _conf(src):
    p=urlparse(src).path.lower().rstrip("/")
    s=p.split("/")[-1] if p else ""
    f=p+" "+s
    if any(k in f for k in HI): return "high"
    if any(k in f for k in MD): return "medium"
    if p in ("","/"): return "medium"
    return "low"

def _sigs(pages):
    s={}
    for u in pages:
        p=urlparse(u).path.lower()
        if any(k in p for k in ["write-for-us","guest-post","contribute","submit"]): s["write_for_us_page"]=u
        if any(k in p for k in ["advertise","advertising","sponsor","media-kit"]): s["advertise_page"]=u
        if "/blog" in p or "/articles" in p or "/news" in p: s["blog_page"]=u
        if "contact" in p: s["contact_page"]=u
    return s

def _biz(base, root, html):
    soup=BeautifulSoup(html,"html.parser")
    hints=["contact","about","team","support","blog","write-for-us","guest-post","advertise"]
    pages=[]
    for a in soup.find_all("a",href=True):
        href=a["href"].strip()
        if not href or href.startswith(("#","mailto:","tel:","javascript:")): continue
        full=urljoin(base,href)
        h=urlparse(full).netloc.lower()
        if _blocked(h): continue
        if not _same(root,full): continue
        txt=(href+" "+a.get_text(" ")).lower()
        if any(k in txt for k in hints): pages.append(full.split("#")[0])
    seen=set(); uniq=[]
    for p in pages:
        if p not in seen: seen.add(p); uniq.append(p)
    return uniq[:MAX_PAGES]

def _fb(html, root):
    links=re.findall(r'https?://(?:www\.)?facebook\.com/[a-zA-Z0-9._\-]+',html)
    if not links: return []
    out=[]
    for url in [links[0].rstrip("/")+"/about", links[0]]:
        h=_get(url, TIMEOUT_QUICK)
        if not h: continue
        for e in _find(h):
            if _junk(e) or _blocked(e.split("@")[-1]): continue
            l,_,d=e.partition("@")
            out.append({"email":e,"domain":root,"source_url":url,
                "role_based":any(l.startswith(p) for p in ROLE_PFX),
                "mx_ok":True,"email_type":_typ(e,root),
                "confidence":"medium","domain_match":(d==root)})
        if out: break
    return out


def extract_domain(domain, mode="vendor"):
    root=_root(domain)
    if not root or _blocked(root):
        return {"domain":root,"contacts":[],"status":"skipped","vendor_signals":{},"client_category":""}

    base="https://"+root
    home=_get(base)
    if not home: home=_get("http://"+root)
    if not home: home=_get("https://www."+root)
    if not home:
        return {"domain":root,"contacts":[],"status":"site not reachable","vendor_signals":{},"client_category":""}

    html_all=home; raw=_find(home); src={e:base for e in raw}

    pages=_biz(base,root,home)
    for p in GUESS:
        u=base+p
        if u not in pages: pages.append(u)

    loaded=[base]
    for pg in pages[:MAX_PAGES]:
        h=_get(pg, TIMEOUT_QUICK)
        if h:
            loaded.append(pg); html_all+=" "+h
            for e in _find(h):
                if e not in src: src[e]=pg
            raw|=set(src.keys())

    vs=_sigs(loaded) if mode=="vendor" else {}

    cat=""
    if mode=="client":
        t=html_all.lower()
        if "e-commerce" in t or "ecommerce" in t or "shop" in t or "store" in t: cat="E-commerce"
        elif "saas" in t or "software" in t or "platform" in t: cat="SaaS/Tech"
        elif "agency" in t or "marketing" in t or "seo" in t or "digital" in t: cat="Agency"
        elif "blog" in t or "magazine" in t or "news" in t or "media" in t: cat="Blog/Media"
        elif "health" in t or "medical" in t or "clinic" in t: cat="Health"
        elif "finance" in t or "fintech" in t or "bank" in t: cat="Finance"
        elif "education" in t or "course" in t or "training" in t: cat="Education"
        elif "real estate" in t or "property" in t: cat="Real Estate"
        elif "food" in t or "restaurant" in t: cat="Food"
        elif "travel" in t or "hotel" in t or "tour" in t: cat="Travel"
        else: cat="Business"

    contacts=[]
    seen=set()
    for e in sorted(raw):
        l,_,d=e.partition("@")
        if not d or not l or e in seen: continue
        seen.add(e)
        if _junk(e) or _blocked(d): continue
        s=src.get(e,base)
        dm=(d==root or d.endswith("."+root))
        contacts.append({"email":e,"domain":root,"source_url":s,
            "role_based":any(l.startswith(p) for p in ROLE_PFX),
            "mx_ok":True,"email_type":_typ(e,root),
            "confidence":_conf(s),"domain_match":dm})

    if not contacts:
        contacts.extend(_fb(html_all,root))

    co={"high":0,"medium":1,"low":2}
    to={"domain_email":0,"free_provider_email":1,"cross_domain_email":2}
    contacts.sort(key=lambda c:(not c["domain_match"],co.get(c["confidence"],2),
        not c["role_based"],to.get(c["email_type"],2),len(c["email"])))

    return {"domain":root,"contacts":contacts,
            "status":"scraped" if contacts else "no business email found",
            "vendor_signals":vs,"client_category":cat}
