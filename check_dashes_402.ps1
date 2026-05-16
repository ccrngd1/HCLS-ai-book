$paths = @(
    'C:\Users\lawsnic\OneDrive - amazon.com\Documents\HCLS-ai-book\chapter04.02-patient-education-content-matching.md',
    'C:\Users\lawsnic\OneDrive - amazon.com\Documents\HCLS-ai-book\chapter04.02-python-example.md'
)
foreach ($p in $paths) {
    $content = Get-Content -Raw -Path $p
    $em = ([regex]::Matches($content, [char]0x2014)).Count
    $en = ([regex]::Matches($content, [char]0x2013)).Count
    Write-Output ("FILE: " + $p)
    Write-Output ("  EM_DASH_COUNT: " + $em)
    Write-Output ("  EN_DASH_COUNT: " + $en)
}
