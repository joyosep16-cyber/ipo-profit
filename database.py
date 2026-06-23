import os
from datetime import datetime
from typing import Optional

from sqlalchemy import (
    Column, Integer, String, Float, Date, DateTime, Text,
    create_engine, extract, func, select, text
)
from sqlalchemy.orm import DeclarativeBase, Session

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DATA_DIR = os.path.join(BASE_DIR, "data")
os.makedirs(DATA_DIR, exist_ok=True)
DB_PATH = os.path.join(DATA_DIR, "ipo.db")


def _build_engine():
    db_url = os.getenv("DATABASE_URL", "").strip()
    if db_url:
        return create_engine(db_url, echo=False)
    return create_engine(
        f"sqlite:///{DB_PATH}",
        echo=False,
        connect_args={"check_same_thread": False},
    )


engine = _build_engine()


class Base(DeclarativeBase):
    pass


class IPORecord(Base):
    __tablename__ = "ipo_records"

    id = Column(Integer, primary_key=True, autoincrement=True)
    date = Column(Date, nullable=False)
    sub_start = Column(Date, nullable=True)
    stock_name = Column(String(100), nullable=False)
    broker = Column(String(50), nullable=False)
    ipo_price = Column(Integer, nullable=False)
    sub_type = Column(String(10), nullable=False)
    sub_result = Column(String(10), default="당첨")
    profit = Column(Integer, default=0)
    quantity = Column(Integer, default=0)
    sell_date = Column(Date, nullable=True)
    sell_price = Column(Integer, default=0)
    return_rate = Column(Float, nullable=True)
    memo = Column(Text, default="")
    created_at = Column(DateTime, default=datetime.now)
    updated_at = Column(DateTime, default=datetime.now)


class AppSetting(Base):
    __tablename__ = "app_settings"

    key = Column(String(100), primary_key=True)
    value = Column(Text, default="")


class YearlyNote(Base):
    __tablename__ = "yearly_notes"

    year = Column(Integer, primary_key=True)
    note = Column(Text, default="")


class NotificationLog(Base):
    __tablename__ = "notification_log"

    id = Column(Integer, primary_key=True, autoincrement=True)
    type = Column(String(50), nullable=False)
    ref_key = Column(String(50), nullable=True)
    sent_at = Column(DateTime, default=datetime.now)


class WatchlistItem(Base):
    __tablename__ = "watchlist"

    id           = Column(Integer, primary_key=True, autoincrement=True)
    stock_name   = Column(String(100), nullable=False)
    broker       = Column(String(50),  nullable=True)
    sub_start    = Column(Date, nullable=True)
    sub_end      = Column(Date, nullable=True)
    listing_date = Column(Date, nullable=True)
    ipo_price    = Column(Integer, nullable=True)
    memo         = Column(Text, default="")
    status       = Column(String(20), default="관심")
    created_at   = Column(DateTime, default=datetime.now)
    # 공모주 분석 점수 연동 (analyzer 엔진 결과)
    analysis_score = Column(Integer, nullable=True)    # 총점 (스팩/리츠는 NULL)
    analysis_grade = Column(String(20), nullable=True) # 추천 등급
    data_quality   = Column(String(30), nullable=True) # 🟢/🟡/🔴 데이터 신뢰도
    otc_premium    = Column(Float, nullable=True)      # 장외 괴리율(%)
    analyzed_at    = Column(DateTime, nullable=True)   # 분석 시각


# watchlist 분석 점수 컬럼 (SQLite/PG 공통 정의)
_WATCHLIST_SCORE_COLUMNS = [
    ("analysis_score", "INTEGER"),
    ("analysis_grade", "VARCHAR(20)"),
    ("data_quality",   "VARCHAR(30)"),
    ("otc_premium",    "DOUBLE PRECISION"),  # SQLite는 타입 무시(동적), PG는 실수형
    ("analyzed_at",    "TIMESTAMP"),
]


def _sqlite_migrate() -> None:
    """컬럼 존재 여부를 먼저 확인한 뒤 없을 때만 ADD COLUMN — 멱등 실행 보장."""
    _IPO_COLUMNS = [
        ("sell_price", "INTEGER DEFAULT 0"),
        ("sub_result", "TEXT DEFAULT '당첨'"),
        ("sell_date",  "DATE"),
        ("sub_start",  "DATE"),
    ]
    with engine.connect() as conn:
        existing = {row[1] for row in conn.execute(text("PRAGMA table_info(ipo_records)"))}
        for col, defn in _IPO_COLUMNS:
            if col not in existing:
                conn.execute(text(f"ALTER TABLE ipo_records ADD COLUMN {col} {defn}"))

        # watchlist 분석 점수 컬럼 (SQLite는 타입 표기 단순화)
        wl_existing = {row[1] for row in conn.execute(text("PRAGMA table_info(watchlist)"))}
        for col, _defn in _WATCHLIST_SCORE_COLUMNS:
            if col not in wl_existing:
                conn.execute(text(f"ALTER TABLE watchlist ADD COLUMN {col}"))
        conn.commit()


