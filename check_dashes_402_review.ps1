param([string]$Path)
$content = Get-Content -Raw -Encoding UTF8 -LiteralPath $Path
$emCount = ([regex]::Matches($content, [string][char]0x2014)).Count
$enCount = ([regex]::Matches($content, [string][char]0x2013)).Count
Write-Host "File: $Path"
Write-Host "em-dashes (U+2014): $emCount"
Write-Host "en-dashes (U+2013): $enCount"

# Show a few lines containing dashes if any
$lines = Get-Content -Encoding UTF8 -LiteralPath $Path
for ($i = 0; $i -lt $lines.Count; $i++) {
    $line = $lines[$i]
    if ($line -match [string][char]0x2014) {
        Write-Host "  EM-DASH at line $($i+1): $line"
    }
    if ($line -match [string][char]0x2013) {
        Write-Host "  EN-DASH at line $($i+1): $line"
    }
}
