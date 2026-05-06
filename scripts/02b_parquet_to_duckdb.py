"""
02b: interim parquet + status JSON → DuckDB

- 입력: data/interim/fact_trade_{YYYY}.parquet  (20개)
        data/interim/fact_total_{YYYY}.parquet  (20개)
        data/raw/.progress/status_{YYYY}.json   (20개)
- 출력: data/processed/kcsdb.duckdb (3 테이블: fact_trade, fact_total, meta_calls)
- 정책:
    * 기본은 from-scratch 빌드 (기존 .duckdb 파일이 있으면 --overwrite 필요)
    * 인덱스는 미생성 (DuckDB의 컬럼 기반 압축으로 충분히 빠름)
    * 검증 SQL을 마지막에 실행

실행 예:
  python scripts\02b_parquet_to_duckdb.py
  python scripts\02b_parquet_to_duckdb.py --overwrite
"""

from __future__ import annotations
import argparse
import glob
import json
import logging
import sys
from datetime import datetime
from pathlib import Path

import duckdb
import pandas as pd


# ──────────────────────────────────────────────
# 경로 설정
# ──────────────────────────────────────────────

PROJECT_ROOT = Path(__file__).resolve().parent.parent
INTERIM_DIR = PROJECT_ROOT / "data" / "interim"
PROCESSED_DIR = PROJECT_ROOT / "data" / "processed"
PROGRESS_DIR = PROJECT_ROOT / "data" / "raw" / ".progress"
LOG_DIR = PROJECT_ROOT / "logs"

PROCESSED_DIR.mkdir(parents=True, exist_ok=True)
LOG_DIR.mkdir(exist_ok=True)

DB_PATH = PROCESSED_DIR / "kcsdb.duckdb"


# 로그
LOG_PATH = LOG_DIR / f"load_duckdb_{datetime.now().strftime('%Y%m%d_%H%M%S')}.log"
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[
        logging.FileHandler(LOG_PATH, encoding="utf-8"),
        logging.StreamHandler(sys.stdout),
    ],
)
logger = logging.getLogger(__name__)


# ──────────────────────────────────────────────
# meta_calls 빌드: status JSON → DataFrame
# ──────────────────────────────────────────────

META_DTYPES = {
    "yyyymm": "int32",
    "year": "int16",
    "month": "int8",
    "stat_cd": "string",
    "success": "boolean",
    "result_code": "string",
    "result_msg": "string",
    "item_count": "int32",
    "response_bytes": "int32",
    "elapsed_sec": "float32",
    "timestamp": "datetime64[ns]",
}


def build_meta_calls_df() -> pd.DataFrame:
    """20개 status JSON을 통합한 DataFrame 반환."""
    records = []
    n_files = 0
    for fp in sorted(PROGRESS_DIR.glob("status_*.json")):
        with open(fp, encoding="utf-8") as f:
            d = json.load(f)
        for key, v in d.items():
            # key 형식: "YYYYMM_CC"
            try:
                yyyymm_str, cnty = key.split("_")
                yyyymm = int(yyyymm_str)
            except (ValueError, IndexError):
                logger.warning(f"  잘못된 status 키: {key} (in {fp.name})")
                continue
            records.append({
                "yyyymm": yyyymm,
                "year": yyyymm // 100,
                "month": yyyymm % 100,
                "stat_cd": cnty,
                "success": bool(v.get("success", False)),
                "result_code": v.get("result_code") or "",
                "result_msg": v.get("result_msg") or "",
                "item_count": int(v.get("item_count", 0) or 0),
                "response_bytes": int(v.get("response_bytes", 0) or 0),
                "elapsed_sec": float(v.get("elapsed_sec", 0.0) or 0.0),
                "timestamp": v.get("timestamp"),
            })
        n_files += 1

    logger.info(f"  status JSON 파일: {n_files}개")
    logger.info(f"  meta_calls 레코드: {len(records):,}")

    df = pd.DataFrame(records)
    # 자료형 캐스팅 (timestamp는 별도)
    df["timestamp"] = pd.to_datetime(df["timestamp"], errors="coerce")
    for col, dtype in META_DTYPES.items():
        if col == "timestamp":
            continue
        df[col] = df[col].astype(dtype)
    return df


# ──────────────────────────────────────────────
# DuckDB 빌드
# ──────────────────────────────────────────────

