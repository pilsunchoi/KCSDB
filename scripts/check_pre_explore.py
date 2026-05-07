"""
사전 점검: 본격 분석 진입 전 작업 1·2 SELECT
- 작업 1: dim_hs2 비등장 코드 식별
- 작업 2-a: MF 행 현재 상태
- 작업 2-b: dim_country ISO 결측 전체 점검 (예상: EU + MF 두 행만)

read_only 연결. 데이터 변경 없음.

실행:
    cd C:\\Projects\\KCSDB
    conda activate kcsdb
    python scripts\\check_pre_explore.py
"""

import duckdb
from pathlib import Path
import sys

DB_PATH = Path("data/processed/kcsdb.duckdb")


def main():
    if not DB_PATH.exists():
        print(f"[ERROR] DB 파일 없음: {DB_PATH.resolve()}")
        print(f"        현재 작업 폴더: {Path.cwd()}")
        print(f"        C:\\Projects\\KCSDB 에서 실행 필요")
        sys.exit(1)

    con = duckdb.connect(str(DB_PATH), read_only=True)

    # ===== 작업 1 =====
    print("=" * 64)
    print("작업 1: dim_hs2 비등장 코드 식별")
    print("=" * 64)

    q1 = """
        SELECT LPAD(range::VARCHAR, 2, '0') AS hs2_missing
        FROM range(1, 100)
        WHERE LPAD(range::VARCHAR, 2, '0') NOT IN (SELECT hs2 FROM dim_hs2)
        ORDER BY hs2_missing
    """
    rows = con.execute(q1).fetchall()
    print(f"비등장 코드 수: {len(rows)}")
    for r in rows:
        print(f"  HS2 = {r[0]}")
    if len(rows) != 2:
        print(f"  [경고] 예상 2개와 다름. 분기 결정 필요")

    # ===== 작업 2-a =====
    print()
    print("=" * 64)
    print("작업 2-a: MF 행 현재 상태")
    print("=" * 64)

    q2a = """
        SELECT stat_cd, name_ko_mofa, iso3, iso_num
        FROM dim_country
        WHERE stat_cd = 'MF'
    """
    rows = con.execute(q2a).fetchall()
    if not rows:
        print("  [경고] MF 행이 dim_country에 없음")
    else:
        for r in rows:
            iso3_v = r[2] if r[2] is not None else "NULL"
            iso_num_v = str(r[3]) if r[3] is not None else "NULL"
            print(f"  stat_cd      = {r[0]}")
            print(f"  name_ko_mofa = {r[1]}")
            print(f"  iso3         = {iso3_v}")
            print(f"  iso_num      = {iso_num_v}")

    # ===== 작업 2-b =====
    print()
    print("=" * 64)
    print("작업 2-b: dim_country ISO 결측 전체 점검")
    print("=" * 64)

    q2b = """
        SELECT stat_cd, name_ko_mofa, iso3, iso_num
        FROM dim_country
        WHERE iso3 IS NULL OR iso_num IS NULL
        ORDER BY stat_cd
    """
    rows = con.execute(q2b).fetchall()
    print(f"ISO 결측 행 수: {len(rows)}")
    for r in rows:
        iso3_v = r[2] if r[2] is not None else "NULL"
        iso_num_v = str(r[3]) if r[3] is not None else "NULL"
        print(f"  {r[0]} | {r[1]} | iso3={iso3_v} | iso_num={iso_num_v}")

    expected_set = {"EU", "MF"}
    actual_set = {r[0] for r in rows}
    print()
    if actual_set == expected_set:
        print("  판정: 예상대로 EU + MF 두 행만 NULL")
    else:
        print(f"  [경고] 예상({expected_set})과 다름")
        unexpected = actual_set - expected_set
        missing = expected_set - actual_set
        if unexpected:
            print(f"         예상 외 결측: {unexpected}")
        if missing:
            print(f"         예상 중 누락: {missing}")
        print(f"         분기 결정 필요")

    con.close()

    print()
    print("=" * 64)
    print("점검 완료. 위 출력을 채팅으로 복사해 보고")
    print("=" * 64)


if __name__ == "__main__":
    main()
