param(
    [string]$ProjectPath = (Get-Location).Path,
    [switch]$IncludeData,
    [switch]$IncludeOutput
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

# ============================================================
# CONFIGURACIÃ“N
# ============================================================

$timestamp = Get-Date -Format "yyyyMMdd_HHmmss"
$projectRoot = (Resolve-Path $ProjectPath).Path.TrimEnd("\", "/")
$projectName = Split-Path $projectRoot -Leaf

$exportBase = Join-Path $projectRoot "_export"
$exportName = "${projectName}_${timestamp}"
$stagingPath = Join-Path $exportBase $exportName
$zipPath = Join-Path $exportBase "${exportName}.zip"

$maxTextFileSize = 2MB

# Carpetas excluidas por defecto.
$excludedDirectories = @(
    ".git",
    ".venv",
    "venv",
    "env",
    "__pycache__",
    ".pytest_cache",
    ".mypy_cache",
    ".ruff_cache",
    ".idea",
    ".vscode",
    "node_modules",
    "dist",
    "build",
    "_export"
)

if (-not $IncludeData) {
    $excludedDirectories += "data"
}

if (-not $IncludeOutput) {
    $excludedDirectories += "output"
}

# Nunca exportar secretos.
$excludedExactFiles = @(
    ".env"
)

# Archivos potencialmente sensibles o innecesarios.
$excludedExtensions = @(
    ".db-journal",
    ".sqlite-journal",
    ".pyc",
    ".pyo",
    ".log",
    ".tmp",
    ".temp"
)

# Extensiones que se incluirÃ¡n dentro de PROJECT_CONTEXT.md.
$textExtensions = @(
    ".py",
    ".html",
    ".htm",
    ".css",
    ".js",
    ".jsx",
    ".ts",
    ".tsx",
    ".json",
    ".yaml",
    ".yml",
    ".toml",
    ".ini",
    ".cfg",
    ".conf",
    ".md",
    ".txt",
    ".ps1",
    ".psm1",
    ".sh",
    ".bat",
    ".cmd",
    ".xml",
    ".sql",
    ".csv",
    ".env.example"
)

# ============================================================
# FUNCIONES
# ============================================================

function Get-RelativePath {
    param(
        [Parameter(Mandatory = $true)]
        [string]$FullPath
    )

    return $FullPath.Substring($projectRoot.Length).TrimStart("\", "/")
}

function Test-ExcludedPath {
    param(
        [Parameter(Mandatory = $true)]
        [string]$RelativePath,

        [Parameter(Mandatory = $true)]
        [System.IO.FileInfo]$File
    )

    $segments = $RelativePath -split "[\\/]"

    foreach ($segment in $segments) {
        if ($excludedDirectories -contains $segment) {
            return $true
        }
    }

    if ($excludedExactFiles -contains $File.Name) {
        return $true
    }

    if ($excludedExtensions -contains $File.Extension.ToLowerInvariant()) {
        return $true
    }

    return $false
}

function Test-TextFile {
    param(
        [Parameter(Mandatory = $true)]
        [System.IO.FileInfo]$File
    )

    if ($File.Name -eq ".gitignore") {
        return $true
    }

    if ($File.Name -eq ".env.example") {
        return $true
    }

    if ($File.Name -eq "requirements.txt") {
        return $true
    }

    return $textExtensions -contains $File.Extension.ToLowerInvariant()
}

function Get-LanguageName {
    param(
        [Parameter(Mandatory = $true)]
        [System.IO.FileInfo]$File
    )

    switch ($File.Extension.ToLowerInvariant()) {
        ".py"   { return "python" }
        ".html" { return "html" }
        ".htm"  { return "html" }
        ".css"  { return "css" }
        ".js"   { return "javascript" }
        ".jsx"  { return "jsx" }
        ".ts"   { return "typescript" }
        ".tsx"  { return "tsx" }
        ".json" { return "json" }
        ".yaml" { return "yaml" }
        ".yml"  { return "yaml" }
        ".toml" { return "toml" }
        ".xml"  { return "xml" }
        ".sql"  { return "sql" }
        ".ps1"  { return "powershell" }
        ".sh"   { return "bash" }
        ".bat"  { return "batch" }
        ".cmd"  { return "batch" }
        ".md"   { return "markdown" }
        default { return "text" }
    }
}

# ============================================================
# PREPARAR CARPETAS
# ============================================================

Write-Host ""
Write-Host "=============================================" -ForegroundColor Cyan
Write-Host " EXPORTADOR DE PROYECTO" -ForegroundColor Cyan
Write-Host "=============================================" -ForegroundColor Cyan
Write-Host "Proyecto: $projectRoot"
Write-Host ""

New-Item -ItemType Directory -Force -Path $exportBase | Out-Null
New-Item -ItemType Directory -Force -Path $stagingPath | Out-Null

if (Test-Path $zipPath) {
    Remove-Item $zipPath -Force
}

# ============================================================
# BUSCAR Y COPIAR ARCHIVOS
# ============================================================

$sourceFiles = Get-ChildItem `
    -Path $projectRoot `
    -File `
    -Recurse `
    -Force |
    ForEach-Object {
        $relativePath = Get-RelativePath -FullPath $_.FullName

        if (-not (Test-ExcludedPath -RelativePath $relativePath -File $_)) {
            [PSCustomObject]@{
                File         = $_
                RelativePath = $relativePath
            }
        }
    } |
    Sort-Object RelativePath

if (-not $sourceFiles) {
    throw "No se encontraron archivos para exportar."
}

foreach ($item in $sourceFiles) {
    $destination = Join-Path $stagingPath $item.RelativePath
    $destinationDirectory = Split-Path $destination -Parent

    if (-not (Test-Path $destinationDirectory)) {
        New-Item `
            -ItemType Directory `
            -Force `
            -Path $destinationDirectory | Out-Null
    }

    Copy-Item `
        -LiteralPath $item.File.FullName `
        -Destination $destination `
        -Force
}

Write-Host "[OK] Archivos copiados: $($sourceFiles.Count)" -ForegroundColor Green

# ============================================================
# GENERAR ESTRUCTURA DEL PROYECTO
# ============================================================

$treePath = Join-Path $stagingPath "PROJECT_TREE.txt"

$treeContent = @()
$treeContent += "PROYECTO: $projectName"
$treeContent += "GENERADO: $(Get-Date -Format 'yyyy-MM-dd HH:mm:ss')"
$treeContent += ""
$treeContent += "ARCHIVOS:"
$treeContent += ""

foreach ($item in $sourceFiles) {
    $treeContent += $item.RelativePath
}

$treeContent | Set-Content `
    -Path $treePath `
    -Encoding UTF8

# ============================================================
# GENERAR MANIFIESTO JSON
# ============================================================

$manifestPath = Join-Path $stagingPath "PROJECT_MANIFEST.json"

$manifestItems = foreach ($item in $sourceFiles) {
    $hash = Get-FileHash `
        -LiteralPath $item.File.FullName `
        -Algorithm SHA256

    [PSCustomObject]@{
        path          = $item.RelativePath
        size_bytes    = $item.File.Length
        extension     = $item.File.Extension
        sha256        = $hash.Hash
        last_modified = $item.File.LastWriteTime.ToString("yyyy-MM-dd HH:mm:ss")
    }
}

$manifest = [PSCustomObject]@{
    project_name      = $projectName
    generated_at      = (Get-Date).ToString("yyyy-MM-dd HH:mm:ss")
    total_files       = $sourceFiles.Count
    includes_data     = [bool]$IncludeData
    includes_output   = [bool]$IncludeOutput
    secrets_excluded  = @(".env")
    files             = $manifestItems
}

$manifest |
    ConvertTo-Json -Depth 10 |
    Set-Content -Path $manifestPath -Encoding UTF8

# ============================================================
# GENERAR CONTEXTO COMPLETO PARA CHATGPT / CODEX
# ============================================================

$contextPath = Join-Path $stagingPath "PROJECT_CONTEXT.md"
$builder = New-Object System.Text.StringBuilder

[void]$builder.AppendLine("# Contexto completo del proyecto")
[void]$builder.AppendLine("")
[void]$builder.AppendLine("- Proyecto: $projectName")
[void]$builder.AppendLine("- Generado: $(Get-Date -Format 'yyyy-MM-dd HH:mm:ss')")
[void]$builder.AppendLine("- Total de archivos: $($sourceFiles.Count)")
[void]$builder.AppendLine("- .env fue excluido para proteger secretos.")
[void]$builder.AppendLine("")
[void]$builder.AppendLine("## Estructura")
[void]$builder.AppendLine("")
[void]$builder.AppendLine("~~~~text")

foreach ($item in $sourceFiles) {
    [void]$builder.AppendLine($item.RelativePath)
}

[void]$builder.AppendLine("~~~~")
[void]$builder.AppendLine("")
[void]$builder.AppendLine("## Contenido de los archivos")
[void]$builder.AppendLine("")

foreach ($item in $sourceFiles) {
    $file = $item.File

    if (-not (Test-TextFile -File $file)) {
        [void]$builder.AppendLine("### $($item.RelativePath)")
        [void]$builder.AppendLine("")
        [void]$builder.AppendLine(
            "_Archivo binario incluido en el ZIP. TamaÃ±o: $($file.Length) bytes._"
        )
        [void]$builder.AppendLine("")
        continue
    }

    if ($file.Length -gt $maxTextFileSize) {
        [void]$builder.AppendLine("### $($item.RelativePath)")
        [void]$builder.AppendLine("")
        [void]$builder.AppendLine(
            "_Archivo omitido del contexto por superar $maxTextFileSize bytes. EstÃ¡ incluido en el ZIP._"
        )
        [void]$builder.AppendLine("")
        continue
    }

    try {
        $language = Get-LanguageName -File $file
        $content = Get-Content `
            -LiteralPath $file.FullName `
            -Raw `
            -Encoding UTF8

        [void]$builder.AppendLine("### $($item.RelativePath)")
        [void]$builder.AppendLine("")
        [void]$builder.AppendLine("~~~~$language")
        [void]$builder.AppendLine($content)
        [void]$builder.AppendLine("~~~~")
        [void]$builder.AppendLine("")
    }
    catch {
        [void]$builder.AppendLine("### $($item.RelativePath)")
        [void]$builder.AppendLine("")
        [void]$builder.AppendLine(
            "_No se pudo leer como texto: $($_.Exception.Message)_"
        )
        [void]$builder.AppendLine("")
    }
}

$builder.ToString() |
    Set-Content -Path $contextPath -Encoding UTF8

Write-Host "[OK] PROJECT_CONTEXT.md generado" -ForegroundColor Green

# ============================================================
# GENERAR PROMPT BASE PARA CODEX
# ============================================================

$codexPromptPath = Join-Path $stagingPath "CODEX_REVIEW_PROMPT.md"

$codexPrompt = @'
# RevisiÃ³n del proyecto Tech News Video Scraper

Analiza completamente este proyecto antes de modificar archivos.

## Contexto

Es una aplicaciÃ³n local en Python que:

- busca noticias de tecnologÃ­a e inteligencia artificial;
- filtra noticias fuera del tema;
- evita noticias repetidas mediante SQLite;
- detecta imÃ¡genes y videos;
- traduce informaciÃ³n al espaÃ±ol;
- genera cinco slides visuales;
- agrega una imagen de introducciÃ³n;
- agrega una imagen de salida;
- envÃ­a los slides a Telegram;
- guarda cada ejecuciÃ³n en una carpeta separada.

## Reglas de trabajo

1. No elimines funcionalidades que ya estÃ¡n operativas.
2. No cambies el diseÃ±o visual de los slides sin autorizaciÃ³n.
3. No expongas ni escribas tokens de Telegram.
4. Usa las variables de `.env`.
5. No incluyas `.env` en commits.
6. Revisa el cÃ³digo completo antes de proponer cambios.
7. Identifica duplicaciÃ³n, errores silenciosos y dependencias innecesarias.
8. MantÃ©n compatibilidad con Windows y PowerShell.
9. Ejecuta pruebas o validaciones antes de dar una tarea por terminada.
10. Explica quÃ© archivos cambiarÃ¡s antes de modificarlos.

## Primera tarea

Realiza primero una auditorÃ­a y entrega:

- resumen de la arquitectura actual;
- flujo completo desde la bÃºsqueda hasta Telegram;
- errores o riesgos encontrados;
- mejoras prioritarias;
- archivos que deberÃ­an modificarse;
- propuesta de implementaciÃ³n por etapas.

No modifiques todavÃ­a el cÃ³digo hasta finalizar esta auditorÃ­a.
'@

$codexPrompt |
    Set-Content -Path $codexPromptPath -Encoding UTF8

# ============================================================
# GENERAR RESUMEN
# ============================================================

$summaryPath = Join-Path $stagingPath "EXPORT_SUMMARY.txt"

$textFileCount = (
    $sourceFiles |
    Where-Object { Test-TextFile -File $_.File }
).Count

$binaryFileCount = $sourceFiles.Count - $textFileCount

$summary = @"
EXPORTACIÃ“N COMPLETADA

Proyecto: $projectName
Fecha: $(Get-Date -Format "yyyy-MM-dd HH:mm:ss")

Archivos originales exportados: $($sourceFiles.Count)
Archivos de texto: $textFileCount
Archivos binarios: $binaryFileCount

Incluye data: $([bool]$IncludeData)
Incluye output: $([bool]$IncludeOutput)

Archivos adicionales generados:
- PROJECT_TREE.txt
- PROJECT_MANIFEST.json
- PROJECT_CONTEXT.md
- CODEX_REVIEW_PROMPT.md
- EXPORT_SUMMARY.txt

Por seguridad no se incluyÃ³:
- .env
- .venv
- cachÃ©s de Python
- repositorio .git
"@

$summary |
    Set-Content -Path $summaryPath -Encoding UTF8

# ============================================================
# CREAR ZIP
# ============================================================

Compress-Archive `
    -Path (Join-Path $stagingPath "*") `
    -DestinationPath $zipPath `
    -CompressionLevel Optimal `
    -Force

$zipSizeMb = [math]::Round(
    (Get-Item $zipPath).Length / 1MB,
    2
)

Write-Host ""
Write-Host "=============================================" -ForegroundColor Green
Write-Host " EXPORTACIÃ“N COMPLETADA" -ForegroundColor Green
Write-Host "=============================================" -ForegroundColor Green
Write-Host ""
Write-Host "Carpeta preparada:"
Write-Host $stagingPath -ForegroundColor Yellow
Write-Host ""
Write-Host "ZIP para subir a ChatGPT o revisar:"
Write-Host $zipPath -ForegroundColor Yellow
Write-Host ""
Write-Host "TamaÃ±o ZIP: $zipSizeMb MB"
Write-Host ""
Write-Host "IMPORTANTE: el archivo .env no fue incluido." -ForegroundColor Cyan
