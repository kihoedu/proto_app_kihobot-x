# ═══════════════════════════════════════════════════════════════════
#  kihobot_x 팀원 공유 패키지 생성 스크립트
#  ─────────────────────────────────────────────────────────────────
#  용도: 팀원에게 배포할 zip 파일 생성
#
#  사용법:
#    PowerShell 창에서:
#      cd C:\projects\kihobot_x
#      .\make_share_zip.ps1
#
#  결과:
#    상위 폴더에 kihobot_x_share_YYYYMMDD.zip 생성됨
#    → 팀원에게 이 zip 파일 전달
# ═══════════════════════════════════════════════════════════════════

$ErrorActionPreference = "Stop"

$ProjectRoot = $PSScriptRoot
$Date = Get-Date -Format "yyyyMMdd"
$ZipName = "kihobot_x_share_$Date.zip"
$ZipPath = Join-Path (Split-Path $ProjectRoot -Parent) $ZipName
$StageDir = Join-Path $env:TEMP "kihobot_x_stage_$Date"

Write-Host "=" * 65 -ForegroundColor Cyan
Write-Host "  kihobot_x 팀원 공유 패키지 생성" -ForegroundColor Cyan
Write-Host "=" * 65 -ForegroundColor Cyan
Write-Host ""
Write-Host "프로젝트 경로: $ProjectRoot"
Write-Host "출력 zip:      $ZipPath"
Write-Host ""

# ── 스테이징 폴더 준비 ─────────────────────────────────────
if (Test-Path $StageDir) {
    Write-Host "기존 스테이징 폴더 삭제 중..." -ForegroundColor Yellow
    Remove-Item $StageDir -Recurse -Force
}
New-Item -ItemType Directory -Path $StageDir | Out-Null

# ── 복사 대상 정의 (포함할 것) ───────────────────────────
$IncludeItems = @(
    ".env.example",
    ".gitignore",
    ".dockerignore",
    "README.md",
    "INSTALL.md",
    "main.py",
    "requirements.txt",
    "package.json",
    "package-lock.json",
    "docker-compose.yml",
    "Dockerfile",
    "analy_engine",
    "common",
    "eval_engine",
    "portal"
)

# ── 제외 대상 (폴더 복사 시) ────────────────────────────
$ExcludePatterns = @(
    "__pycache__",
    "*.pyc",
    ".pytest_cache",
    "node_modules",
    ".venv",
    "venv",
    "*.log",
    ".DS_Store",
    "*.swp"
)

# ── 파일/폴더 복사 ─────────────────────────────────────
Write-Host "파일 복사 중..." -ForegroundColor Green
foreach ($item in $IncludeItems) {
    $src = Join-Path $ProjectRoot $item
    $dst = Join-Path $StageDir $item

    if (-not (Test-Path $src)) {
        Write-Host "  [건너뜀] $item (없음)" -ForegroundColor DarkYellow
        continue
    }

    if (Test-Path $src -PathType Container) {
        # 폴더: robocopy 로 제외 패턴 적용
        $excludeArgs = @()
        foreach ($pat in $ExcludePatterns) {
            $excludeArgs += "/XD"
            $excludeArgs += $pat
            $excludeArgs += "/XF"
            $excludeArgs += $pat
        }
        $null = robocopy $src $dst /E /NFL /NDL /NJH /NJS /NC /NS /NP @excludeArgs
        Write-Host "  [폴더]   $item/"
    } else {
        Copy-Item $src $dst -Force
        Write-Host "  [파일]   $item"
    }
}

# ── data 폴더는 구조만 (빈 폴더들) ───────────────────────
Write-Host "data/ 폴더 구조 생성 (.gitkeep만 포함)..." -ForegroundColor Green
$DataSubdirs = @("uploads", "outputs", "lesson_json", "lesson_md", "chroma_db")
foreach ($sub in $DataSubdirs) {
    $subPath = Join-Path $StageDir "data\$sub"
    New-Item -ItemType Directory -Path $subPath -Force | Out-Null
    New-Item -ItemType File -Path (Join-Path $subPath ".gitkeep") -Force | Out-Null
}

# ── .env 절대 포함되면 안 됨 (안전 체크) ─────────────────
$envPath = Join-Path $StageDir ".env"
if (Test-Path $envPath) {
    Write-Host "⚠️  .env 파일이 감지되어 삭제합니다!" -ForegroundColor Red
    Remove-Item $envPath -Force
}

# ── zip 압축 ───────────────────────────────────────────
if (Test-Path $ZipPath) {
    Write-Host "기존 zip 삭제..." -ForegroundColor Yellow
    Remove-Item $ZipPath -Force
}

Write-Host ""
Write-Host "zip 압축 중... (잠시만)" -ForegroundColor Green
Compress-Archive -Path "$StageDir\*" -DestinationPath $ZipPath -CompressionLevel Optimal

# ── 스테이징 폴더 정리 ──────────────────────────────────
Remove-Item $StageDir -Recurse -Force

# ── 결과 출력 ──────────────────────────────────────────
$size = (Get-Item $ZipPath).Length / 1MB
Write-Host ""
Write-Host "=" * 65 -ForegroundColor Cyan
Write-Host "  ✅ 완료!" -ForegroundColor Green
Write-Host "=" * 65 -ForegroundColor Cyan
Write-Host ""
Write-Host "  파일:   $ZipPath"
Write-Host "  크기:   $([math]::Round($size, 2)) MB"
Write-Host ""
Write-Host "다음 단계:" -ForegroundColor Yellow
Write-Host "  1. 팀원에게 이 zip 파일 전달 (드라이브/메일/슬랙)"
Write-Host "  2. 팀원은 zip 풀고 INSTALL.md 대로 설치"
Write-Host ""