def _pg_migrate() -> None:
    """PostgreSQL(Neon): create_all 은 신규 컬럼을 추가하지 않으므로 명시 ALTER.
    ADD COLUMN IF NOT EXISTS 로 멱등 실행."""
    with engine.connect() as conn:
        for col, defn in _WATCHLIST_SCORE_COLUMNS:
            conn.execute(text(
                f"ALTER TABLE watchlist ADD COLUMN IF NOT EXISTS {col} {defn}"))
        conn.commit()


def init_db() -> None:
    Base.metadata.create_all(engine)
    if "sqlite" in str(engine.url):
        _sqlite_migrate()
    else:
        _pg_migrate()


def _to_dict(r: IPORecord) -> dict:
    return {
        "id": r.id,
        "date": r.date,
        "sub_start": r.sub_start,
        "stock_name": r.stock_name,
        "broker": r.broker,
        "ipo_price": r.ipo_price,
        "sub_type": r.sub_type,
        "sub_result": r.sub_result or "당첨",
        "profit": r.profit,
        "quantity": r.quantity,
        "sell_date": r.sell_date,
        "sell_price": r.sell_price,
        "return_rate": r.return_rate,
        "memo": r.memo,
        "created_at": r.created_at,
        "updated_at": r.updated_at,
    }


def get_setting(key: str, default: str = "") -> str:
    with Session(engine) as session:
        rec = session.get(AppSetting, key)
        return rec.value if (rec and rec.value is not None) else default


def set_setting(key: str, value: str) -> None:
    with Session(engine) as session:
        rec = session.get(AppSetting, key)
        if rec:
            rec.value = value
        else:
            session.add(AppSetting(key=key, value=value))
        session.commit()


def add_record(data: dict) -> dict:
    with Session(engine) as session:
        record = IPORecord(**data)
        session.add(record)
        session.commit()
        session.refresh(record)
        return _to_dict(record)


def update_record(record_id: int, data: dict) -> Optional[dict]:
    with Session(engine) as session:
        record = session.get(IPORecord, record_id)
        if not record:
            return None
        for key, value in data.items():
            setattr(record, key, value)
        record.updated_at = datetime.now()
        session.commit()
        session.refresh(record)
        return _to_dict(record)


def delete_record(record_id: int) -> Optional[dict]:
    with Session(engine) as session:
        record = session.get(IPORecord, record_id)
        if not record:
            return None
        data = _to_dict(record)
        session.delete(record)
        session.commit()
        return data


def get_record_by_id(record_id: int) -> Optional[dict]:
    with Session(engine) as session:
        record = session.get(IPORecord, record_id)
        return _to_dict(record) if record else None


def get_records(year: Optional[int] = None) -> list[dict]:
    with Session(engine) as session:
        stmt = select(IPORecord).order_by(IPORecord.date.desc())
        if year:
            stmt = stmt.where(extract("year", IPORecord.date) == year)
        return [_to_dict(r) for r in session.execute(stmt).scalars().all()]


def get_available_years() -> list[int]:
    with Session(engine) as session:
        stmt = (
            select(extract("year", IPORecord.date).label("year"))
            .distinct()
            .order_by(extract("year", IPORecord.date).desc())
        )
        return [int(y) for y in session.execute(stmt).scalars().all()]


def get_yearly_summary() -> list[dict]:
    with Session(engine) as session:
        stmt = (
            select(
                extract("year", IPORecord.date).label("year"),
                func.sum(IPORecord.profit).label("total_profit"),
                func.count(IPORecord.id).label("count"),
                func.avg(IPORecord.return_rate).label("avg_return_rate"),
            )
            .group_by(extract("year", IPORecord.date))
            .order_by(extract("year", IPORecord.date).desc())
        )
        results = []
        for row in session.execute(stmt).all():
            year = int(row.year)
            note_rec = session.get(YearlyNote, year)
            results.append({
                "year": year,
                "total_profit": int(row.total_profit or 0),
                "count": int(row.count),
                "avg_return_rate": float(row.avg_return_rate) if row.avg_return_rate else None,
                "note": note_rec.note if note_rec else "",
            })
        return results


def upsert_yearly_note(year: int, note: str) -> None:
    with Session(engine) as session:
        existing = session.get(YearlyNote, year)
        if existing:
            existing.note = note
        else:
            session.add(YearlyNote(year=year, note=note))
        session.commit()


