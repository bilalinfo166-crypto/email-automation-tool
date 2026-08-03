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

DOMAIN_BUDGET = 11    # max seconds per domain. Most sites that have a public
                      # email give it up on the homepage or /contact within a
                      # few seconds; sites that burn the full budget almost
                      # never have one. Lowering 18->11 roughly doubles
                      # throughput on big lists at a tiny cost in coverage.
PAGE_TIMEOUT = 5      # homepage timeout
PAGE_TIMEOUT_QUICK = 3  # subsequent pages
MAX_PAGES = 6         # check pages when email not found (was 9 — the last few
                      # rarely add an email but cost real time per domain)
UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"

# requests' connect timeout does NOT cover DNS resolution on most systems: a
# domain whose nameserver never answers can block a worker for 20-30s (the OS
# resolver default) even though we asked for a 3s connect. That's how 49 workers
# ended up wedged at once on a list full of dead domains. A global default
# socket timeout bounds the DNS/socket layer itself, so no single lookup can
# hold a worker past a few seconds.
import socket as _socket
_socket.setdefaulttimeout(6)

_s = requests.Session()
_s.headers.update({"User-Agent": UA})
_s.verify = False
# Connection pool for 50+ workers
adapter = requests.adapters.HTTPAdapter(pool_connections=120, pool_maxsize=120, max_retries=1)
_s.mount("https://", adapter)
_s.mount("http://", adapter)

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
    r"^(yourname|youremail)@",
    r"@example\.(com|org|net)$", r"@test\.", r"@localhost",
    r"@.*sentry", r"@.*wixpress", r"@.*wix\.com$",
    r"@.*wordpress\.(com|org)$", r"@.*squarespace\.com$", r"@.*shopify\.com$",
    r"@.*mailchimp\.com$", r"@.*sendgrid", r"@.*cloudflare\.com$",
    r"@.*hubspot", r"@.*herokuapp", r"@.*netlify", r"@.*vercel",
    r"@.*amazonaws", r"@.*googleusercontent", r"@.*gravatar",
    r"@.*typeform", r"@.*zendesk", r"@.*intercom", r"@.*gstatic",
    r"@.*\.(png|jpg|gif|svg|css|js)$", r"[0-9a-f]{20,}@",
]]

BLOCKED = {"facebook.com","fb.com","linkedin.com","instagram.com","twitter.com",
           "x.com","youtube.com","t.me","wa.me","reddit.com","quora.com","medium.com"}

# Real, valid TLDs — anything ending in something NOT here is junk (you@ease.davis,
# x@y.can, foo@bar.inte etc. all get rejected). Covers common gTLDs + all ccTLDs.
VALID_TLDS = {
    # Common generic
    "com","org","net","edu","gov","mil","int","info","biz","name","pro","mobi",
    "co","io","ai","app","dev","tech","online","site","website","store","shop",
    "blog","news","media","agency","digital","design","studio","group","world",
    "life","live","today","email","cloud","host","space","xyz","club","fun","vip",
    "top","icu","cyou","link","click","page","wiki","tv","fm","cc","me","us","uk",
    "ca","au","de","fr","es","it","nl","se","no","fi","dk","pl","ru","in","pk",
    "cn","jp","kr","br","mx","ar","za","ng","ke","eg","ae","sa","tr","id","my",
    "sg","ph","th","vn","hk","tw","nz","ie","pt","gr","cz","ro","hu","at","ch",
    "be","bg","hr","sk","si","lt","lv","ee","is","lu","mt","cy","ua","by","kz",
    "il","ir","iq","jo","lb","kw","qa","bh","om","ye","af","bd","lk","np","mm",
    "kh","la","mn","uz","ge","am","az","co.uk","com.au","co.in","co.za","com.pk",
    "co.nz","com.br","com.mx","co.jp","or.jp","ne.jp","gov.uk","ac.uk","org.uk",
    "io","one","ltd","llc","inc","company","enterprises","solutions","services",
    "consulting","expert","guru","ninja","rocks","cool","zone","network","systems",
    "finance","money","market","marketing","business","careers","jobs","academy",
    "education","school","university","institute","center","care","health","fit",
    "coach","fitness","travel","tours","holiday","estate","realty","homes","house",
    "law","legal","tax","insurance","bank","capital","fund","trade","global","asia",
    "eu","africa","io","art","photo","photography","gallery","games","game","play",
    "software","computer","codes","data","security","hosting","domains","web",
}


