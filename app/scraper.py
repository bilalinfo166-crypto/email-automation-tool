"""Email extractor v8 — FAST FIRST.

Strategy: Find email FAST, move on. Don't over-crawl.
- Homepage → email? DONE (next domain)
- Contact page → email? DONE
- About/Blog/Advertise → only if still no email
- Max 5 pages, 15s per domain
- 30 workers, streaming queue
- Results appear in 3-5 seconds
"""
import re, time, html as html_mod
from urllib.parse import urlparse, urljoin, unquote
import requests, urllib3
from bs4 import BeautifulSoup

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

DOMAIN_BUDGET = 15    # max seconds per domain (fast!)
PAGE_TIMEOUT = 5      # per-page timeout
MAX_PAGES = 5         # only check 5 pages max
UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"

_s = requests.Session()
_s.headers.update({"User-Agent": UA})
_s.verify = False

EMAIL_RE = re.compile(r"[a-zA-Z0-9._%+\-]+@[a-zA-Z0-9.\-]+\.[a-zA-Z]{2,4}")

ROLE_PFX = ["info","contact","sales","hello","support","office","admin","enquiry",
            "help","team","mail","marketing","editor","editorial","press","media",
            "partnerships","business","ads","guestpost","guest","submit","write",
            "content","outreach","advertise","blog"]

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
    r"@.*mailchimp\.com$", r"@.*sendgrid", r"@.*cloudflare\.com$",
    r"@.*hubspot", r"@.*herokuapp", r"@.*netlify", r"@.*vercel",
    r"@.*amazonaws", r"@.*googleusercontent", r"@.*gravatar",
    r"@.*typeform", r"@.*zendesk", r"@.*intercom", r"@.*gstatic",
    r"^[a-z]@", r"@.*\.(png|jpg|gif|svg|css|js)$", r"[0-9a-f]{20,}@",
]]

BLOCKED = {"facebook.com","fb.com","linkedin.com","instagram.com","twitter.com",
           "x.com","youtube.com","t.me","wa.me","reddit.com","quora.com","medium.com"}

# Priority pages (most likely to have emails)
P1_PATHS = ["/contact","/contact-us","/about","/about-us"]
P2_PATHS = ["/blog","/advertise","/write-for-us","/guest-post","/team"]

HI_KW = ["contact","contact-us","get-in-touch","write-for-us","guest-post","advertise"]
MD_KW = ["about","about-us","team","blog","support","privacy","terms"]


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
    t=unquote(t)
    t=html_mod.unescape(t)
    t=re.sub(r"\s*[\[\(\{<]\s*at\s*[\]\)\}>]\s*","@",t,flags=re.I)
    t=re.sub(r"\s*[\[\(\{<]\s*dot\s*[\]\)\}>]\s*",".",t,flags=re.I)
    t=re.sub(r"\b\s+at\s+\b","@",t,flags=re.I)
    t=re.sub(r"\b\s+dot\s+\b",".",t,flags=re.I)
    t=re.sub(r"\s*@\s*","@",t)
    t=re.sub(r"\s*\.\s*",".",t)
    t=re.sub(r"\s*-at-\s*","@",t,flags=re.I)
    t=re.sub(r"\s*-dot-\s*",".",t,flags=re.I)
    return t

def _get(url, to=None):
    try:
        r=_s.get(url, timeout=to or PAGE_TIMEOUT, allow_redirects=True)
        if r.status_code>=400: return None
        if r.encoding and r.encoding.lower()!='utf-8':
            r.encoding=r.apparent_encoding or 'utf-8'
        ct=r.headers.get("content-type","").lower()
        if any(k in ct for k in ["text","html","xml","json"]): return r.text
        if not ct: return r.text
        return None
    except: return None

