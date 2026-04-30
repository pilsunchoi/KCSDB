"""
관세청 OpenAPI 시범 호출 스크립트
=========================================

목적
----
본격 수집 전에 API의 실제 동작을 직접 확인하는 "정찰" 스크립트.
docs/02_api_spec_analysis.md 의 미해결 질문 Q1~Q8 에 답하는 것이 목표.

답해야 할 질문
-------------
Q1. pageNo, numOfRows 가 동작하는가? 한 호출당 최대 행수는?
Q2. hsSgn 생략 시 응답 HS 자릿수는?
Q3. cntyCd 생략 시 전체 국가 반환되는가?
Q4. statCd 가 ISO2 와 항상 일치하는가?
Q5. 응답에서 expDlr 등 금액 단위가 USD 인가, 천USD 인가?
Q6. 한 달치 전체 데이터 응답 행수는?
Q7. HTTPS 로도 호출되는가?
Q8. year 필드 형식은? (2016.01 같은 소수점 표기)

설계 원칙
--------
1. 단계적 호출: 한 번에 모든 것을 시도하지 않음
2. 모든 raw XML 응답을 data/raw/test/ 에 저장 (디버깅·재현 가능성)
3. 인증키 절대 출력 금지
4. 학생들이 따라할 수 있도록 풍부한 주석

실행
----
    cd C:\\Projects\\KCSDB
    conda activate kcsdb
    python scripts/00_test_api.py
"""

import os
import sys
from pathlib import Path
from datetime import datetime
import xml.etree.ElementTree as ET

import requests
from dotenv import load_dotenv


# ============================================================
# 1. 경로 및 설정
# ============================================================

# 본 스크립트는 프로젝트 루트의 scripts/ 안에 위치
# 따라서 부모의 부모가 프로젝트 루트
PROJECT_ROOT = Path(__file__).resolve().parent.parent

# 시범 호출 결과 저장 경로
TEST_OUT_DIR = PROJECT_ROOT / "data" / "raw" / "test"
TEST_OUT_DIR.mkdir(parents=True, exist_ok=True)

# API 엔드포인트 — docs/02_api_spec_analysis.md 참조
# Q7 검증을 위해 http/https 둘 다 시험
BASE_URL_HTTP = "http://apis.data.go.kr/1220000/nitemtrade/getNitemtradeList"
BASE_URL_HTTPS = "https://apis.data.go.kr/1220000/nitemtrade/getNitemtradeList"


# ============================================================
# 2. 인증키 로드
# ============================================================
# 핵심 보안 원칙: 키는 .env 파일에서 로드. 코드에 직접 쓰지 않음.

ENV_PATH = PROJECT_ROOT / "config" / "api_key.env"

if not ENV_PATH.exists():
    print(f"[FATAL] {ENV_PATH} 가 없습니다.")
    print(f"        config/api_key.env.example 을 복사하여 만들고 실제 키를 입력하세요.")
    sys.exit(1)

load_dotenv(ENV_PATH)
API_KEY = os.getenv("DATA_GO_KR_API_KEY")

if not API_KEY:
    print("[FATAL] DATA_GO_KR_API_KEY 가 .env 에서 로드되지 않았습니다.")
    sys.exit(1)

if API_KEY.startswith("여기에"):
    print("[FATAL] 인증키가 placeholder 상태입니다. 실제 키를 입력하세요.")
    sys.exit(1)

# 안전 출력: 키 일부만 표시 (앞 4자 + ...)
print(f"[OK] 인증키 로드 완료: {API_KEY[:4]}...{API_KEY[-4:]} (length={len(API_KEY)})")
print()


# ============================================================
# 3. 호출 헬퍼 함수
# ============================================================