def _valid_tld(dom):
    """True if the domain ends in a real TLD (rejects .davis, .can, .inte etc.)."""
    # Try two-part TLD first (co.uk, com.pk), then single
    two = ".".join(dom.rsplit(".", 2)[-2:]) if dom.count(".") >= 2 else ""
    one = dom.rsplit(".", 1)[-1] if "." in dom else ""
    return two in VALID_TLDS or one in VALID_TLDS

# Priority pages (most likely to have emails)
P1_PATHS = ["/contact","/contact-us","/contactus","/about","/about-us","/aboutus",
            "/privacy","/privacy-policy","/legal/privacy-policy","/legal/privacy",
            "/legal","/legal-notice","/contact.html","/about.html",
            "/pages/contact","/pages/about","/get-in-touch","/reach-us"]
P2_PATHS = ["/blog","/advertise","/write-for-us","/guest-post","/team","/support",
            "/terms","/terms-and-conditions","/legal/terms","/legal/terms-and-condition",
            "/imprint","/disclaimer","/cookie-policy","/impressum"]

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

def _timeout_tuple(to=None):
    """A single number as requests' timeout is the PER-READ limit, not a total.
    A server that dribbles one byte at a time can hold a worker open far past
    the intended budget — which is exactly how 25 domains pinned 25 workers and
    the whole job stalled. A (connect, read) tuple bounds both phases.

    Connect is capped at 3s: a domain that can't establish a TCP connection in
    3s is almost always dead (bad DNS, host down), and we were spending ~5s per
    attempt x 4 homepage variations = 20s per dead domain. 3s makes dead sites
    fall through fast so workers move on to live ones."""
    secs = to or PAGE_TIMEOUT
    return (min(3, secs), secs)


def _get(url, to=None):
    """Fetch URL with robust error handling. Accepts 403 (Cloudflare) if content exists."""
    return _get2(url, to)[0]


