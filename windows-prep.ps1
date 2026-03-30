[CmdletBinding()]
param(
  [switch]$EnableDebugLog,
  [switch]$DisableDebugLog,
  [string]$DebugLogPath = (Join-Path $PSScriptRoot 'windows-prep-run.log'),
  [string]$AutoInput = $env:OMARCHY_AUTOINPUT
)

Add-Type -AssemblyName System.Net.Http

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'
$UsePseudoTui = $true
$script:CanUseConsoleReadKey = $false
$script:EnableDebugLog = if ($DisableDebugLog) {
  $false
} elseif ($PSBoundParameters.ContainsKey('EnableDebugLog')) {
  [bool]$EnableDebugLog
} else {
  $true
}
$script:DebugLogPath = $DebugLogPath
$script:MaxPromptAttempts = 20
$script:AutoInputEnabled = -not [string]::IsNullOrWhiteSpace($AutoInput)
$script:AutoInputQueue = [System.Collections.Generic.Queue[string]]::new()
$script:TuiFrameCount = 0
$script:TuiRenderFailed = $false
$script:RunId = [guid]::NewGuid().ToString('N')
$script:RunStopwatch = [System.Diagnostics.Stopwatch]::StartNew()
$script:SupportedPlanSchemaVersion = '0.1.0'
$script:TuiState = [ordered]@{
  Title       = 'Omarchy Windows Pre-Install Assistant'
  Section     = 'Initializing'
  Stage       = ''
  StageStatus = ''
  StagePct    = 0
  Prompt      = ''
  Focus       = 'idle'
  Footer      = 'Enter Submit | y/n Confirm | Ctrl+C Quit'
  SpinnerIx   = 0
  Logs        = [System.Collections.Generic.List[string]]::new()
  UseUnicode  = $true
}

if ($script:AutoInputEnabled) {
  foreach ($entry in ($AutoInput -split '\|')) {
    $script:AutoInputQueue.Enqueue([string]$entry)
  }
}

function Write-DebugLog {
  param(
    [string]$Category,
    [string]$Message
  )

  if (-not $script:EnableDebugLog) {
    return
  }

  try {
    $ts = (Get-Date).ToString('o')
    $line = "$ts [$Category] $Message"
    Add-Content -Path $script:DebugLogPath -Value $line -Encoding UTF8
  } catch {
    # Never break workflow if debug logging fails.
  }
}

if ($script:EnableDebugLog) {
  try {
    $dir = Split-Path -Path $script:DebugLogPath -Parent
    if (-not [string]::IsNullOrWhiteSpace($dir)) {
      New-Item -ItemType Directory -Path $dir -Force | Out-Null
    }
    Set-Content -Path $script:DebugLogPath -Value '' -Encoding UTF8
  } catch {
    # Keep running if debug log file setup fails.
  }
  Write-DebugLog -Category 'debug.init' -Message ("runId={0} log='{1}' autoInput={2} queue={3}" -f $script:RunId, $script:DebugLogPath, $script:AutoInputEnabled, $script:AutoInputQueue.Count)
  Write-DebugLog -Category 'debug.env' -Message ("ps={0} host='{1}' os='{2}' user='{3}\{4}' machine='{5}' cwd='{6}' scriptRoot='{7}'" -f $PSVersionTable.PSVersion, $Host.Name, [System.Environment]::OSVersion.VersionString, $env:USERDOMAIN, $env:USERNAME, $env:COMPUTERNAME, (Get-Location).Path, $PSScriptRoot)
  Write-DebugLog -Category 'debug.args' -Message ("EnableDebugLog={0} DisableDebugLog={1} DebugLogPath='{2}'" -f $EnableDebugLog, $DisableDebugLog, $script:DebugLogPath)
}

function Read-UiHostLine {
  param(
    [Parameter(Mandatory = $true)][string]$Prompt,
    [switch]$SuppressPrompt
  )

  if ($script:AutoInputEnabled) {
    if ($script:AutoInputQueue.Count -eq 0) {
      throw "AutoInput queue exhausted at prompt: $Prompt"
    }

    $value = [string]$script:AutoInputQueue.Dequeue()
    Write-DebugLog -Category 'prompt.auto' -Message ("{0} => '{1}' (remaining={2})" -f $Prompt, $value, $script:AutoInputQueue.Count)
    return $value
  }

  if ($SuppressPrompt -and $UsePseudoTui -and $script:CanUseConsoleReadKey) {
    $value = [Console]::ReadLine()
  } else {
    $value = Read-Host $Prompt
  }

  if ($null -eq $value) {
    $value = ''
  }
  Write-DebugLog -Category 'prompt.user' -Message ("{0} => '{1}'" -f $Prompt, $value)
  return $value
}

function Initialize-UiRuntime {
  $canRender = $false
  $canReadKey = $false
  $useUnicode = $true

  try {
    $null = $Host.UI.RawUI.WindowSize
    $canRender = $true
  } catch {
    $canRender = $false
  }

  try {
    $canReadKey = -not [Console]::IsInputRedirected
  } catch {
    $canReadKey = $false
  }

  try {
    $enc = [Console]::OutputEncoding
    if ($null -eq $enc -or $enc.WebName -notin @('utf-8', 'utf8')) {
      $useUnicode = $false
    }
  } catch {
    $useUnicode = $false
  }

  $script:CanUseConsoleReadKey = $canReadKey
  $script:TuiState.UseUnicode = $useUnicode
  $script:UsePseudoTui = [bool]($UsePseudoTui -and $canRender)
  Write-DebugLog -Category 'runtime.init' -Message ("requestedTui={0} canRender={1} canReadKey={2} unicode={3} effectiveTui={4}" -f $UsePseudoTui, $canRender, $canReadKey, $useUnicode, $script:UsePseudoTui)

  if ($script:UsePseudoTui) {
    Disable-ConsoleQuickEdit
  }
}

function Disable-ConsoleQuickEdit {
  $isWindowsHost = $false
  try {
    $isWindowsHost = [System.Environment]::OSVersion.Platform -eq [System.PlatformID]::Win32NT
  } catch {
    $isWindowsHost = $true
  }

  if (-not $isWindowsHost) {
    Write-DebugLog -Category 'quickedit.skip' -Message 'non-windows host'
    return
  }

  $typeName = 'OmarchyConsoleMode'
  if (-not ($typeName -as [type])) {
    $typeDef = @'
using System;
using System.Runtime.InteropServices;

public static class OmarchyConsoleMode
{
    [DllImport("kernel32.dll", SetLastError=true)]
    public static extern IntPtr GetStdHandle(int nStdHandle);

    [DllImport("kernel32.dll", SetLastError=true)]
    public static extern bool GetConsoleMode(IntPtr hConsoleHandle, out uint lpMode);

    [DllImport("kernel32.dll", SetLastError=true)]
    public static extern bool SetConsoleMode(IntPtr hConsoleHandle, uint dwMode);
}
'@
    try {
      Add-Type -TypeDefinition $typeDef -ErrorAction Stop | Out-Null
    } catch {
      Write-DebugLog -Category 'quickedit.skip' -Message ("Add-Type failed: {0}" -f $_.Exception.Message)
      return
    }
  }

  $STD_INPUT_HANDLE = -10
  $ENABLE_QUICK_EDIT_MODE = 0x0040
  $ENABLE_EXTENDED_FLAGS = 0x0080

  $handle = [OmarchyConsoleMode]::GetStdHandle($STD_INPUT_HANDLE)
  if ($handle -eq [IntPtr]::Zero -or $handle -eq ([IntPtr](-1))) {
    Write-DebugLog -Category 'quickedit.skip' -Message 'invalid std input handle'
    return
  }

  $mode = [uint32]0
  if (-not [OmarchyConsoleMode]::GetConsoleMode($handle, [ref]$mode)) {
    Write-DebugLog -Category 'quickedit.skip' -Message 'GetConsoleMode failed'
    return
  }

  $newMode = ($mode -bor $ENABLE_EXTENDED_FLAGS) -band (-bnot $ENABLE_QUICK_EDIT_MODE)
  $applied = [OmarchyConsoleMode]::SetConsoleMode($handle, [uint32]$newMode)
  Write-DebugLog -Category 'quickedit.apply' -Message ("old=0x{0:X} new=0x{1:X} applied={2}" -f $mode, $newMode, $applied)
}

function Get-UiWindowSize {
  try {
    $window = $Host.UI.RawUI.WindowSize
    $width = [Math]::Max(80, [int]$window.Width)
    $height = [Math]::Max(24, [int]$window.Height)
    return [PSCustomObject]@{
      Width  = $width
      Height = $height
    }
  } catch {
    return [PSCustomObject]@{
      Width  = 120
      Height = 32
    }
  }
}

function Format-UiCell {
  param(
    [string]$Text,
    [int]$Width
  )

  $value = if ($null -eq $Text) { '' } else { [string]$Text }
  if ($Width -le 0) {
    return ''
  }

  if ($value.Length -gt $Width) {
    if ($Width -gt 3) {
      return ($value.Substring(0, $Width - 3) + '...')
    }

    return $value.Substring(0, $Width)
  }

  return $value.PadRight($Width)
}

function Split-UiLine {
  param(
    [string]$Text,
    [int]$Width
  )

  $lines = [System.Collections.Generic.List[string]]::new()
  if ($Width -le 0) {
    $lines.Add('')
    return $lines
  }

  $rawText = if ($null -eq $Text) { '' } else { [string]$Text }
  $clean = $rawText -replace "`t", '  '
  if ($clean.Length -eq 0) {
    $lines.Add('')
    return $lines
  }

  while ($clean.Length -gt $Width) {
    $lines.Add($clean.Substring(0, $Width))
    $clean = $clean.Substring($Width)
  }

  $lines.Add($clean)
  return $lines
}

function Write-ConsoleLine {
  param(
    [string]$Text,
    [ConsoleColor]$Color = [ConsoleColor]::Gray
  )

  $supportsAnsi = $false
  try {
    $supportsAnsi = [bool]$Host.UI.SupportsVirtualTerminal
  } catch {
    $supportsAnsi = $false
  }

  if (-not $supportsAnsi) {
    Write-Host $Text -ForegroundColor $Color
    return
  }

  $ansiCode = switch ($Color) {
    ([ConsoleColor]::Black) { '30' }
    ([ConsoleColor]::DarkRed) { '31' }
    ([ConsoleColor]::DarkGreen) { '32' }
    ([ConsoleColor]::DarkYellow) { '33' }
    ([ConsoleColor]::DarkBlue) { '34' }
    ([ConsoleColor]::DarkMagenta) { '35' }
    ([ConsoleColor]::DarkCyan) { '36' }
    ([ConsoleColor]::Gray) { '37' }
    ([ConsoleColor]::DarkGray) { '90' }
    ([ConsoleColor]::Red) { '91' }
    ([ConsoleColor]::Green) { '92' }
    ([ConsoleColor]::Yellow) { '93' }
    ([ConsoleColor]::Blue) { '94' }
    ([ConsoleColor]::Magenta) { '95' }
    ([ConsoleColor]::Cyan) { '96' }
    ([ConsoleColor]::White) { '97' }
    default { '' }
  }

  if ([string]::IsNullOrWhiteSpace($ansiCode)) {
    Write-Host $Text -ForegroundColor $Color
    return
  }

  $esc = [char]27
  Write-Host ("$esc[{0}m{1}$esc[0m" -f $ansiCode, $Text)
}

function Get-UiMessageColor {
  param([string]$Message)

  if ($Message.StartsWith('[ERROR]')) { return [ConsoleColor]::Red }
  if ($Message.StartsWith('[WARN]')) { return [ConsoleColor]::Yellow }
  if ($Message.StartsWith('[SECTION]')) { return [ConsoleColor]::Cyan }
  if ($Message.StartsWith('[INFO]')) { return [ConsoleColor]::Gray }
  return [ConsoleColor]::Gray
}

