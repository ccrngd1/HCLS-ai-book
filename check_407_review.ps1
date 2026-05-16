$paths = @(
    'C:\Users\lawsnic\OneDrive - amazon.com\Documents\HCLS-ai-book\chapter04.07-care-management-program-enrollment.md',
    'C:\Users\lawsnic\OneDrive - amazon.com\Documents\HCLS-ai-book\chapter04.07-python-example.md'
)
foreach ($p in $paths) {
    $c = [System.IO.File]::ReadAllText($p)
    $em = ([regex]::Matches($c, [string][char]0x2014)).Count
    $en = ([regex]::Matches($c, [string][char]0x2013)).Count
    Write-Host "$p em=$em en=$en"
}
