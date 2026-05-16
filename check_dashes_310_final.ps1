$content = Get-Content -Raw -Path 'C:\Users\lawsnic\OneDrive - amazon.com\Documents\HCLS-ai-book\chapter03.10-epidemic-outbreak-detection.md' -Encoding UTF8
$emDash = [char]0x2014
$enDash = [char]0x2013
$emCount = 0
$enCount = 0
foreach ($c in $content.ToCharArray()) {
    if ($c -eq $emDash) { $emCount++ }
    if ($c -eq $enDash) { $enCount++ }
}
Write-Host ("Em dashes (U+2014): {0}" -f $emCount)
Write-Host ("En dashes (U+2013): {0}" -f $enCount)
Write-Host ("File length: {0}" -f $content.Length)