function Get-UiSpinnerGlyph {
  $frames = if ($script:TuiState.UseUnicode) {
    @('⠋','⠙','⠹','⠸','⠼','⠴','⠦','⠧','⠇','⠏')
  } else {
    # Avoid '|' — it is visually identical to the ASCII border character and
    # causes the stage line to look broken on non-unicode consoles.
    @('-','\\',':','/')
  }
  if ($script:TuiState.SpinnerIx -ge $frames.Count) {
    $script:TuiState.SpinnerIx = 0
  }

  $glyph = $frames[$script:TuiState.SpinnerIx]
  $script:TuiState.SpinnerIx = ($script:TuiState.SpinnerIx + 1) % $frames.Count
  return $glyph
}

function Show-TuiFrame {
  if (-not $UsePseudoTui) {
    return
  }

  $script:TuiFrameCount++
  if (($script:TuiFrameCount % 25) -eq 1) {
    Write-DebugLog -Category 'tui.frame' -Message ("render #{0} | section='{1}' | stage='{2}' | focus='{3}' | logs={4}" -f $script:TuiFrameCount, $script:TuiState.Section, $script:TuiState.Stage, $script:TuiState.Focus, $script:TuiState.Logs.Count)
  }

  $size = Get-UiWindowSize
  $width = $size.Width
  $height = $size.Height
  $contentWidth = [Math]::Max(20, $width - 4)
  $left = if ($script:TuiState.UseUnicode) { '│' } else { '|' }
  $topLeft = if ($script:TuiState.UseUnicode) { '┌' } else { '+' }
  $topRight = if ($script:TuiState.UseUnicode) { '┐' } else { '+' }
  $midLeft = if ($script:TuiState.UseUnicode) { '├' } else { '+' }
  $midRight = if ($script:TuiState.UseUnicode) { '┤' } else { '+' }
  $bottomLeft = if ($script:TuiState.UseUnicode) { '└' } else { '+' }
  $bottomRight = if ($script:TuiState.UseUnicode) { '┘' } else { '+' }
  $h = if ($script:TuiState.UseUnicode) { '─' } else { '-' }
  $topBorder = ($topLeft + ($h * ($width - 2)) + $topRight)
  $separator = ($midLeft + ($h * ($width - 2)) + $midRight)
  $bottomBorder = ($bottomLeft + ($h * ($width - 2)) + $bottomRight)
  # height-13 → total rows = 11 + (height-13) = height-2.
  # Each Write-Host appends \n.  With height-1 rows the final \n lands on the
  # last viewport row and can trigger a one-line scroll on some terminals.
  # Keeping one spare row (height-2 total) eliminates that edge case.
  $logRows = [Math]::Max(4, $height - 13)

  # Use fast ANSI cursor-home + erase instead of Clear-Host.
  # Clear-Host fills the entire console buffer with spaces via the Windows
  # Console API — slow enough to produce a visible blank flash between frames.
  # \e[?25l hides the cursor during drawing to prevent it jumping around;
  # \e[H\e[2J homes the cursor and erases the visible viewport instantly.
  $ansiAvail = $false
  try { $ansiAvail = [bool]$Host.UI.SupportsVirtualTerminal } catch {}
  if ($ansiAvail) {
    $esc = [char]27
    Write-Host "$esc[?25l$esc[H$esc[2J" -NoNewline
  } else {
    try { Clear-Host } catch { Write-Verbose 'Clear-Host is unavailable in this host; continuing without screen clear.' }
  }

  Write-ConsoleLine -Text $topBorder -Color DarkCyan
  Write-ConsoleLine -Text ("$left " + (Format-UiCell -Text $script:TuiState.Title -Width $contentWidth) + " $left") -Color Cyan
  Write-ConsoleLine -Text $separator -Color DarkCyan

  $focusText = switch ($script:TuiState.Focus) {
    'input' { 'Focus: Input' }
    'confirm' { 'Focus: Confirmation' }
    default { 'Focus: Status' }
  }
  $sectionText = if ([string]::IsNullOrWhiteSpace($script:TuiState.Section)) { 'Section: (none)' } else { "Section: $($script:TuiState.Section) | $focusText" }
  $spinner = Get-UiSpinnerGlyph
  $stageText = if ([string]::IsNullOrWhiteSpace($script:TuiState.Stage)) { 'Stage: idle' } else { "Stage: $spinner $($script:TuiState.Stage)" }
  if (-not [string]::IsNullOrWhiteSpace($script:TuiState.StageStatus)) {
    $stageText += " | $($script:TuiState.StageStatus)"
  }
  if ($script:TuiState.StagePct -gt 0) {
    $stageText += " | $($script:TuiState.StagePct)%"
  }

  Write-ConsoleLine -Text ("$left " + (Format-UiCell -Text $sectionText -Width $contentWidth) + " $left") -Color Gray
  Write-ConsoleLine -Text ("$left " + (Format-UiCell -Text $stageText -Width $contentWidth) + " $left") -Color DarkYellow
  Write-ConsoleLine -Text $separator -Color DarkCyan
  Write-ConsoleLine -Text ("$left " + (Format-UiCell -Text 'Messages' -Width $contentWidth) + " $left") -Color DarkGray

  $logStart = [Math]::Max(0, $script:TuiState.Logs.Count - $logRows)
  if ($script:TuiState.Logs.Count -eq 0) {
    Write-ConsoleLine -Text ("$left " + (Format-UiCell -Text "No events yet. Progress and prompts will appear here." -Width $contentWidth) + " $left") -Color DarkGray
    for ($i = 1; $i -lt $logRows; $i++) {
      Write-ConsoleLine -Text ("$left " + (' ' * $contentWidth) + " $left") -Color Gray
    }
  } else {
    for ($i = 0; $i -lt $logRows; $i++) {
      $line = ''
      if (($logStart + $i) -lt $script:TuiState.Logs.Count) {
      $line = [string]$script:TuiState.Logs[$logStart + $i]
      }

      $color = Get-UiMessageColor -Message $line
      Write-ConsoleLine -Text ("$left " + (Format-UiCell -Text $line -Width $contentWidth) + " $left") -Color $color
    }
  }

  Write-ConsoleLine -Text $separator -Color DarkCyan
  $activePrompt = if ($script:TuiState.UseUnicode) { 'Input ▶' } else { 'Input >' }
  $promptLabel = if ($script:TuiState.Focus -eq 'input' -or $script:TuiState.Focus -eq 'confirm') { $activePrompt } else { 'Input' }
  $promptText = if ([string]::IsNullOrWhiteSpace($script:TuiState.Prompt)) { "$promptLabel (none)" } else { "$promptLabel $($script:TuiState.Prompt)" }
  Write-ConsoleLine -Text ("$left " + (Format-UiCell -Text $promptText -Width $contentWidth) + " $left") -Color White
  Write-ConsoleLine -Text ("$left " + (Format-UiCell -Text $script:TuiState.Footer -Width $contentWidth) + " $left") -Color DarkGray
  Write-ConsoleLine -Text $bottomBorder -Color DarkCyan

  # Restore cursor visibility after the frame is fully drawn.
  if ($ansiAvail) {
    $esc = [char]27
    Write-Host "$esc[?25h" -NoNewline
  }
}

function Invoke-TuiRender {
  if (-not $UsePseudoTui) {
    return
  }

  try {
    Show-TuiFrame
  } catch {
    $script:TuiRenderFailed = $true
    Write-DebugLog -Category 'tui.render.failure' -Message $_.Exception.Message
    $script:UsePseudoTui = $false
    Write-Warn 'TUI render failed; falling back to plain console mode.'
  }
}

function Add-UiLog {
  param(
    [string]$Message,
    [switch]$SkipRender
  )

  $text = if ($null -eq $Message) { '' } else { [string]$Message }
  Write-DebugLog -Category 'ui.log' -Message $text
  if ($UsePseudoTui) {
    $size = Get-UiWindowSize
    $wrapWidth = [Math]::Max(20, $size.Width - 4)
    $wrapped = Split-UiLine -Text $text -Width $wrapWidth
    foreach ($line in $wrapped) {
      $script:TuiState.Logs.Add($line)
    }

    while ($script:TuiState.Logs.Count -gt 400) {
      $script:TuiState.Logs.RemoveAt(0)
    }

    if (-not $SkipRender) {
      Invoke-TuiRender
    }
    return
  }

  Write-ConsoleLine -Text $text -Color (Get-UiMessageColor -Message $text)
}

function Show-UiPrompt {
  param(
    [string]$Prompt,
    [string]$Focus = 'input'
  )

  $script:TuiState.Prompt = $Prompt
  $script:TuiState.Focus = $Focus
  if ($UsePseudoTui) {
    Invoke-TuiRender
  }
}

function Read-UiLine {
  param(
    [Parameter(Mandatory = $true)][string]$Prompt,
    [string]$DefaultValue = ''
  )

  if ($UsePseudoTui) {
    Show-UiPrompt -Prompt "$Prompt" -Focus 'input'
  }

  $raw = Read-UiHostLine -Prompt $Prompt -SuppressPrompt:$UsePseudoTui
  if ($UsePseudoTui) {
    Show-UiPrompt -Prompt '' -Focus 'status'
  }

  if ([string]::IsNullOrWhiteSpace($raw) -and -not [string]::IsNullOrWhiteSpace($DefaultValue)) {
    return $DefaultValue
  }

  return $raw
}

function Write-Section {
  param([string]$Title)
  $script:TuiState.Section = $Title
  $script:TuiState.Focus = 'status'
  Add-UiLog -Message "[SECTION] $Title"
}

function Write-Info {
  param([string]$Message)
  Add-UiLog -Message "[INFO] $Message"
}

function Write-Warn {
  param([string]$Message)
  Add-UiLog -Message "[WARN] $Message"
}

function Write-Err {
  param([string]$Message)
  Add-UiLog -Message "[ERROR] $Message"
}

function Format-Eta {
  param([double]$Seconds)

  if ($Seconds -lt 0) {
    return 'calculating...'
  }

  $remaining = [TimeSpan]::FromSeconds([Math]::Ceiling($Seconds))
  if ($remaining.TotalHours -ge 1) {
    return ('{0}h {1}m {2}s' -f [int]$remaining.TotalHours, $remaining.Minutes, $remaining.Seconds)
  }

  if ($remaining.TotalMinutes -ge 1) {
    return ('{0}m {1}s' -f [int]$remaining.TotalMinutes, $remaining.Seconds)
  }

  return ('{0}s' -f [int][Math]::Ceiling($remaining.TotalSeconds))
}

function Write-StageProgress {
  param(
    [int]$Id,
    [int]$Step,
    [int]$Total,
    [string]$Activity,
    [int]$EtaMinutes = 0,
    [string]$Status = ''
  )

  $percent = [Math]::Min(100, [Math]::Max(0, [int](($Step * 100) / [Math]::Max(1, $Total))))
  $resolvedStatus = if (-not [string]::IsNullOrWhiteSpace($Status)) {
    $Status
  } elseif ($EtaMinutes -gt 0) {
    "Step $Step of $Total | ETA ~$EtaMinutes min"
  } else {
    "Step $Step of $Total"
  }

  if ($UsePseudoTui) {
    Write-DebugLog -Category 'stage.progress' -Message ("id={0} step={1}/{2} activity='{3}' status='{4}' pct={5}" -f $Id, $Step, $Total, $Activity, $resolvedStatus, $percent)
    $script:TuiState.Stage = $Activity
    $script:TuiState.StageStatus = $resolvedStatus
    $script:TuiState.StagePct = $percent
    $script:TuiState.Focus = 'status'
    Invoke-TuiRender
    return
  }

  Write-UiProgress -Id $Id -Activity $Activity -Status $resolvedStatus -PercentComplete $percent
}

