import logging
import os
from datetime import datetime, timezone

import requests

from utils.calculator import format_krw

logger = logging.getLogger(__name__)


def _webhook_url() -> str:
    url = os.getenv("DISCORD_WEBHOOK_URL", "")
    if not url:
        try:
            from database import get_setting
            url = get_setting("DISCORD_WEBHOOK_URL") or ""
        except Exception:
            pass
    return url


def _send(embed: dict) -> None:
    url = _webhook_url()
    if not url:
        logger.warning("DISCORD_WEBHOOK_URL이 설정되지 않아 알림을 건너뜁니다.")
        return
    try:
        resp = requests.post(url, json={"embeds": [embed]}, timeout=10)
        if resp.status_code not in (200, 204):
            logger.warning(f"Discord 웹훅 응답 오류: HTTP {resp.status_code} — {resp.text[:200]}")
    except Exception as e:
        logger.error(f"Discord 알림 전송 실패: {e}")




def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def send_record_added(record: dict) -> None:
    rr = record.get("return_rate")
    _send({
        "title": "🆕 새 공모주 추가",
        "color": 0x00B894,
        "fields": [
            {"name": "📌 종목", "value": record["stock_name"], "inline": True},
            {"name": "🏦 증권사", "value": record["broker"], "inline": True},
            {"name": "💰 공모가", "value": f"₩{record['ipo_price']:,}", "inline": True},
            {"name": "📋 청약방식", "value": record["sub_type"], "inline": True},
            {"name": "🎯 당첨여부", "value": record.get("sub_result", "당첨"), "inline": True},
            {"name": "📦 수량", "value": f"{record['quantity']}주", "inline": True},
            {"name": "💵 수익", "value": format_krw(record["profit"], signed=True), "inline": True},
            {"name": "📈 수익률", "value": f"{rr:.1f}%" if rr is not None else "-", "inline": True},
            {"name": "📅 날짜", "value": str(record["date"]), "inline": True},
        ],
        "timestamp": _now_iso(),
    })


def send_record_updated(old: dict, new: dict) -> None:
    _send({
        "title": "✏️ 공모주 수정",
        "color": 0x0984E3,
        "fields": [
            {"name": "📌 종목", "value": new["stock_name"], "inline": True},
            {"name": "📅 날짜", "value": str(new["date"]), "inline": True},
            {"name": "🎯 당첨여부", "value": new.get("sub_result", "당첨"), "inline": True},
            {"name": "💵 수익 (이전)", "value": format_krw(old["profit"], signed=True), "inline": True},
            {"name": "💵 수익 (변경)", "value": format_krw(new["profit"], signed=True), "inline": True},
        ],
        "timestamp": _now_iso(),
    })


def send_record_deleted(record: dict) -> None:
    _send({
        "title": "🗑️ 공모주 삭제",
        "color": 0xD63031,
        "fields": [
            {"name": "📌 종목", "value": record["stock_name"], "inline": True},
            {"name": "🏦 증권사", "value": record["broker"], "inline": True},
            {"name": "🎯 당첨여부", "value": record.get("sub_result", "당첨"), "inline": True},
            {"name": "💵 수익", "value": format_krw(record["profit"], signed=True), "inline": True},
            {"name": "📅 날짜", "value": str(record["date"]), "inline": True},
        ],
        "timestamp": _now_iso(),
    })


def send_high_return_alert(record: dict) -> None:
    rr = record.get("return_rate")
    if rr is None:
        return
    _send({
        "title": "🎉 고수익 달성!",
        "color": 0xFDCB6E,
        "description": f"**{record['stock_name']}** 에서 **{rr:.1f}%** 수익률 달성!",
        "fields": [
            {"name": "📌 종목", "value": record["stock_name"], "inline": True},
            {"name": "🏦 증권사", "value": record["broker"], "inline": True},
            {"name": "💵 수익", "value": format_krw(record["profit"], signed=True), "inline": True},
            {"name": "📈 수익률", "value": f"{rr:.1f}%", "inline": True},
        ],
        "timestamp": _now_iso(),
    })


def send_monthly_summary(year: int, month: int, stats: dict) -> None:
    if stats["count"] == 0:
        return
    best = stats.get("best_record")
    best_str = (
        f"{best['stock_name']} ({format_krw(best['profit'], signed=True)})" if best else "-"
    )
    _send({
        "title": f"📊 {year}년 {month}월 공모주 수익 요약",
        "color": 0x6C5CE7,
        "fields": [
            {"name": "📦 청약 종목 수", "value": f"{stats['count']}개", "inline": True},
            {"name": "💵 총 수익", "value": format_krw(stats["total_profit"], signed=True), "inline": True},
            {"name": "🏆 최고 수익 종목", "value": best_str, "inline": False},
        ],
        "timestamp": _now_iso(),
    })


def send_watchlist_reminder(item: dict) -> None:
    _send({
        "title": "⏰ 청약 마감 내일!",
        "color": 0xFFA07A,
        "fields": [
            {"name": "📌 종목",     "value": item["stock_name"],                                           "inline": True},
            {"name": "🏦 증권사",   "value": item.get("broker") or "-",                                   "inline": True},
            {"name": "📅 청약 마감", "value": str(item["sub_end"]) if item.get("sub_end") else "-",        "inline": True},
            {"name": "💰 공모가",   "value": f"₩{item['ipo_price']:,}" if item.get("ipo_price") else "-", "inline": True},
        ],
        "timestamp": _now_iso(),
    })


def send_watchlist_missed(item: dict) -> None:
    _send({
        "title": "❌ 청약 미신청 처리됨",
        "color": 0x808080,
        "fields": [
            {"name": "📌 종목",     "value": item["stock_name"],                                    "inline": True},
            {"name": "🏦 증권사",   "value": item.get("broker") or "-",                            "inline": True},
            {"name": "📅 청약 마감", "value": str(item["sub_end"]) if item.get("sub_end") else "-", "inline": True},
        ],
        "timestamp": _now_iso(),
    })


def send_app_started(public_url: str) -> None:
    _send({
        "title": "🚀 공모주 수익 관리 앱 시작",
        "color": 0x55EFC4,
        "description": "앱이 실행되었습니다. 아래 링크로 접속하세요.",
        "fields": [
            {"name": "🔗 접속 URL", "value": public_url, "inline": False},
        ],
        "timestamp": _now_iso(),
    })
