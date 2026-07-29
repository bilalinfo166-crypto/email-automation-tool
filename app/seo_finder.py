"""SEO Agency Finder — discovers agency/business websites for a keyword +
location using a public search endpoint, then hands the domains to the existing
scraper so their PUBLIC emails get extracted. No LinkedIn/Google scraping (those
break their terms); this uses a legal web-search API for discovery only.

Discovery uses DuckDuckGo's HTML endpoint (no API key, allows light automated
queries) to find candidate sites. Email extraction reuses scraper.py, which
only reads public pages (contact/about/team/footer).
"""
from __future__ import annotations
import re, time
from urllib.parse import quote_plus, urlparse

try:
    import requests
    from bs4 import BeautifulSoup
    _OK = True
except Exception:
    _OK = False

_UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
       "(KHTML, like Gecko) Chrome/120.0 Safari/537.36")

# Sites that are directories/socials, not the agency's own site — skip as leads.
_SKIP_HOSTS = {
    "linkedin.com", "facebook.com", "twitter.com", "x.com", "instagram.com",
    "youtube.com", "yelp.com", "google.com", "bing.com", "duckduckgo.com",
    "clutch.co", "trustpilot.com", "glassdoor.com", "indeed.com",
    "wikipedia.org", "reddit.com", "medium.com", "quora.com", "pinterest.com",
    "goodfirms.co", "upwork.com", "fiverr.com", "crunchbase.com",
}


def _root(url: str) -> str:
    try:
        h = urlparse(url if "://" in url else "http://" + url).netloc.lower()
        return h[4:] if h.startswith("www.") else h
    except Exception:
        return ""


def _skip(host: str) -> bool:
    if any(host == s or host.endswith("." + s) for s in _SKIP_HOSTS):
        return True
    # Also reject free/hosted-subdomain providers (blogspot, wordpress.com, wix…)
    try:
        from .scraper_jobs import is_free_host
        return is_free_host(host)
    except Exception:
        return False


def search_domains(keyword: str, location: str = "", max_results: int = 30):
    """Return candidate agency domains for a keyword (+optional location).
    Tries DuckDuckGo's HTML endpoints (public, no key). Directories/socials are
    filtered out so what's left is agencies' own sites. If DDG blocks the
    request, returns a clear message so the UI can suggest a search API."""
    if not _OK:
        return {"error": "requests/bs4 not available", "domains": []}
    q = keyword.strip()
    if location.strip():
        q += " " + location.strip()

    endpoints = [
        ("https://html.duckduckgo.com/html/", {"q": q}),
        ("https://lite.duckduckgo.com/lite/", {"q": q}),
    ]
    found, seen = [], set()
    last_err = ""
    for base, data in endpoints:
        try:
            r = requests.post(base, headers={"User-Agent": _UA,
                              "Accept": "text/html", "Referer": "https://duckduckgo.com/"},
                              timeout=15, data=data)
            if r.status_code != 200:
                last_err = f"HTTP {r.status_code}"
                continue
            soup = BeautifulSoup(r.text, "html.parser")
            # both layouts: result__a anchors, or plain result links in lite
            anchors = soup.select("a.result__a") or soup.select("a[href*='uddg']") \
                or [a for a in soup.find_all("a") if a.get("href", "").startswith("http")]
            from urllib.parse import unquote
            for a in anchors:
                href = a.get("href") or ""
                m = re.search(r"uddg=([^&]+)", href)
                target = unquote(m.group(1)) if m else href
                if not target.startswith("http"):
                    continue
                host = _root(target)
                if not host or _skip(host) or host in seen:
                    continue
                seen.add(host)
                found.append({"domain": host, "url": target,
                              "title": a.get_text(strip=True)[:120],
                              "source": "DuckDuckGo", "keyword": keyword,
                              "location": location})
                if len(found) >= max_results:
                    break
            if found:
                return {"domains": found, "query": q, "count": len(found)}
        except Exception as e:
            last_err = str(e)
            continue
    return {"domains": found, "query": q, "count": len(found),
            "note": ("Search returned no results" if not last_err
                     else f"Search blocked ({last_err}). A search API (Serper/Brave) "
                          "would be more reliable.")}


def quality_score(lead: dict) -> tuple[int, str]:
    """A public-signal quality score for a discovered lead."""
    score, why = 40, []
    if lead.get("email"):
        score += 30; why.append("public email found")
    if lead.get("domain"):
        score += 15; why.append("has website")
    if lead.get("title"):
        score += 10; why.append("clear listing")
    if lead.get("multiple_pages"):
        score += 5; why.append("multiple public pages")
    score = min(100, score)
    band = ("High" if score >= 85 else "Good" if score >= 70
            else "Average" if score >= 50 else "Low")
    return score, f"{band} — " + ", ".join(why) if why else band
