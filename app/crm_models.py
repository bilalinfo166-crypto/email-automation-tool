"""CRM tables: domains, extracted business contacts, suppression list,
campaigns (with structural compliance fields), send queue, and event log."""
from datetime import datetime
from sqlalchemy import String, Integer, Boolean, DateTime, Text, ForeignKey
from sqlalchemy.orm import Mapped, mapped_column
from .database import Base


class Domain(Base):
    __tablename__ = "domains"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    domain: Mapped[str] = mapped_column(String, unique=True, index=True)
    status: Mapped[str] = mapped_column(String, default="pending")  # pending/scraped/failed
    mode: Mapped[str] = mapped_column(String, default="vendor", index=True)  # vendor / client
    contacts_found: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)


class Contact(Base):
    __tablename__ = "contacts"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    email: Mapped[str] = mapped_column(String, unique=True, index=True)
    domain: Mapped[str] = mapped_column(String, index=True)
    mode: Mapped[str] = mapped_column(String, default="vendor", index=True)  # vendor / client
    source_url: Mapped[str] = mapped_column(String, default="")   # the public page it came from
    role_based: Mapped[bool] = mapped_column(Boolean, default=False)  # info@/contact@/sales@ ...
    mx_ok: Mapped[bool] = mapped_column(Boolean, default=False)   # domain has a mail server
    status: Mapped[str] = mapped_column(String, default="new")   # new/queued/sent
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)


class Suppression(Base):
    __tablename__ = "suppression"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    email: Mapped[str] = mapped_column(String, unique=True, index=True)
    reason: Mapped[str] = mapped_column(String, default="unsubscribe")  # unsubscribe/bounce/complaint/manual
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)


class Campaign(Base):
    __tablename__ = "campaigns"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String)
    mode: Mapped[str] = mapped_column(String, default="vendor", index=True)  # vendor / client
    # --- required for a lawful, identifiable email (CAN-SPAM style) ---
    subject: Mapped[str] = mapped_column(String, default="")
    from_name: Mapped[str] = mapped_column(String, default="")
    company: Mapped[str] = mapped_column(String, default="")
    postal_address: Mapped[str] = mapped_column(String, default="")
    reason_for_contact: Mapped[str] = mapped_column(Text, default="")
    unsubscribe_url: Mapped[str] = mapped_column(String, default="")   # optional external; app also injects a working one
    body_html: Mapped[str] = mapped_column(Text, default="")
    # --- gates ---
    lawful_basis_confirmed: Mapped[bool] = mapped_column(Boolean, default=False)
    status: Mapped[str] = mapped_column(String, default="draft")  # draft/pending_review/approved/sending/completed
    # --- pacing (rate limits) ---
    per_sender_daily_cap: Mapped[int] = mapped_column(Integer, default=100)
    min_delay_sec: Mapped[int] = mapped_column(Integer, default=25)
    max_delay_sec: Mapped[int] = mapped_column(Integer, default=60)
    # --- autopilot & scheduling ---
    emails_per_batch: Mapped[int] = mapped_column(Integer, default=10)
    delay_seconds: Mapped[int] = mapped_column(Integer, default=60)
    scheduled_time: Mapped[str] = mapped_column(String, default="")   # ISO datetime or empty
    sender_emails: Mapped[str] = mapped_column(Text, default="")      # comma-separated selected senders
    autopilot: Mapped[bool] = mapped_column(Boolean, default=False)   # keep sending daily until list done
    total_target: Mapped[int] = mapped_column(Integer, default=0)     # how many emails this campaign should send
    sent_count: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)


class QueueItem(Base):
    __tablename__ = "queue_items"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    campaign_id: Mapped[int] = mapped_column(ForeignKey("campaigns.id"), index=True)
    contact_id: Mapped[int] = mapped_column(Integer, default=0)
    sender_id: Mapped[int] = mapped_column(Integer, default=0)
    email: Mapped[str] = mapped_column(String, default="")
    subject: Mapped[str] = mapped_column(String, default="")
    body_html: Mapped[str] = mapped_column(Text, default="")
    status: Mapped[str] = mapped_column(String, default="queued")
    unsub_token: Mapped[str] = mapped_column(String, default="", index=True)
    error: Mapped[str] = mapped_column(String, default="")
    sent_at: Mapped[datetime] = mapped_column(DateTime, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)


