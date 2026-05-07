"""
03d: dim_hs2 description 보강 (description_ko, description_en, section)

배경:
- 03b는 dim_hs2를 fact 데이터로부터 도출 가능한 정보만으로 생성
- description_ko, section은 외부 자료(부류목록) 필요 — NULL로 후속 작업 분리 (결정 21)
- description_en은 양쪽 병기 결정으로 추가 (결정 23)

흐름:
    03a 진단 → 03b dim 생성 → 03c 패치 → 03d 보강 (본 스크립트) → 04 검증

자료 출처 (data/external/kcsdb_hs2_chapter_titles_20260507.csv):
- description_ko, section: 한국 관세청 관세율표 부류목록 (UI-ULS-0201-002Q, 2026년판)
- description_en: WCO HS 2022 Nomenclature 표준 chapter titles
- section 표기: 로마숫자 I~XXI (WCO 표준, 결정 3)

데이터 사항:
- 97 행 (HS01~HS97 96개 + HS99 — HS77, HS98은 dim_hs2 미수록)
- HS99: description_ko/en/section 모두 NULL 유지 (결정 2 옵션 a)
  - 사유: 한국 통계 특수 분류, 부류목록에 정의 없음. NULL이 *모름*을 정직하게 표현.

스키마 변경:
- ALTER TABLE dim_hs2 ADD COLUMN description_en VARCHAR (없는 경우만)

idempotent: 재실행해도 안전. 같은 값으로 UPDATE.

실행:
    cd C:\\Projects\\KCSDB
    conda activate kcsdb
    python scripts\\03d_enrich_dim_hs2.py
"""

from __future__ import annotations
import csv
import sys
from pathlib import Path

import duckdb


PROJECT_ROOT = Path(__file__).resolve().parent.parent
DB_PATH = PROJECT_ROOT / "data" / "processed" / "kcsdb.duckdb"
CSV_PATH = PROJECT_ROOT / "data" / "external" / "kcsdb_hs2_chapter_titles_20260507.csv"


def column_exists(con: duckdb.DuckDBPyConnection, table: str, column: str) -> bool:
    rows = con.execute(f"""
        SELECT column_name FROM duckdb_columns()
        WHERE schema_name = 'main' AND table_name = '{table}'
          AND column_name = '{column}'
    """).fetchall()
    return len(rows) > 0


def _clean(v):
    """빈 문자열 → None (DuckDB NULL 적재)."""
    if v is None:
        return None
    if isinstance(v, str) and v.strip() == "":
        return None
    return v


