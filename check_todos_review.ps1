$path = 'C:\Users\lawsnic\OneDrive - amazon.com\Documents\HCLS-ai-book\chapter03.07-patient-deterioration-early-warning.md'
$matches = Select-String -Path $path -Pattern 'TODO'
foreach ($m in $matches) {
  Write-Output ("{0,5}: {1}" -f $m.LineNumber, $m.Line.Trim())
}
Write-Output "----"
Write-Output ("Total TODOs: " + $matches.Count)
