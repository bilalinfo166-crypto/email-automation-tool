"""Database setup + the Sender table (all sender details live here)."""
from datetime import datetime, date
from sqlalchemy import create_engine, String, Integer, Boolean, DateTime, Date, Text, inspect, text, event, UniqueConstraint
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, sessionmaker
from .config import settings

engine = create_engine(
    settings.DATABASE_URL,
    # timeout = how long a connection waits for a write lock before erroring
    connect_args={"check_same_thread": False, "timeout": 30},
    # SQLAlchemy's default pool for SQLite is 5 connections + 10 overflow = 15
    # TOTAL for the whole app. That is nowhere near enough here: the blog
    # research engine alone runs a 50-worker pool where every worker opens its
    # own session, and the dashboard fires a dozen parallel calls on load. Once
    # all 15 were taken, every other request — including "start a new scrape" —
    # sat waiting the full 30s pool timeout, silently. That's what made the app
    # work fine sometimes and hang for minutes other times.
    # SQLite connections are cheap, and WAL lets them read in parallel.
    pool_size=30,
    max_overflow=70,      # 100 total
    pool_timeout=10,      # and fail loudly instead of hanging if we ever hit it
    pool_recycle=1800,
)


@event.listens_for(engine, "connect")
def _sqlite_pragmas(dbapi_conn, _rec):
    """WAL + busy timeout so parallel scraper threads don't hit 'database is locked'."""
    try:
        cur = dbapi_conn.cursor()
        cur.execute("PRAGMA journal_mode=WAL")
        cur.execute("PRAGMA busy_timeout=8000")    # fail loudly in 8s, don't hang for 30
        cur.execute("PRAGMA synchronous=NORMAL")   # safe with WAL, much faster
        cur.execute("PRAGMA wal_autocheckpoint=400")   # checkpoint sooner (~1.6 MB)
        cur.execute("PRAGMA journal_size_limit=16777216")  # and shrink the file back to <=16 MB
        cur.close()
    except Exception:
        pass


SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False)


class Base(DeclarativeBase):
    pass