def call_api(params: dict, label: str, base_url: str = BASE_URL_HTTP, timeout: int = 30) -> requests.Response:
    """
    API 를 호출하고, 응답을 raw 파일로 저장한 뒤 Response 객체를 반환.

    Parameters
    ----------
    params : dict
        쿼리 파라미터. serviceKey 는 자동으로 추가됨.
    label : str
        파일명에 들어갈 시험 이름 (예: "step1_minimal")
    base_url : str
        API 엔드포인트
    timeout : int
        요청 타임아웃 (초)

    Returns
    -------
    requests.Response
    """
    # serviceKey 자동 추가
    full_params = {"serviceKey": API_KEY, **params}

    # 호출
    print(f"--- {label} ---")
    print(f"  URL: {base_url}")
    # 인증키 제외하고 출력
    safe_params = {k: v for k, v in full_params.items() if k != "serviceKey"}
    print(f"  Params: {safe_params}")

    try:
        response = requests.get(base_url, params=full_params, timeout=timeout)
    except requests.exceptions.RequestException as e:
        print(f"  [ERROR] 요청 실패: {e}")
        return None

    print(f"  Status: {response.status_code}")
    print(f"  Response size: {len(response.content)} bytes")

    # raw 응답 저장 (디버깅 + 재현 가능성)
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    out_path = TEST_OUT_DIR / f"{timestamp}_{label}.xml"
    out_path.write_bytes(response.content)
    print(f"  Saved: {out_path.relative_to(PROJECT_ROOT)}")

    return response


def parse_response(response: requests.Response):
    """
    XML 응답에서 핵심 정보 추출.

    공공데이터포털 표준 응답 구조 (예상):
        <response>
            <header>
                <resultCode>00</resultCode>
                <resultMsg>OK</resultMsg>
            </header>
            <body>
                <items>
                    <item>...</item>
                    <item>...</item>
                </items>
                <numOfRows>...</numOfRows>
                <pageNo>...</pageNo>
                <totalCount>...</totalCount>
            </body>
        </response>

    또는 명세상의 응답 (resultCode/resultMsg/year/... 가 평면 구조).
    실제 구조는 시범 호출 결과로 확인.
    """
    if response is None:
        return

    try:
        root = ET.fromstring(response.content)
    except ET.ParseError as e:
        print(f"  [ERROR] XML 파싱 실패: {e}")
        # 비정상 응답 첫 500자 확인
        text_preview = response.text[:500]
        print(f"  Response preview: {text_preview}")
        return

    # 결과 코드 확인 (공공데이터포털 표준)
    # header/resultCode 또는 그냥 resultCode 어디에 있는지 확인
    result_code_elements = root.iter("resultCode")
    result_msg_elements = root.iter("resultMsg")

    rcs = [e.text for e in result_code_elements]
    rms = [e.text for e in result_msg_elements]
    print(f"  resultCode: {rcs}, resultMsg: {rms}")

    # 페이지네이션 정보가 있는지 확인 (Q1)
    for tag in ["numOfRows", "pageNo", "totalCount"]:
        elements = list(root.iter(tag))
        if elements:
            print(f"  {tag}: {[e.text for e in elements]}")

    # item 태그들 카운트
    items = list(root.iter("item"))
    print(f"  <item> count: {len(items)}")

    # 첫 item 의 필드 출력 (응답 구조 파악)
    if items:
        print(f"  First <item> children:")
        for child in items[0]:
            text = (child.text or "").strip()
            # 너무 길면 자르기
            if len(text) > 50:
                text = text[:50] + "..."
            print(f"    <{child.tag}>: {text}")


def print_section(title: str):
    print()
    print("=" * 70)
    print(f"  {title}")
    print("=" * 70)


# ============================================================
# 4. 시범 호출 시나리오
# ============================================================

# Step 1: 최소 호출
# 가장 단순한 호출로 응답을 받아오는지부터 확인
# 명세 sample: strtYymm=201601, hsSgn=1001999090, cntyCd=US
# 우리는 더 최근 데이터로 시도: 2024-01, HS=8517(전화기 등 통신기기), 미국
print_section("Step 1: 최소 호출 (단일 월, 단일 HS, 단일 국가)")
r1 = call_api(
    params={
        "strtYymm": "202401",
        "endYymm": "202401",
        "hsSgn": "8517120000",  # 휴대전화 (HS10)
        "cntyCd": "US",
    },
    label="step1_minimal",
)
parse_response(r1)


