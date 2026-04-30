# 프로젝트 협업 일지

본 문서는 Claude(AI)와의 협업 과정에서 내려진 주요 결정과 그 근거를 시간순으로 기록합니다.
학생 교육 자료로도 사용됩니다.

---

## 2026-05-01: 프로젝트 시작

### 배경
- 한국 무역구조 변화에 관한 연구 아이디어가 출발점
- 처음에는 "코로나19가 한국 국제무역에 미친 인과효과" 분석을 검토
- AI와의 논의를 통해 연구 설계상 식별 위협이 큼을 인식

### 주요 결정 1: 연구 프레임 전환 (인과 → 기술)

**결정**: 인과효과 추정이 아닌 *관찰된 변화의 체계적 기록*으로 연구 프레임 전환

**근거**:
- 코로나19/정권교체 등 글로벌·동시발생 충격은 표준 중력모형으로 식별 어려움
- 다자저항(multilateral resistance)의 비대칭적 변화로 양쪽 시간 FE 만으로는 부족
- 동시 발생 충격(미중분쟁, IRA, 우크라전쟁, 반도체 싸이클 등)을 분리 불가

**대안**: 기술적 분석(descriptive analysis)을 통한 무역구조 변화 기록
- 시기별 비중 변화, HHI 등 다변화 지수
- 중력모형 잔차를 *벤치마크 도구*로 활용 (예측 vs 실제 비교)

### 주요 결정 2: 데이터셋 구축이 주(主) 목표

**결정**: 연구질문에 종속된 데이터 수집이 아닌, 재사용 가능한 자산으로서의 데이터셋 구축

**근거**:
- 한 번 잘 만들어두면 향후 다양한 연구·강의에 활용 가능
- 학생 교육 자료로서의 가치 (AI 협업 + 데이터 파이프라인 사례)
- 연구주제는 데이터 만들면서 자연스럽게 결정 가능

### 주요 결정 3: 데이터 출처 — KITA → 관세청 OpenAPI

**결정**: 한국무역협회(KITA) K-stat 대신 관세청 공공데이터포털 OpenAPI 직접 사용

**근거**:
- KITA K-stat은 외부 연구자용 공식 REST API 미제공 (수동 다운로드 또는 스크래핑)
- 관세청은 공공데이터포털을 통해 정식 OpenAPI 제공
- KITA의 한국무역통계 자체가 관세청 자료의 가공본이므로 원천을 직접 사용하는 것이 정공법

**참고**: AI(Claude)가 처음에는 "KITA가 표준" 식으로 답했으나, 사용자 질문("API 자동화 공식 지원이 약하다는게 무슨 의미?")으로 재검색 → 관세청 OpenAPI의 존재를 확인하고 정정. **AI도 틀릴 수 있으며 사용자의 검증이 중요하다는 사례.**

### 주요 결정 4: 수집 범위 1차 목표

| 차원 | 범위 |
|---|---|
| 시간 | 2010년 ~ 2026년 (월별) |
| 품목 | HS10 (가능 시 풀 해상도) |
| 국가 | 전체 상대국 |
| 변수 | 수출액, 수입액, 수출중량, 수입중량 |

### 주요 결정 5: 운영 환경

- OS: Windows
- 버전관리: GitHub 공개 레포
- 문서 언어: 한국어
- 저장: DuckDB + Parquet

---

## 2026-05-01: API 명세 분석

### 핵심 사용 API
**관세청_품목별 국가별 수출입실적(GW)** — `data.go.kr/data/15100475`

### 명세 추출 (사용자가 Swagger UI 스크린샷 공유)

#### Endpoint
```
http://apis.data.go.kr/1220000/nitemtrade/getNitemtradeList
```

#### 요청 파라미터
| 영문명 | 자릿수 | 필수/옵션 | 의미 |
|---|---|---|---|
| serviceKey | 100 | 필수 | 인증키 |
| strtYymm | 6 | 필수 | 시작년월 YYYYMM |
| endYymm | 6 | 필수 | 종료년월 YYYYMM |
| hsSgn | 10 | 옵션 | HS 코드 |
| cntyCd | 2 | 옵션 | 국가코드 |

#### 응답 필드 (12개)
year, statCdCntnKor1(국가명), statCd(국가코드), statKor(품명), hsCd(HS코드),
expWgt(수출중량 kg), expDlr(수출금액), impWgt(수입중량 kg), impDlr(수입금액),
balPayments(무역수지), resultCode, resultMsg

### 결정적 제약
1. **조회기간 1년 이내** → 연도별 분할 호출 필수
2. **개발계정 일일 10,000건** → 호출 예산 관리 필요
3. **갱신 주기**: 매월 15일경 전월까지 자료 갱신

### 미해결 질문 (시범 호출에서 확인 예정)
- pageNo/numOfRows 동작 여부 및 한 호출당 최대 행수
- hsSgn 생략 시 응답 HS 자릿수
- cntyCd 생략 시 전체 국가 반환 여부
- statCd 코드 체계 (ISO2 호환성)
- 금액 단위 (USD vs 천USD)
- HTTPS 지원 여부

---

---

## 2026-05-01: 환경 관리 도구 결정

### 배경
초기에는 Python venv 사용을 가정하고 README/01_api_setup 작성. 사용자 PC에서 `python -m venv .venv` + `Activate.ps1` 시도 시 활성화 실패.

### 진단
- 사용자 PC에 Anaconda 설치, 프롬프트에 `(base)` 자동 표시
- base 환경이 활성화된 상태에서 venv 생성·활성화 시도 → venv가 base 위에 덮이지 않음
- 추가로 cmd에서 PowerShell 전용 `Activate.ps1` 실행 시도 → 무시됨

### 결정
**conda 환경 방식으로 통일**

```cmd
conda create -n kcsdb python=3.12 -y
conda activate kcsdb
```

### 근거
1. 사용자 PC에 이미 Anaconda 깔려 있고 항상 base가 자동 활성화됨 → conda가 자연스러움
2. 학생들도 데이터과학 강의에서 보통 Anaconda 사용 → 일관성
3. venv와 conda를 섞으면 혼란

### 학생용 교훈 추가
`docs/99_lessons_learned.md` 에 함정 1~4 정리:
- 공공데이터포털 Encoding/Decoding 키 차이
- Anaconda base + venv 충돌
- cmd vs PowerShell 활성화 스크립트 차이
- 인증키 GitHub 노출 위험

---

## 다음 단계

1. 로컬 환경 셋업 (Windows + Anaconda conda + Git) — 진행 중
2. API 인증키 발급 (`docs/01_api_setup.md` 작성) — 완료
3. 시범 호출 스크립트 (`scripts/00_test_api.py`) 작성 — 다음
4. 미해결 질문 Q1–Q8 답변 → 본격 수집 전략 확정