def _get2(url, to=None):
    """Like _get but also returns WHY it failed, so the caller can decide
    whether trying other URL variations is worth it.
    Returns (html_or_None, reason) where reason is one of:
      "ok", "dns", "refused", "timeout", "ssl", "http_error", "other".
    A "dns"/"refused" on the bare host means the domain is effectively dead —
    no point trying www/http variants, which is what wasted ~20s per dead site."""
    try:
        r=_s.get(url, timeout=_timeout_tuple(to), allow_redirects=True)
        if r.status_code >= 500: return (None, "http_error")
        if r.status_code >= 400 and r.status_code != 403: return (None, "http_error")
        if r.encoding and r.encoding.lower()!='utf-8':
            r.encoding=r.apparent_encoding or 'utf-8'
        ct=r.headers.get("content-type","").lower()
        if any(k in ct for k in ["text","html","xml","json"]): return (r.text, "ok")
        if not ct: return (r.text, "ok")
        return (None, "http_error")
    except requests.exceptions.SSLError:
        try:
            r=_s.get(url.replace("https://","http://"), timeout=_timeout_tuple(to), allow_redirects=True)
            if r.status_code<400: return (r.text, "ok")
        except: pass
        return (None, "ssl")
    except requests.exceptions.ConnectionError as e:
        msg=str(e).lower()
        # Only a REAL name-resolution failure means the domain is dead. Under a
        # big batch the DNS server can rate-limit us and throw generic connection
        # errors for domains that are actually fine — those must be retryable,
        # not marked "does not resolve".
        if ("name or service not known" in msg or "nodename nor servname" in msg
                or "getaddrinfo failed" in msg or "name resolution" in msg
                or "no address associated" in msg):
            return (None, "dns")
        if "refused" in msg:
            return (None, "refused")
        # timeouts, reset, temporary failures — retryable, not dead
        return (None, "timeout")
    except requests.exceptions.Timeout:
        return (None, "timeout")
    except Exception:
        return (None, "other")
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
        # ALL script tags (not just JSON-LD) — emails in JS variables
        for sc in soup.find_all("script"):
            if sc.string and "@" in sc.string:
                found|=set(EMAIL_RE.findall(sc.string))
    except: pass

    # HTML comments (<!-- contact: info@site.com -->)
    for m in re.findall(r'<!--(.*?)-->', html_text, re.S):
        found|=set(EMAIL_RE.findall(m))
        found|=set(EMAIL_RE.findall(_deob(m)))

    # Validate + clean — fast, accurate filtering
    # Only DEFINITE placeholders. Removed ambiguous ones (name/user/me/your/email/you/my/
    # site/company/person/someone) because real businesses use these as real inboxes
    # (email@site.com, me@brand.com, name@corp.com). Placeholder detection relies on
    # domain (example.com etc.) + JUNK_RE instead, so real emails are never wrongly skipped.
    PLACEHOLDER_LOCALS = {"exemple","yourname","youremail","johndoe","janedoe",
                          "firstname","lastname","dummy","placeholder","undefined",
                          "email","e-mail","address","user","username"}
    clean=set()
    # A "domain" that ends in a file/image extension isn't a real domain — these
    # come from filenames like 08.28.53@2x.jpeg being mistaken for an address.
    FILE_EXT_TLDS = {"jpeg","jpg","png","gif","webp","svg","bmp","ico","pdf",
                     "doc","docx","zip","mp4","mp3","css","js","json","xml",
                     "woff","woff2","ttf","eot","webm","mov","avi"}
    for e in found:
        e=e.lower().strip(".")
        if len(e)>60 or len(e)<5: continue
        local,_,dom=e.partition("@")
        if not dom or not local: continue
        if ".." in dom or ".." in local: continue
        if len(local)>40 or len(dom)>40: continue
        tld=dom.rsplit(".",1)[-1]
        if len(tld)>10 or len(tld)<2: continue  # generous TLD length
        if tld in FILE_EXT_TLDS: continue  # reject image/file "emails"
        # Reject local parts that look like a timestamp / filename fragment, e.g.
        # "08.28.53" from screenshot names, not a real inbox.
        if re.match(r'^\d{1,2}[.\-]\d{1,2}[.\-]\d{1,2}', local): continue
        if re.match(r'^\d+x\d*$', local): continue   # "2x", "1024x768"
        if not re.match(r'^[a-z0-9][a-z0-9.\-]*\.[a-z]{2,10}$',dom): continue
        # REAL TLD CHECK — reject fake TLDs like .davis .can .inte .con
        if not _valid_tld(dom): continue
        # Reject all-numeric domain part (337-216-4423.inte)
        parts=dom.rsplit(".",1)
        if re.match(r'^[\d.\-]+$',parts[0]): continue
        if not re.match(r'^[a-z0-9][a-z0-9._+\-]*$',local): continue
        if re.match(r'^\d+$',local): continue  # numeric-only local
        if local in PLACEHOLDER_LOCALS: continue
        # Reject single-word "sentence fragment" locals glued to a name-like domain:
        # e.g. "you@ease.davis" (you + ease + Davis from running text). If the local
        # is a common English word AND the domain's first label is also a common word,
        # it's almost certainly text mis-parsed as an email.
        FRAGMENT_WORDS = {"you","ease","the","and","for","with","your","our","this",
                          "that","from","have","will","are","was","were","been","being",
                          "at","to","in","on","of","is","it","we","us","me","my","he",
                          "she","they","them","please","here","click","read","more","see"}
        dom_first = parts[0].split(".")[0] if parts else ""
        if local in FRAGMENT_WORDS and dom_first in FRAGMENT_WORDS: continue
        # Reject placeholder domains
        PLACEHOLDER_DOMS = {"company.com","domain.com","website.com","site.com","yoursite.com",
                           "yourdomain.com","yourcompany.com","business.com","mysite.com",
                           "mycompany.com","mydomain.com","samplesite.com","testsite.com",
                           "email.com","name.com","sentry.io","sentry.wixpress.com"}
        if dom in PLACEHOLDER_DOMS: continue
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
    hints=["contact","about","team","blog","write-for-us","guest-post","advertise",
           "privacy","terms","legal","press","media","editorial","imprint","disclaimer",
           "support","help","partnerships","cookie"]
    pages=[]
    for a in soup.find_all("a",href=True):
        href=a["href"].strip()
        if not href or href.startswith(("#","mailto:","tel:","javascript:")): continue
        full=urljoin(base,href)
        h=urlparse(full).netloc.lower()
        if _blocked(h) or not _same(root,full): continue
        url_path=urlparse(full).path.lower()
        link_text=a.get_text(" ").lower()
        combined=url_path+" "+link_text+" "+href.lower()
        if any(k in combined for k in hints):
            clean=full.split("#")[0].split("?")[0]
            if clean not in pages: pages.append(clean)
    return pages[:MAX_PAGES]


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

    if confidence < 40:
        return ("Unknown", confidence)

    return (top, confidence)


