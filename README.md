# 한국 관세청 무역통계 데이터셋 구축

본 프로젝트는 한국 관세청 OpenAPI를 활용하여 한국의 품목별·국가별 수출입 무역통계를 체계적으로 수집·정제·저장하는 것을 목적으로 합니다.

## 프로젝트 목적

1. **연구 자산 구축**: 2010–2026년 한국 무역구조 변화 분석을 위한 장기 패널 데이터셋
2. **교육 자료**: AI(Claude)와의 협업을 통한 데이터 파이프라인 구축 과정 문서화
3. **재현 가능성**: 모든 수집·처리 단계가 코드로 재현 가능

## 데이터 출처

- **메인**: 관세청_품목별 국가별 수출입실적(GW) — `data.go.kr/data/15100475`
- **보조**: 관세청 월별/국가별/품목별 OpenAPI 다수
- **검증**: 산업통상자원부 월간 수출입동향, KITA K-stat

## 디렉토리 구조

```
korea-trade-db/
├── README.md                    # 본 파일
├── requirements.txt             # Python 패키지 목록
├── .gitignore                   # 인증키·대용량 파일 제외
├── config/
│   ├── settings.yaml.example    # 설정 템플릿 (커밋됨)
│   ├── settings.yaml            # 실제 설정 (.gitignore)
│   └── api_key.env              # API 인증키 (.gitignore)
├── docs/
│   ├── 00_project_log.md        # AI 협업 일지
│   ├── 01_api_setup.md          # API 발급 절차
│   ├── 02_api_spec_analysis.md  # API 명세 분석
│   ├── 03_validation_log.md     # 교차검증 결과
│   └── 99_lessons_learned.md    # 학생용 교훈 정리
├── config/
├── scripts/
│   ├── 00_test_api.py           # 시범 호출
│   ├── 01_fetch_raw.py          # 본격 수집
│   ├── 02_load_duckdb.py        # 적재
│   ├── 03_build_dims.py         # 차원 테이블
│   ├── 04_validate.py           # 교차검증
│   └── utils/
│       ├── api_client.py
│       └── logging_config.py
├── data/
│   ├── raw/                     # API 원응답 (gitignored)
│   ├── interim/                 # 중간 처리물 (gitignored)
│   └── processed/               # 최종 DuckDB/Parquet (gitignored)
├── notebooks/
│   └── exploration/             # Jupyter 탐색용
└── tests/
    └── test_validation.py       # pytest 검증 스크립트
```

## 시작하기

### 사전 요구사항

- Anaconda 또는 Miniconda (Python 환경 관리)
- Git
- 공공데이터포털(data.go.kr) 회원가입 및 OpenAPI 인증키
  - 신청 대상: 관세청_품목별 국가별 수출입실적(GW) — 데이터 ID `15100475`

### 환경 설정

상세 절차는 `docs/01_api_setup.md` 참조.

```cmd
:: conda 환경 생성 및 활성화
conda create -n kcsdb python=3.12 -y
conda activate kcsdb

:: 패키지 설치
pip install -r requirements.txt

:: 인증키 등록 (config\api_key.env 파일 생성)
:: 내용: DATA_GO_KR_API_KEY=발급받은_인증키
```

## 진행 상태

- [x] 프로젝트 스켈레톤 구축
- [ ] API 인증키 발급
- [ ] 시범 호출 (`scripts/00_test_api.py`)
- [ ] 본격 수집 파이프라인 구축
- [ ] 차원 테이블 정비 (HS 코드, 국가 코드)
- [ ] 교차검증
- [ ] 분석 시작

## 라이선스 및 인용

- 코드: MIT License
- 데이터: 관세청 무역통계 (공공데이터포털 이용허락 범위 제한 없음)

학술 인용 시: (작성 예정)