function Write-UiProgress {
  param(
    [int]$Id,
    [string]$Activity,
    [string]$Status = '',
    [int]$PercentComplete = 0,
    [int]$SecondsRemaining = -1,
    [switch]$Completed
  )

  if ($UsePseudoTui) {
    Write-DebugLog -Category 'ui.progress' -Message ("id={0} activity='{1}' status='{2}' pct={3} completed={4}" -f $Id, $Activity, $Status, $PercentComplete, [bool]$Completed)
    if (-not [string]::IsNullOrWhiteSpace($Activity)) {
      $script:TuiState.Stage = $Activity
    }

    if ($Completed) {
      $script:TuiState.StageStatus = 'Completed'
      $script:TuiState.StagePct = 100
    } else {
      $script:TuiState.StageStatus = $Status
      $script:TuiState.StagePct = [Math]::Min(100, [Math]::Max(0, $PercentComplete))
    }

    $script:TuiState.Focus = 'status'
    Invoke-TuiRender
    return
  }

  if ($Completed) {
    Write-Progress -Id $Id -Activity $Activity -Completed
    return
  }

  if ($SecondsRemaining -ge 0) {
    Write-Progress -Id $Id -Activity $Activity -Status $Status -PercentComplete $PercentComplete -SecondsRemaining $SecondsRemaining
    return
  }

  Write-Progress -Id $Id -Activity $Activity -Status $Status -PercentComplete $PercentComplete
}

function Invoke-DownloadWithProgress {
  param(
    [Parameter(Mandatory = $true)][string]$Url,
    [Parameter(Mandatory = $true)][string]$OutFile,
    [string]$Activity = 'Downloading',
    [int]$ProgressId = 40,
    [int]$Threads = 0    # 0 = auto (min of 8 and CPU core count)
  )

  $resolvedOutFile = try {
    [System.IO.Path]::GetFullPath($OutFile)
  } catch {
    throw "Invalid download output path '$OutFile': $($_.Exception.Message)"
  }

  $outDir = Split-Path -Path $resolvedOutFile -Parent
  if ([string]::IsNullOrWhiteSpace($outDir)) {
    throw "Could not determine output directory for '$resolvedOutFile'."
  }

  New-Item -ItemType Directory -Path $outDir -Force | Out-Null
  if (-not (Test-Path -LiteralPath $outDir)) {
    throw "Output directory was not created or is inaccessible: '$outDir'"
  }

  $effectiveThreads = if ($Threads -le 0) {
    [Math]::Max(1, [Math]::Min(8, [System.Environment]::ProcessorCount))
  } else {
    [Math]::Max(1, $Threads)
  }

  Write-DebugLog -Category 'download.start' -Message ("activity='{0}' url='{1}' out='{2}' threads={3}" -f $Activity, $Url, $resolvedOutFile, $effectiveThreads)

  # Probe the server with a HEAD request to learn Content-Length and whether it
  # supports byte-range requests (required for parallel chunked download).
  $totalBytes    = [int64]0
  $acceptsRanges = $false
  $probeClient   = [System.Net.Http.HttpClient]::new()
  try {
    $probeReq  = [System.Net.Http.HttpRequestMessage]::new([System.Net.Http.HttpMethod]::Head, $Url)
    $probeResp = $probeClient.SendAsync($probeReq).GetAwaiter().GetResult()
    $clv = $probeResp.Content.Headers.ContentLength
    if ($null -ne $clv) { $totalBytes = [int64]$clv }
    $rangeVals = $null
    if ($probeResp.Headers.TryGetValues('Accept-Ranges', [ref]$rangeVals)) {
      $acceptsRanges = (@($rangeVals)[0] -eq 'bytes')
    }
    $probeResp.Dispose()
    $probeReq.Dispose()
    Write-DebugLog -Category 'download.probe' -Message ("totalBytes={0} acceptsRanges={1}" -f $totalBytes, $acceptsRanges)
  } catch {
    Write-DebugLog -Category 'download.probe.warn' -Message ("HEAD probe failed, falling back to single-thread: {0}" -f $_.Exception.Message)
  } finally {
    $probeClient.Dispose()
  }

  if ($acceptsRanges -and $totalBytes -gt 10MB -and $effectiveThreads -gt 1) {
    Write-DebugLog -Category 'download.mode' -Message "parallel"
    Invoke-ChunkedParallelDownload -Url $Url -OutFile $resolvedOutFile -TotalBytes $totalBytes `
      -Threads $effectiveThreads -Activity $Activity -ProgressId $ProgressId
  } else {
    Write-DebugLog -Category 'download.mode' -Message "single-thread"
    Invoke-SingleThreadedDownload -Url $Url -OutFile $resolvedOutFile -TotalBytes $totalBytes `
      -Activity $Activity -ProgressId $ProgressId
  }
}

function Invoke-SingleThreadedDownload {
  param(
    [Parameter(Mandatory = $true)][string]$Url,
    [Parameter(Mandatory = $true)][string]$OutFile,
    [int64]$TotalBytes = 0,
    [string]$Activity = 'Downloading',
    [int]$ProgressId = 40
  )

  $client = [System.Net.Http.HttpClient]::new()
  $response = $null
  $stream = $null
  $fileStream = $null
  $downloadedBytes = [int64]0

  try {
    $response = $client.GetAsync($Url, [System.Net.Http.HttpCompletionOption]::ResponseHeadersRead).GetAwaiter().GetResult()
    [void]$response.EnsureSuccessStatusCode()

    if ($TotalBytes -le 0) {
      $clv = $response.Content.Headers.ContentLength
      if ($null -ne $clv) { $TotalBytes = [int64]$clv }
    }

    $stream     = $response.Content.ReadAsStreamAsync().GetAwaiter().GetResult()
    $fileStream = [System.IO.File]::Open($OutFile, [System.IO.FileMode]::Create, [System.IO.FileAccess]::Write, [System.IO.FileShare]::None)
    $buffer     = New-Object byte[] (1MB)
    $stopwatch  = [System.Diagnostics.Stopwatch]::StartNew()
    $nextLogPct = 10

    while (($read = $stream.Read($buffer, 0, $buffer.Length)) -gt 0) {
      $fileStream.Write($buffer, 0, $read)
      $downloadedBytes += $read

      if ($TotalBytes -gt 0) {
        $percent          = [Math]::Min(100, [int](($downloadedBytes * 100) / $TotalBytes))
        $rate             = if ($stopwatch.Elapsed.TotalSeconds -gt 0) { $downloadedBytes / $stopwatch.Elapsed.TotalSeconds } else { 0.0 }
        $remainingSeconds = if ($rate -gt 0) { ($TotalBytes - $downloadedBytes) / $rate } else { -1 }
        $status = ('{0:N1}/{1:N1} MiB | ETA {2}' -f ($downloadedBytes / 1MB), ($TotalBytes / 1MB), (Format-Eta -Seconds $remainingSeconds))
        Write-UiProgress -Id $ProgressId -Activity $Activity -Status $status -PercentComplete $percent -SecondsRemaining ([int][Math]::Max(0, [Math]::Ceiling($remainingSeconds)))
        if ($percent -ge $nextLogPct) {
          Write-DebugLog -Category 'download.progress' -Message ("pct={0} bytes={1}/{2}" -f $percent, $downloadedBytes, $TotalBytes)
          while ($percent -ge $nextLogPct) { $nextLogPct += 10 }
        }
      } else {
        Write-UiProgress -Id $ProgressId -Activity $Activity -Status ('{0:N1} MiB downloaded' -f ($downloadedBytes / 1MB)) -PercentComplete 0
      }
    }

    Write-UiProgress -Id $ProgressId -Activity $Activity -Completed
    Write-DebugLog -Category 'download.complete' -Message ("bytes={0} elapsedSec={1:N1}" -f $downloadedBytes, $stopwatch.Elapsed.TotalSeconds)
  } catch {
    Write-DebugLog -Category 'download.error' -Message ("bytes={0} error='{1}'" -f $downloadedBytes, $_.Exception.Message)
    throw
  } finally {
    if ($fileStream) { $fileStream.Dispose() }
    if ($stream)     { $stream.Dispose() }
    if ($response)   { $response.Dispose() }
    if ($client)     { $client.Dispose() }
  }
}

function Invoke-ChunkedParallelDownload {
  # Downloads a file in parallel byte-range chunks using PowerShell Runspaces,
  # then merges the chunk files into the final output.  The server must support
  # Accept-Ranges: bytes (verified by the caller).
  param(
    [Parameter(Mandatory = $true)][string]$Url,
    [Parameter(Mandatory = $true)][string]$OutFile,
    [Parameter(Mandatory = $true)][int64]$TotalBytes,
    [int]$Threads = 4,
    [string]$Activity = 'Downloading',
    [int]$ProgressId = 40
  )

  $chunkSize = [int64][Math]::Ceiling($TotalBytes / $Threads)
  $tmpDir    = Join-Path ([System.IO.Path]::GetTempPath()) ('omarchy_dl_' + [guid]::NewGuid().ToString('N'))
  New-Item -ItemType Directory -Path $tmpDir -Force | Out-Null

  # Synchronized hashtable for cross-runspace progress reporting.
  $progress = [System.Collections.Hashtable]::Synchronized(@{})
  for ($i = 0; $i -lt $Threads; $i++) {
    $progress["bytes_$i"] = [int64]0
    $progress["done_$i"]  = $false
    $progress["error_$i"] = $null
  }

  # Self-contained chunk-downloader script (no references to parent session).
  $chunkScript = {
    param(
      [string]$Url,
      [string]$OutFile,
      [int64]$From,
      [int64]$To,
      [int]$ChunkIndex,
      [hashtable]$Progress
    )
    Add-Type -AssemblyName System.Net.Http
    $client = [System.Net.Http.HttpClient]::new()
    try {
      $req = [System.Net.Http.HttpRequestMessage]::new([System.Net.Http.HttpMethod]::Get, $Url)
      $req.Headers.Range = [System.Net.Http.Headers.RangeHeaderValue]::new($From, $To)
      $resp = $client.SendAsync($req, [System.Net.Http.HttpCompletionOption]::ResponseHeadersRead).GetAwaiter().GetResult()
      [void]$resp.EnsureSuccessStatusCode()
      $inStream = $resp.Content.ReadAsStreamAsync().GetAwaiter().GetResult()
      $fs  = [System.IO.File]::Open($OutFile, [System.IO.FileMode]::Create,
               [System.IO.FileAccess]::Write, [System.IO.FileShare]::None)
      $buf = New-Object byte[] 524288   # 512 KiB
      try {
        while (($read = $inStream.Read($buf, 0, $buf.Length)) -gt 0) {
          $fs.Write($buf, 0, $read)
          $Progress["bytes_$ChunkIndex"] += $read
        }
      } finally {
        $fs.Dispose()
        $inStream.Dispose()
        $resp.Dispose()
      }
      $Progress["done_$ChunkIndex"] = $true
    } catch {
      $Progress["error_$ChunkIndex"] = $_.Exception.Message
      $Progress["done_$ChunkIndex"] = $true
    } finally {
      $client.Dispose()
    }
  }

  # Open a runspace pool and launch one runspace per chunk.
  $pool    = [System.Management.Automation.Runspaces.RunspaceFactory]::CreateRunspacePool(1, $Threads)
  $pool.Open()
  $handles = [System.Collections.Generic.List[hashtable]]::new()

  for ($i = 0; $i -lt $Threads; $i++) {
    $from      = [int64]($i * $chunkSize)
    $to        = [int64]([Math]::Min($from + $chunkSize - 1, $TotalBytes - 1))
    $chunkFile = Join-Path $tmpDir "chunk_$i.bin"

    $ps = [System.Management.Automation.PowerShell]::Create()
    $ps.RunspacePool = $pool
    [void]$ps.AddScript($chunkScript).AddParameters(@{
      Url        = $Url
      OutFile    = $chunkFile
      From       = $from
      To         = $to
      ChunkIndex = $i
      Progress   = $progress
    })
    $handles.Add(@{ PS = $ps; Handle = $ps.BeginInvoke(); Chunk = $chunkFile; Index = $i })
  }

  # Poll progress from the main thread and update the TUI every 250 ms.
  $stopwatch  = [System.Diagnostics.Stopwatch]::StartNew()
  $nextLogPct = 10
  do {
    Start-Sleep -Milliseconds 250
    $totalDone = [int64]0
    $allDone   = $true
    for ($i = 0; $i -lt $Threads; $i++) {
      $totalDone += [int64]$progress["bytes_$i"]
      if (-not [bool]$progress["done_$i"]) { $allDone = $false }
    }
    $pct    = if ($TotalBytes -gt 0) { [Math]::Min(99, [int](($totalDone * 100) / $TotalBytes)) } else { 0 }
    $rate   = if ($stopwatch.Elapsed.TotalSeconds -gt 0) { $totalDone / $stopwatch.Elapsed.TotalSeconds } else { 0.0 }
    $eta    = if ($rate -gt 0 -and $TotalBytes -gt $totalDone) { ($TotalBytes - $totalDone) / $rate } else { -1 }
    $status = ('{0:N1}/{1:N1} MiB | {2} threads | ETA {3}' -f ($totalDone / 1MB), ($TotalBytes / 1MB), $Threads, (Format-Eta -Seconds $eta))
    Write-UiProgress -Id $ProgressId -Activity $Activity -Status $status -PercentComplete $pct
    if ($pct -ge $nextLogPct) {
      Write-DebugLog -Category 'download.parallel.pct' -Message ("pct={0} bytes={1}/{2}" -f $pct, $totalDone, $TotalBytes)
      while ($pct -ge $nextLogPct) { $nextLogPct += 10 }
    }
  } while (-not $allDone)

  # Collect async results and surface any errors.
  $errors = [System.Collections.Generic.List[string]]::new()
  foreach ($h in $handles) {
    $h.PS.EndInvoke($h.Handle) | Out-Null
    $h.PS.Dispose()
    $err = [string]$progress["error_$($h.Index)"]
    if (-not [string]::IsNullOrEmpty($err)) {
      $errors.Add("Chunk $($h.Index): $err")
    }
  }
  $pool.Dispose()

  if ($errors.Count -gt 0) {
    Remove-Item -LiteralPath $tmpDir -Recurse -Force -ErrorAction SilentlyContinue
    throw ("Parallel download failed:`n" + ($errors -join "`n"))
  }

  # Merge all chunk files sequentially into the final output file.
  Write-UiProgress -Id $ProgressId -Activity $Activity -Status ('Merging {0} chunks...' -f $Threads) -PercentComplete 99
  Write-DebugLog -Category 'download.parallel.merge' -Message ("threads={0} out='{1}'" -f $Threads, $OutFile)

  $outStream = [System.IO.File]::Open($OutFile, [System.IO.FileMode]::Create,
    [System.IO.FileAccess]::Write, [System.IO.FileShare]::None)
  $mergeBuf  = New-Object byte[] 4194304   # 4 MiB
  try {
    for ($i = 0; $i -lt $Threads; $i++) {
      $chunkFile   = Join-Path $tmpDir "chunk_$i.bin"
      $chunkStream = [System.IO.File]::OpenRead($chunkFile)
      try {
        while (($read = $chunkStream.Read($mergeBuf, 0, $mergeBuf.Length)) -gt 0) {
          $outStream.Write($mergeBuf, 0, $read)
        }
      } finally {
        $chunkStream.Dispose()
        Remove-Item -LiteralPath $chunkFile -Force -ErrorAction SilentlyContinue
      }
    }
  } finally {
    $outStream.Dispose()
  }

  Remove-Item -LiteralPath $tmpDir -Recurse -Force -ErrorAction SilentlyContinue
  Write-UiProgress -Id $ProgressId -Activity $Activity -Completed
  Write-DebugLog -Category 'download.parallel.done' -Message ("totalBytes={0} threads={1} elapsedSec={2:N1}" -f $TotalBytes, $Threads, $stopwatch.Elapsed.TotalSeconds)
}

