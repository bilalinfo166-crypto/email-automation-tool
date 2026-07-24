"""Read the commercial terms out of a vendor's reply.

Site owners answer in prose, not forms — "125 EUR for a guest post, link
insertion 60, 2 dofollow, TAT 3 days". This pulls those numbers out so the
deals sheet fills itself in instead of being typed by hand.

Everything here is best-effort: if a value can't be found with confidence it's
left blank rather than guessed, because a wrong price is worse than none.
"""
import re

# --- currency -------------------------------------------------------------
CURRENCY_SYMBOLS = {"$": "USD", "€": "EUR", "£": "GBP", "₹": "INR", "¥": "JPY"}
CURRENCY_WORDS = {
    "usd": "USD", "dollar": "USD", "dollars": "USD", "us$": "USD",
    "eur": "EUR", "euro": "EUR", "euros": "EUR",
    "gbp": "GBP", "pound": "GBP", "pounds": "GBP", "quid": "GBP",
    "inr": "INR", "rupee": "INR", "rupees": "INR",
    "cad": "CAD", "aud": "AUD",
}

# a money amount, with the currency either before or after
MONEY = re.compile(
    r"(?:(?P<sym1>[$€£₹¥])\s*(?P<amt1>\d[\d,]*(?:\.\d{1,2})?)"
    r"|(?P<amt2>\d[\d,]*(?:\.\d{1,2})?)\s*(?P<cur2>usd|eur|gbp|inr|cad|aud|dollars?|euros?|pounds?|rupees?)"
    r"|(?P<cur3>usd|eur|gbp|inr|cad|aud)\s*(?P<amt3>\d[\d,]*(?:\.\d{1,2})?))",
    re.I)

GUEST_POST_HINTS = ["guest post", "guest-post", "guestpost", "sponsored post",
                    "sponsored article", "article", "publishing", "per post",
                    "post price", "posting"]
INSERT_HINTS = ["link insertion", "link-insertion", "niche edit", "niche-edit",
                "insertion", "existing post", "existing article", "inserting"]

SHEET_RE = re.compile(
    r"https?://(?:docs\.google\.com/spreadsheets/[^\s\"'<>]+"
    r"|drive\.google\.com/[^\s\"'<>]+"
    r"|[^\s\"'<>]*\.(?:xlsx|csv)(?:\?[^\s\"'<>]*)?)", re.I)

URL_RE = re.compile(r"https?://[^\s\"'<>\)]+", re.I)

DONE_HINTS = ["finaliz", "finalis", "confirmed the deal", "deal is confirmed",
              "we have a deal", "agreed", "invoice", "payment sent",
              "proceed with the order", "order confirmed"]


def _clean_amount(raw):
    try:
        return f"{float(str(raw).replace(',', '')):g}"
    except Exception:
        return ""


def _money_near(text, hints, window=70):
    """Find the price that belongs to one of these phrases.

    People write it both ways round — "link insertion is $45" and "$45 for link
    insertion" — so both shapes are matched explicitly before falling back to
    "whatever number is nearest".

    Returns (amount, currency, position) so the caller can spot two phrases
    that have latched onto the very same figure.
    """
    MONEY_BIT = r"(?:[$€£₹¥]\s*\d[\d,]*(?:\.\d{1,2})?|\d[\d,]*(?:\.\d{1,2})?\s*(?:usd|eur|gbp|inr|cad|aud|dollars?|euros?|pounds?|rupees?))"

    def _take(fragment, offset):
        m = MONEY.search(fragment)
        if not m:
            return None
        amt = m.group("amt1") or m.group("amt2") or m.group("amt3")
        if not amt:
            return None
        cur = (CURRENCY_SYMBOLS.get(m.group("sym1") or "")
               or CURRENCY_WORDS.get((m.group("cur2") or m.group("cur3") or "").lower())
               or "")
        return _clean_amount(amt), cur, offset + m.start()

    low = text.lower()

    # Gather candidates from BOTH shapes, then keep the one closest to the
    # phrase. Trying one shape first meant "125 EUR for the guest post and 70
    # EUR for link insertion" gave the guest post a price of 70.
    candidates = []          # (distance from phrase, amount, currency, position)
    for hint in hints:
        for hm in re.finditer(re.escape(hint), low):
            hpos = hm.start()
            # "<phrase> ... is/at/costs <money>" — but the gap must stay inside
            # the same clause. "guest post AND 70 EUR for link insertion" is a
            # different item, not this one's price.
            m = re.search(rf"{re.escape(hint)}\b([^.;\n]{{0,40}}?)({MONEY_BIT})",
                          low[hpos:hpos + 120])
            if m:
                gap = m.group(1)
                if not re.search(r"\band\b|\bor\b|,|;", gap):
                    got = _take(text[hpos + m.start(2): hpos + m.end(2)],
                                hpos + m.start(2))
                    if got:
                        candidates.append((abs(got[2] - hpos), *got))
            # "<money> for/per <phrase>"
            back = low[max(0, hpos - 90):hpos + len(hint)]
            boff = max(0, hpos - 90)
            for m2 in re.finditer(
                    rf"({MONEY_BIT})\s*(?:for|per)\s+(?:a\s+|the\s+|one\s+)?{re.escape(hint)}",
                    back):
                got = _take(text[boff + m2.start(1): boff + m2.end(1)], boff + m2.start(1))
                if got:
                    candidates.append((abs(got[2] - hpos), *got))
    if candidates:
        candidates.sort(key=lambda c: c[0])
        return candidates[0][1], candidates[0][2], candidates[0][3]

    # 3) fall back to the nearest figure, slightly preferring one that follows
    best = None
    for hint in hints:
        start = 0
        while True:
            i = low.find(hint, start)
            if i < 0:
                break
            start = i + len(hint)
            seg_start = max(0, i - window)
            seg = text[seg_start: i + len(hint) + window]
            for m in MONEY.finditer(seg):
                amt = m.group("amt1") or m.group("amt2") or m.group("amt3")
                if not amt:
                    continue
                cur = (CURRENCY_SYMBOLS.get(m.group("sym1") or "")
                       or CURRENCY_WORDS.get((m.group("cur2") or m.group("cur3") or "").lower())
                       or "")
                abs_pos = seg_start + m.start()
                raw = abs_pos - i
                dist = raw if raw >= 0 else (abs(raw) + 30)
                if best is None or dist < best[0]:
                    best = (dist, _clean_amount(amt), cur, abs_pos)
    if best is None:
        return "", "", None
    return best[1], best[2], best[3]