def main():
    if not DB_PATH.exists():
        print(f"[ERROR] DB 파일 없음: {DB_PATH}")
        sys.exit(1)
    if not CSV_PATH.exists():
        print(f"[ERROR] CSV 파일 없음: {CSV_PATH}")
        print(f"        kcsdb_hs2_chapter_titles_20260507.csv 를")
        print(f"        data/external/ 에 두고 재실행")
        sys.exit(1)

    print("=" * 64)
    print("03d: dim_hs2 description 보강")
    print("=" * 64)
    print(f"DB:  {DB_PATH}")
    print(f"CSV: {CSV_PATH}")

    con = duckdb.connect(str(DB_PATH), read_only=False)

    # ===== Step 1: 스키마 보강 =====
    print()
    print("Step 1: dim_hs2 스키마 점검")
    print("-" * 64)
    if column_exists(con, "dim_hs2", "description_en"):
        print("  description_en 컬럼 이미 존재. ALTER 불필요")
    else:
        con.execute("ALTER TABLE dim_hs2 ADD COLUMN description_en VARCHAR")
        print("  description_en 컬럼 추가 완료")

    # ===== Step 2: CSV 읽기 + 사전 점검 =====
    print()
    print("Step 2: CSV 읽기 + dim_hs2 hs2 코드 비교")
    print("-" * 64)

    csv_rows = []
    with open(CSV_PATH, "r", encoding="utf-8-sig", newline="") as f:
        reader = csv.DictReader(f)
        for r in reader:
            csv_rows.append(r)

    print(f"  CSV 행 수: {len(csv_rows)}")

    db_hs2 = set(r[0] for r in con.execute(
        "SELECT hs2 FROM dim_hs2").fetchall())
    csv_hs2 = set(r["hs2"] for r in csv_rows)

    only_csv = csv_hs2 - db_hs2
    only_db = db_hs2 - csv_hs2

    if only_csv:
        print(f"  [경고] CSV에만 있는 hs2: {sorted(only_csv)}")
        print(f"         이 행들은 UPDATE에서 영향 없음 (WHERE 매치 실패)")
    if only_db:
        print(f"  [경고] dim_hs2에만 있는 hs2: {sorted(only_db)}")
        print(f"         이 행들은 description NULL로 남음")
    if not only_csv and not only_db:
        print(f"  CSV vs dim_hs2 hs2 코드 정확히 일치 ({len(csv_hs2)}개)")

    # ===== Step 3: UPDATE =====
    print()
    print("Step 3: UPDATE 실행")
    print("-" * 64)

    for r in csv_rows:
        con.execute("""
            UPDATE dim_hs2
            SET description_ko = ?, description_en = ?, section = ?
            WHERE hs2 = ?
        """, [_clean(r["description_ko"]),
              _clean(r["description_en"]),
              _clean(r["section"]),
              r["hs2"]])

    print(f"  UPDATE 시도 행 수: {len(csv_rows)}")

    # ===== Step 4: 결과 검증 =====
    print()
    print("Step 4: 결과 검증")
    print("-" * 64)

    rows = con.execute("""
        SELECT hs2,
               description_ko IS NULL AS ko_null,
               description_en IS NULL AS en_null,
               section IS NULL AS sect_null
        FROM dim_hs2
        ORDER BY hs2
    """).fetchall()

    null_ko = [r[0] for r in rows if r[1]]
    null_en = [r[0] for r in rows if r[2]]
    null_sect = [r[0] for r in rows if r[3]]

    print(f"  description_ko NULL: {null_ko}  (기대 ['99'])")
    print(f"  description_en NULL: {null_en}  (기대 ['99'])")
    print(f"  section        NULL: {null_sect}  (기대 ['99'])")

    expected_null = ['99']
    ok = (null_ko == expected_null
          and null_en == expected_null
          and null_sect == expected_null)

    if ok:
        print()
        print("  검증 통과: HS99만 NULL, 나머지 96개 모두 채워짐")
    else:
        print()
        print("  [경고] 예상 외 NULL 패턴. 수동 점검 필요")

    # ===== Step 5: 부(section) 분포 (참고용) =====
    print()
    print("Step 5: 부(section) 단위 류 분포 (참고용)")
    print("-" * 64)
    sect_dist = con.execute("""
        SELECT section, COUNT(*) AS n_chapter,
               MIN(hs2) AS hs2_min, MAX(hs2) AS hs2_max
        FROM dim_hs2
        WHERE section IS NOT NULL
        GROUP BY section
        ORDER BY MIN(hs2)
    """).fetchall()
    for s, n, mn, mx in sect_dist:
        if mn == mx:
            range_str = mn
        else:
            range_str = f"{mn}~{mx}"
        print(f"  {s:5s}  {n:2d}개 류 (HS{range_str})")
    total = sum(n for _, n, _, _ in sect_dist)
    print(f"  총 {total}개 (기대 96)")

    # ===== Step 6: HS99 행 확인 =====
    print()
    print("Step 6: HS99 행 확인 (NULL 유지 여부)")
    print("-" * 64)
    h99 = con.execute("""
        SELECT hs2, n_hs10, first_yyyymm, last_yyyymm,
               description_ko, description_en, section
        FROM dim_hs2 WHERE hs2 = '99'
    """).fetchone()
    if h99:
        cols = ['hs2', 'n_hs10', 'first_yyyymm', 'last_yyyymm',
                'description_ko', 'description_en', 'section']
        for c, v in zip(cols, h99):
            v_str = "NULL" if v is None else str(v)
            print(f"  {c:<15} = {v_str}")
    else:
        print("  [경고] HS99 행 없음")

    con.close()

    print()
    print("=" * 64)
    if ok:
        print("dim_hs2 보강 완료. 다음: 04_validate.py 재실행 권장")
        sys.exit(0)
    else:
        print("[ERROR] 검증 실패. 수동 점검 필요")
        sys.exit(1)


if __name__ == "__main__":
    main()
