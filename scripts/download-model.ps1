<#
  Descarga modelos GGUF de Qwen3 (oficiales de Qwen en HuggingFace) a .\models\

  Ejemplos:
    .\download-model.ps1                      # Qwen3-4B Q4_K_M (recomendado, ~2.5GB)
    .\download-model.ps1 -Size 8B             # Máxima calidad (Orin NX 16GB lo aguanta)
    .\download-model.ps1 -Size 0.6B           # Draft p/ decodificación especulativa
    .\download-model.ps1 -Endpoint https://hf-mirror.com   # Espejo si HF está bloqueado (China)
#>
[CmdletBinding()]
param(
    [ValidateSet("0.6B", "1.7B", "4B", "8B")]
    [string]$Size = "4B",

    [ValidateSet("Q4_K_M", "Q5_K_M", "Q6_K", "Q8_0")]
    [string]$Quant = "Q4_K_M",

    [string]$Endpoint = $(if ($env:HF_ENDPOINT) { $env:HF_ENDPOINT } else { "https://huggingface.co" }),

    [string]$OutDir = $(Join-Path $PSScriptRoot "..\models")
)

$ErrorActionPreference = "Stop"

$repo = "Qwen/Qwen3-$Size-GGUF"
$file = "Qwen3-$Size-$Quant.gguf"
$url  = "$($Endpoint.TrimEnd('/'))/$repo/resolve/main/$file"
New-Item -ItemType Directory -Force -Path $OutDir | Out-Null
$dest = Join-Path $OutDir $file

if (Test-Path $dest) {
    Write-Host "Ya existe: $dest" -ForegroundColor Yellow
    Write-Host "(bórralo si quieres re-descargar; curl reanudaría descargas parciales)"
    exit 0
}

Write-Host "Descargando $file"
Write-Host "  URL:  $url"
Write-Host "  Dest: $dest"

if (Get-Command curl.exe -ErrorAction SilentlyContinue) {
    # -C - reanuda descargas interrumpidas; --fail evita guardar páginas de error
    curl.exe -L --fail --retry 3 --retry-delay 2 -C - --progress-bar -o $dest $url
    if ($LASTEXITCODE -ne 0) { throw "curl.exe falló con código $LASTEXITCODE. ¿Existe $file en $repo con esa cuantización?" }
} else {
    $ProgressPreference = "SilentlyContinue"  # IWR es muy lento con la barra activa
    Invoke-WebRequest -Uri $url -OutFile $dest
}

$sizeMB = [math]::Round((Get-Item $dest).Length / 1MB, 1)
Write-Host "OK: $dest ($sizeMB MB)" -ForegroundColor Green
Write-Host "Ajusta MODEL_PATH=/models/$file en tu .env si no es el modelo por defecto."
