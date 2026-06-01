"""기업명 정규화 (Entity Normalization).

38커뮤니케이션 종목명과 DART 기업명이 다를 수 있어
('(주)피스피스스튜디오' vs '피스피스스튜디오')
양쪽에서 접두어·특수문자·공백을 제거하고 소문자로 비교한다.
"""
import re

# 제거할 접두어/접미어 패턴 (순서대로 치환)
_PREFIX_RE = re.compile(
    r"주식회사|㈜|\(주\)|\( ?주 ?\)|\(유\)|\( ?유 ?\)|코스닥|코스피|유가증권",
    re.IGNORECASE,
)
# 남은 특수문자·공백 제거
_CLEAN_RE = re.compile(r"[\s\(\)（）\.\-_&·,·]")


def normalize(name: str) -> str:
    """'(주)피스피스스튜디오' → '피스피스스튜디오' (소문자, 특수문자 제거)."""
    if not name:
        return ""
    name = _PREFIX_RE.sub("", name)
    name = _CLEAN_RE.sub("", name)
    return name.lower().strip()


def is_same_company(name_a: str, name_b: str) -> bool:
    """두 기업명이 정규화 후 동일한지 판정.

    완전 일치 또는 한쪽이 다른 쪽에 포함되면 동일로 간주.
    예) '피스피스스튜디오' vs '㈜피스피스스튜디오' → True
    """
    na, nb = normalize(name_a), normalize(name_b)
    if not na or not nb:
        return False
    if na == nb:
        return True
    # 부분 포함 매칭은 '의미 있는 길이(2자 이상)'일 때만 허용.
    # ('n' 이 'nh스팩33호'에 매칭되는 등 1글자 오매칭 방지)
    shorter = min(len(na), len(nb))
    if shorter < 2:
        return False
    return na in nb or nb in na
