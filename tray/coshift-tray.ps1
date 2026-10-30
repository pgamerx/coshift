# Coshift tray for Windows: an icon by the clock with every account's limits, a menu to start
# Claude Code as an account, and a pop-up when a session needs you. Nothing to install beyond
# Windows PowerShell (built in) and Python. Started at login by `coshift tray install`.
# ASCII only on purpose: Windows PowerShell 5.1 misreads UTF-8 files without a BOM.
param([string]$Board = "$env:USERPROFILE\.coshift\board.py")

Add-Type -AssemblyName System.Windows.Forms
Add-Type -AssemblyName System.Drawing

$py = $null; $pyArgs = @()
foreach ($c in @("py", "python", "python3")) {
  if (Get-Command $c -ErrorAction SilentlyContinue) { $py = $c; if ($c -eq "py") { $pyArgs = @("-3") }; break }
}

# a small orange dot as the icon
$bmp = New-Object System.Drawing.Bitmap 16, 16
$g = [System.Drawing.Graphics]::FromImage($bmp)
$g.SmoothingMode = [System.Drawing.Drawing2D.SmoothingMode]::AntiAlias
$g.FillEllipse((New-Object System.Drawing.SolidBrush ([System.Drawing.Color]::FromArgb(224, 128, 94))), 2, 2, 12, 12)
$g.Dispose()

$icon = New-Object System.Windows.Forms.NotifyIcon
$icon.Icon = [System.Drawing.Icon]::FromHandle($bmp.GetHicon())
$icon.Text = "Coshift"
$icon.Visible = $true
$menu = New-Object System.Windows.Forms.ContextMenuStrip
$icon.ContextMenuStrip = $menu
$script:seen = $null

function Read-Board {
  if (-not $py) { return $null }
  $out = & $py @pyArgs $Board tray-json 2>$null
  if ($LASTEXITCODE -ne 0 -or -not $out) { return $null }
  try { return (($out | Out-String) | ConvertFrom-Json) } catch { return $null }
}

function Refresh-Tray {
  $s = Read-Board
  $menu.Items.Clear()
  if (-not $s) {
    [void]$menu.Items.Add($(if ($py) { "Coshift isn't set up yet: run coshift setup" } else { "Python not found: install Python 3.9+" }))
    $icon.Text = "Coshift"
  } else {
    $tip = @()
    foreach ($a in $s.accounts) {
      $line = "{0}   5h {1}%  -  week {2}%" -f $a.name, $a.five_hour_pct, $a.weekly_pct
      if ($a.stop) { $line += "  (stopped)" }
      $n = $a.name
      $item = $menu.Items.Add($line)
      $item.add_Click({ Start-Process "cmd.exe" -ArgumentList "/k", "coshift run $n" }.GetNewClosure())
      $tip += ("{0} {1}/{2}%" -f $a.name, $a.five_hour_pct, $a.weekly_pct)
    }
    $u = $s.url
    if (@($s.needs).Count -gt 0) {
      $first = @($s.needs)[0]
      $item = $menu.Items.Add(("! {0} need you: #{1} {2}" -f @($s.needs).Count, $first.id, $first.title))
      $item.add_Click({ Start-Process $u }.GetNewClosure())
    }
    [void]$menu.Items.Add("-")
    $item = $menu.Items.Add("Start Claude Code (most limit left)")
    $item.add_Click({ Start-Process "cmd.exe" -ArgumentList "/k", "coshift run" })
    $item = $menu.Items.Add("Open Coshift board")
    $item.add_Click({ Start-Process $u }.GetNewClosure())
    $t = "Coshift  " + ($tip -join "  ")
    if ($t.Length -gt 63) { $t = $t.Substring(0, 63) }  # Windows caps tooltip text at 63 characters
    $icon.Text = $t
    $ids = @(@($s.needs) | ForEach-Object { $_.id })
    if ($null -ne $script:seen) {
      foreach ($q in @($s.needs)) {
        if ($script:seen -notcontains $q.id) { $icon.ShowBalloonTip(8000, ("{0} needs you on #{1}" -f $q.by, $q.id), $q.q, [System.Windows.Forms.ToolTipIcon]::Info) }
      }
    }
    $script:seen = $ids
  }
  [void]$menu.Items.Add("-")
  $item = $menu.Items.Add("Refresh")
  $item.add_Click({ Refresh-Tray })
  $item = $menu.Items.Add("Quit")
  $item.add_Click({ $icon.Visible = $false; [System.Windows.Forms.Application]::Exit() })
}

Refresh-Tray
$timer = New-Object System.Windows.Forms.Timer
$timer.Interval = 60000
$timer.add_Tick({ Refresh-Tray })
$timer.Start()
[System.Windows.Forms.Application]::Run()
