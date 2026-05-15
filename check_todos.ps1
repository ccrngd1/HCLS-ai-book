$path = 'C:\Users\lawsnic\OneDrive - amazon.com\Documents\HCLS-ai-book\chapter03.07-patient-deterioration-early-warning.md'
$content = [System.IO.File]::ReadAllText($path, [System.Text.Encoding]::UTF8)
# Skip the editor-comment block at the very top (until first H1)
$h1Index = $content.IndexOf("`n# Recipe")
$bodyOnly = $content.Substring($h1Index)
$matches = [regex]::Matches($bodyOnly, '<!-- TODO \(TechWriter')
Write-Output ("TODO markers in body (after editor block): " + $matches.Count)
