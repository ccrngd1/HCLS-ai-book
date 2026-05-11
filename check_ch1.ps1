$files = Get-ChildItem -Path 'C:\Users\lawsnic\OneDrive - amazon.com\Documents\HCLS-ai-book' -Filter 'chapter01.*.md'
$emDash = [char]0x2014
$enDash = [char]0x2013

foreach ($file in $files) {
    $content = [System.IO.File]::ReadAllText($file.FullName, [System.Text.Encoding]::UTF8)
    $emCount = 0
    $enCount = 0
    for ($i = 0; $i -lt $content.Length; $i++) {
        if ($content[$i] -eq $emDash) { $emCount++ }
        if ($content[$i] -eq $enDash) { $enCount++ }
    }
    if ($emCount -gt 0 -or $enCount -gt 0) {
        Write-Output "$($file.Name): em=$emCount en=$enCount"
    }
}