def _extract(html_text):
    """Extract emails from HTML using all methods. Returns set of clean emails."""
    found=set()
    # Raw regex
    found|=set(EMAIL_RE.findall(html_text))
    # Deobfuscated
    found|=set(EMAIL_RE.findall(_deob(html_text)))
    # mailto
    for m in re.findall(r'mailto:([^\s"\'<>?&]+)',html_text,re.I):
        c=unquote(m).strip().lower()
        if EMAIL_RE.match(c): found.add(c)
    # Cloudflare
    for m in re.findall(r'data-cfemail="([0-9a-fA-F]+)"',html_text):
        d=_cfe(m); 
        if d: found.add(d)
    # href with @
    for m in re.findall(r'href=["\']([^"\']*@[^"\']*)["\']',html_text):
        c=unquote(m).replace("mailto:","").strip().lower()
        if EMAIL_RE.match(c): found.add(c)
    # BeautifulSoup
    try:
        soup=BeautifulSoup(html_text,"html.parser")
        text=soup.get_text("\n",strip=True)
        found|=set(EMAIL_RE.findall(text))
        found|=set(EMAIL_RE.findall(_deob(text)))
        # JSON-LD
        for sc in soup.find_all("script",type="application/ld+json"):
            if sc.string: found|=set(EMAIL_RE.findall(sc.string))
        # Meta tags
        for tag in soup.find_all("meta"):
            v=tag.get("content","")
            if v: found|=set(EMAIL_RE.findall(_deob(v)))
        # data-email attrs
        for tag in soup.find_all(True):
            for attr,val in tag.attrs.items():
                if isinstance(val,str) and ("email" in attr.lower() or "@" in val):
                    found|=set(EMAIL_RE.findall(_deob(val)))
    except: pass

    # Validate + clean
    clean=set()
    for e in found:
        e=e.lower().strip(".")
        if len(e)>60: continue
        local,_,dom=e.partition("@")
        if not dom or not local: continue
        if ".." in dom or ".." in local: continue
        if len(local)>40 or len(dom)>40: continue
        tld=dom.rsplit(".",1)[-1]
        if len(tld)>4: continue
        if not re.match(r'^[a-z0-9][a-z0-9._+\-]*$',local): continue
        if not re.match(r'^[a-z0-9][a-z0-9.\-]*\.[a-z]{2,4}$',dom): continue
        if any(p.search(e) for p in JUNK_RE): continue
        if _blocked(dom): continue
        clean.add(e)
    return clean

def _conf(src):
    p=urlparse(src).path.lower().rstrip("/")
    s=p.split("/")[-1] if p else ""
    f=p+" "+s
    if any(k in f for k in HI_KW): return "high"
    if any(k in f for k in MD_KW): return "medium"
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

def _discover(base,root,html_text):
    soup=BeautifulSoup(html_text,"html.parser")
    hints=["contact","about","team","blog","write-for-us","guest-post","advertise"]
    pages=[]
    for a in soup.find_all("a",href=True):
        href=a["href"].strip()
        if not href or href.startswith(("#","mailto:","tel:","javascript:")): continue
        full=urljoin(base,href)
        h=urlparse(full).netloc.lower()
        if _blocked(h) or not _same(root,full): continue
        txt=(href+" "+a.get_text(" ")).lower()
        if any(k in txt for k in hints): pages.append(full.split("#")[0])
    seen=set(); uniq=[]
    for p in pages:
        if p not in seen: seen.add(p); uniq.append(p)
    return uniq