function Copy-DirectoryWithProgress {
  param(
    [Parameter(Mandatory = $true)][string]$Source,
    [Parameter(Mandatory = $true)][string]$Destination,
    [string]$Activity = 'Copying files',
    [int]$ProgressId = 50
  )

  $srcRoot = (Resolve-Path -LiteralPath $Source).Path
  if (-not $srcRoot.EndsWith('\')) {
    $srcRoot += '\'
  }

  New-Item -ItemType Directory -Path $Destination -Force | Out-Null

  Get-ChildItem -LiteralPath $srcRoot -Directory -Recurse | ForEach-Object {
    $relDir = $_.FullName.Substring($srcRoot.Length)
    $targetDir = Join-Path $Destination $relDir
    New-Item -ItemType Directory -Path $targetDir -Force | Out-Null
  }

  $files = Get-ChildItem -LiteralPath $srcRoot -File -Recurse
  $totalBytes = [int64](($files | Measure-Object -Property Length -Sum).Sum)
  if ($totalBytes -le 0) {
    Write-UiProgress -Id $ProgressId -Activity $Activity -Completed
    return
  }

  $copiedBytes = [int64]0
  $stopwatch = [System.Diagnostics.Stopwatch]::StartNew()
  $buffer = New-Object byte[] (1MB)

  foreach ($file in $files) {
    $relativePath = $file.FullName.Substring($srcRoot.Length)
    $targetPath = Join-Path $Destination $relativePath
    $targetDir = Split-Path -Path $targetPath -Parent
    if ($targetDir) {
      New-Item -ItemType Directory -Path $targetDir -Force | Out-Null
    }

    $srcStream = [System.IO.File]::OpenRead($file.FullName)
    $dstStream = [System.IO.File]::Open($targetPath, [System.IO.FileMode]::Create, [System.IO.FileAccess]::Write, [System.IO.FileShare]::None)
    try {
      while (($read = $srcStream.Read($buffer, 0, $buffer.Length)) -gt 0) {
        $dstStream.Write($buffer, 0, $read)
        $copiedBytes += $read

        $percent = [Math]::Min(100, [int](($copiedBytes * 100) / $totalBytes))
        $rate = if ($stopwatch.Elapsed.TotalSeconds -gt 0) { $copiedBytes / $stopwatch.Elapsed.TotalSeconds } else { 0.0 }
        $remainingSeconds = if ($rate -gt 0) { ($totalBytes - $copiedBytes) / $rate } else { -1 }
        $status = ('{0:N1}/{1:N1} MiB | {2} | ETA {3}' -f ($copiedBytes / 1MB), ($totalBytes / 1MB), $relativePath, (Format-Eta -Seconds $remainingSeconds))
        Write-UiProgress -Id $ProgressId -Activity $Activity -Status $status -PercentComplete $percent -SecondsRemaining ([int][Math]::Max(0, [Math]::Ceiling($remainingSeconds)))
      }
    } finally {
      $srcStream.Dispose()
      $dstStream.Dispose()
    }
  }

  Write-UiProgress -Id $ProgressId -Activity $Activity -Completed
}

function Test-Admin {
  $current = [Security.Principal.WindowsIdentity]::GetCurrent()
  $principal = New-Object Security.Principal.WindowsPrincipal($current)
  return $principal.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)
}

function Read-YesNo {
  param(
    [Parameter(Mandatory = $true)][string]$Message,
    [bool]$DefaultYes = $true
  )

  $attempts = 0
  while ($true) {
    $attempts++
    if ($attempts -gt $script:MaxPromptAttempts) {
      throw "Exceeded maximum prompt attempts ($($script:MaxPromptAttempts)) while waiting for yes/no input."
    }

    $suffix = if ($DefaultYes) { '[Y/n]' } else { '[y/N]' }
    if ($UsePseudoTui) {
      Show-UiPrompt -Prompt "$Message $suffix" -Focus 'confirm'
    }

    $raw = Read-UiHostLine -Prompt "$Message $suffix" -SuppressPrompt:$UsePseudoTui
    if ($UsePseudoTui) {
      Show-UiPrompt -Prompt '' -Focus 'status'
    }

    if ([string]::IsNullOrWhiteSpace($raw)) {
      Write-DebugLog -Category 'prompt.yesno' -Message ("{0} => default ({1})" -f $Message, $DefaultYes)
      return $DefaultYes
    }

    $normalized = $raw.Trim().ToLowerInvariant()
    switch ($normalized) {
      'y' { Write-DebugLog -Category 'prompt.yesno' -Message ("{0} => true ('{1}')" -f $Message, $normalized); return $true }
      'yes' { Write-DebugLog -Category 'prompt.yesno' -Message ("{0} => true ('{1}')" -f $Message, $normalized); return $true }
      'n' { Write-DebugLog -Category 'prompt.yesno' -Message ("{0} => false ('{1}')" -f $Message, $normalized); return $false }
      'no' { Write-DebugLog -Category 'prompt.yesno' -Message ("{0} => false ('{1}')" -f $Message, $normalized); return $false }
      default { Write-Warn 'Please answer y or n.' }
    }
  }
}

Initialize-UiRuntime

function Read-Int {
  param(
    [Parameter(Mandatory = $true)][string]$Message,
    [int]$Default,
    [int]$Min,
    [int]$Max
  )

  $attempts = 0
  while ($true) {
    $attempts++
    if ($attempts -gt $script:MaxPromptAttempts) {
      throw "Exceeded maximum prompt attempts ($($script:MaxPromptAttempts)) while waiting for integer input."
    }

    $raw = Read-UiLine -Prompt "$Message [$Default]"
    if ([string]::IsNullOrWhiteSpace($raw)) {
      return $Default
    }

    $value = 0
    if (-not [int]::TryParse($raw, [ref]$value)) {
      Write-Warn 'Enter a valid whole number.'
      continue
    }

    if ($value -lt $Min -or $value -gt $Max) {
      Write-Warn "Enter a value between $Min and $Max."
      continue
    }

    return $value
  }
}

function Convert-ToGiB {
  param([UInt64]$Bytes)
  return [Math]::Round($Bytes / 1GB, 1)
}

function Get-DefaultInternalDisk {
  $cPartition = Get-Partition -DriveLetter C -ErrorAction SilentlyContinue
  if ($cPartition) {
    return Get-Disk -Number $cPartition.DiskNumber
  }

  $disk = Get-Disk |
    Where-Object { $_.BusType -ne 'USB' -and $_.Size -gt 0 } |
    Sort-Object -Property Size -Descending |
    Select-Object -First 1

  return $disk
}

function Get-SecureBootState {
  try {
    $secureBoot = Confirm-SecureBootUEFI
    if ($secureBoot) {
      return 'Enabled'
    }

    return 'Disabled'
  } catch {
    return 'Unknown'
  }
}

function Invoke-SecureBootFirmwareReboot {
  param([Parameter(Mandatory = $true)][string]$SecureBootState)

  if ($SecureBootState -ne 'Enabled') {
    return $false
  }

  Write-Warn 'Secure Boot is enabled. Omarchy install requires Secure Boot disabled in BIOS/UEFI.'
  if (Read-YesNo -Message 'Reboot now directly into firmware settings to disable Secure Boot?' -DefaultYes $true) {
    Write-Info 'Rebooting to firmware setup screen now...'
    shutdown /r /fw /t 0 | Out-Null
    return $true
  }

  return $false
}