def _first_money(text):
    m = MONEY.search(text)
    if not m:
        return "", ""
    amt = m.group("amt1") or m.group("amt2") or m.group("amt3")
    cur = (CURRENCY_SYMBOLS.get(m.group("sym1") or "")
           or CURRENCY_WORDS.get((m.group("cur2") or m.group("cur3") or "").lower())
           or "")
    return _clean_amount(amt), cur


def _count_near(text, word):
    """'2 dofollow links' -> 2. Also handles 'dofollow: 2' and 'two dofollow'."""
    words = {"one": "1", "two": "2", "three": "3", "four": "4", "five": "5"}
    low = text.lower()
    pats = [
        rf"(\d+)\s*(?:x\s*)?{word}",
        rf"{word}\s*(?:links?)?\s*[:=-]\s*(\d+)",
        rf"(\w+)\s+{word}\s+links?",
    ]
    for p in pats:
        m = re.search(p, low)
        if m:
            v = m.group(1)
            if v.isdigit():
                return v
            if v in words:
                return words[v]
    # A bare mention only counts if it's a statement. "How many dofollow links
    # are allowed?" is a question we asked — not a number they gave us.
    for sent in re.split(r"[.!?\n]", low):
        if word in sent and "?" not in sent:
            if re.search(rf"(?:allow|offer|include|give|provide|accept)\w*\s[^.]*\b{word}\b", sent):
                return "1"
    return ""


def _tat(text):
    """Turnaround time, e.g. '3 days', '24-48 hours', '1 week'."""
    m = re.search(r"(?:tat|turn\s*around|turnaround|delivery|within)\D{0,20}"
                  r"(\d+\s*(?:-|to|–)?\s*\d*\s*(?:hours?|hrs?|days?|weeks?|business days?))",
                  text, re.I)
    if m:
        return re.sub(r"\s+", " ", m.group(1)).strip()
    m = re.search(r"\b(\d+\s*(?:-|to|–)?\s*\d*\s*(?:days?|weeks?|hours?))\b", text, re.I)
    return re.sub(r"\s+", " ", m.group(1)).strip() if m else ""


# Real top-level domains. Without this check, an email local part like
# "hira.bradvertisers" reads as a domain, because "bradvertisers" looks like
# a TLD to a naive pattern.
KNOWN_TLDS = {
    "com", "net", "org", "io", "co", "uk", "us", "ca", "au", "in", "pk", "de",
    "fr", "es", "it", "nl", "se", "no", "dk", "fi", "pl", "ru", "br", "mx",
    "jp", "cn", "kr", "sg", "hk", "ae", "sa", "za", "ng", "ke", "ie", "ch",
    "at", "be", "pt", "gr", "cz", "ro", "hu", "tr", "il", "nz", "ph", "my",
    "id", "th", "vn", "biz", "info", "me", "tv", "cc", "app", "dev", "ai",
    "blog", "news", "online", "site", "store", "shop", "tech", "media",
    "agency", "digital", "world", "life", "today", "space", "website", "xyz",
    "club", "pro", "edu", "gov", "int", "eu", "asia", "cloud", "email",
}