# Step 2: 페이지네이션 시험 (Q1)
# 명세서에 없는 pageNo, numOfRows 가 동작하는지
print_section("Step 2: 페이지네이션 파라미터 시험 (Q1)")
r2 = call_api(
    params={
        "strtYymm": "202401",
        "endYymm": "202401",
        "hsSgn": "8517120000",
        "cntyCd": "US",
        "pageNo": "1",
        "numOfRows": "10",
    },
    label="step2_pagination",
)
parse_response(r2)


# Step 3: hsSgn 생략 (Q2)
# HS 코드 안 주면 어떤 자릿수로 집계되는가?
print_section("Step 3: hsSgn 생략 시 응답 자릿수 (Q2)")
r3 = call_api(
    params={
        "strtYymm": "202401",
        "endYymm": "202401",
        "cntyCd": "US",
        "pageNo": "1",
        "numOfRows": "10",
    },
    label="step3_no_hssgn",
)
parse_response(r3)


# Step 4: cntyCd 생략 (Q3)
# 국가 코드 안 주면 전체 국가 나오는가?
print_section("Step 4: cntyCd 생략 시 전체 국가 반환 여부 (Q3)")
r4 = call_api(
    params={
        "strtYymm": "202401",
        "endYymm": "202401",
        "hsSgn": "8517120000",
        "pageNo": "1",
        "numOfRows": "20",
    },
    label="step4_no_cntycd",
)
parse_response(r4)


# Step 5: 큰 응답 시험 (Q6)
# 한 달치 데이터에서 페이지네이션 없이 / 큰 numOfRows 로 호출
# 응답 크기와 행수 확인
print_section("Step 5: 큰 응답 — numOfRows=1000 (Q6)")
r5 = call_api(
    params={
        "strtYymm": "202401",
        "endYymm": "202401",
        "cntyCd": "US",  # 미국만 (전체 호출은 너무 클 수 있음)
        "pageNo": "1",
        "numOfRows": "1000",
    },
    label="step5_large_response",
    timeout=60,
)
parse_response(r5)


# Step 6: HTTPS 시험 (Q7)
print_section("Step 6: HTTPS 호출 가능 여부 (Q7)")
r6 = call_api(
    params={
        "strtYymm": "202401",
        "endYymm": "202401",
        "hsSgn": "8517120000",
        "cntyCd": "US",
    },
    label="step6_https",
    base_url=BASE_URL_HTTPS,
)
parse_response(r6)


# Step 7: 1년 단위 호출 — 제약 확인
# 명세 "조회기간 1년 이내" 가 12개월 OK 인지, 11개월까지인지
print_section("Step 7: 12개월 조회 가능 여부")
r7 = call_api(
    params={
        "strtYymm": "202401",
        "endYymm": "202412",
        "hsSgn": "8517120000",
        "cntyCd": "US",
        "pageNo": "1",
        "numOfRows": "100",
    },
    label="step7_full_year",
)
parse_response(r7)


# Step 8: 13개월 호출 — 제약 위반 시 어떤 오류?
print_section("Step 8: 13개월 조회 (제약 위반 시 응답 확인)")
r8 = call_api(
    params={
        "strtYymm": "202401",
        "endYymm": "202501",  # 13개월
        "hsSgn": "8517120000",
        "cntyCd": "US",
    },
    label="step8_13months",
)
parse_response(r8)


# ============================================================
# 5. 마무리
# ============================================================
print()
print("=" * 70)
print("  시범 호출 완료")
print("=" * 70)
print(f"  raw XML 응답들이 다음 위치에 저장되었습니다:")
print(f"    {TEST_OUT_DIR.relative_to(PROJECT_ROOT)}")
print()
print(f"  다음 단계:")
print(f"    1. 위 출력을 검토하여 Q1~Q8 답변 도출")
print(f"    2. docs/02_api_spec_analysis.md 의 미해결 질문 섹션 갱신")
print(f"    3. 본격 수집 전략 결정")