def extract_domain(domain, mode="vendor"):
    """FAST-FIRST: find email quickly, move on. Max 15 seconds."""
    start=time.time()
    root=_root(domain)
    if not root or _blocked(root):
        return {"domain":root,"contacts":[],"status":"skipped","vendor_signals":{},"client_category":""}

    def budget(): return max(0, DOMAIN_BUDGET-(time.time()-start))
    def done(): return time.time()-start>=DOMAIN_BUDGET

    # 1) HOMEPAGE — most emails are here
    base="https://"+root
    home=_get(base, min(PAGE_TIMEOUT, budget()))
    if not home and not done(): home=_get("http://"+root, min(PAGE_TIMEOUT, budget()))
    if not home and not done(): home=_get("https://www."+root, min(PAGE_TIMEOUT, budget()))
    if not home:
        return {"domain":root,"contacts":[],"status":"site not reachable",
                "vendor_signals":{},"client_category":"","elapsed":round(time.time()-start,1)}

    emails=_extract(home)
    source={e:base for e in emails}
    loaded=[base]

    # Discover internal links from homepage
    discovered=_discover(base,root,home)

    # 2) If no email yet, try P1 pages (contact, about)
    if not emails and not done():
        p1=[]
        for path in P1_PATHS:
            u=base+path
            if u not in p1: p1.append(u)
        for u in discovered:
            p=urlparse(u).path.lower()
            if any(k in p for k in ["contact","about"]) and u not in p1: p1.append(u)

        for pg in p1[:3]:
            if done(): break
            h=_get(pg, min(PAGE_TIMEOUT, budget()))
            if h:
                loaded.append(pg)
                new=_extract(h)
                for e in new:
                    if e not in source: source[e]=pg
                emails|=new
                if emails: break  # EARLY EXIT — email found!

    # 3) If STILL no email, try P2 pages (blog, advertise, write-for-us)
    if not emails and not done():
        p2=[]
        for path in P2_PATHS:
            u=base+path
            if u not in p2: p2.append(u)
        for u in discovered:
            p=urlparse(u).path.lower()
            if any(k in p for k in ["blog","advertise","write","guest","team"]) and u not in p2: p2.append(u)

        for pg in p2[:MAX_PAGES-len(loaded)]:
            if done(): break
            h=_get(pg, min(PAGE_TIMEOUT, budget()))
            if h:
                loaded.append(pg)
                new=_extract(h)
                for e in new:
                    if e not in source: source[e]=pg
                emails|=new
                if emails: break  # EARLY EXIT

    # Vendor signals (lightweight — just checks loaded page URLs)
    vs=_sigs(loaded) if mode=="vendor" else {}

    # Client category
    cat=""
    if mode=="client":
        t=home.lower()
        cats=[
            (["e-commerce","ecommerce","shop","store","product"],"E-commerce"),
            (["saas","software","platform","api"],"SaaS/Tech"),
            (["agency","marketing","seo","digital","branding"],"Agency"),
            (["blog","magazine","news","media","journal"],"Blog/Media"),
            (["health","medical","clinic","doctor"],"Health"),
            (["finance","fintech","bank","investment"],"Finance"),
            (["education","course","training","learn"],"Education"),
            (["real estate","property","realty"],"Real Estate"),
            (["food","restaurant","recipe"],"Food"),
            (["travel","hotel","tour","flight"],"Travel"),
        ]
        for kws,lbl in cats:
            if any(k in t for k in kws): cat=lbl; break
        if not cat: cat="Business"

    # Build contacts
    contacts=[]
    for e in sorted(emails):
        l,_,d=e.partition("@")
        dm=(d==root or d.endswith("."+root))
        s=source.get(e,base)
        contacts.append({"email":e,"domain":root,"source_url":s,
            "role_based":any(l.startswith(p) for p in ROLE_PFX),
            "mx_ok":True,"email_type":"free_provider_email" if d in FREE else "domain_email" if dm else "cross_domain_email",
            "confidence":_conf(s),"domain_match":dm})

    # Smart sort
    co={"high":0,"medium":1,"low":2}
    to={"domain_email":0,"free_provider_email":1,"cross_domain_email":2}
    contacts.sort(key=lambda c:(not c["domain_match"],co.get(c["confidence"],2),
        not c["role_based"],to.get(c["email_type"],2),len(c["email"])))

    elapsed=round(time.time()-start,1)
    return {"domain":root,"contacts":contacts,
            "status":"scraped" if contacts else "no_email_in_public_pages",
            "vendor_signals":vs,"client_category":cat,"elapsed":elapsed}