# URL shorteners and trackers — never the site itself
SHORTENERS = {
    "bit.ly", "t.ly", "tinyurl.com", "goo.gl", "ow.ly", "buff.ly", "rebrand.ly",
    "cutt.ly", "is.gd", "shorturl.at", "lnkd.in", "t.co", "rb.gy", "shrtco.de",
    "mailchi.mp", "sendgrid.net", "list-manage.com", "hubspotlinks.com",
}


def _valid_domain(d: str) -> bool:
    """Is this actually a website address?"""
    if not d or "." not in d or " " in d:
        return False
    if ":" in d:                      # host:port — our own server, not a site
        return False
    if re.match(r"^\d{1,3}(?:\.\d{1,3}){1,3}$", d):   # bare IP
        return False
    if d in SHORTENERS or d in ("localhost",):
        return False
    labels = d.split(".")
    if len(labels) < 2 or any(not l for l in labels):
        return False
    if labels[-1] not in KNOWN_TLDS:
        return False
    if len(d) > 80:
        return False
    return True


def _is_ours(d: str) -> bool:
    """Our own site, or anything built on our brand name."""
    try:
        from . import blog_research as _br
        own, brands = _br._OWN_DOMAINS, _br._OWN_BRANDS
    except Exception:
        own, brands = set(), set()
    for o in own:
        if d == o or d.endswith("." + o):
            return True
    labels = d.split(".")
    for b in brands:
        if b in labels or b in d.replace(".", ""):
            return True
    return False


def _domains(text, exclude=()):
    """Domains the sender mentions — an owner often lists several sites.

    Email addresses are removed first: their local parts ("hira.bradvertisers")
    otherwise read as domains and end up on the deals sheet.
    """
    out, seen = [], set()
    skip = {"gmail.com", "googlemail.com", "yahoo.com", "outlook.com", "hotmail.com",
            "google.com", "docs.google.com", "drive.google.com", "example.com",
            "w3.org", "schema.org", "gravatar.com", "youtube.com", "facebook.com",
            "twitter.com", "linkedin.com", "instagram.com"}
    skip.update(x.lower().replace("www.", "") for x in exclude if x)

    # Drop every email address before looking for site names
    cleaned = re.sub(r"[\w.\-+]+@[\w.\-]+\.\w+", " ", text)

    def _add(d):
        d = d.lower().strip(".,;:)")
        d = re.sub(r"^www\.", "", d)
        if d in skip or d in seen:
            return
        if not _valid_domain(d) or _is_ours(d):
            return
        seen.add(d)
        out.append(d)

    for raw in URL_RE.findall(cleaned):
        _add(re.sub(r"^https?://", "", raw).split("/")[0])
    for m in re.finditer(r"\b((?:[a-z0-9][a-z0-9-]*\.)+[a-z]{2,})\b", cleaned, re.I):
        _add(m.group(1))
    return out


def parse_reply(text: str, exclude_domains=()) -> dict:
    """Pull whatever deal terms are present. Missing values stay empty."""
    text = re.sub(r"<[^>]+>", " ", text or "")          # strip any html
    text = re.sub(r"&nbsp;?", " ", text)
    text = re.sub(r"\s+", " ", text).strip()
    if not text:
        return {}

    gp_amt, gp_cur, gp_pos = _money_near(text, GUEST_POST_HINTS)
    li_amt, li_cur, li_pos = _money_near(text, INSERT_HINTS)
    # If both phrases matched the SAME figure, only the nearer one keeps it.
    if gp_amt and li_amt and gp_pos == li_pos:
        if gp_pos is not None:
            li_amt, li_cur = "", ""

    # If nothing matched a phrase but a price is clearly stated, treat the first
    # amount as the guest-post price — that's what a bare number nearly always means.
    if not gp_amt and not li_amt:
        gp_amt, gp_cur = _first_money(text)

    currency = gp_cur or li_cur
    if not currency:
        for sym, code in CURRENCY_SYMBOLS.items():
            if sym in text:
                currency = code
                break
    if not currency:
        for w, code in CURRENCY_WORDS.items():
            if re.search(rf"\b{re.escape(w)}\b", text, re.I):
                currency = code
                break

    sheets = SHEET_RE.findall(text)
    sample = ""
    m = re.search(r"(?:sample|example|reference)\D{0,40}(https?://[^\s\"'<>\)]+)", text, re.I)
    if m:
        sample = m.group(1)

    return {
        "currency": currency,
        "guest_post_price": gp_amt,
        "link_insert_price": li_amt,
        "dofollow_links": _count_near(text, "dofollow"),
        "nofollow_links": _count_near(text, "nofollow"),
        "tat": _tat(text),
        "sheet_url": sheets[0] if sheets else "",
        "sample_url": sample,
        "domains": _domains(text, exclude=exclude_domains),
        "looks_done": any(h in text.lower() for h in DONE_HINTS),
    }
