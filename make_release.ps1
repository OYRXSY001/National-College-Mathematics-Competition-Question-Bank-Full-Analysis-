# Builds a distributable zip for recipients.
# Usage: powershell -ExecutionPolicy Bypass -File make_release.ps1
$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $MyInvocation.MyCommand.Path
$stamp = Get-Date -Format "yyyyMMdd-HHmm"
$outName = "question-bank-portable-$stamp.zip"
$desktop = [Environment]::GetFolderPath("Desktop")
$outPath = Join-Path $desktop $outName

# dev-only directories that never ship to recipients
$excludeDirs = @(
    ".git", ".venv", "venv", "node_modules", "staticfiles",
    "__pycache__", ".zcode", ".workbuddy", ".agent-teams",
    ".claude", ".dsh-vision-toolkit", "data", "deploy", ".idea", ".vscode",
    # recipients only need the runnable web site; sources below stay as-is in the repo
    "微信小程序", "mini-program", "viz", "marketing", "scripts",
    # pyinstaller artifacts & build-only assets & seeded db staging
    "build", "dist", "packaging_tmp", "packaging_assets"
)
# *.sqlite3* 挡掉开发库/备份/临时库——发布包一律不带真实用户数据，
# 数据文件统一用下面注入的 packaging_tmp 干净种子库
$excludeFilePatterns = @("*.pyc", "*.log", "*.sqlite3*", ".env", "splash", "package.json", "package-lock.json", "make_release.ps1", "smoke-*.png", "exam-result.png", ".bank.lock")

if (Test-Path $outPath) { Remove-Item $outPath -Force }

Add-Type -AssemblyName System.IO.Compression
Add-Type -AssemblyName System.IO.Compression.FileSystem
$zip = [System.IO.Compression.ZipFile]::Open($outPath, [System.IO.Compression.ZipArchiveMode]::Create)
try {
    # surface the quick-start guide at the root of the archive
    $guideSrc = Join-Path $root "使用者必看.md"
    if (-not (Test-Path $guideSrc)) { $guideSrc = Join-Path $root "docs\deploy-guide.md" }
    if (Test-Path $guideSrc) {
        [System.IO.Compression.ZipFileExtensions]::CreateEntryFromFile(
            $zip, $guideSrc, "_READ_ME_FIRST.md") | Out-Null
    }

    # 数据库：注入清空了用户数据的种子库（scripts/prepare_seed_db.py 的产物），
    # 方式一/二的收件人 migrate 后即有全量题库；绝不携带开发库里的真实账号与作答记录
    $seedDb = Join-Path $root "packaging_tmp\db.sqlite3"
    if (Test-Path $seedDb) {
        [System.IO.Compression.ZipFileExtensions]::CreateEntryFromFile(
            $zip, $seedDb, "db.sqlite3") | Out-Null
    }
    else {
        Write-Warning "未找到 packaging_tmp\db.sqlite3 —— 请先运行 scripts/prepare_seed_db.py，否则 zip 里没有题库数据！"
    }

    Get-ChildItem -LiteralPath $root -Recurse -Force | ForEach-Object {
        $full = $_.FullName
        if ($full -eq $outPath) { return }
        foreach ($d in $excludeDirs) {
            if ($full -like "*\$d" -or $full -like "*\$d\*") { return }
        }
        if (-not $_.PSIsContainer) {
            foreach ($p in $excludeFilePatterns) {
                if ($_.Name -like $p) { return }
            }
            $rel = $full.Substring($root.Length + 1)
            [System.IO.Compression.ZipFileExtensions]::CreateEntryFromFile($zip, $full, $rel) | Out-Null
        }
    }
}
finally { $zip.Dispose() }

$sizeMb = [math]::Round((Get-Item $outPath).Length / 1MB, 1)
Write-Host ""
Write-Host "Done: $outPath  ($sizeMb MB)"
Write-Host "Send this zip to recipients. They only need Python 3.11+ installed."
