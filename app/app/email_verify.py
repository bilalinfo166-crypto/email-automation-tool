"""Email verification — check if email is deliverable BEFORE sending.
Reduces bounce rate by filtering invalid/dead emails.
"""
import re
import socket
import smtplib
import dns.resolver

# Cache MX lookups to avoid repeated DNS queries
_mx_cache = {}

def _get_mx(domain):
    """Get MX record for domain. Cached."""
    if domain in _mx_cache:
        return _mx_cache[domain]
    try:
        records = dns.resolver.resolve(domain, 'MX', lifetime=5)
        mx = str(sorted(records, key=lambda r: r.preference)[0].exchange).rstrip('.')
        _mx_cache[domain] = mx
        return mx
    except Exception:
        _mx_cache[domain] = None
        return None


def verify_email(email, timeout=8):
    """Verify email deliverability. Returns (is_valid, reason).
    Levels: syntax → MX record → SMTP check."""
    # 1. Syntax check
    if not re.match(r'^[a-zA-Z0-9._%+\-]+@[a-zA-Z0-9.\-]+\.[a-zA-Z]{2,}$', email):
        return (False, "invalid_syntax")

    domain = email.split('@')[-1].lower()

    # 2. MX record check
    mx = _get_mx(domain)
    if not mx:
        return (False, "no_mx_record")

    # 3. SMTP check (does the mailbox exist?)
    try:
        server = smtplib.SMTP(timeout=timeout)
        server.connect(mx, 25)
        server.helo("uplyncio.com")
        server.mail("verify@uplyncio.com")
        code, _ = server.rcpt(email)
        server.quit()
        if code == 250:
            return (True, "valid")
        elif code == 550:
            return (False, "mailbox_not_found")
        else:
            return (True, "accepted")  # ambiguous — treat as valid
    except smtplib.SMTPServerDisconnected:
        return (True, "accepted")  # server closed — many block verification, assume valid
    except smtplib.SMTPConnectError:
        return (True, "accepted")
    except socket.timeout:
        return (True, "accepted")  # timeout — don't reject, assume valid
    except Exception:
        return (True, "accepted")  # any error — err on side of sending


def quick_verify(email):
    """Fast check: syntax + MX only (no SMTP). Much faster for bulk."""
    if not re.match(r'^[a-zA-Z0-9._%+\-]+@[a-zA-Z0-9.\-]+\.[a-zA-Z]{2,}$', email):
        return (False, "invalid_syntax")
    domain = email.split('@')[-1].lower()
    mx = _get_mx(domain)
    if not mx:
        return (False, "no_mx_record")
    return (True, "valid")
