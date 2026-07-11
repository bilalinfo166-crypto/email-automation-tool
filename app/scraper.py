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

DOMAIN_BUDGET = 20    # max seconds per domain — enough for slow sites
PAGE_TIMEOUT = 10     # homepage timeout (slow sites need this)
PAGE_TIMEOUT_QUICK = 5  # subsequent pages
MAX_PAGES = 8         # check more pages when email not found
UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"

_s = requests.Session()
_s.headers.update({"User-Agent": UA})
_s.verify = False

EMAIL_RE = re.compile(r"[a-zA-Z0-9._%+\-]+@[a-zA-Z0-9.\-]+\.[a-zA-Z]{2,10}")

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
P1_PATHS = ["/contact","/contact-us","/about","/about-us","/privacy","/privacy-policy"]
P2_PATHS = ["/blog","/advertise","/write-for-us","/guest-post","/team","/support","/terms","/legal","/imprint"]

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

    # Validate + clean — fast, accurate filtering
    PLACEHOLDER_LOCALS = {"exemple","example","test","demo","sample","placeholder","yourname",
                          "youremail","email","name","user","admin","your","you","me","my",
                          "someone","anybody","person","company","domain","website","site"}
    clean=set()
    for e in found:
        e=e.lower().strip(".")
        if len(e)>60 or len(e)<5: continue
        local,_,dom=e.partition("@")
        if not dom or not local: continue
        if ".." in dom or ".." in local: continue
        if len(local)>40 or len(dom)>40: continue
        tld=dom.rsplit(".",1)[-1]
        if len(tld)>10 or len(tld)<2: continue  # generous TLD length
        if not re.match(r'^[a-z0-9][a-z0-9.\-]*\.[a-z]{2,10}$',dom): continue
        # Reject all-numeric domain part (337-216-4423.inte)
        parts=dom.rsplit(".",1)
        if re.match(r'^[\d.\-]+$',parts[0]): continue
        if not re.match(r'^[a-z0-9][a-z0-9._+\-]*$',local): continue
        if re.match(r'^\d+$',local): continue  # numeric-only local
        if local in PLACEHOLDER_LOCALS: continue
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

def _sigs(pages, homepage_html=None, base=""):
    """Detect signals from loaded pages + homepage links (so completed sites also show signals)."""
    s={}
    for u in pages:
        p=urlparse(u).path.lower()
        if any(k in p for k in ["write-for-us","guest-post","contribute","submit"]): s["write_for_us_page"]=u
        if any(k in p for k in ["advertise","advertising","sponsor","media-kit"]): s["advertise_page"]=u
        if "/blog" in p or "/articles" in p or "/news" in p: s["blog_page"]=u
        if "contact" in p: s["contact_page"]=u
    # Also scan homepage links (header/footer/nav) for signals even if we didn't load those pages
    if homepage_html and base:
        try:
            soup=BeautifulSoup(homepage_html,"html.parser")
            for a in soup.find_all("a",href=True):
                href=a["href"].strip()
                full=urljoin(base,href)
                txt=(href+" "+a.get_text(" ")).lower()
                if any(k in txt for k in ["write-for-us","guest-post","contribute","submit a post"]):
                    if "write_for_us_page" not in s: s["write_for_us_page"]=full
                if any(k in txt for k in ["advertise","advertising","sponsor","media kit"]):
                    if "advertise_page" not in s: s["advertise_page"]=full
                if "blog" in txt or "/blog" in href.lower():
                    if "blog_page" not in s: s["blog_page"]=full
                if "contact" in txt or "/contact" in href.lower():
                    if "contact_page" not in s: s["contact_page"]=full
        except: pass
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


