$ErrorActionPreference = 'Stop'
$projectRoot = Split-Path -Parent $PSScriptRoot
Push-Location $projectRoot
try {
    $uvPath = Join-Path $projectRoot '.tools/uv/bin/uv.exe'
    if (-not (Test-Path -LiteralPath $uvPath)) {
        python -m pip install --target .tools/uv 'uv==0.13.1' --disable-pip-version-check
        if ($LASTEXITCODE -ne 0) { throw 'uv 설치 실패' }
    }
    $pythonVersion = (Get-Content -LiteralPath '.python-version' -Raw).Trim()
    & $uvPath python install $pythonVersion --install-dir .tools/python --cache-dir .cache/uv --no-bin --no-registry --no-progress
    if ($LASTEXITCODE -ne 0) { throw 'Python 설치 실패' }
    $pythonPath = Join-Path $projectRoot ('.tools/python/cpython-' + $pythonVersion + '-windows-x86_64-none/python.exe')
    & $uvPath sync --locked --python $pythonPath --all-groups --cache-dir .cache/uv --no-progress
    if ($LASTEXITCODE -ne 0) { throw '의존성 설치 실패' }
    Write-Output '개발 환경 준비 완료: .venv/Scripts/python.exe'
} finally {
    Pop-Location
}