def build_duckdb(overwrite: bool) -> None:
    if DB_PATH.exists():
        if not overwrite:
            logger.error(f"이미 존재: {DB_PATH}")
            logger.error(f"  덮어쓰려면 --overwrite 옵션 사용")
            sys.exit(1)
        logger.warning(f"  기존 DB 삭제: {DB_PATH}")
        DB_PATH.unlink()

    logger.info(f"DB 생성: {DB_PATH}")
    con = duckdb.connect(str(DB_PATH))

    # 1. fact_trade
    trade_glob = str(INTERIM_DIR / "fact_trade_*.parquet")
    n_trade_files = len(glob.glob(trade_glob))
    logger.info(f"\n[1/3] fact_trade 적재 ({n_trade_files}개 parquet)")
    t0 = datetime.now()
    con.execute(f"""
        CREATE TABLE fact_trade AS
        SELECT * FROM read_parquet('{trade_glob.replace(chr(92), '/')}')
    """)
    n_trade = con.execute("SELECT COUNT(*) FROM fact_trade").fetchone()[0]
    logger.info(f"  완료: {n_trade:,}행 / {(datetime.now()-t0).total_seconds():.1f}초")

    # 2. fact_total
    total_glob = str(INTERIM_DIR / "fact_total_*.parquet")
    n_total_files = len(glob.glob(total_glob))
    logger.info(f"\n[2/3] fact_total 적재 ({n_total_files}개 parquet)")
    t0 = datetime.now()
    con.execute(f"""
        CREATE TABLE fact_total AS
        SELECT * FROM read_parquet('{total_glob.replace(chr(92), '/')}')
    """)
    n_total = con.execute("SELECT COUNT(*) FROM fact_total").fetchone()[0]
    logger.info(f"  완료: {n_total:,}행 / {(datetime.now()-t0).total_seconds():.1f}초")

    # 3. meta_calls
    logger.info(f"\n[3/3] meta_calls 적재 (status JSON)")
    t0 = datetime.now()
    df_meta = build_meta_calls_df()
    con.execute("CREATE TABLE meta_calls AS SELECT * FROM df_meta")
    n_meta = con.execute("SELECT COUNT(*) FROM meta_calls").fetchone()[0]
    logger.info(f"  완료: {n_meta:,}행 / {(datetime.now()-t0).total_seconds():.1f}초")

    # 검증
    logger.info(f"\n" + "=" * 60)
    logger.info(f"검증 SQL")
    logger.info(f"=" * 60)

    # 검증 1: 기본 행수
    logger.info(f"  fact_trade:  {n_trade:>12,}행")
    logger.info(f"  fact_total:  {n_total:>12,}행")
    logger.info(f"  meta_calls:  {n_meta:>12,}행")

    # 검증 2: meta_calls 성공 페어의 item_count 합 vs (fact_trade + 거래있는 fact_total)
    sql_check = """
        WITH meta_sum AS (
            SELECT SUM(item_count) AS s FROM meta_calls WHERE success
        ),
        total_with_trade AS (
            SELECT COUNT(*) AS c FROM fact_total
            WHERE NOT (exp_dlr=0 AND imp_dlr=0 AND exp_wgt=0 AND imp_wgt=0)
        ),
        trade_count AS (
            SELECT COUNT(*) AS c FROM fact_trade
        )
        SELECT meta_sum.s, trade_count.c, total_with_trade.c,
               meta_sum.s - trade_count.c - total_with_trade.c AS diff
        FROM meta_sum, trade_count, total_with_trade
    """
    s, t, tt, diff = con.execute(sql_check).fetchone()
    logger.info(f"")
    logger.info(f"  적재 무결성 검증:")
    logger.info(f"    meta_calls.item_count 합     = {s:>12,}")
    logger.info(f"    fact_trade 행수              = {t:>12,}")
    logger.info(f"    fact_total 거래 있는 행수    = {tt:>12,}")
    logger.info(f"    차이 (0이면 무결)            = {diff:>12,}")
    if diff == 0:
        logger.info(f"    ✓ 적재 무결성 통과")
    else:
        logger.error(f"    ✗ 적재 무결성 실패 — 조사 필요")

    # 검증 3: 거래 0건 페어 수
    n_zero = con.execute("""
        SELECT COUNT(*) FROM fact_total
        WHERE exp_dlr=0 AND imp_dlr=0 AND exp_wgt=0 AND imp_wgt=0
    """).fetchone()[0]
    logger.info(f"")
    logger.info(f"  거래 0건 페어 (fact_total에 0값으로 기록): {n_zero:,}")

    # 검증 4: 실패 페어
    n_fail = con.execute("SELECT COUNT(*) FROM meta_calls WHERE NOT success").fetchone()[0]
    logger.info(f"  실패 페어 (meta_calls.success=false): {n_fail:,}")

    # 검증 5: 시간 범위
    rng = con.execute("""
        SELECT MIN(yyyymm), MAX(yyyymm) FROM fact_trade
    """).fetchone()
    logger.info(f"")
    logger.info(f"  fact_trade 시간 범위: {rng[0]} ~ {rng[1]}")

    # 검증 6: 국가 수
    n_country = con.execute("SELECT COUNT(DISTINCT stat_cd) FROM fact_trade").fetchone()[0]
    logger.info(f"  fact_trade 국가 수: {n_country}")

    # 검증 7: HS 코드 수
    n_hs = con.execute("SELECT COUNT(DISTINCT hs10) FROM fact_trade").fetchone()[0]
    logger.info(f"  fact_trade hs10 고유 수: {n_hs:,}")

    # 검증 8: 파일 크기
    db_size_mb = DB_PATH.stat().st_size / 1024**2
    logger.info(f"")
    logger.info(f"  DuckDB 파일 크기: {db_size_mb:.1f} MB")

    con.close()
    logger.info(f"\n✓ DuckDB 빌드 완료: {DB_PATH}")


# ──────────────────────────────────────────────
# 메인
# ──────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--overwrite", action="store_true",
                        help="기존 DB 파일이 있으면 덮어쓰기")
    args = parser.parse_args()

    logger.info("=" * 60)
    logger.info(f"02b: parquet → DuckDB 빌드")
    logger.info(f"interim: {INTERIM_DIR}")
    logger.info(f"DB:      {DB_PATH}")
    logger.info("=" * 60)

    t_start = datetime.now()
    build_duckdb(overwrite=args.overwrite)
    t_elapsed = (datetime.now() - t_start).total_seconds()

    logger.info(f"\n총 시간: {t_elapsed:.1f}초")
    logger.info(f"상세 로그: {LOG_PATH}")


if __name__ == "__main__":
    main()
