$ErrorActionPreference = 'Stop'
$projectRoot = Split-Path -Parent $PSScriptRoot
Set-Location -LiteralPath $projectRoot
$python = Join-Path $projectRoot '.venv\Scripts\python.exe'
$compiler = Join-Path $projectRoot '.tools\inno\ISCC.exe'
$env:PYTHONUTF8 = '1'
$env:QT_QPA_PLATFORM = 'offscreen'
function Run-Checked([string[]]$Arguments) {
    & $python @Arguments
    if ($LASTEXITCODE -ne 0) { throw ('검증 또는 빌드 실패: ' + ($Arguments -join ' ')) }
}
Run-Checked @('-m', 'ruff', 'check', '.')
Run-Checked @('-m', 'pytest', '-q')
Run-Checked @('scripts/prepare_package.py')
Run-Checked @('-m', 'PyInstaller', '--noconfirm', 'packaging/YouTubeLiveRecorder.spec')
Run-Checked @('scripts/verify_package.py')
if (-not (Test-Path -LiteralPath $compiler)) {
    throw 'Inno Setup 컴파일러가 없습니다. scripts/fetch_inno.ps1을 먼저 실행하세요. 실행 폴더 검증은 완료했습니다.'
}
& $compiler 'packaging/installer.iss'
if ($LASTEXITCODE -ne 0) { throw 'Setup.exe 생성에 실패했습니다.' }
$setup = Join-Path $projectRoot 'dist\installer\YouTubeLiveRecorder-0.3.3-Setup.exe'
$setupHash = (Get-FileHash -LiteralPath $setup -Algorithm SHA256).Hash.ToLowerInvariant()
Set-Content -LiteralPath ($setup + '.sha256') -Value ($setupHash + '  ' + [IO.Path]::GetFileName($setup)) -Encoding ascii
Write-Output $setupHash
