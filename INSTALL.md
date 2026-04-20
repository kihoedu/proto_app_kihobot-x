# kihobot_x 설치 가이드 (팀원용)

박기호논술 통합 플랫폼을 로컬에서 실행하기 위한 5단계 설치 가이드입니다.

---

## 준비물 (사전 설치)

아래 세 가지가 컴퓨터에 설치돼 있어야 합니다. 이미 있으면 건너뛰세요.

### 1) Python 3.11 이상
- 다운로드: https://www.python.org/downloads/
- 설치 시 **"Add Python to PATH" 꼭 체크**

확인:
```powershell
python --version
```
→ `Python 3.11.x` 같은 버전이 보이면 OK

### 2) Node.js 20 이상 (교안 DOCX 생성용)
- 다운로드: https://nodejs.org/
- LTS 버전 선택

확인:
```powershell
node -v
```
→ `v20.x.x` 이상이면 OK

### 3) Poppler (PDF 변환용)
- 다운로드: https://github.com/oschwartz10612/poppler-windows/releases
- 최신 zip 다운로드 → 원하는 위치에 압축 해제
- 예: `C:\poppler-24.08.0\`
- 나중에 `.env`에 이 경로를 입력해야 합니다

### 4) Gemini API 키
- 발급: https://aistudio.google.com/apikey
- "Create API key" 클릭해서 키 발급 (무료)
- 키 문자열 복사해 메모장 등에 잠시 저장

---

## 설치 5단계

### ① 프로젝트 압축 해제

받으신 `kihobot_x_share_YYYYMMDD.zip` 파일을 원하는 위치에 압축 해제하세요.

예: `C:\projects\kihobot_x\`

### ② PowerShell에서 프로젝트 폴더로 이동

```powershell
cd C:\projects\kihobot_x
```

### ③ 가상환경 생성 & 패키지 설치

```powershell
# 파이썬 가상환경 생성
python -m venv venv

# 가상환경 활성화
.\venv\Scripts\Activate.ps1

# Python 패키지 설치 (몇 분 소요)
pip install -r requirements.txt

# Node.js 패키지 설치
npm install
```

가상환경 활성화가 성공하면 프롬프트 앞에 `(venv)`가 붙습니다:
```
(venv) C:\projects\kihobot_x>
```

> **참고**: PowerShell에서 `Activate.ps1` 실행 시 권한 에러가 나면 한 번만 아래를 실행하세요:
> ```powershell
> Set-ExecutionPolicy -Scope CurrentUser -ExecutionPolicy RemoteSigned
> ```

### ④ 환경변수 설정

`.env.example` 파일을 복사해서 `.env`로 이름 바꾼 뒤 편집:

```powershell
copy .env.example .env
notepad .env
```

아래 두 줄만 수정하면 됩니다:

```bash
# Gemini API 키 입력
GEMINI_API_KEY=여기에_발급받은_키_붙여넣기

# Poppler 설치 경로 입력
POPPLER_PATH=C:\poppler-24.08.0\Library\bin
```

> 나머지 값들(`GEMINI_MODEL`, `KIHOBOT_ENV` 등)은 기본값 그대로 두면 됩니다.

### ⑤ 실행

```powershell
python main.py
```

아래 로그가 뜨면 성공:

```
============================================================
  🤖 kihobot_x 통합 플랫폼 기동
============================================================
  포털 홈:   http://localhost:8000/
  평가엔진:  http://localhost:8000/eval/
  분석엔진:  http://localhost:8000/analy/
============================================================
```

브라우저에서 **http://localhost:8000** 접속!

---

## 서비스 소개

포털 홈에서 두 엔진으로 진입 가능:

- **평가엔진 (`/eval/`)** — 학생 답안 OCR → 첨삭 → PDF 리포트
- **분석엔진 (`/analy/`)** — 기출 PDF → 교안 DOCX + 수업 PPT

---

## 다음 실행부터

설치 후 두 번째부터는 아래 두 줄만 실행하면 됩니다:

```powershell
cd C:\projects\kihobot_x
.\venv\Scripts\Activate.ps1
python main.py
```

종료는 `Ctrl + C`.

---

## 문제 해결

### `ModuleNotFoundError: No module named 'xxx'`
가상환경에서 다시 설치:
```powershell
.\venv\Scripts\Activate.ps1
pip install -r requirements.txt
```

### `pdftotext` 관련 에러
`.env`의 `POPPLER_PATH` 경로가 맞는지 확인. 경로 안에 `pdftotext.exe`가 있어야 합니다.

### Gemini API 에러
`.env`의 `GEMINI_API_KEY`가 올바른지 확인. https://aistudio.google.com/apikey 에서 키 상태 확인 가능.

### 포트 8000 이미 사용 중
다른 포트로 실행:
```powershell
$env:PORT=8080; python main.py
```

### 그 외 문제
박기호 선생님께 문의하거나, 에러 메시지 전체를 복사해서 공유해주세요.

---

## 참고

- 프로젝트 전체 구조는 `README.md` 참고
- 민감 정보(`.env`, API 키)는 절대 다른 사람에게 공유하지 마세요