def _sitemap_urls(base, root, get_fn, budget_fn, max_urls=8):
    """Find contact-ish pages via robots.txt and sitemap(s).

    Many sites don't put their contact page at a guessable path like /contact —
    it lives somewhere only the sitemap knows (e.g. /company/reach-out). We read
    robots.txt for Sitemap: lines, fall back to the usual sitemap locations,
    parse the XML, and return only URLs whose path looks like a contact/about/
    team/imprint page. Blog posts, products, tags and pagination are ignored so
    we don't waste the domain's time budget on pages that never list an address.
    """
    import re as _re
    want = ("contact", "about", "team", "support", "privacy", "imprint",
            "impressum", "legal", "get-in-touch", "reach", "company", "kontakt")
    skip = ("/blog/", "/product", "/tag/", "/category/", "/page/", "/20",  # dated posts
            "/shop", "/cart", "/news/", "/author/", "/wp-content", ".jpg", ".png", ".pdf")
    sitemaps = []

    # 1) robots.txt → Sitemap: lines
    if budget_fn() > 1:
        robots = get_fn(base + "/robots.txt", min(4, budget_fn()))
        if robots:
            for line in robots.splitlines():
                if line.lower().startswith("sitemap:"):
                    sm = line.split(":", 1)[1].strip()
                    if sm:
                        sitemaps.append(sm)

    # 2) common sitemap locations as a fallback
    for path in ("/sitemap.xml", "/sitemap_index.xml"):
        if base + path not in sitemaps:
            sitemaps.append(base + path)

    found, seen_sm = [], set()
    # Follow at most a couple of sitemaps (index files can point to many)
    for sm in sitemaps[:3]:
        if budget_fn() < 2 or len(found) >= max_urls:
            break
        if sm in seen_sm:
            continue
        seen_sm.add(sm)
        xml = get_fn(sm, min(4, budget_fn()))
        if not xml:
            continue
        locs = _re.findall(r"<loc>\s*([^<\s]+)\s*</loc>", xml, _re.I)
        # If this is a sitemap index, its <loc>s are more sitemaps → follow one
        # level that itself looks contact-related, to keep it cheap.
        child_sitemaps = [u for u in locs if u.lower().endswith(".xml")]
        page_urls = [u for u in locs if not u.lower().endswith(".xml")]
        for u in page_urls:
            lu = u.lower()
            if any(s in lu for s in skip):
                continue
            if any(w in lu for w in want) and _same(root, u):
                clean = u.split("#")[0].split("?")[0]
                if clean not in found:
                    found.append(clean)
                    if len(found) >= max_urls:
                        break
        # descend into one promising child sitemap (e.g. sitemap-pages.xml)
        for cs in child_sitemaps[:2]:
            if len(found) >= max_urls or budget_fn() < 2:
                break
            if cs in seen_sm or not any(k in cs.lower() for k in ("page", "main", "site")):
                continue
            seen_sm.add(cs)
            cxml = get_fn(cs, min(4, budget_fn()))
            if not cxml:
                continue
            for u in _re.findall(r"<loc>\s*([^<\s]+)\s*</loc>", cxml, _re.I):
                lu = u.lower()
                if lu.endswith(".xml") or any(s in lu for s in skip):
                    continue
                if any(w in lu for w in want) and _same(root, u):
                    clean = u.split("#")[0].split("?")[0]
                    if clean not in found:
                        found.append(clean)
                        if len(found) >= max_urls:
                            break
    return found