def _classify_site(html_text, base_url):
    """Weighted multi-signal website classifier.
    Analyzes: title, meta description, H1, JSON-LD, nav links, footer, body text.
    Returns (category, confidence_pct). 'Unknown' if confidence < 70%."""

    CATEGORIES = {
        "SaaS": {"strong":["saas","software as a service","cloud platform","subscription software","cloud-based"],
                 "medium":["platform","dashboard","analytics tool","automation tool","crm","erp"],
                 "weak":["software","app","solution","monthly plan"]},
        "AI": {"strong":["artificial intelligence","machine learning","ai platform","deep learning","nlp","computer vision","generative ai","llm","large language model"],
               "medium":["ai-powered","ai tool","neural network","chatbot","ai assistant"],
               "weak":["ai","intelligent","smart"]},
        "SEO": {"strong":["seo agency","search engine optimization","seo services","seo tool","link building","keyword research"],
                "medium":["seo","backlink","serp","organic traffic","rank tracking"],
                "weak":["ranking","search","optimization"]},
        "Marketing Agency": {"strong":["marketing agency","digital marketing agency","performance marketing","growth agency","advertising agency"],
                            "medium":["digital marketing","content marketing","social media marketing","ppc management","media buying"],
                            "weak":["marketing","campaign","lead generation"]},
        "Web Design": {"strong":["web design agency","website design","ui/ux design","web development agency","design studio"],
                       "medium":["web design","ux design","ui design","responsive design","website builder"],
                       "weak":["design","creative","layout"]},
        "Software Development": {"strong":["software development company","custom software","app development","mobile development","web development company"],
                                 "medium":["development","engineering","full-stack","backend","frontend","devops"],
                                 "weak":["developer","code","programming"]},
        "Developer Tools": {"strong":["developer tools","dev tools","sdk","api platform","code editor","ide"],
                           "medium":["api","cli","framework","library","open source","documentation","github"],
                           "weak":["developer","build","deploy"]},
        "API": {"strong":["api platform","api gateway","api management","rest api","graphql"],
                "medium":["api","endpoint","webhook","integration","microservice"],
                "weak":["connect","integrate"]},
        "Cybersecurity": {"strong":["cybersecurity","information security","penetration testing","threat detection","soc","siem"],
                         "medium":["security","firewall","encryption","vulnerability","malware","zero trust"],
                         "weak":["protection","secure","safety"]},
        "FinTech": {"strong":["fintech","financial technology","payment platform","digital banking","neobank"],
                    "medium":["payment","transaction","lending","cryptocurrency exchange","trading platform"],
                    "weak":["finance","money","banking"]},
        "Healthcare": {"strong":["healthcare","health tech","telemedicine","electronic health record","patient portal","clinical"],
                       "medium":["health","medical","hospital","clinic","patient","diagnosis","therapy"],
                       "weak":["care","wellness","treatment"]},
        "Dental": {"strong":["dental clinic","dentist","dental practice","orthodontics","dental care"],
                   "medium":["dental","teeth","oral health","dentistry"],
                   "weak":["smile","tooth"]},
        "Legal": {"strong":["law firm","attorney","legal services","lawyer","legal practice","litigation"],
                  "medium":["legal","counsel","paralegal","court","lawsuit","compliance"],
                  "weak":["law","justice"]},
        "Education": {"strong":["online education","e-learning","edtech","learning platform","online course","lms"],
                      "medium":["education","training","tutorial","course","certification","academy","school"],
                      "weak":["learn","teach","study"]},
        "University": {"strong":["university","college","campus","faculty","admissions","undergraduate","postgraduate"],
                       "medium":["academic","research","professor","department","scholarship"],
                       "weak":["degree","semester"]},
        "Non-profit": {"strong":["non-profit","nonprofit","charity","foundation","ngo","donate"],
                       "medium":["mission","volunteer","cause","community impact","social good"],
                       "weak":["help","support","give"]},
        "Government": {"strong":["government","gov","public sector","municipality","federal","state department"],
                       "medium":["public service","civic","regulation","policy","citizen"],
                       "weak":["official","department"]},
        "News": {"strong":["news","newspaper","breaking news","journalism","newsroom"],
                 "medium":["reporter","headline","press","editorial","correspondent"],
                 "weak":["latest","today","update"]},
        "Blog": {"strong":["blog","personal blog","blogging","blogger","wordpress blog"],
                 "medium":["article","post","author","opinion","write","contributor"],
                 "weak":["read","story"]},
        "Media": {"strong":["media company","publishing","media house","broadcast","podcast network"],
                  "medium":["media","magazine","publication","journal","podcast","video"],
                  "weak":["content","channel"]},
        "Food": {"strong":["restaurant","food delivery","catering","recipe","cookbook","food blog"],
                 "medium":["food","meal","cuisine","chef","menu","dining","bakery","cafe"],
                 "weak":["eat","taste","delicious"]},
        "Travel": {"strong":["travel agency","tour operator","hotel booking","flight booking","travel blog"],
                   "medium":["travel","hotel","resort","tourism","destination","vacation","booking"],
                   "weak":["trip","explore","adventure"]},
        "Fashion": {"strong":["fashion brand","clothing line","fashion blog","apparel","fashion design"],
                    "medium":["fashion","clothing","outfit","style","wear","collection","designer"],
                    "weak":["trend","look"]},
        "Beauty": {"strong":["beauty brand","cosmetics","skincare","beauty salon","makeup"],
                   "medium":["beauty","skin","hair","nail","spa","cosmetic"],
                   "weak":["glow","natural"]},
        "Photography": {"strong":["photography studio","photographer","photo gallery","wedding photography"],
                        "medium":["photography","photo","portrait","shoot","camera","lens"],
                        "weak":["picture","image"]},
        "Real Estate": {"strong":["real estate","property listing","realty","real estate agent","property management"],
                        "medium":["property","apartment","house","rent","mortgage","listing","broker"],
                        "weak":["home","land","building"]},
        "Automotive": {"strong":["automotive","car dealer","auto repair","vehicle","car dealership"],
                       "medium":["car","auto","motor","vehicle","driving","garage"],
                       "weak":["drive","road"]},
        "Manufacturing": {"strong":["manufacturing","factory","industrial","production line","fabrication"],
                          "medium":["manufacture","industrial","supply chain","warehouse","assembly"],
                          "weak":["produce","material"]},
        "E-commerce": {"strong":["e-commerce platform","online store","shopify store","add to cart","buy now","checkout"],
                       "medium":["shop","store","buy","price","cart","order","shipping","product catalog"],
                       "weak":["product","sale"]},
        "Marketplace": {"strong":["marketplace","buy and sell","peer to peer","classified","auction"],
                        "medium":["marketplace","listing","seller","buyer","vendor","bid"],
                        "weak":["sell","list"]},
        "Finance": {"strong":["financial services","investment firm","wealth management","accounting firm","bookkeeping"],
                    "medium":["finance","investment","accounting","tax","audit","portfolio"],
                    "weak":["money","fund"]},
        "HR": {"strong":["hr software","human resources","hris","people management","employee engagement"],
               "medium":["hr","payroll","recruitment","talent","workforce","onboarding"],
               "weak":["employee","team","hire"]},
        "Recruitment": {"strong":["recruitment agency","staffing","job board","career portal","headhunting"],
                        "medium":["recruitment","job","career","hiring","talent acquisition","resume"],
                        "weak":["position","vacancy"]},
        "Insurance": {"strong":["insurance company","insurance broker","insurtech","policy","premium","coverage"],
                      "medium":["insurance","insure","claim","underwriting","risk"],
                      "weak":["protect","cover"]},
        "Sports": {"strong":["sports","athletic","fitness center","gym","sports team","stadium"],
                   "medium":["sport","fitness","workout","training","athlete","coach"],
                   "weak":["play","game","match"]},
        "Gaming": {"strong":["gaming","video game","game studio","esports","game development"],
                   "medium":["game","gamer","play","console","steam","multiplayer"],
                   "weak":["level","score"]},
        "Crypto": {"strong":["cryptocurrency","blockchain","bitcoin","ethereum","defi","web3","nft"],
                   "medium":["crypto","token","wallet","mining","decentralized","smart contract"],
                   "weak":["coin","chain"]},
        "Hosting": {"strong":["web hosting","cloud hosting","vps","dedicated server","hosting provider"],
                    "medium":["hosting","server","domain","ssl","cpanel","uptime"],
                    "weak":["host","bandwidth"]},
        "WordPress": {"strong":["wordpress theme","wordpress plugin","wordpress developer","wordpress agency"],
                      "medium":["wordpress","wp","theme","plugin","elementor","woocommerce"],
                      "weak":["cms","template"]},
        "Business Services": {"strong":["business consulting","management consulting","advisory","b2b services"],
                              "medium":["consulting","business","enterprise","corporate","strategy","outsourcing"],
                              "weak":["service","professional","client"]},
    }

    try:
        soup = BeautifulSoup(html_text, "html.parser")
    except:
        return ("Unknown", 0)

    # Extract signals with different weights
    title = (soup.title.string or "").lower() if soup.title else ""
    meta_desc = ""
    for tag in soup.find_all("meta", attrs={"name": re.compile(r"description", re.I)}):
        meta_desc = (tag.get("content", "") or "").lower()
    h1 = " ".join(h.get_text(" ", strip=True).lower() for h in soup.find_all("h1")[:3])

    # JSON-LD type
    jsonld_type = ""
    for sc in soup.find_all("script", type="application/ld+json"):
        if sc.string:
            for t in re.findall(r'"@type"\s*:\s*"([^"]+)"', sc.string):
                jsonld_type += " " + t.lower()

    # Nav links text
    nav_text = ""
    for nav in soup.find_all(["nav", "header", "footer"]):
        nav_text += " " + nav.get_text(" ", strip=True).lower()

    # Body text (first 3000 chars for speed)
    body = soup.get_text(" ", strip=True).lower()[:3000]

    # URL keywords
    url_text = base_url.lower()

    # Score each category
    scores = {}
    for cat_name, kw_groups in CATEGORIES.items():
        score = 0
        # Strong keywords in title/H1/meta = very high signal
        for kw in kw_groups.get("strong", []):
            if kw in title: score += 30
            if kw in h1: score += 25
            if kw in meta_desc: score += 20
            if kw in jsonld_type: score += 25
            if kw in url_text: score += 15
            if kw in nav_text: score += 10
            if kw in body: score += 5
        # Medium keywords
        for kw in kw_groups.get("medium", []):
            if kw in title: score += 15
            if kw in h1: score += 12
            if kw in meta_desc: score += 10
            if kw in jsonld_type: score += 12
            if kw in nav_text: score += 5
            if kw in body: score += 3
        # Weak keywords (low weight — avoid false positives)
        for kw in kw_groups.get("weak", []):
            if kw in title: score += 5
            if kw in h1: score += 4
            if kw in meta_desc: score += 3
            if kw in body: score += 1
        if score > 0:
            scores[cat_name] = score

    if not scores:
        return ("Unknown", 0)

    # Pick top category
    top = max(scores, key=scores.get)
    top_score = scores[top]

    # Normalize confidence (0-100%)
    # A strong match typically scores 50-150+, weak <30
    confidence = min(100, int(top_score * 1.5))

    if confidence < 70:
        return ("Unknown", confidence)

    return (top, confidence)


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

    # 2) Try P1 pages (contact, about, privacy)
    #    If email found → STOP immediately. If not → keep going.
    if not done():
        p1=[]
        for path in P1_PATHS:
            u=base+path
            if u not in p1: p1.append(u)
        for u in discovered:
            p=urlparse(u).path.lower()
            if any(k in p for k in ["contact","about","privacy"]) and u not in p1: p1.append(u)

        for pg in p1[:4]:
            if done(): break
            h=_get(pg, min(PAGE_TIMEOUT_QUICK, budget()))
            if h:
                loaded.append(pg)
                new=_extract(h)
                for e in new:
                    if e not in source: source[e]=pg
                emails|=new
                if emails: break  # EMAIL FOUND → STOP, move to next domain

    # 3) If STILL no email, try P2 pages — DON'T give up, use remaining budget
    if not emails and not done():
        p2=[]
        for path in P2_PATHS:
            u=base+path
            if u not in p2: p2.append(u)
        for u in discovered:
            p=urlparse(u).path.lower()
            if any(k in p for k in ["blog","advertise","write","guest","team","support","terms","legal"]) and u not in p2: p2.append(u)

        for pg in p2[:MAX_PAGES-len(loaded)]:
            if done(): break
            h=_get(pg, min(PAGE_TIMEOUT_QUICK, budget()))
            if h:
                loaded.append(pg)
                new=_extract(h)
                for e in new:
                    if e not in source: source[e]=pg
                emails|=new
                if emails: break  # EMAIL FOUND → STOP

    # Vendor signals (lightweight — just checks loaded page URLs)
    vs=_sigs(loaded, home, base) if mode=="vendor" else {}

    # Client category — WEIGHTED MULTI-SIGNAL CLASSIFIER
    cat=""; cat_confidence=0
    if mode=="client":
        cat, cat_confidence = _classify_site(home, base)

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
            "vendor_signals":vs,"client_category":cat,"client_confidence":cat_confidence,"elapsed":elapsed}
