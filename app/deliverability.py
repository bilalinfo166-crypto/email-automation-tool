"""Deliverability / authentication checker — real DNS-based diagnostics.

Checks a domain's email authentication setup: SPF, DKIM, DMARC, MX. All results
come from real public DNS records, not fabricated. For each check we return a
status (pass / warning / fail / unknown) and a plain explanation of what it
means and what to fix.

This is the honest, buildable half of "deliverability monitoring": DNS-based
authentication is public and verifiable. (Real inbox-vs-spam placement would
need a seed-inbox network, which this does not fake.)
"""
from __future__ import annotations
import re

try:
    import dns.resolver
    _HAVE_DNS = True
except Exception:
    _HAVE_DNS = False

# Common DKIM selectors used by major providers / ESPs. We probe these because
# DKIM keys live at <selector>._domainkey.<domain> and there's no way to list
# selectors from DNS — you have to know/guess them.
COMMON_DKIM_SELECTORS = [
    "google", "default", "selector1", "selector2", "k1", "k2", "k3",
    "mail", "dkim", "smtp", "s1", "s2", "mandrill", "mailjet", "sendgrid",
    "amazonses", "zoho", "protonmail", "protonmail2", "protonmail3",
    "fm1", "fm2", "fm3", "mesmtp", "everlytickey1", "everlytickey2",
]


def _resolver():
    r = dns.resolver.Resolver()
    r.lifetime = 6.0          # hard cap per lookup — never hang the UI
    r.timeout = 3.0
    return r


def _txt(domain: str):
    """All TXT records for a domain, decoded, or [] on any failure."""
    try:
        ans = _resolver().resolve(domain, "TXT")
        out = []
        for r in ans:
            try:
                out.append(b"".join(r.strings).decode(errors="ignore"))
            except Exception:
                out.append(str(r))
        return out
    except Exception:
        return []


def check_spf(domain: str) -> dict:
    """SPF says which servers may send mail for the domain."""
    recs = [t for t in _txt(domain) if t.lower().startswith("v=spf1")]
    if not recs:
        return {"status": "fail", "record": "",
                "detail": "No SPF record found. Receivers can't verify which "
                          "servers may send for this domain — add a v=spf1 record."}
    if len(recs) > 1:
        return {"status": "fail", "record": " | ".join(recs),
                "detail": "More than one SPF record. RFC allows only one — "
                          "merge them into a single v=spf1 record or SPF fails."}
    rec = recs[0]
    if "-all" in rec:
        strength = "strict (-all)"
        status = "pass"
    elif "~all" in rec:
        strength = "soft-fail (~all)"
        status = "pass"
    elif "?all" in rec or "+all" in rec:
        strength = "neutral/allow-all — weak"
        status = "warning"
    else:
        strength = "no 'all' mechanism"
        status = "warning"
    return {"status": status, "record": rec,
            "detail": f"SPF present, policy: {strength}."}


def check_dmarc(domain: str) -> dict:
    """DMARC ties SPF+DKIM together and tells receivers what to do on failure."""
    recs = [t for t in _txt("_dmarc." + domain) if t.lower().startswith("v=dmarc1")]
    if not recs:
        return {"status": "fail", "record": "",
                "detail": "No DMARC record. Add one at _dmarc." + domain +
                          " — without it, spoofing protection and reporting are off."}
    rec = recs[0]
    m = re.search(r"\bp=(\w+)", rec)
    policy = (m.group(1).lower() if m else "none")
    if policy == "reject":
        status, note = "pass", "strict policy (p=reject)"
    elif policy == "quarantine":
        status, note = "pass", "policy p=quarantine"
    else:
        status, note = "warning", "policy p=none (monitoring only — not enforcing)"
    return {"status": status, "record": rec,
            "detail": f"DMARC present, {note}."}


def check_dkim(domain: str) -> dict:
    """Probe common selectors for a DKIM public key."""
    found = []
    for sel in COMMON_DKIM_SELECTORS:
        host = f"{sel}._domainkey.{domain}"
        recs = _txt(host)
        for t in recs:
            if "v=dkim1" in t.lower() or "p=" in t:
                found.append(sel)
                break
    if found:
        return {"status": "pass", "record": ", ".join(found),
                "detail": f"DKIM key found (selector: {', '.join(found)})."}
    return {"status": "warning", "record": "",
            "detail": "No DKIM key found on common selectors. Your provider may "
                      "use a custom selector — check its DKIM setup. DKIM signs "
                      "your mail so receivers trust it wasn't altered."}


def check_mx(domain: str) -> dict:
    """MX says where mail for the domain is delivered."""
    try:
        ans = _resolver().resolve(domain, "MX")
        hosts = sorted((r.preference, str(r.exchange).rstrip(".")) for r in ans)
        if not hosts:
            raise Exception("empty")
        return {"status": "pass", "record": ", ".join(h for _, h in hosts),
                "detail": f"{len(hosts)} mail server(s) configured."}
    except Exception:
        return {"status": "fail", "record": "",
                "detail": "No MX records — this domain can't receive mail, "
                          "which also hurts sending reputation."}


def check_domain(domain: str) -> dict:
    """Full authentication report for one domain."""
    domain = (domain or "").strip().lower().lstrip("@")
    if not domain or "." not in domain:
        return {"domain": domain, "error": "invalid domain"}
    if not _HAVE_DNS:
        return {"domain": domain, "error": "dnspython not installed",
                "detail": "Run: pip install dnspython"}

    spf = check_spf(domain)
    dkim = check_dkim(domain)
    dmarc = check_dmarc(domain)
    mx = check_mx(domain)

    # Overall grade from the four checks.
    checks = {"spf": spf, "dkim": dkim, "dmarc": dmarc, "mx": mx}
    fails = sum(1 for c in checks.values() if c["status"] == "fail")
    warns = sum(1 for c in checks.values() if c["status"] == "warning")
    if fails == 0 and warns == 0:
        overall = "excellent"
    elif fails == 0:
        overall = "good"
    elif fails == 1:
        overall = "needs attention"
    else:
        overall = "poor"
    score = max(0, 100 - fails * 30 - warns * 10)

    return {"domain": domain, "overall": overall, "score": score, **checks}


def domain_of(email: str) -> str:
    return (email or "").split("@")[-1].strip().lower()