function Show-SystemReadiness {
  param([string]$SecureBootState = $null)

  Write-Section 'Machine Readiness Checks'

  if ([string]::IsNullOrWhiteSpace($SecureBootState)) {
    $SecureBootState = Get-SecureBootState
  }

  if ($SecureBootState -eq 'Enabled') {
    Write-Warn 'Secure Boot is enabled. You should disable it in BIOS/UEFI before installing Omarchy.'
  } elseif ($SecureBootState -eq 'Disabled') {
    Write-Info 'Secure Boot appears disabled.'
  } else {
    Write-Warn 'Secure Boot status could not be read from this session.'
  }

  try {
    $osDrive = "$($env:SystemDrive.TrimEnd(':')):"
    $bl = Get-BitLockerVolume -MountPoint $osDrive -ErrorAction Stop
    if ($bl.ProtectionStatus -eq 'On') {
      Write-Warn "BitLocker is ON for $osDrive. Back up recovery keys before partition changes."
    } else {
      Write-Info "BitLocker is not active on $osDrive."
    }
  } catch {
    Write-Warn 'BitLocker status unavailable (module/policy may be missing).'
  }

  try {
    $fastStartup = Get-ItemPropertyValue -Path 'HKLM:\SYSTEM\CurrentControlSet\Control\Session Manager\Power' -Name HiberbootEnabled
    if ($fastStartup -eq 1) {
      Write-Warn 'Fast Startup is enabled and must be disabled before proceeding with Omarchy prep.'
    } else {
      Write-Info 'Fast Startup is already disabled.'
    }
  } catch {
    Write-Warn 'Could not query or modify Fast Startup setting.'
  }
}

function Invoke-NonNegotiableAbortGate {
  param(
    [string]$SecureBootState = $null,
    [string]$MediaTargetDir = ''
  )

  $blockers = [System.Collections.Generic.List[string]]::new()

  if (-not (Test-Admin)) {
    $blockers.Add('admin: run the workflow from an elevated PowerShell session.')
  }

  if ([string]::IsNullOrWhiteSpace($SecureBootState)) {
    $SecureBootState = Get-SecureBootState
  }
  if ($SecureBootState -eq 'Enabled') {
    $blockers.Add('boot: Secure Boot is enabled and must be disabled before continuing.')
  }

  try {
    $osDrive = "$($env:SystemDrive.TrimEnd(':')):"
    $bl = Get-BitLockerVolume -MountPoint $osDrive -ErrorAction Stop
    if ($bl.ProtectionStatus -eq 'On') {
      $blockers.Add("security: BitLocker is ON for $osDrive and recovery keys/backups are required before any partition work.")
    }
  } catch {
    $blockers.Add('security: BitLocker state could not be confirmed safely.')
  }

  try {
    $fastStartup = Get-ItemPropertyValue -Path 'HKLM:\SYSTEM\CurrentControlSet\Control\Session Manager\Power' -Name HiberbootEnabled
    if ($fastStartup -eq 1) {
      $blockers.Add('security: Fast Startup is enabled and must be disabled before continuing.')
    }
  } catch {
    $blockers.Add('security: Fast Startup state could not be confirmed safely.')
  }

  if (-not (Get-DefaultInternalDisk)) {
    $blockers.Add('identity: no stable internal target disk could be identified.')
  }

  if (-not [string]::IsNullOrWhiteSpace($MediaTargetDir)) {
    try {
      $null = Invoke-ReleaseCompatibilityGate -TargetDir $MediaTargetDir
    } catch {
      $blockers.Add("version/supply_chain: $($_.Exception.Message)")
    }
  }

  if ($blockers.Count -gt 0) {
    throw ("Non-negotiable abort conditions were met: {0}" -f ($blockers -join '; '))
  }
}

function Show-DiskOverview {
  Write-Section 'Disk Overview'
  $disks = Get-Disk | Sort-Object Number
  foreach ($d in $disks) {
    $sizeGiB = Convert-ToGiB -Bytes $d.Size
    $freeGiB = Convert-ToGiB -Bytes $d.LargestFreeExtent
    Write-Info ("Disk {0}: {1} | {2} GiB | Free(unallocated): {3} GiB | Bus: {4}" -f $d.Number, $d.FriendlyName, $sizeGiB, $freeGiB, $d.BusType)
  }
}

function Invoke-UnallocatedSpacePreparation {
  param([int]$DesiredGiB = 120)

  Write-Section 'Partition Space Preparation'

  $targetDisk = Get-DefaultInternalDisk
  if (-not $targetDisk) {
    throw 'Unable to determine target internal disk.'
  }

  $currentFreeGiB = [int](Convert-ToGiB -Bytes $targetDisk.LargestFreeExtent)
  Write-Info "Target disk inferred as Disk $($targetDisk.Number) ($($targetDisk.FriendlyName))."
  Write-Info "Current unallocated space: $currentFreeGiB GiB"

  if ($currentFreeGiB -ge $DesiredGiB) {
    Write-Info "No resize needed. You already have at least $DesiredGiB GiB unallocated."
    return
  }

  $missing = $DesiredGiB - $currentFreeGiB
  Write-Warn "You are short by about $missing GiB of unallocated space."

  if (-not (Read-YesNo -Message 'Attempt to shrink C: automatically to create more space?' -DefaultYes $true)) {
    Write-Warn 'Skipping automatic resize. You can shrink manually in Disk Management.'
    return
  }

  $cPart = Get-Partition -DriveLetter C
  $supported = Get-PartitionSupportedSize -DriveLetter C

  $maxShrinkBytes = [UInt64]($cPart.Size - $supported.SizeMin)
  $maxShrinkGiB = [int](Convert-ToGiB -Bytes $maxShrinkBytes)

  if ($maxShrinkGiB -lt 20) {
    Write-Warn 'Windows reports very limited shrink capacity. Defrag/reboot and try again, or shrink manually.'
    return
  }

  $recommendedShrinkGiB = [Math]::Min([Math]::Max($missing, 80), $maxShrinkGiB)
  $shrinkGiB = Read-Int -Message "Enter shrink size in GiB (max $maxShrinkGiB)" -Default $recommendedShrinkGiB -Min 20 -Max $maxShrinkGiB

  $newSize = [UInt64]($cPart.Size - ($shrinkGiB * 1GB))

  if (-not (Read-YesNo -Message "Resize C: down by $shrinkGiB GiB now?" -DefaultYes $false)) {
    Write-Warn 'Resize cancelled by user.'
    return
  }

  Write-UiProgress -Id 31 -Activity 'Resizing Windows partition' -Status "Shrinking C: by $shrinkGiB GiB | ETA ~3 min" -PercentComplete 20 -SecondsRemaining 180
  Resize-Partition -DriveLetter C -Size $newSize
  Write-UiProgress -Id 31 -Activity 'Resizing Windows partition' -Status 'Resize complete' -PercentComplete 100
  Write-UiProgress -Id 31 -Activity 'Resizing Windows partition' -Completed

  $updated = Get-Disk -Number $targetDisk.Number
  $newFreeGiB = [int](Convert-ToGiB -Bytes $updated.LargestFreeExtent)
  Write-Info "Resize complete. New unallocated space on Disk $($targetDisk.Number): $newFreeGiB GiB"
}

function Get-LatestArchIso {
  $base = 'https://geo.mirror.pkgbuild.com/iso/latest/'
  Write-Info "Querying $base for latest ISO..."
  $resp = Invoke-WebRequest -Uri $base -UseBasicParsing

  $match = [regex]::Matches($resp.Content, 'archlinux-[0-9]{4}\.[0-9]{2}\.[0-9]{2}-x86_64\.iso') |
    Select-Object -ExpandProperty Value -Unique |
    Sort-Object -Descending |
    Select-Object -First 1

  if (-not $match) {
    throw 'Could not find latest Arch ISO from mirror index.'
  }

  $isoName = $match
  $shaName = "sha256sums.txt"

  return [PSCustomObject]@{
    IsoName = $isoName
    IsoUrl  = "$base$isoName"
    ShaUrl  = "$base$shaName"
  }
}

function Get-GitHubReleaseIso {
  # Queries the GitHub Releases API for the latest omarchy-auto ISO.
  # Returns $null if no release is found, otherwise a PSCustomObject with
  # IsoUrl, ShaUrl, ReleaseManifestUrl, CompatibilityManifestUrl, Repository, Tag, and IsoName.
  param(
    [string]$Owner = '',
    [string]$Repo  = ''
  )

  $resolvedFromOrigin = $false
  if ([string]::IsNullOrWhiteSpace($Owner) -or [string]::IsNullOrWhiteSpace($Repo)) {
    try {
      $remoteUrl = (& git remote get-url origin 2>$null | Select-Object -First 1)
      if (-not [string]::IsNullOrWhiteSpace($remoteUrl)) {
        $remoteUrl = $remoteUrl.Trim()
        $m = [regex]::Match($remoteUrl, 'github\.com[:/](?<owner>[^/]+)/(?<repo>[^/.]+)(?:\.git)?$', [System.Text.RegularExpressions.RegexOptions]::IgnoreCase)
        if ($m.Success) {
          if ([string]::IsNullOrWhiteSpace($Owner)) { $Owner = $m.Groups['owner'].Value }
          if ([string]::IsNullOrWhiteSpace($Repo)) { $Repo = $m.Groups['repo'].Value }
          $resolvedFromOrigin = $true
          Write-DebugLog -Category 'github.release.repo' -Message ("Resolved from git origin: owner='{0}' repo='{1}'" -f $Owner, $Repo)
        }
      }
    } catch {
      Write-DebugLog -Category 'github.release.repo.warn' -Message $_.Exception.Message
    }
  }

  if ([string]::IsNullOrWhiteSpace($Owner)) { $Owner = 'lachthox' }
  if ([string]::IsNullOrWhiteSpace($Repo)) { $Repo = 'OmarchyInstaller' }

  $apiUrl = "https://api.github.com/repos/$Owner/$Repo/releases/latest"
  Write-DebugLog -Category 'github.release' -Message ("Querying {0}" -f $apiUrl)

  try {
    $headers = @{ 'Accept' = 'application/vnd.github+json'; 'User-Agent' = 'OmarchyInstaller/1.0' }
    $release = Invoke-RestMethod -Uri $apiUrl -Headers $headers -UseBasicParsing -ErrorAction Stop
  } catch {
    Write-DebugLog -Category 'github.release.error' -Message $_.Exception.Message
    return $null
  }

  $isoAsset = $release.assets | Where-Object { $_.name -match '-omarchy-auto\.iso$' } | Select-Object -First 1
  $shaAsset = $release.assets | Where-Object { $_.name -match '-omarchy-auto\.iso\.sha256$' } | Select-Object -First 1
  $releaseManifestAsset = $release.assets | Where-Object { $_.name -eq 'release_manifest.json' } | Select-Object -First 1
  $compatibilityManifestAsset = $release.assets | Where-Object { $_.name -eq 'compatibility_manifest.json' } | Select-Object -First 1

  if (-not $isoAsset) {
    Write-DebugLog -Category 'github.release.warn' -Message 'No omarchy-auto ISO asset found in latest release.'
    return $null
  }

  return [PSCustomObject]@{
    IsoUrl  = [string]$isoAsset.browser_download_url
    ShaUrl  = if ($shaAsset) { [string]$shaAsset.browser_download_url } else { $null }
    ReleaseManifestUrl = if ($releaseManifestAsset) { [string]$releaseManifestAsset.browser_download_url } else { $null }
    CompatibilityManifestUrl = if ($compatibilityManifestAsset) { [string]$compatibilityManifestAsset.browser_download_url } else { $null }
    Repository = "$Owner/$Repo"
    RepositoryResolvedFromOrigin = $resolvedFromOrigin
    Tag     = [string]$release.tag_name
    IsoName = [string]$isoAsset.name
  }
}

function Get-CurrentExecutablePath {
  try {
    return [System.Diagnostics.Process]::GetCurrentProcess().MainModule.FileName
  } catch {
    return $null
  }
}

function Get-FileSha256 {
  param(
    [Parameter(Mandatory = $true)][string]$Path
  )

  if (-not (Test-Path -LiteralPath $Path)) {
    return $null
  }

  return (Get-FileHash -Path $Path -Algorithm SHA256).Hash.Trim().ToLowerInvariant()
}

function Convert-ToVersionObject {
  param(
    [string]$Value
  )

  if ([string]::IsNullOrWhiteSpace($Value)) {
    return $null
  }

  $normalized = ([string]$Value).Trim() -replace '[^0-9\.]', ''
  if ([string]::IsNullOrWhiteSpace($normalized)) {
    return $null
  }

  try {
    return [version]$normalized
  } catch {
    return $null
  }
}

