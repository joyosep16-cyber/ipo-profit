from io import BytesIO

import pandas as pd

_COL_MAP = {
    "sub_start": "청약 시작일",
    "date": "청약 종료일",
    "stock_name": "종목명",
    "broker": "증권사",
    "ipo_price": "공모가",
    "sub_type": "청약방식",
    "sub_result": "당첨 여부",
    "sell_date": "상장일",
    "sell_price": "매도가",
    "profit": "수익",
    "quantity": "수량",
    "return_rate": "수익률(%)",
    "memo": "메모",
}


def export_to_excel(records: list) -> bytes:
    try:
        if not records:
            return b""
        df = pd.DataFrame(records)
        cols = [c for c in _COL_MAP if c in df.columns]
        df = df[cols].rename(columns=_COL_MAP)
        buf = BytesIO()
        df.to_excel(buf, index=False, engine="openpyxl")

        from openpyxl import load_workbook
        buf.seek(0)
        wb = load_workbook(buf)
        ws = wb.active
        for col_cells in ws.columns:
            max_len = 0
            col_letter = col_cells[0].column_letter
            for cell in col_cells:
                if cell.value is not None:
                    # 한글은 영문 대비 약 1.8배 너비
                    text = str(cell.value)
                    cell_len = sum(1.8 if ord(c) > 127 else 1 for c in text)
                    max_len = max(max_len, cell_len)
            ws.column_dimensions[col_letter].width = max_len + 2

        out = BytesIO()
        wb.save(out)
        return out.getvalue()
    except Exception:
        return b""


def import_from_excel(file) -> list[dict]:
    try:
        df = pd.read_excel(file, engine="openpyxl")
    except Exception as e:
        raise ValueError(f"엑셀 파일을 읽을 수 없습니다: {e}") from e
    reverse = {v: k for k, v in _COL_MAP.items()}
    df = df.rename(columns=reverse)
    records = []
    for _, row in df.iterrows():
        record = {}
        for k in _COL_MAP:
            if k not in row or not pd.notna(row[k]):
                continue
            val = row[k]
            if isinstance(val, str) and not val.strip():
                continue
            if k in ("date", "sub_start", "sell_date"):
                try:
                    val = pd.to_datetime(val).date()
                except Exception:
                    raise ValueError(f"날짜 형식을 인식할 수 없습니다: '{val}'")
            record[k] = val
        if record:
            records.append(record)
    return records
