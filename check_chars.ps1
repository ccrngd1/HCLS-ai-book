$path = 'C:\Users\lawsnic\OneDrive - amazon.com\Documents\HCLS-ai-book\chapter04.04-wellness-program-recommendations.md'
$lines = Get-Content -Path $path
$line214 = $lines[213]
Write-Output ("Length: " + $line214.Length)
foreach ($ch in $line214.ToCharArray()) {
    $code = [int][char]$ch
    if ($code -gt 127) {
        Write-Output ("Char: " + $ch + " | Hex: U+" + $code.ToString("X4"))
    }
}

Write-Output "---"
Write-Output "Line 151:"
$line151 = $lines[150]
foreach ($ch in $line151.ToCharArray()) {
    $code = [int][char]$ch
    if ($code -gt 127) {
        Write-Output ("Char: " + $ch + " | Hex: U+" + $code.ToString("X4"))
    }
}