function Test-VersionAtLeast {
  param(
    [string]$Current,
    [string]$Minimum
  )

  $currentVersion = Convert-ToVersionObject -Value $Current
  $minimumVersion = Convert-ToVersionObject -Value $Minimum
  if (-not $currentVersion -or -not $minimumVersion) {
    return $null
  }

  return ($currentVersion -ge $minimumVersion)
}

function Get-ReleaseCompatibilityReport {
  param(
    [Parameter(Mandatory = $true)][string]$TargetDir
  )

  $report = [ordered]@{
    CanProceed = $true
    Checks = [System.Collections.Generic.List[object]]::new()
  }

  $release = Get-GitHubReleaseIso
  if (-not $release) {
    $report.Checks.Add([PSCustomObject]@{
      Name = 'release_metadata'
      Status = 'warn'
      Message = 'Latest release metadata is unavailable; skipping freshness enforcement.'
      Current = 'unavailable'
      Expected = 'latest GitHub release assets'
    })
    return [PSCustomObject]$report
  }

  if (-not $release.ReleaseManifestUrl -or -not $release.CompatibilityManifestUrl) {
    $report.Checks.Add([PSCustomObject]@{
      Name = 'release_metadata_assets'
      Status = 'warn'
      Message = 'Latest release is missing release or compatibility manifest assets; compatibility checks are limited.'
      Current = "releaseManifest=$($release.ReleaseManifestUrl) compatibilityManifest=$($release.CompatibilityManifestUrl)"
      Expected = 'both manifest assets'
    })
    return [PSCustomObject]$report
  }

  try {
    $headers = @{ 'Accept' = 'application/vnd.github+json'; 'User-Agent' = 'OmarchyInstaller/1.0' }
    $releaseManifest = Invoke-RestMethod -Uri $release.ReleaseManifestUrl -Headers $headers -UseBasicParsing -ErrorAction Stop
    $compatibilityManifest = Invoke-RestMethod -Uri $release.CompatibilityManifestUrl -Headers $headers -UseBasicParsing -ErrorAction Stop
  } catch {
    $report.Checks.Add([PSCustomObject]@{
      Name = 'release_manifest_fetch'
      Status = 'warn'
      Message = 'Could not load release compatibility metadata; freshness checks were skipped.'
      Current = $_.Exception.Message
      Expected = 'reachable release_manifest.json and compatibility_manifest.json assets'
    })
    return [PSCustomObject]$report
  }

  $releaseTag = [string]$releaseManifest.tag
  $compatibilityTag = [string]$compatibilityManifest.tag
  if ($releaseTag -ne $compatibilityTag) {
    $report.CanProceed = $false
    $report.Checks.Add([PSCustomObject]@{
      Name = 'build_pairing'
      Status = 'fail'
      Message = 'Release and compatibility manifests disagree on the release tag.'
      Current = $releaseTag
      Expected = $compatibilityTag
    })
  }

  if (-not $release.RepositoryResolvedFromOrigin) {
    $report.Checks.Add([PSCustomObject]@{
      Name = 'repo_contract'
      Status = 'warn'
      Message = 'Git origin did not resolve cleanly; using the default GitHub repository contract.'
      Current = $release.Repository
      Expected = 'resolved from git origin'
    })
  } else {
    $report.Checks.Add([PSCustomObject]@{
      Name = 'repo_contract'
      Status = 'pass'
      Message = 'Git origin resolved to the release repository contract.'
      Current = $release.Repository
      Expected = $release.Repository
    })
  }

  $releaseIsoSha = [string]$releaseManifest.artifacts.iso.sha256
  $compatIsoSha = [string]$compatibilityManifest.artifact_pairing.iso_sha256
  if ($releaseIsoSha -and $compatIsoSha -and $releaseIsoSha -ne $compatIsoSha) {
    $report.CanProceed = $false
    $report.Checks.Add([PSCustomObject]@{
      Name = 'build_pairing_iso'
      Status = 'fail'
      Message = 'Release and compatibility manifests disagree on the ISO SHA256.'
      Current = $releaseIsoSha
      Expected = $compatIsoSha
    })
  }

  $releaseExeSha = [string]$releaseManifest.artifacts.exe.sha256
  $compatExeSha = [string]$compatibilityManifest.artifact_pairing.exe_sha256
  if ($releaseExeSha -and $compatExeSha -and $releaseExeSha -ne $compatExeSha) {
    $report.CanProceed = $false
    $report.Checks.Add([PSCustomObject]@{
      Name = 'build_pairing_exe'
      Status = 'fail'
      Message = 'Release and compatibility manifests disagree on the EXE SHA256.'
      Current = $releaseExeSha
      Expected = $compatExeSha
    })
  }

  $supportedSchema = $script:SupportedPlanSchemaVersion
  $releaseSchema = [string]$releaseManifest.contracts.plan_schema_version
  $compatSchema = [string]$compatibilityManifest.minimum_versions.live_runtime_plan_schema_version
  if (($releaseSchema -and $releaseSchema -ne $supportedSchema) -or ($compatSchema -and $compatSchema -ne $supportedSchema)) {
    $report.CanProceed = $false
    $report.Checks.Add([PSCustomObject]@{
      Name = 'schema_compatibility'
      Status = 'fail'
      Message = 'The Windows app schema contract does not match the latest release compatibility contract.'
      Current = "release=$releaseSchema compatibility=$compatSchema supported=$supportedSchema"
      Expected = $supportedSchema
    })
  }

  $bootstrapExpectations = $compatibilityManifest.bootstrap_expectations
  $expectedBootstrapContracts = [ordered]@{
    live_entrypoint = 'python3 /opt/omarchy-installer/main.py'
    live_setup_wrapper = '/opt/omarchy-setup/setup.sh'
    live_entrypoint_compat_alias = 'python3 /opt/omarchy-setup/main.py'
    firstboot_wrapper_target = '/usr/local/bin/omarchy-firstboot-wrapper.sh'
    omarchy_timing_contract = 'post-install-only'
  }

  if (-not $bootstrapExpectations) {
    $report.Checks.Add([PSCustomObject]@{
      Name = 'bootstrap_expectations'
      Status = 'warn'
      Message = 'Compatibility manifest does not include bootstrap expectations; skipping strict location enforcement.'
      Current = 'missing'
      Expected = 'bootstrap_expectations object'
    })
  } else {
    foreach ($entry in $expectedBootstrapContracts.GetEnumerator()) {
      $actual = [string]$bootstrapExpectations.($entry.Key)
      if ([string]::IsNullOrWhiteSpace($actual)) {
        $report.Checks.Add([PSCustomObject]@{
          Name = "bootstrap_$($entry.Key)"
          Status = 'warn'
          Message = 'Bootstrap expectation is missing from compatibility metadata; strict enforcement skipped for this field.'
          Current = 'missing'
          Expected = $entry.Value
        })
        continue
      }

      if ($actual -ne $entry.Value) {
        $report.CanProceed = $false
        $report.Checks.Add([PSCustomObject]@{
          Name = "bootstrap_$($entry.Key)"
          Status = 'fail'
          Message = 'The bootstrap location contract has drifted from the expected release metadata.'
          Current = $actual
          Expected = $entry.Value
        })
        continue
      }

      $report.Checks.Add([PSCustomObject]@{
        Name = "bootstrap_$($entry.Key)"
        Status = 'pass'
        Message = 'Bootstrap location contract matches the release metadata.'
        Current = $actual
        Expected = $entry.Value
      })
    }
  }

  $exePath = Get-CurrentExecutablePath
  if ($exePath) {
    $exeName = [System.IO.Path]::GetFileName($exePath)
    $exeHash = Get-FileSha256 -Path $exePath
    $exeVersion = ''
    try {
      $exeVersion = ([System.Diagnostics.FileVersionInfo]::GetVersionInfo($exePath)).FileVersion
    } catch {
      $exeVersion = ''
    }

    if ($exeName -notin @('powershell.exe', 'pwsh.exe')) {
      $versionCheck = Test-VersionAtLeast -Current $exeVersion -Minimum ([string]$compatibilityManifest.minimum_versions.windows_prep_exe_version)
      if ($versionCheck -eq $false) {
        $report.CanProceed = $false
        $report.Checks.Add([PSCustomObject]@{
          Name = 'stale_exe_version'
          Status = 'fail'
          Message = 'The running Windows app build is older than the latest compatible release.'
          Current = $exeVersion
          Expected = [string]$compatibilityManifest.minimum_versions.windows_prep_exe_version
        })
      }

      if ($exeHash) {
        if ($exeHash -ne $compatExeSha) {
          $report.CanProceed = $false
          $report.Checks.Add([PSCustomObject]@{
            Name = 'stale_exe_hash'
            Status = 'fail'
            Message = 'The running Windows app binary does not match the latest release pairing.'
            Current = $exeHash
            Expected = $compatExeSha
          })
        }
      } else {
        $report.Checks.Add([PSCustomObject]@{
          Name = 'exe_hash_validation'
          Status = 'warn'
          Message = 'The packaged EXE hash could not be computed.'
          Current = $exeName
          Expected = $compatExeSha
        })
      }
    } else {
      $report.Checks.Add([PSCustomObject]@{
        Name = 'exe_freshness'
        Status = 'warn'
        Message = 'Running under a shell host, so packaged EXE freshness checks were skipped.'
        Current = $exeName
        Expected = 'packaged OmarchyInstaller.exe'
      })
    }
  }

  $isoPath = Join-Path $TargetDir $release.IsoName
  if (Test-Path -LiteralPath $isoPath) {
    $isoHash = Get-FileSha256 -Path $isoPath
    if ($isoHash -and $isoHash -ne $compatIsoSha) {
      $report.Checks.Add([PSCustomObject]@{
        Name = 'stale_iso_cache'
        Status = 'warn'
        Message = 'A cached Ventoy ISO is present but does not match the latest compatible release; it will be refreshed before use.'
        Current = $isoHash
        Expected = $compatIsoSha
      })
    } elseif ($isoHash) {
      $report.Checks.Add([PSCustomObject]@{
        Name = 'stale_iso_cache'
        Status = 'pass'
        Message = 'Cached Ventoy ISO matches the latest compatible release.'
        Current = $isoHash
        Expected = $compatIsoSha
      })
    }
  } else {
    $report.Checks.Add([PSCustomObject]@{
      Name = 'stale_iso_cache'
      Status = 'warn'
      Message = 'No cached Ventoy ISO was found locally; the latest release will be downloaded on demand.'
      Current = 'missing'
      Expected = $release.IsoName
    })
  }

  return [PSCustomObject]$report
}

function Write-ReleaseCompatibilityReport {
  param(
    [Parameter(Mandatory = $true)]$Report
  )

  Write-Section 'Release Compatibility'
  foreach ($check in $Report.Checks) {
    switch ($check.Status) {
      'pass' { Write-Info ("[PASS] {0}: {1}" -f $check.Name, $check.Message) }
      'warn' { Write-Warn ("[WARN] {0}: {1}" -f $check.Name, $check.Message) }
      default { Write-Warn ("[FAIL] {0}: {1}" -f $check.Name, $check.Message) }
    }
  }
}

function Invoke-ReleaseCompatibilityGate {
  param(
    [Parameter(Mandatory = $true)][string]$TargetDir
  )

  $report = Get-ReleaseCompatibilityReport -TargetDir $TargetDir
  Write-ReleaseCompatibilityReport -Report $report

  if (-not $report.CanProceed) {
    $failures = $report.Checks | Where-Object { $_.Status -eq 'fail' }
    $summary = ($failures | ForEach-Object { "$($_.Name): $($_.Message)" }) -join '; '
    throw "Release/update compatibility check failed: $summary"
  }

  return $report
}

