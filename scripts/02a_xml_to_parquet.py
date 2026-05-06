"""
02a: raw XML → interim parquet 변환

- 입력: data/raw/{YYYY}/{YYYYMM}_{CC}.xml.gz (56,852개)
- 출력: data/interim/fact_trade_{YYYY}.parquet
        data/interim/fact_total_{YYYY}.parquet
- 정책: 연도 단위 idempotent. 이미 있으면 skip. --force 로 재생성.

실행 예:
  python scripts\02a_xml_to_parquet.py
  python scripts\02a_xml_to_parquet.py --year 2024
  python scripts\02a_xml_to_parquet.py --force
"""

from __future__ import annotations
import argparse
import gzip
import logging
import re
import sys
import xml.etree.ElementTree as ET
from datetime import datetime
from pathlib import Path

import pandas as pd
from tqdm import tqdm


# ──────────────────────────────────────────────
# 경로 설정
# ──────────────────────────────────────────────

PROJECT_ROOT = Path(__file__).resolve().parent.parent
RAW_DIR = PROJECT_ROOT / "data" / "raw"
INTERIM_DIR = PROJECT_ROOT / "data" / "interim"
LOG_DIR = PROJECT_ROOT / "logs"

INTERIM_DIR.mkdir(parents=True, exist_ok=True)
LOG_DIR.mkdir(exist_ok=True)


# 로그
LOG_PATH = LOG_DIR / f"load_xml_{datetime.now().strftime('%Y%m%d_%H%M%S')}.log"
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[
        logging.FileHandler(LOG_PATH, encoding="utf-8"),
        logging.StreamHandler(sys.stdout),
    ],
)
logger = logging.getLogger(__name__)


# 파일명 패턴: {YYYYMM}_{CC}.xml.gz
FNAME_RE = re.compile(r"^(\d{6})_([A-Z]{2})\.xml\.gz$")


# ──────────────────────────────────────────────
# XML 파싱
# ──────────────────────────────────────────────

def parse_one_file(xml_gz_path: Path) -> tuple[list[dict], dict | None]:
    """한 파일 파싱. (거래 행 리스트, 총계 행 dict 또는 None) 반환.

    파일명이 결정하는 두 값을 추가한다:
    - cnty_cd: 호출 파라미터 (총계 행의 stat_cd 로 사용)
    - yyyymm:  호출 시기

    raw의 year 필드 형식: "YYYY.MM" (거래 행) 또는 "총계" (총계 행).
    이 함수는 파일명에서 yyyymm을 가져오고 year 필드는 분류용으로만 본다.
    """
    m = FNAME_RE.match(xml_gz_path.name)
    if not m:
        raise ValueError(f"잘못된 파일명: {xml_gz_path.name}")
    yyyymm_str, cnty_cd = m.group(1), m.group(2)
    yyyymm = int(yyyymm_str)
    year = yyyymm // 100
    month = yyyymm % 100

    with gzip.open(xml_gz_path, "rb") as f:
        tree = ET.parse(f)

    root = tree.getroot()

    # 응답 정상성 확인. resultCode != "00" 인 파일(예: XK)은 거래 행 0건이지만
    # 호출 자체는 일어났으니 raw 파일이 존재한다. 거래·총계 모두 비어 있다.
    rc = root.findtext(".//resultCode")
    if rc != "00":
        return [], None

    items = root.findall(".//item")

    # 거래 0건 페어 처리: resultCode=00이지만 items가 비어 있는 경우.
    # 이는 *그 (월, 국가) 조합에 한국 무역 거래가 전혀 없었음*을 의미한다.
    # 이 페어를 fact_total에 0값 행으로 기록해 두면 분석 시 다음을 구분할 수 있다:
    #   (a) 거래 0건이었다 (정상, 작은 무역국)
    #   (b) 데이터 자체가 없다 (수집 실패, XK 등)
    # XK 같은 (b) 케이스는 위 rc != "00" 분기에서 이미 (None, None)으로 처리된다.
    if not items:
        empty_total = {
            "yyyymm": yyyymm,
            "year": year,
            "month": month,
            "stat_cd": cnty_cd,
            "exp_dlr": 0,
            "imp_dlr": 0,
            "exp_wgt": 0,
            "imp_wgt": 0,
            "bal_payments": 0,
        }
        return [], empty_total

    rows = []
    total_row = None

    for it in items:
        d = {child.tag: child.text for child in it}

        # 총계 행 식별: year 필드가 "총계" 또는 hsCd가 "-"
        if d.get("year") == "총계":
            total_row = {
                "yyyymm": yyyymm,
                "year": year,
                "month": month,
                "stat_cd": cnty_cd,  # 파일명에서 가져옴
                "exp_dlr": int(d.get("expDlr") or 0),
                "imp_dlr": int(d.get("impDlr") or 0),
                "exp_wgt": int(d.get("expWgt") or 0),
                "imp_wgt": int(d.get("impWgt") or 0),
                "bal_payments": int(d.get("balPayments") or 0),
            }
            continue

        # 거래 행
        hs10 = (d.get("hsCd") or "").strip()
        rows.append({
            "yyyymm": yyyymm,
            "year": year,
            "month": month,
            "stat_cd": (d.get("statCd") or cnty_cd).strip(),
            "stat_kor": (d.get("statCdCntnKor1") or "").strip(),
            "hs10": hs10,
            "hs2": hs10[:2] if len(hs10) >= 2 else "",
            "hs4": hs10[:4] if len(hs10) >= 4 else "",
            "hs6": hs10[:6] if len(hs10) >= 6 else "",
            "stat_kor_item": (d.get("statKor") or "").strip(),
            "exp_dlr": int(d.get("expDlr") or 0),
            "imp_dlr": int(d.get("impDlr") or 0),
            "exp_wgt": int(d.get("expWgt") or 0),
            "imp_wgt": int(d.get("impWgt") or 0),
            "bal_payments": int(d.get("balPayments") or 0),
        })

    return rows, total_row


