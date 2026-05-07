"""
03c: dim 패치 — 외부 자료의 알려진 결함을 코드로 정정

배경:
- 03b_build_dims.py는 외교부 자료(country_codes_mofa_20251222.csv)를
  그대로 dim_country로 적재
- 외교부 자료에 *입력 결함* 있음. 본 스크립트로 코드 명시 정정.

흐름:
    03a 진단 → 03b dim 생성 → 03c 패치 (본 스크립트) → 04 검증

알려진 패치 1건 (2026-05-06 기준):
- MF (세인트마틴 섬) iso3, iso_num NULL → ISO 3166-1 표준값
  - iso3: NULL → 'MAF'
  - iso_num: NULL → 663
  - 출처: ISO 3166-1 alpha-3 / numeric 표준
  - 근거: 외교부 CSV의 'NULL' 문자열 입력 (함정 19)

향후 추가 패치 발견 시 본 파일에 PATCHES 리스트로 추가.

idempotent: 이미 정정된 행은 재실행해도 변경 없음.

실행:
    cd C:\\Projects\\KCSDB
    conda activate kcsdb
    python scripts\\03c_patch_dims.py
"""

import duckdb
from pathlib import Path
import sys

DB_PATH = Path("data/processed/kcsdb.duckdb")

# 알려진 패치 목록. 향후 추가 시 dict 한 항목씩 append.
PATCHES = [
    {
        "id": "MF_iso_fix",
        "description": "MF (세인트마틴 섬) iso3, iso_num 정정",
        "table": "dim_country",
        "where": "stat_cd = 'MF'",
        "expected_before": {"iso3": None, "iso_num": None},
        "expected_after": {"iso3": "MAF", "iso_num": 663},
        "source": "ISO 3166-1 alpha-3 / numeric",
    },
]


def show_row(con, table, where, label):
    print("-" * 64)
    print(f"{label}: {table} WHERE {where}")
    print("-" * 64)
    rows = con.execute(f"SELECT * FROM {table} WHERE {where}").fetchall()
    cols = [d[0] for d in con.description]
    if not rows:
        print("  [ERROR] 해당 행 없음")
        return None
    r = rows[0]
    for c, v in zip(cols, r):
        v_str = "NULL" if v is None else str(v)
        print(f"  {c:<20} = {v_str}")
    return dict(zip(cols, r))


def apply_mf_iso_fix(con):
    patch = PATCHES[0]
    print()
    print("=" * 64)
    print(f"패치: {patch['id']} — {patch['description']}")
    print(f"출처: {patch['source']}")
    print("=" * 64)

    # Before
    before = show_row(con, patch["table"], patch["where"], "Before")
    if before is None:
        return False

    # idempotent 체크
    already_fixed = (
        before["iso3"] == patch["expected_after"]["iso3"]
        and before["iso_num"] == patch["expected_after"]["iso_num"]
    )
    if already_fixed:
        print()
        print("  → 이미 정정된 상태. SKIP")
        return True

    # 결함 형태가 예상과 다른지 점검
    if (
        before["iso3"] != patch["expected_before"]["iso3"]
        or before["iso_num"] != patch["expected_before"]["iso_num"]
    ):
        print()
        print(f"  [경고] 결함 형태가 예상과 다름")
        print(f"         기대 before: {patch['expected_before']}")
        print(f"         실제 before: iso3={before['iso3']}, iso_num={before['iso_num']}")
        print(f"         수동 점검 필요. 패치 SKIP")
        return False

    # UPDATE 실행 (parameterized)
    print()
    print("  UPDATE 실행:")
    print(f"    SET iso3    = '{patch['expected_after']['iso3']}'")
    print(f"    SET iso_num = {patch['expected_after']['iso_num']}")
    print(f"    WHERE {patch['where']}")
    con.execute(
        f"""
        UPDATE {patch['table']}
        SET iso3 = ?, iso_num = ?
        WHERE {patch['where']}
        """,
        [patch["expected_after"]["iso3"], patch["expected_after"]["iso_num"]],
    )

    # After
    print()
    after = show_row(con, patch["table"], patch["where"], "After")
    if after is None:
        return False

    # 검증
    ok = (
        after["iso3"] == patch["expected_after"]["iso3"]
        and after["iso_num"] == patch["expected_after"]["iso_num"]
    )
    print()
    if ok:
        print(f"  → 패치 적용 완료")
    else:
        print(f"  [ERROR] 패치 후 값이 예상과 다름")
    return ok


def main():
    if not DB_PATH.exists():
        print(f"[ERROR] DB 파일 없음: {DB_PATH.resolve()}")
        print(f"        현재 작업 폴더: {Path.cwd()}")
        sys.exit(1)

    print("=" * 64)
    print("03c: dim 패치 적용")
    print("=" * 64)
    print(f"DB: {DB_PATH}")
    print(f"패치 수: {len(PATCHES)}")

    con = duckdb.connect(str(DB_PATH), read_only=False)

    results = []
    for patch in PATCHES:
        if patch["id"] == "MF_iso_fix":
            ok = apply_mf_iso_fix(con)
        else:
            print(f"[ERROR] 알 수 없는 패치 ID: {patch['id']}")
            ok = False
        results.append((patch["id"], ok))

    con.close()

    # 요약
    print()
    print("=" * 64)
    print("요약")
    print("=" * 64)
    for pid, ok in results:
        mark = "OK" if ok else "FAIL"
        print(f"  [{mark}] {pid}")

    if all(ok for _, ok in results):
        print()
        print("모든 패치 적용 완료. 다음 단계: 04_validate.py 재실행 권장")
        sys.exit(0)
    else:
        sys.exit(1)


if __name__ == "__main__":
    main()
