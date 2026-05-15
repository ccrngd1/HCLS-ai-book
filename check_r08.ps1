$f = 'C:\Users\lawsnic\OneDrive - amazon.com\Documents\HCLS-ai-book\chapter03.08-readmission-risk-anomaly-detection.md'
$c = Get-Content $f -Raw
$em = [char]0x2014
$en = [char]0x2013
Write-Host ('em-dash count: ' + ([regex]::Matches($c, $em)).Count)
Write-Host ('en-dash count: ' + ([regex]::Matches($c, $en)).Count)
Write-Host ('TODO comment count: ' + ([regex]::Matches($c, '<!-- TODO')).Count)
Write-Host ('evaluation_track present: ' + ($c -match 'evaluation_track'))
Write-Host ('cold_start_flag present: ' + ($c -match 'cold_start_flag'))
Write-Host ('engagement_decay_flag present: ' + ($c -match 'engagement_decay_flag'))
Write-Host ('processed-outcome-events present: ' + ($c -match 'processed-outcome-events'))
Write-Host ('DLQ mention count: ' + ([regex]::Matches($c, 'DLQ|dead.letter')).Count)
Write-Host ('per-cohort endpoint present: ' + ($c -match 'per-cohort.*endpoint'))
Write-Host ('worklist-bus minimal payload pattern: ' + ($c -match 'minimal.*payload|row_id.*only|only.*row_id'))
