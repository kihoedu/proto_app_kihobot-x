# kihobot_x

박기호논술 통합 플랫폼. 분석엔진(교안 자동화) + 평가엔진(논술 첨삭) 을 하나의 서비스로 통합.

## 구조

```
kihobot_x/
├── main.py                  # 통합 진입점
├── common/                  # 공통 인프라 (DB · 설정 · 공통 템플릿)
├── portal/                  # 메인 홈 (두 엔진 진입)
├── eval_engine/             # 평가엔진 · 논술 첨삭
└── analy_engine/            # 분석엔진 · 교안 · PPT 자동화
```

접속 경로:
- `/` — 메인 포털 (두 개의 큰 버튼)
- `/eval/` — 평가엔진 (논술 첨삭)
- `/analy/` — 분석엔진 (교안 · PPT)

## 빠른 시작 (Docker)

### 1. 사전 준비

- Docker Desktop 설치 (WSL2 기반)
- NVIDIA Container Toolkit (GPU 쓰려면)
- Gemini API 키: https://aistudio.google.com/apikey

### 2. 환경변수 설정

```bash
cp .env.example .env
# .env 파일 열어서 GEMINI_API_KEY 입력
```

### 3. 기동

```bash
# 전체 빌드 + 기동
docker compose up -d --build

# 로그 보기
docker compose logs -f kihobot

# Gemma 3 모델 다운로드 (처음 1회)
docker exec -it kihobot_ollama ollama pull gemma3:12b
```

### 4. 접속

브라우저에서 `http://localhost:8000` 열기.

### 5. Cloudflare Tunnel (외부 접속 · 선택)

```bash
# Cloudflare Zero Trust 에서 터널 생성 후 토큰 복사
# .env 에 CLOUDFLARE_TUNNEL_TOKEN=... 추가

# tunnel 프로필로 기동
docker compose --profile tunnel up -d
```

## 로컬 실행 (Docker 없이)

```bash
# Python 가상환경
python -m venv venv
source venv/bin/activate  # Windows: venv\Scripts\activate

# 의존성
pip install -r requirements.txt
npm install

# 환경변수 (POPPLER_PATH 필수)
cp .env.example .env
# .env 수정

# 실행
python main.py
```

Windows 추가 설치:
- Poppler: https://github.com/oschwartz10612/poppler-windows/releases
- Node.js 20+: https://nodejs.org

## 자주 쓰는 명령어

```bash
docker compose up -d                           # 시작
docker compose down                            # 중지
docker compose restart kihobot                 # 재시작 (앱만)
docker compose logs -f kihobot                 # 로그
docker exec -it kihobot_x bash                 # 컨테이너 접속
docker exec postgres pg_dump -U essay essay_db > backup.sql  # DB 백업
```

## 통합 워크플로우

```
기출 PDF
   ↓ (analy_engine)
JSON 추출 → 교안 DOCX + 수업 PPT
   ↓
학생에게 배포 · 수업 진행
   ↓
학생 답안 이미지
   ↓ (eval_engine)
OCR → 멀티에이전트 첨삭 → 교사 검토 → PDF 리포트
```

## 개발 로드맵

### 완료 (MVP)
- [x] kihobot_x 통합 구조
- [x] eval_engine (essay_eval2 이관)
- [x] analy_engine (EOLE 이관)
- [x] 포털 홈 (두 엔진 진입)
- [x] Docker 통합 환경 (Python + Node.js + Poppler)

### 진행 중
- [ ] Gemini SDK 통일 (langchain 기준)
- [ ] DB 통합 (analy_engine 파일 기반 → DB)
- [ ] 문제 은행 공통화

### 계획
- [ ] 해설 리치 에디터 (Tiptap)
- [ ] 작업 잠금 (동시 편집 방지)
- [ ] 로그인/인증
- [ ] 작업 현황 대시보드 (단계별 · 선생님별)
- [ ] Cloudflare Tunnel 상시 운영

## 프로젝트 히스토리

- 2026-04: essay_eval2 + EOLE → kihobot_x 통합
- 이전: 두 프로젝트 독립 개발
