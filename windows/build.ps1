param([switch]$SkipTests)
$ErrorActionPreference = 'Stop'
$Root = Split-Path -Parent $PSScriptRoot
$Out = Join-Path $Root 'deliverables'
$Stage = Join-Path $Root '.artifacts\windows-alpha\payload'
$HostOut = Join-Path $Stage 'app'
$Dotnet = if ($env:INTENT_DOTNET) { $env:INTENT_DOTNET } else { (Get-Command dotnet -ErrorAction Stop).Source }
$Node = if ($env:INTENT_NODE) { $env:INTENT_NODE } else { (Get-Command node -ErrorAction Stop).Source }
$Python = if ($env:INTENT_PYTHON) { $env:INTENT_PYTHON } else { Join-Path $Root '.venv\Scripts\python.exe' }
Remove-Item -Recurse -Force $Out,$Stage -ErrorAction SilentlyContinue
New-Item -ItemType Directory -Force $Out,$HostOut | Out-Null

if (-not $SkipTests) {
  & $Python -m pytest
  if ($LASTEXITCODE -ne 0) { throw "Python tests failed ($LASTEXITCODE)." }
  $JsTests = @(Get-ChildItem (Join-Path $Root 'ui\ids\tests\*.test.js')) +
    @(Get-Item (Join-Path $Root 'ui\shell\tests\shell.test.js')) +
    @(Get-ChildItem (Join-Path $Root 'ui\shell\product\*.test.js'))
  & $Node --test @($JsTests.FullName)
  if ($LASTEXITCODE -ne 0) { throw "JavaScript tests failed ($LASTEXITCODE)." }
  & $Node --check (Join-Path $Root 'ui\shell\product\product.js')
  if ($LASTEXITCODE -ne 0) { throw "Product UI syntax check failed ($LASTEXITCODE)." }
}
& $Python -m PyInstaller --noconfirm --clean (Join-Path $Root 'product_bridge.spec') `
  --distpath $HostOut --workpath (Join-Path $Root '.artifacts\windows-alpha\bridge-build')
if ($LASTEXITCODE -ne 0) { throw "Product bridge publish failed ($LASTEXITCODE)." }
& $Python (Join-Path $Root 'tests\smoke_packaged_bridge.py') (Join-Path $HostOut 'IntentOS.Bridge.exe')
if ($LASTEXITCODE -ne 0) { throw "Packaged Unicode bridge smoke test failed ($LASTEXITCODE)." }
& $Dotnet publish (Join-Path $PSScriptRoot 'host\IntentOS.WindowsHost.csproj') -c Release -r win-x64 `
  --self-contained true -p:PublishSingleFile=true -p:IncludeNativeLibrariesForSelfExtract=true -o $HostOut
if ($LASTEXITCODE -ne 0) { throw "Windows host publish failed ($LASTEXITCODE)." }
Get-ChildItem $HostOut -File | Where-Object Extension -in '.pdb', '.xml' | Remove-Item -Force
Copy-Item -Recurse (Join-Path $Root 'ui') (Join-Path $Stage 'ui')
Copy-Item (Join-Path $PSScriptRoot 'version.json') (Join-Path $Stage 'version.json')
New-Item -ItemType Directory -Force (Join-Path $Stage 'assets'),(Join-Path $Stage 'runtime') | Out-Null

$Portable = Join-Path $Out 'IntentOS-Product-Alpha-2.1.4-Portable.zip'
Compress-Archive -Path (Join-Path $Stage '*') -DestinationPath $Portable -CompressionLevel Optimal
Copy-Item $Portable (Join-Path $PSScriptRoot 'installer\Payload.zip') -Force
& $Dotnet publish (Join-Path $PSScriptRoot 'installer\IntentOS.Installer.csproj') -c Release -r win-x64 `
  --self-contained true -p:PublishSingleFile=true -p:IncludeNativeLibrariesForSelfExtract=true `
  -o (Join-Path $Root '.artifacts\windows-alpha\installer')
if ($LASTEXITCODE -ne 0) { throw "Windows installer publish failed ($LASTEXITCODE)." }
Copy-Item (Join-Path $Root '.artifacts\windows-alpha\installer\IntentOS-Alpha-Windows-Setup.exe') `
  (Join-Path $Out 'IntentOS-Product-Alpha-2.1.4-Setup.exe')

Get-ChildItem $Out -File | Get-FileHash -Algorithm SHA256 | ForEach-Object { "$($_.Hash)  $($_.Path | Split-Path -Leaf)" } |
  Set-Content -Encoding ascii (Join-Path $Out 'CHECKSUMS.txt')
Get-ChildItem $Stage -Recurse -File | ForEach-Object { $_.FullName.Substring($Stage.Length + 1) } |
  Set-Content -Encoding utf8 (Join-Path $Out 'INSTALLED_FILES_MANIFEST.txt')
Copy-Item (Join-Path $Root 'docs\windows\INSTALL_WINDOWS.md') $Out
Copy-Item (Join-Path $Root 'docs\windows\MANUAL_TEST_PRODUCT_ALPHA_2_1_4.md') $Out
Copy-Item (Join-Path $Root 'docs\windows\PRODUCT_ALPHA_2_1_4_REPORT.md') $Out