def extract_domain(domain, mode="vendor"):
    """FAST-FIRST: find email quickly, move on. Max 15 seconds."""
    start=time.time()
    root=_root(domain)
    if not root or _blocked(root):
        return {"domain":root,"contacts":[],"status":"skipped","vendor_signals":{},"client_category":""}

    def budget(): return max(0, DOMAIN_BUDGET-(time.time()-start))
    def done(): return time.time()-start>=DOMAIN_BUDGET

    # 1) HOMEPAGE — try variations, but bail immediately on a dead host.
    # If DNS can't resolve the domain at all, no variation will help, so we
    # stop after the first attempt instead of burning ~20s on four of them.
    base="https://"+root
    home, why = _get2(base, min(PAGE_TIMEOUT, budget()))
    if not home and why == "dns":
        # Bare domain doesn't resolve — try www once (some hosts only have www),
        # then give up fast.
        if not done():
            home, why2 = _get2("https://www."+root, min(PAGE_TIMEOUT, budget()))
            if not home and why2 == "dns":
                return {"domain":root,"contacts":[],"status":"site not reachable",
                        "error":"DNS: domain does not resolve",
                        "vendor_signals":{},"client_category":"","elapsed":round(time.time()-start,1)}
    if not home and not done(): home=_get("http://"+root, min(PAGE_TIMEOUT, budget()))
    if not home and not done(): home=_get("https://www."+root, min(PAGE_TIMEOUT, budget()))
    if not home and not done(): home=_get("http://www."+root, min(PAGE_TIMEOUT, budget()))
    if not home:
        return {"domain":root,"contacts":[],"status":"site not reachable",
                "vendor_signals":{},"client_category":"","elapsed":round(time.time()-start,1)}
    # Update base to actual URL (after redirects)
    emails=_extract(home)
    source={e:base for e in emails}
    loaded=[base]

    # Discover internal links from homepage
    discovered=_discover(base,root,home)

    # 2) Try P1 pages (contact, about, privacy) — ALL discovered + guessed
    if not done():
        p1=[]
        for path in P1_PATHS:
            u=base+path
            if u not in p1: p1.append(u)
        for u in discovered:
            p=urlparse(u).path.lower()
            if any(k in p for k in ["contact","about","privacy","legal","terms"]) and u not in p1: p1.append(u)

        for pg in p1[:8]:
            if done(): break
            h=_get(pg, min(PAGE_TIMEOUT_QUICK, budget()))
            if h:
                loaded.append(pg)
                new=_extract(h)
                for e in new:
                    if e not in source: source[e]=pg
                emails|=new
                if emails: break  # EMAIL FOUND → STOP, move to next domain

    # 2.5) STILL no email? Ask robots.txt + sitemap where the contact page is.
    # This catches sites whose contact/about page isn't at a guessable path.
    # Only runs when we haven't found anything yet, so fast hits stay fast.
    if not emails and not done():
        sm_pages = _sitemap_urls(base, root, _get, budget, max_urls=6)
        for pg in sm_pages:
            if done(): break
            if pg in loaded: continue
            h=_get(pg, min(PAGE_TIMEOUT_QUICK, budget()))
            if h:
                loaded.append(pg)
                new=_extract(h)
                for e in new:
                    if e not in source: source[e]=pg
                emails|=new
                if emails: break  # EMAIL FOUND → STOP

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
