"""Database setup + the Sender table (all sender details live here)."""
from datetime import datetime, date
from sqlalchemy import create_engine, String, Integer, Boolean, DateTime, Date, Text, inspect, text, event
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, sessionmaker
from .config import settings

engine = create_engine(
    settings.DATABASE_URL, connect_args={"check_same_thread": False}
)


@event.listens_for(engine, "connect")
def _sqlite_pragmas(dbapi_conn, _rec):
    """WAL + busy timeout so parallel scraper threads don't hit 'database is locked'."""
    try:
        cur = dbapi_conn.cursor()
        cur.execute("PRAGMA journal_mode=WAL")
        cur.execute("PRAGMA busy_timeout=8000")
        cur.close()
    except Exception:
        pass


SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False)


class Base(DeclarativeBase):
    pass


class Sender(Base):
    __tablename__ = "senders"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    email: Mapped[str] = mapped_column(String, unique=True, index=True)
    name: Mapped[str] = mapped_column(String, default="")
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


def init_db():
    Base.metadata.create_all(bind=engine)
    try:
        _migrate()
    except Exception as e:
        print("migration warning:", e)


# FastAPI dependency: hands a DB session to each request
def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