function Invoke-DownloadCustomizedIso {
  # Downloads the pre-built customized ISO from GitHub Releases.
  # Returns the local path to the downloaded ISO, or $null on failure.
  param(
    [Parameter(Mandatory = $true)][string]$TargetDir,
    [int]$ProgressId = 43
  )

  $activity = 'Downloading Customized ISO'
  Write-UiProgress -Id $ProgressId -Activity $activity -Status 'Querying GitHub for latest release...' -PercentComplete 5

  $release = Get-GitHubReleaseIso
  if (-not $release) {
    Write-Warn 'No pre-built customized ISO found in GitHub Releases.'
    Write-Info 'The ISO is built automatically by CI. If this is a fresh repo, push to main first.'
    return $null
  }

  Write-Info ("Found release: {0} ({1})" -f $release.Tag, $release.IsoName)
  $isoPath = Join-Path $TargetDir $release.IsoName

  if (Test-Path -LiteralPath $isoPath) {
    Write-Info "Customized ISO already cached: $isoPath"
  } else {
    Write-Info "Downloading customized ISO: $($release.IsoName)"
    Invoke-DownloadWithProgress -Url $release.IsoUrl -OutFile $isoPath -Activity $activity -ProgressId $ProgressId
  }

  # Verify checksum if .sha256 asset is available
  if ($release.ShaUrl) {
    $shaPath = Join-Path $TargetDir ($release.IsoName + '.sha256')
    Write-UiProgress -Id $ProgressId -Activity $activity -Status 'Downloading checksum...' -PercentComplete 90
    Invoke-DownloadWithProgress -Url $release.ShaUrl -OutFile $shaPath -Activity 'Downloading checksum' -ProgressId ($ProgressId + 1)

    $shaLine = (Get-Content -LiteralPath $shaPath -ErrorAction Stop | Select-Object -First 1)
    $expected = ($shaLine -split '\s+')[0].Trim().ToLowerInvariant()
    $actual = (Get-FileHash -Path $isoPath -Algorithm SHA256).Hash.Trim().ToLowerInvariant()

    if ($expected -ne $actual) {
      Write-Warn 'Customized ISO checksum mismatch. Deleting and re-downloading...'
      Remove-Item -LiteralPath $isoPath -Force
      Invoke-DownloadWithProgress -Url $release.IsoUrl -OutFile $isoPath -Activity 'Re-downloading customized ISO' -ProgressId $ProgressId
      $actual = (Get-FileHash -Path $isoPath -Algorithm SHA256).Hash.Trim().ToLowerInvariant()
      if ($expected -ne $actual) {
        throw "SHA256 mismatch for customized ISO after re-download. Expected=$expected Actual=$actual"
      }
    }

    Write-Info 'Customized ISO checksum verified.'
  } else {
    Write-Warn 'No .sha256 asset in release — skipping checksum verification.'
  }

  Write-UiProgress -Id $ProgressId -Activity $activity -Completed
  return $isoPath
}

function Get-FreeDriveLetter {
  $used = (Get-Volume | Where-Object DriveLetter | Select-Object -ExpandProperty DriveLetter)
  foreach ($letter in 'U','V','W','X','Y','Z') {
    if ($used -notcontains $letter) {
      return $letter
    }
  }

  throw 'No free drive letter available for USB assignment.'
}

function Get-VentoyCliPath {
  $cmd = Get-Command 'Ventoy2Disk.exe' -ErrorAction SilentlyContinue
  if ($cmd) {
    return $cmd.Source
  }

  $candidateRoots = @(
    (Join-Path $env:LOCALAPPDATA 'Microsoft\WinGet\Packages'),
    (Join-Path ${env:ProgramFiles} 'Ventoy'),
    (Join-Path ${env:ProgramFiles(x86)} 'Ventoy')
  )

  foreach ($root in $candidateRoots) {
    if (-not [string]::IsNullOrWhiteSpace($root) -and (Test-Path -LiteralPath $root)) {
      $exe = Get-ChildItem -LiteralPath $root -Recurse -File -Filter 'Ventoy2Disk.exe' -ErrorAction SilentlyContinue |
        Select-Object -First 1
      if ($exe) {
        return $exe.FullName
      }
    }
  }

  return $null
}

function Install-VentoyCli {
  $ventoyPath = [string](Get-VentoyCliPath)
  if ($ventoyPath) {
    return $ventoyPath
  }

  if (-not (Get-Command winget -ErrorAction SilentlyContinue)) {
    throw 'Ventoy CLI not found and winget is not available. Install Ventoy manually or install winget.'
  }

  if (-not (Read-YesNo -Message 'Ventoy CLI is not installed. Install Ventoy now via winget?' -DefaultYes $true)) {
    throw 'Ventoy CLI is required for command-line USB media creation.'
  }

  Write-Info 'Installing Ventoy via winget...'
  $null = (& winget install --id Ventoy.Ventoy --exact --silent --accept-package-agreements --accept-source-agreements 2>&1)
  if ($LASTEXITCODE -ne 0) {
    throw "winget install Ventoy failed with exit code $LASTEXITCODE."
  }

  $ventoyPath = [string](Get-VentoyCliPath)
  if (-not $ventoyPath) {
    throw 'Ventoy appears installed but Ventoy2Disk.exe was not found.'
  }

  return $ventoyPath
}

function Get-UsbDataDriveLetter {
  param([Parameter(Mandatory = $true)][int]$UsbDiskNumber)

  $partitions = Get-Partition -DiskNumber $UsbDiskNumber -ErrorAction Stop | Sort-Object PartitionNumber
  $volumes = foreach ($partition in $partitions) {
    try {
      $vol = $partition | Get-Volume -ErrorAction Stop
      if ($vol) {
        [PSCustomObject]@{
          PartitionNumber = $partition.PartitionNumber
          DriveLetter     = $vol.DriveLetter
          FileSystem      = $vol.FileSystem
          Size            = $partition.Size
        }
      }
    } catch {
      Write-Verbose "Skipping partition $($partition.PartitionNumber): no readable volume metadata."
    }
  }

  $candidate = $volumes |
    Where-Object { $_.DriveLetter -and $_.FileSystem -in @('exFAT', 'NTFS', 'FAT32') } |
    Sort-Object Size -Descending |
    Select-Object -First 1

  if ($candidate) {
    return [string]$candidate.DriveLetter
  }

  $targetPartition = $partitions | Sort-Object Size -Descending | Select-Object -First 1
  if (-not $targetPartition) {
    return $null
  }

  Add-PartitionAccessPath -DiskNumber $UsbDiskNumber -PartitionNumber $targetPartition.PartitionNumber -AssignDriveLetter -ErrorAction Stop
  Start-Sleep -Seconds 2

  $updated = Get-Partition -DiskNumber $UsbDiskNumber -PartitionNumber $targetPartition.PartitionNumber -ErrorAction Stop | Get-Volume -ErrorAction SilentlyContinue
  if ($updated -and $updated.DriveLetter) {
    return [string]$updated.DriveLetter
  }

  return $null
}

function Copy-FileWithProgress {
  param(
    [Parameter(Mandatory = $true)][string]$Source,
    [Parameter(Mandatory = $true)][string]$Destination,
    [string]$Activity = 'Copying file',
    [int]$ProgressId = 55
  )

  $src = Get-Item -LiteralPath $Source -ErrorAction Stop
  $totalBytes = [int64]$src.Length
  $copiedBytes = [int64]0
  $buffer = New-Object byte[] (4MB)
  $stopwatch = [System.Diagnostics.Stopwatch]::StartNew()
  $nextLogPercent = 10
  Write-DebugLog -Category 'copy.start' -Message ("activity='{0}' source='{1}' destination='{2}' bytes={3}" -f $Activity, $Source, $Destination, $totalBytes)

  $destDir = Split-Path -Path $Destination -Parent
  if ($destDir) {
    New-Item -ItemType Directory -Path $destDir -Force | Out-Null
  }

  $srcStream = [System.IO.File]::OpenRead($src.FullName)
  $dstStream = [System.IO.File]::Open($Destination, [System.IO.FileMode]::Create, [System.IO.FileAccess]::Write, [System.IO.FileShare]::None)
  try {
    while (($read = $srcStream.Read($buffer, 0, $buffer.Length)) -gt 0) {
      $dstStream.Write($buffer, 0, $read)
      $copiedBytes += $read

      $percent = if ($totalBytes -gt 0) { [Math]::Min(100, [int](($copiedBytes * 100) / $totalBytes)) } else { 0 }
      $rate = if ($stopwatch.Elapsed.TotalSeconds -gt 0) { $copiedBytes / $stopwatch.Elapsed.TotalSeconds } else { 0.0 }
      $remainingSeconds = if ($rate -gt 0) { ($totalBytes - $copiedBytes) / $rate } else { -1 }
      $status = ('{0:N1}/{1:N1} MiB | ETA {2}' -f ($copiedBytes / 1MB), ($totalBytes / 1MB), (Format-Eta -Seconds $remainingSeconds))
      Write-UiProgress -Id $ProgressId -Activity $Activity -Status $status -PercentComplete $percent -SecondsRemaining ([int][Math]::Max(0, [Math]::Ceiling($remainingSeconds)))
      if ($percent -ge $nextLogPercent) {
        Write-DebugLog -Category 'copy.progress' -Message ("activity='{0}' pct={1} bytes={2}/{3} elapsedSec={4:N1}" -f $Activity, $percent, $copiedBytes, $totalBytes, $stopwatch.Elapsed.TotalSeconds)
        while ($percent -ge $nextLogPercent) {
          $nextLogPercent += 10
        }
      }
    }
    Write-DebugLog -Category 'copy.complete' -Message ("activity='{0}' bytes={1} elapsedSec={2:N1}" -f $Activity, $copiedBytes, $stopwatch.Elapsed.TotalSeconds)
  } finally {
    $srcStream.Dispose()
    $dstStream.Dispose()
  }

  Write-UiProgress -Id $ProgressId -Activity $Activity -Completed
}

function Invoke-UsbFromIsoUefi {
  param(
    [Parameter(Mandatory = $true)][string]$IsoPath,
    [Parameter(Mandatory = $true)][int]$UsbDiskNumber
  )

  Write-Section 'USB Creation (CLI mode)'
  Write-Warn "This will ERASE all data on USB disk $UsbDiskNumber."

  if (-not (Read-YesNo -Message 'Proceed with USB wipe and creation?' -DefaultYes $false)) {
    Write-Warn 'USB creation cancelled.'
    return
  }

  if (-not (Test-Path -LiteralPath $IsoPath)) {
    throw "ISO not found: $IsoPath"
  }

  $usbDisk = Get-Disk -Number $UsbDiskNumber -ErrorAction Stop
  if ($usbDisk.BusType -ne 'USB') {
    throw "Refusing to write to non-USB disk $UsbDiskNumber ($($usbDisk.BusType))."
  }

  $ventoyExe = Install-VentoyCli
  Write-Info "Using Ventoy CLI: $ventoyExe"
  Write-DebugLog -Category 'ventoy.exec' -Message ("exe='{0}' disk={1}" -f $ventoyExe, $UsbDiskNumber)

  $usbProgressId = 52
  $usbTotal = 3
  $usbStep = 0
  $usbStep++
  Write-StageProgress -Id $usbProgressId -Step $usbStep -Total $usbTotal -Activity 'USB media creation' -EtaMinutes 6
  Write-UiProgress -Id 53 -Activity 'Installing Ventoy to USB' -Status 'Writing bootable Ventoy layout | ETA ~2 min' -PercentComplete 25 -SecondsRemaining 120
  $ventoyOutput = (& $ventoyExe VTOYCLI /I "/PhyDrive:$UsbDiskNumber" /GPT 2>&1 | Out-String).Trim()
  if (-not [string]::IsNullOrWhiteSpace($ventoyOutput)) {
    Write-DebugLog -Category 'ventoy.output' -Message $ventoyOutput
  }
  Write-DebugLog -Category 'ventoy.exit' -Message ("exitCode={0}" -f $LASTEXITCODE)
  if ($LASTEXITCODE -ne 0) {
    if (-not [string]::IsNullOrWhiteSpace($ventoyOutput)) {
      Write-Err "Ventoy output:`n$ventoyOutput"
    }
    throw "Ventoy CLI failed with exit code $LASTEXITCODE."
  }
  Write-UiProgress -Id 53 -Activity 'Installing Ventoy to USB' -Status 'Ventoy install complete' -PercentComplete 100
  Write-UiProgress -Id 53 -Activity 'Installing Ventoy to USB' -Completed

  $dataDrive = Get-UsbDataDriveLetter -UsbDiskNumber $UsbDiskNumber
  if (-not $dataDrive) {
    throw 'Could not determine USB data partition drive letter after Ventoy install.'
  }

  $usbStep++
  Write-StageProgress -Id $usbProgressId -Step $usbStep -Total $usbTotal -Activity 'USB media creation' -EtaMinutes 4
  $isoName = Split-Path -Path $IsoPath -Leaf
  $dstPath = "${dataDrive}:\$isoName"
  Write-Info "Copying ISO file to Ventoy volume ${dataDrive}: ..."
  Copy-FileWithProgress -Source $IsoPath -Destination $dstPath -Activity 'Copying ISO to USB' -ProgressId 51

  $usbStep++
  Write-StageProgress -Id $usbProgressId -Step $usbStep -Total $usbTotal -Activity 'USB media creation'
  Write-UiProgress -Id $usbProgressId -Activity 'USB media creation' -Completed
  Write-Info "USB live media is ready. Boot from USB and select $isoName in Ventoy menu."
}

