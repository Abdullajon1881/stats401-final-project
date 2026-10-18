# Export a .docx to PDF with Microsoft Word, so the PDF matches the Word file exactly.
#
#   powershell -ExecutionPolicy Bypass -File submission/tools/export_pdf.ps1 `
#       -Docx submission/report/Tashkent_Transit_Walkability_Final_Report.docx
#
# Requires Microsoft Word on Windows. The PDF is written next to the .docx.
param([Parameter(Mandatory = $true)][string]$Docx)

$docxPath = (Resolve-Path $Docx).Path
$pdfPath = [System.IO.Path]::ChangeExtension($docxPath, '.pdf')
$word = New-Object -ComObject Word.Application
$word.Visible = $false
$word.DisplayAlerts = 0
try {
    $doc = $word.Documents.Open($docxPath, $false, $true)
    $doc.Fields.Update() | Out-Null
    # 17 = wdExportFormatPDF; optimise for print; create heading bookmarks.
    $doc.ExportAsFixedFormat($pdfPath, 17, $false, 0, 0, 1, 1, 0, $true, $true, 1, $true, $true, $false)
    $pages = $doc.ComputeStatistics(2)
    $words = $doc.ComputeStatistics(0)
    $doc.Close($false)
    Write-Output "wrote $pdfPath ($pages pages, Word count incl. tables/captions: $words)"
}
finally {
    $word.Quit()
    [System.Runtime.InteropServices.Marshal]::ReleaseComObject($word) | Out-Null
}
