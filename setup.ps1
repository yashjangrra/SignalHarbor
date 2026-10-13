# Windows: powershell -ExecutionPolicy Bypass -File setup.ps1
$ErrorActionPreference = 'Stop'
Set-Location $PSScriptRoot
foreach ($candidate in @('python', 'python3')) {
    $command = Get-Command $candidate -ErrorAction SilentlyContinue
    if ($command) {
        & $command.Source -c 'import sys,venv;sys.exit(sys.version_info < (3,12))' 2>$null
        if ($LASTEXITCODE -eq 0) {
            & $command.Source (Join-Path $PSScriptRoot 'setup.py') @args
            exit $LASTEXITCODE
        }
    }
}
$uv = Get-Command uv -ErrorAction SilentlyContinue
$uvPath = Join-Path $HOME '.local\bin\uv.exe'
if ($uv) { $uvPath = $uv.Source }
if (-not (Test-Path $uvPath)) {
    $env:UV_INSTALL_DIR = Join-Path $HOME '.local\bin'
    $env:UV_NO_MODIFY_PATH = '1'
    $installer = Join-Path ([System.IO.Path]::GetTempPath()) ([System.IO.Path]::GetRandomFileName() + '.ps1')
    try {
        Invoke-WebRequest 'https://astral.sh/uv/install.ps1' -OutFile $installer
        & $installer
    } finally { Remove-Item $installer -ErrorAction SilentlyContinue }
}
& $uvPath python install 3.12
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
& $uvPath run --no-project --python 3.12 (Join-Path $PSScriptRoot 'setup.py') @args
exit $LASTEXITCODE