class Sender(Base):
    __tablename__ = "senders"
    # A Gmail address is unique PER MODE, not globally — the same inbox can be a
    # sender in more than one dashboard (e.g. client + blog), each row keeping
    # its own counters so the dashboards' data stays separate.
    __table_args__ = (
        UniqueConstraint("email", "mode", name="uq_sender_email_mode"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    email: Mapped[str] = mapped_column(String, index=True)
    name: Mapped[str] = mapped_column(String, default="")
    mode: Mapped[str] = mapped_column(String, default="vendor")  # vendor / client / blog
    method: Mapped[str] = mapped_column(String)          # "oauth" or "app_password"

    # secrets (encrypted). Only one is used depending on method.
    oauth_token: Mapped[str] = mapped_column(Text, default="")     # encrypted JSON
    app_password: Mapped[str] = mapped_column(Text, default="")    # encrypted 16-char code

    # settings + live stats (the "sender details")
    daily_cap: Mapped[int] = mapped_column(Integer, default=150)
    warmup: Mapped[bool] = mapped_column(Boolean, default=True)
    warmup_day: Mapped[int] = mapped_column(Integer, default=0)          # days into warmup ramp
    warmup_sent_today: Mapped[int] = mapped_column(Integer, default=0)   # warmup emails sent today
    status: Mapped[str] = mapped_column(String, default="warming")  # warming / warmed / paused
    health: Mapped[int] = mapped_column(Integer, default=40)

    sent_today: Mapped[int] = mapped_column(Integer, default=0)
    total_sent: Mapped[int] = mapped_column(Integer, default=0)
    replies: Mapped[int] = mapped_column(Integer, default=0)
    failed: Mapped[int] = mapped_column(Integer, default=0)
    opened: Mapped[int] = mapped_column(Integer, default=0)

    last_send_date: Mapped[date] = mapped_column(Date, default=date.today)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)


def _migrate():
    """Add any newly-introduced columns to existing tables (SQLite ADD COLUMN)."""
    insp = inspect(engine)
    tables = set(insp.get_table_names())
    with engine.begin() as conn:
        for table in Base.metadata.sorted_tables:
            if table.name not in tables:
                continue
            have = {c["name"] for c in insp.get_columns(table.name)}
            for col in table.columns:
                if col.name in have:
                    continue
                coltype = col.type.compile(dialect=engine.dialect)
                default = ""
                arg = getattr(col.default, "arg", None) if col.default is not None else None
                if arg is not None and not callable(arg):
                    if isinstance(arg, bool):
                        default = f" DEFAULT {1 if arg else 0}"
                    elif isinstance(arg, (int, float)):
                        default = f" DEFAULT {arg}"
                    elif isinstance(arg, str):
                        default = f" DEFAULT '{arg}'"
                conn.execute(text(f'ALTER TABLE {table.name} ADD COLUMN {col.name} {coltype}{default}'))

    # Enforce one email per mode at the DB level. A plain create_all won't add
    # this to an already-existing table, so we do it here: first remove any
    # legacy duplicate rows (keeping the earliest id), then build the unique
    # index. Once the index exists, every future insert of a duplicate fails at
    # the database, so no code path can reintroduce them.
    if "outreach_entries" in tables:
        with engine.connect() as conn:
            pragma_idx = [r[1] for r in conn.exec_driver_sql(
                "PRAGMA index_list('outreach_entries')").fetchall()]
        has_uq = "uq_outreach_mode_email" in pragma_idx

        if not has_uq:
            with engine.begin() as conn:
                removed = conn.exec_driver_sql(
                    "DELETE FROM outreach_entries WHERE id NOT IN ("
                    "  SELECT MIN(id) FROM outreach_entries GROUP BY mode, lower(email))"
                ).rowcount
            with engine.begin() as conn:
                conn.exec_driver_sql(
                    "CREATE UNIQUE INDEX IF NOT EXISTS uq_outreach_mode_email "
                    "ON outreach_entries (mode, email)")
            print(f"[DB] Removed {removed} duplicate outreach row(s); unique "
                  f"(mode,email) index is now enforced."
                  if removed else
                  "[DB] Added unique (mode,email) index on outreach_entries.")

    # Senders: the old schema made email globally unique, which blocked using
    # the same Gmail in two dashboards (client + blog). Drop that index and add
    # a (email, mode) unique index instead, so an address can exist once per
    # mode with its own counters.
    if "senders" in tables:
        with engine.connect() as conn:
            sidx = [(r[1], bool(r[2])) for r in conn.exec_driver_sql(
                "PRAGMA index_list('senders')").fetchall()]
        has_new = any(n == "uq_sender_email_mode" for n, _ in sidx)
        if not has_new:
            with engine.begin() as conn:
                # Drop any old UNIQUE index that covers email alone.
                for name, uniq in sidx:
                    if not uniq:
                        continue
                    cols = [r[2] for r in conn.exec_driver_sql(
                        f"PRAGMA index_info('{name}')").fetchall()]
                    if cols == ["email"]:
                        try:
                            conn.exec_driver_sql(f'DROP INDEX IF EXISTS "{name}"')
                        except Exception:
                            pass
                conn.exec_driver_sql(
                    "CREATE UNIQUE INDEX IF NOT EXISTS uq_sender_email_mode "
                    "ON senders (email, mode)")
            print("[DB] Senders: email is now unique per-mode "
                  "(same address can be used in more than one dashboard).")


def checkpoint_wal(mode: str = "TRUNCATE"):
    """Fold the -wal file back into the database.

    SQLite can only checkpoint when nothing is holding a transaction open. The
    scraper keeps a session alive for the length of a job, so checkpoints kept
    getting skipped and warmwire.db-wal grew to ~50 MB against a 13 MB
    database. Every read then had to scan that whole WAL index, which is why
    the dashboard got slower and slower until requests simply timed out.
    """
    try:
        with engine.connect() as conn:
            row = conn.exec_driver_sql(f"PRAGMA wal_checkpoint({mode})").fetchone()
        return row
    except Exception as e:
        return ("error", str(e))


def start_wal_maintenance(interval_seconds: int = 60):
    """Keep the WAL small in the background, so it can never run away again."""
    import threading, time

    def _loop():
        while True:
            time.sleep(interval_seconds)
            checkpoint_wal("PASSIVE")

    threading.Thread(target=_loop, daemon=True).start()


def init_db():
    # Import ALL models so they register with Base before create_all.
    # Without this, new tables (like blog research) never get created.
    from . import crm_models  # noqa: F401
    Base.metadata.create_all(bind=engine)
    try:
        _migrate()
    except Exception as e:
        print("migration warning:", e)
    # Start clean: nothing else is connected yet, so this is the one moment a
    # full TRUNCATE checkpoint is guaranteed to work.
    print("[DB] WAL checkpoint at startup:", checkpoint_wal("TRUNCATE"))
    start_wal_maintenance()


# FastAPI dependency: hands a DB session to each request
def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