class EventLog(Base):
    __tablename__ = "events"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    campaign_id: Mapped[int] = mapped_column(Integer, index=True, default=0)
    contact_id: Mapped[int] = mapped_column(Integer, default=0)
    sender_id: Mapped[int] = mapped_column(Integer, default=0)
    type: Mapped[str] = mapped_column(String, index=True)  # sent/opened/clicked/replied/failed/unsubscribed
    meta: Mapped[str] = mapped_column(String, default="")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)


class CompanyProfile(Base):
    """One-time company profile. Its details auto-fill the footer of every email."""
    __tablename__ = "company_profile"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)  # single row (id=1)
    company_name: Mapped[str] = mapped_column(String, default="")
    website_url: Mapped[str] = mapped_column(String, default="")
    business_address: Mapped[str] = mapped_column(String, default="")
    sender_name: Mapped[str] = mapped_column(String, default="")
    reply_to_email: Mapped[str] = mapped_column(String, default="")
    completed: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)


class ScraperJob(Base):
    """One scraping job (a batch of domains). Scoped by mode so vendor/client never mix."""
    __tablename__ = "scraper_jobs"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    mode: Mapped[str] = mapped_column(String, default="vendor", index=True)  # vendor / client
    name: Mapped[str] = mapped_column(String, default="")
    source: Mapped[str] = mapped_column(String, default="manual")   # manual / sheet
    status: Mapped[str] = mapped_column(String, default="queued")   # queued/running/stopped/completed
    total: Mapped[int] = mapped_column(Integer, default=0)
    done: Mapped[int] = mapped_column(Integer, default=0)
    emails_found: Mapped[int] = mapped_column(Integer, default=0)
    max_per_domain: Mapped[int] = mapped_column(Integer, default=2)   # keep best N emails per site
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)


class ScraperJobDomain(Base):
    __tablename__ = "scraper_job_domains"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    job_id: Mapped[int] = mapped_column(ForeignKey("scraper_jobs.id"), index=True)
    domain: Mapped[str] = mapped_column(String, index=True)
    status: Mapped[str] = mapped_column(String, default="pending")  # pending/scraping/completed/failed/no_email/duplicate
    source_url: Mapped[str] = mapped_column(String, default="")
    error: Mapped[str] = mapped_column(String, default="")
    is_duplicate: Mapped[bool] = mapped_column(Boolean, default=False)
    vendor_signals: Mapped[str] = mapped_column(String, default="")  # JSON: guest_post, blog, sponsored etc.
    last_checked: Mapped[datetime] = mapped_column(DateTime, nullable=True)


class ScraperResult(Base):
    __tablename__ = "scraper_results"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    job_id: Mapped[int] = mapped_column(ForeignKey("scraper_jobs.id"), index=True)
    domain: Mapped[str] = mapped_column(String, index=True)
    email: Mapped[str] = mapped_column(String, index=True)
    email_type: Mapped[str] = mapped_column(String, default="domain_email")  # domain_email / free_provider_email
    confidence: Mapped[str] = mapped_column(String, default="medium")        # high / medium / low
    source_url: Mapped[str] = mapped_column(String, default="")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

class OutreachEntry(Base):
    """Campaign sheet — unique emails to send, with live status tracking."""
    __tablename__ = "outreach_entries"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    mode: Mapped[str] = mapped_column(String, default="vendor", index=True)
    email: Mapped[str] = mapped_column(String, index=True)
    domain: Mapped[str] = mapped_column(String, default="")
    email_type: Mapped[str] = mapped_column(String, default="domain_email")
    confidence: Mapped[str] = mapped_column(String, default="medium")
    source_url: Mapped[str] = mapped_column(String, default="")
    # Status tracking
    status: Mapped[str] = mapped_column(String, default="pending")  # pending/sent/opened/replied/bounced/unsubscribed
    sent_at: Mapped[datetime] = mapped_column(DateTime, nullable=True)
    opened_at: Mapped[datetime] = mapped_column(DateTime, nullable=True)
    replied_at: Mapped[datetime] = mapped_column(DateTime, nullable=True)
    sender_email: Mapped[str] = mapped_column(String, default="")  # which sender sent this
    subject: Mapped[str] = mapped_column(String, default="")
    days_since_sent: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