def get_monthly_stats(year: int, month: int) -> dict:
    with Session(engine) as session:
        stmt = select(IPORecord).where(
            extract("year", IPORecord.date) == year,
            extract("month", IPORecord.date) == month,
        )
        records = session.execute(stmt).scalars().all()
        if not records:
            return {"count": 0, "total_profit": 0, "best_record": None}
        best = max(records, key=lambda r: r.profit)
        return {
            "count": len(records),
            "total_profit": sum(r.profit for r in records),
            "best_record": _to_dict(best),
        }


def is_monthly_summary_sent(year: int, month: int) -> bool:
    ref_key = f"{year}-{month:02d}"
    with Session(engine) as session:
        stmt = select(NotificationLog).where(
            NotificationLog.type == "monthly_summary",
            NotificationLog.ref_key == ref_key,
        )
        return session.execute(stmt).scalar() is not None


def log_notification(notification_type: str, ref_key: str = None) -> None:
    with Session(engine) as session:
        session.add(NotificationLog(type=notification_type, ref_key=ref_key))
        session.commit()


def get_sell_tax_schedule() -> list[dict]:
    """매도 증권거래세율 자동표 조회 [{"start":"YYYY-MM-DD","rate":0.15}, ...].
    설정이 없으면 코드 내장 기본표를 시드로 반환."""
    import json
    from utils.constants import SELL_TAX_RATE_SCHEDULE
    raw = get_setting("SELL_TAX_SCHEDULE")
    if raw:
        try:
            data = json.loads(raw)
            rows = [{"start": str(d["start"]), "rate": float(d["rate"])}
                    for d in data if d.get("start") not in (None, "")]
            if rows:
                return rows
        except (ValueError, TypeError, KeyError):
            pass
    return [{"start": s, "rate": r} for s, r in SELL_TAX_RATE_SCHEDULE]


def set_sell_tax_schedule(rows: list) -> None:
    """매도 세율 자동표 저장. rows: [{"start","rate"}, ...] (유효 행만 저장)."""
    import json
    clean = []
    for r in rows:
        start = r.get("start") if isinstance(r, dict) else None
        rate = r.get("rate") if isinstance(r, dict) else None
        if start in (None, "") or rate in (None, ""):
            continue
        try:
            clean.append({"start": str(start)[:10], "rate": float(rate)})
        except (ValueError, TypeError):
            continue
    set_setting("SELL_TAX_SCHEDULE", json.dumps(clean, ensure_ascii=False))


def is_analysis_alerted(ref_key: str) -> bool:
    """공모주 분석 자동알림이 이미 발송된 종목인지 확인 (중복 발송 방지).
    ref_key 는 38커뮤니케이션 고유번호(no) 또는 종목명."""
    return is_notified("analysis_alert", ref_key)


def is_notified(notification_type: str, ref_key: str) -> bool:
    """특정 type+ref_key 알림이 이미 발송됐는지 확인 (중복 발송 방지 범용 헬퍼)."""
    with Session(engine) as session:
        stmt = select(NotificationLog).where(
            NotificationLog.type == notification_type,
            NotificationLog.ref_key == str(ref_key),
        )
        return session.execute(stmt).scalar() is not None


# ── 관심 목록 CRUD ─────────────────────────────────────────────────────────────

def _watchlist_to_dict(w: WatchlistItem) -> dict:
    return {
        "id":           w.id,
        "stock_name":   w.stock_name,
        "broker":       w.broker,
        "sub_start":    w.sub_start,
        "sub_end":      w.sub_end,
        "listing_date": w.listing_date,
        "ipo_price":    w.ipo_price,
        "memo":         w.memo or "",
        "status":       w.status or "관심",
        "created_at":   w.created_at,
        "analysis_score": w.analysis_score,
        "analysis_grade": w.analysis_grade,
        "data_quality":   w.data_quality,
        "otc_premium":    w.otc_premium,
        "analyzed_at":    w.analyzed_at,
    }


def add_watchlist_item(data: dict) -> dict:
    with Session(engine) as session:
        item = WatchlistItem(**data)
        session.add(item)
        session.commit()
        session.refresh(item)
        return _watchlist_to_dict(item)


def get_watchlist(status: Optional[str] = None) -> list[dict]:
    with Session(engine) as session:
        stmt = select(WatchlistItem).order_by(WatchlistItem.sub_end.is_(None).asc(), WatchlistItem.sub_end.asc())
        if status:
            stmt = stmt.where(WatchlistItem.status == status)
        return [_watchlist_to_dict(w) for w in session.execute(stmt).scalars().all()]


def update_watchlist_status(item_id: int, status: str) -> None:
    with Session(engine) as session:
        w = session.get(WatchlistItem, item_id)
        if w:
            w.status = status
            session.commit()


def delete_watchlist_item(item_id: int) -> None:
    with Session(engine) as session:
        w = session.get(WatchlistItem, item_id)
        if w:
            session.delete(w)
            session.commit()