# ──────────────────────────────────────────────
# 연도별 처리
# ──────────────────────────────────────────────

# 자료형 명시 (parquet 스키마 안정성)
TRADE_DTYPES = {
    "yyyymm": "int32",
    "year": "int16",
    "month": "int8",
    "stat_cd": "string",
    "stat_kor": "string",
    "hs10": "string",
    "hs2": "string",
    "hs4": "string",
    "hs6": "string",
    "stat_kor_item": "string",
    "exp_dlr": "int64",
    "imp_dlr": "int64",
    "exp_wgt": "int64",
    "imp_wgt": "int64",
    "bal_payments": "int64",
}

TOTAL_DTYPES = {
    "yyyymm": "int32",
    "year": "int16",
    "month": "int8",
    "stat_cd": "string",
    "exp_dlr": "int64",
    "imp_dlr": "int64",
    "exp_wgt": "int64",
    "imp_wgt": "int64",
    "bal_payments": "int64",
}


def process_year(year: int, force: bool = False) -> dict:
    """한 연도 처리. {success, n_files, n_trade_rows, n_total_rows, errors}"""
    year_dir = RAW_DIR / str(year)
    if not year_dir.exists():
        logger.warning(f"연도 디렉토리 없음: {year_dir}")
        return {"success": False, "n_files": 0, "errors": ["dir_not_found"]}

    out_trade = INTERIM_DIR / f"fact_trade_{year}.parquet"
    out_total = INTERIM_DIR / f"fact_total_{year}.parquet"

    if not force and out_trade.exists() and out_total.exists():
        logger.info(f"  [skip] {year} 이미 변환됨 ({out_trade.name})")
        return {"success": True, "n_files": 0, "skipped": True}

    files = sorted(year_dir.glob("*.xml.gz"))
    logger.info(f"  {year}: {len(files)}개 파일 처리 시작")

    all_trade_rows = []
    all_total_rows = []
    errors = []

    for fp in tqdm(files, desc=f"  {year}", unit="file"):
        try:
            trade_rows, total_row = parse_one_file(fp)
            all_trade_rows.extend(trade_rows)
            if total_row is not None:
                all_total_rows.append(total_row)
        except Exception as e:
            errors.append(f"{fp.name}: {e}")
            logger.error(f"  파싱 실패: {fp.name}: {e}")

    # 데이터프레임 생성 + 자료형 캐스팅
    df_trade = pd.DataFrame(all_trade_rows).astype(TRADE_DTYPES) if all_trade_rows else pd.DataFrame()
    df_total = pd.DataFrame(all_total_rows).astype(TOTAL_DTYPES) if all_total_rows else pd.DataFrame()

    # parquet 저장
    if not df_trade.empty:
        df_trade.to_parquet(out_trade, engine="pyarrow", compression="snappy", index=False)
    if not df_total.empty:
        df_total.to_parquet(out_total, engine="pyarrow", compression="snappy", index=False)

    logger.info(
        f"  {year}: 거래 {len(df_trade):,}행, 총계 {len(df_total):,}행, "
        f"실패 {len(errors)}건 → {out_trade.name}, {out_total.name}"
    )

    return {
        "success": True,
        "year": year,
        "n_files": len(files),
        "n_trade_rows": len(df_trade),
        "n_total_rows": len(df_total),
        "n_errors": len(errors),
        "errors": errors,
    }


# ──────────────────────────────────────────────
# 메인
# ──────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--year", type=int, default=None,
                        help="특정 연도만 처리 (기본: 전체)")
    parser.add_argument("--year-from", type=int, default=2007)
    parser.add_argument("--year-to", type=int, default=2026)
    parser.add_argument("--force", action="store_true",
                        help="이미 변환된 연도도 재생성")
    args = parser.parse_args()

    if args.year is not None:
        years = [args.year]
    else:
        years = list(range(args.year_from, args.year_to + 1))

    logger.info("=" * 60)
    logger.info(f"02a: XML → parquet 변환 시작")
    logger.info(f"대상 연도: {years[0]} ~ {years[-1]} ({len(years)}개)")
    logger.info(f"raw 디렉토리: {RAW_DIR}")
    logger.info(f"출력 디렉토리: {INTERIM_DIR}")
    logger.info("=" * 60)

    results = []
    t_start = datetime.now()

    for y in years:
        result = process_year(y, force=args.force)
        results.append(result)

    t_elapsed = (datetime.now() - t_start).total_seconds()

    # 요약
    logger.info("=" * 60)
    logger.info(f"전체 종료. 총 {t_elapsed:.0f}초 ({t_elapsed/60:.1f}분)")
    total_trade = sum(r.get("n_trade_rows", 0) for r in results)
    total_total = sum(r.get("n_total_rows", 0) for r in results)
    total_errors = sum(r.get("n_errors", 0) for r in results)
    logger.info(f"누적 거래 행: {total_trade:,}")
    logger.info(f"누적 총계 행: {total_total:,}")
    logger.info(f"누적 파싱 실패: {total_errors}")
    logger.info(f"상세 로그: {LOG_PATH}")


if __name__ == "__main__":
    main()
