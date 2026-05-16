$path = 'C:\Users\lawsnic\OneDrive - amazon.com\Documents\HCLS-ai-book\chapter04.05-medication-adherence-intervention-targeting.md'
# Read as UTF-8 explicitly
$content = [System.IO.File]::ReadAllText($path, [System.Text.Encoding]::UTF8)

$em2014 = 0
$en2013 = 0
foreach ($ch in $content.ToCharArray()) {
    $cp = [int][char]$ch
    if ($cp -eq 0x2014) { $em2014++ }
    elseif ($cp -eq 0x2013) { $en2013++ }
}
Write-Output "Em dashes (U+2014) UTF-8: $em2014"
Write-Output "En dashes (U+2013) UTF-8: $en2013"
