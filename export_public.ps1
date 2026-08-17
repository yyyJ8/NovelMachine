# ============================================================
# export_public.ps1 - Export private workspace -> public repo (NovelMachine)
#
# Usage:
#   pwsh -File export_public.ps1
#   pwsh -File export_public.ps1 -Dst "D:\somewhere"
#
# Copies files per PUBLIC_MANIFEST + copies public templates
# (LICENSE/README/CLAUDE/.gitignore) + strips book-specific examples.
# ============================================================
param(
    [string]$Src = "D:\novel\novel",
    [string]$Dst = "D:\novel\novel\.dist\NovelMachine",
    [switch]$Git,   # after export: git add + commit
    [switch]$Push   # after export: git push (requires -Git)
)
$ErrorActionPreference = 'Stop'

Write-Host "== Export: $Src -> $Dst =="

# 1. Prepare target dir (clean, keep .git)
if (Test-Path $Dst) {
    Get-ChildItem $Dst -Force | Where-Object { $_.Name -ne '.git' } | Remove-Item -Recurse -Force
} else {
    New-Item -ItemType Directory -Path $Dst -Force | Out-Null
}

# 2. Public manifest (keep in sync with PUBLIC_MANIFEST.md)
$public = @(
    'novel_rag', '_agents', '_templates', '_workflows',
    'cli.py', 'rag_query.py',
    'requirements.txt', 'pyproject.toml',
    '.env.example', 'config', 'docs', 'tests',
    'RAG_DESIGN.md', 'AGENT_REVIEW.md',
    'PUBLIC_MANIFEST.md', 'export_public.ps1', '_public_templates'
)
foreach ($p in $public) {
    $s = Join-Path $Src $p
    if (Test-Path $s) {
        Copy-Item $s (Join-Path $Dst $p) -Recurse -Force
        Write-Host "  [copy] $p"
    } else {
        Write-Host "  [skip-missing] $p" -ForegroundColor Yellow
    }
}

# 3. Copy public templates (standalone UTF-8 files under _public_templates/)
$templates = @('LICENSE', 'README.md', 'CLAUDE.md', '.gitignore')
foreach ($t in $templates) {
    $tpl = Join-Path $Src "_public_templates\$t"
    if (Test-Path $tpl) {
        Copy-Item $tpl (Join-Path $Dst $t) -Force
        Write-Host "  [template] $t"
    } else {
        Write-Host "  [skip-template-missing] $t" -ForegroundColor Yellow
    }
}

# 4. Strip book-specific example in schema
$events = Join-Path $Dst '_templates\schema\events.yaml'
if (Test-Path $events) {
    $c = [System.IO.File]::ReadAllText($events, [System.Text.Encoding]::UTF8)
    if ($c.Contains('林尘')) {
        $c = $c.Replace('林尘', '主角')
        [System.IO.File]::WriteAllText($events, $c, (New-Object System.Text.UTF8Encoding($false)))
        Write-Host '  [process] events.yaml example: 林尘 -> 主角'
    }
}

Write-Host ''
Write-Host "== Export done: $Dst =="

# 5. Optional git commit / push
if ($Git) {
    Push-Location $Dst
    try {
        if (-not (Test-Path '.git')) {
            git init -b main | Out-Null
        }
        git add -A
        git commit -m 'chore: export public snapshot' --no-verify 2>&1 | Out-Null
        Write-Host '  [git] committed'
        if ($Push) {
            git push origin main 2>&1
            Write-Host '  [git] pushed'
        }
    } finally {
        Pop-Location
    }
}