function Invoke-MediaWorkflow {
  Write-Section 'Live Media Workflow'
  $workflowId = 20
  $workflowTotal = 7
  $workflowStep = 0

  if (-not (Read-YesNo -Message 'Do you want this script to download Arch ISO and create the USB media?' -DefaultYes $true)) {
    Write-Info 'Skipping media workflow. You can use Rufus manually.'
    return
  }

  $workflowStep++
  Write-StageProgress -Id $workflowId -Step $workflowStep -Total $workflowTotal -Activity 'Live media setup' -EtaMinutes 25
  # Keep media artifacts in a deterministic location under the script directory.
  $targetDir = [System.IO.Path]::GetFullPath((Join-Path $PSScriptRoot 'media'))
  New-Item -ItemType Directory -Path $targetDir -Force | Out-Null
  Write-Info "Using media directory: $targetDir"

  $workflowStep++
  Write-StageProgress -Id $workflowId -Step $workflowStep -Total $workflowTotal -Activity 'Live media setup' -EtaMinutes 20
  $isoMeta = Get-LatestArchIso
  $isoPath = Join-Path $targetDir $isoMeta.IsoName
  $shaPath = Join-Path $targetDir 'sha256sums.txt'

  $isoExisted = Test-Path $isoPath
  if (-not $isoExisted) {
    Write-Info "Downloading ISO: $($isoMeta.IsoUrl)"
    Invoke-DownloadWithProgress -Url $isoMeta.IsoUrl -OutFile $isoPath -Activity 'Downloading Arch ISO' -ProgressId 41
  } else {
    Write-Info "ISO already present: $isoPath"
  }

  $workflowStep++
  Write-StageProgress -Id $workflowId -Step $workflowStep -Total $workflowTotal -Activity 'Live media setup' -EtaMinutes 12
  Write-Info 'Downloading checksum file...'
  Invoke-DownloadWithProgress -Url $isoMeta.ShaUrl -OutFile $shaPath -Activity 'Downloading checksum' -ProgressId 42
  Start-Sleep -Milliseconds 200

  $workflowStep++
  Write-StageProgress -Id $workflowId -Step $workflowStep -Total $workflowTotal -Activity 'Live media setup' -EtaMinutes 10
  $expectedLine = (Get-Content $shaPath | Select-String -Pattern ("\b" + [regex]::Escape($isoMeta.IsoName) + "\b") | Select-Object -First 1).Line
  $expected = $null
  if ($expectedLine) {
    $expectedParts = $expectedLine.Split(' ', [System.StringSplitOptions]::RemoveEmptyEntries)
    if ($expectedParts.Count -gt 0) {
      $expected = $expectedParts[0].Trim().ToLowerInvariant()
    }
  }
  if ([string]::IsNullOrWhiteSpace($expected)) {
    throw "Could not find checksum for $($isoMeta.IsoName) in $shaPath"
  }

  # Add a small delay for race condition mitigation as requested.
  Start-Sleep -Milliseconds 500
  $actual = (Get-FileHash -Path $isoPath -Algorithm SHA256).Hash.Trim().ToLowerInvariant()

  if ($expected -ne $actual) {
    if ($isoExisted) {
      Write-Warn 'Existing ISO hash mismatch. Deleting and re-downloading...'
      Remove-Item -LiteralPath $isoPath -Force
      Invoke-DownloadWithProgress -Url $isoMeta.IsoUrl -OutFile $isoPath -Activity 'Re-downloading Arch ISO' -ProgressId 41
      Start-Sleep -Milliseconds 500
      $actual = (Get-FileHash -Path $isoPath -Algorithm SHA256).Hash.Trim().ToLowerInvariant()
    } else {
      # Mismatch on fresh download — re-download the file instead of just re-hashing.
      Write-Warn 'Download hash mismatch. Deleting and re-downloading...'
      Remove-Item -LiteralPath $isoPath -Force
      Invoke-DownloadWithProgress -Url $isoMeta.IsoUrl -OutFile $isoPath -Activity 'Re-downloading Arch ISO' -ProgressId 41
      Start-Sleep -Milliseconds 500
      $actual = (Get-FileHash -Path $isoPath -Algorithm SHA256).Hash.Trim().ToLowerInvariant()
    }

    if ($expected -ne $actual) {
      throw 'SHA256 mismatch for downloaded ISO. Aborting media creation.'
    }
  }

  Write-Info 'ISO checksum verified.'

  Write-StageProgress -Id $workflowId -Step $workflowStep -Total $workflowTotal -Activity 'Live media setup' -EtaMinutes 9 -Status 'Awaiting ISO customization decision'

  if (Read-YesNo -Message 'Use a pre-built customized ISO that auto-prompts setup.sh on first live boot?' -DefaultYes $true) {
    $workflowStep++
    Write-StageProgress -Id $workflowId -Step $workflowStep -Total $workflowTotal -Activity 'Live media setup' -EtaMinutes 9 -Status 'Downloading customized ISO from GitHub Releases'
    $customIsoPath = Invoke-DownloadCustomizedIso -TargetDir $targetDir
    if ($customIsoPath) {
      $isoPath = $customIsoPath
      Write-Info "Customized ISO ready: $isoPath"
    } else {
      Write-Warn 'Could not obtain customized ISO. Falling back to stock Arch ISO.'
      Write-Info 'You will need to launch setup.sh manually from the live environment.'
    }
  } else {
    $workflowStep++
    Write-StageProgress -Id $workflowId -Step $workflowStep -Total $workflowTotal -Activity 'Live media setup' -EtaMinutes 9 -Status 'Skipping ISO customization'
  }

  $usbDisks = Get-Disk | Where-Object { $_.BusType -eq 'USB' -and $_.Size -gt 0 } | Sort-Object Number
  if (-not $usbDisks) {
    Write-Warn 'No USB disk detected. Insert your USB and run this script again.'
    return
  }

  Write-Info ''
  Write-Info 'Detected USB disks:'
  foreach ($d in $usbDisks) {
    Write-Info ("  Disk {0} | {1} | {2} GiB" -f $d.Number, $d.FriendlyName, (Convert-ToGiB -Bytes $d.Size))
  }

  $defaultUsb = ($usbDisks | Sort-Object Size | Select-Object -First 1).Number
  $usbChoice = Read-Int -Message 'Enter USB disk number to erase/create' -Default $defaultUsb -Min 0 -Max 128

  $selected = $usbDisks | Where-Object Number -EQ $usbChoice | Select-Object -First 1
  if (-not $selected) {
    Write-Warn 'Selected disk is not in the detected USB list. Cancelling for safety.'
    return
  }

  $workflowStep++
  Write-StageProgress -Id $workflowId -Step $workflowStep -Total $workflowTotal -Activity 'Live media setup' -EtaMinutes 8
  Invoke-UsbFromIsoUefi -IsoPath $isoPath -UsbDiskNumber $selected.Number
  $workflowStep++
  Write-StageProgress -Id $workflowId -Step $workflowStep -Total $workflowTotal -Activity 'Live media setup'
  Write-UiProgress -Id $workflowId -Activity 'Live media setup' -Completed
}

function Show-NextStep {
  Write-Section 'Next Steps'
  Write-Info '1. Reboot into BIOS/UEFI and confirm Secure Boot is disabled.'
  Write-Info '2. Boot from the Arch USB in UEFI mode.'
  Write-Info '3. Run omarchy-setup/setup.sh from the live environment.'
  Write-Info '4. Continue with installation-guide.md for full flow.'
}

function Main {
  Write-DebugLog -Category 'run.main.start' -Message ("runId={0}" -f $script:RunId)
  Write-Section 'Omarchy Windows Pre-Install Assistant'
  Write-Info 'This script prepares your Windows machine for Omarchy dual-boot and can optionally create live USB media.'
  $mainProgressId = 10
  $mainTotal = 5
  $mainStep = 0

  if (-not (Test-Admin)) {
    throw 'Run this script in an elevated PowerShell session (Run as Administrator).'
  }

  $secureBootState = Get-SecureBootState
  if (Invoke-SecureBootFirmwareReboot -SecureBootState $secureBootState) {
    return
  }

  $mainStep++
  Write-StageProgress -Id $mainProgressId -Step $mainStep -Total $mainTotal -Activity 'Windows pre-install workflow' -EtaMinutes 30
  Show-SystemReadiness -SecureBootState $secureBootState
  Invoke-NonNegotiableAbortGate -SecureBootState $secureBootState -MediaTargetDir ([System.IO.Path]::GetFullPath((Join-Path $PSScriptRoot 'media')))
  $mainStep++
  Write-StageProgress -Id $mainProgressId -Step $mainStep -Total $mainTotal -Activity 'Windows pre-install workflow' -EtaMinutes 25
  Show-DiskOverview

  if (Read-YesNo -Message 'Do you want help creating unallocated disk space now?' -DefaultYes $true) {
    $desired = Read-Int -Message 'Target unallocated space in GiB' -Default 120 -Min 40 -Max 1024
    $mainStep++
    Write-StageProgress -Id $mainProgressId -Step $mainStep -Total $mainTotal -Activity 'Windows pre-install workflow' -EtaMinutes 20
    Invoke-UnallocatedSpacePreparation -DesiredGiB $desired
  } else {
    $mainStep++
    Write-StageProgress -Id $mainProgressId -Step $mainStep -Total $mainTotal -Activity 'Windows pre-install workflow' -EtaMinutes 20
  }

  $mainStep++
  Write-StageProgress -Id $mainProgressId -Step $mainStep -Total $mainTotal -Activity 'Windows pre-install workflow' -EtaMinutes 15
  Invoke-MediaWorkflow
  $mainStep++
  Write-StageProgress -Id $mainProgressId -Step $mainStep -Total $mainTotal -Activity 'Windows pre-install workflow'
  Show-NextStep
  Write-UiProgress -Id $mainProgressId -Activity 'Windows pre-install workflow' -Completed
}

try {
  Main
  Write-DebugLog -Category 'run.main.complete' -Message 'Main completed successfully.'
} catch {
  Write-DebugLog -Category 'run.main.error' -Message ("type='{0}' message='{1}' stack='{2}'" -f $_.Exception.GetType().FullName, $_.Exception.Message, (($_.ScriptStackTrace -replace '\r?\n', ' | ')))
  throw
} finally {
  if ($script:RunStopwatch) {
    $script:RunStopwatch.Stop()
    Write-DebugLog -Category 'run.end' -Message ("runId={0} elapsedSec={1:N1}" -f $script:RunId, $script:RunStopwatch.Elapsed.TotalSeconds)
  }
}



