# Drive a REAL Windows GUI: move a window between monitors, capture it even when covered, and
# click it either with the real pointer or by posting messages.
#
# Why this exists: `windesk.py` drives Stockroom's own window through CDP dev-ids, which no
# third-party program has. Verifying Altium (or any other Windows app) needs a real pointer at a raw
# coordinate, and there was nothing in the toolkit that could do it.
#
# Zero dependencies on purpose (user32 + WinForms). The install's `.venv` has been wiped once
# already and does not carry pydirectinput, and a verification tool that needs its own install is a
# tool that will not be there when it matters.
#
# THREE TRAPS THIS ENCODES, each of which produced a silent wrong answer first:
#   1. Coordinates are SCREENSHOT PIXELS, converted here. A multi-monitor desktop can have a
#      NEGATIVE origin (measured: VirtualScreen.X = -1920), so a raw shot pixel drove the pointer
#      to x = -1, off every display, and the click landed nowhere while reporting success.
#   2. `shotwin` uses PrintWindow(hwnd, 2) so a COVERED window still captures its own content, and
#      nothing has to be raised. Raising steals focus, and a fullscreen game on another monitor can
#      minimise when it loses focus.
#   3. `move` restores before moving: a MAXIMIZED window ignores SetWindowPos and stays put.
#
# `mclick` posts WM_LBUTTONDOWN/UP straight to the window, so the shared pointer never moves. NOTE,
# MEASURED: this does NOT reach child controls in a VCL app such as Altium - the button never sees
# it. Use it only where the target handles mouse messages on its top-level window; otherwise use
# `click`, which moves the real pointer.
param(
  [Parameter(Mandatory=$true)][string]$Action,
  [string]$Title = "Altium Designer",
  [int]$X = 0, [int]$Y = 0, [int]$W = 1920, [int]$H = 1080,
  [string]$Shot = "", [string]$Text = "", [double]$Settle = 0.8
)

Add-Type -AssemblyName System.Windows.Forms, System.Drawing

Add-Type @"
using System;
using System.Text;
using System.Collections.Generic;
using System.Runtime.InteropServices;
public class SRWin {
  [DllImport("user32.dll")] public static extern bool EnumWindows(EnumProc cb, IntPtr p);
  [DllImport("user32.dll")] public static extern int GetWindowTextLength(IntPtr h);
  [DllImport("user32.dll", CharSet=CharSet.Unicode)] public static extern int GetWindowText(IntPtr h, StringBuilder s, int n);
  [DllImport("user32.dll")] public static extern bool IsWindowVisible(IntPtr h);
  [DllImport("user32.dll")] public static extern bool SetWindowPos(IntPtr h, IntPtr after, int x, int y, int cx, int cy, uint flags);
  [DllImport("user32.dll")] public static extern bool ShowWindow(IntPtr h, int cmd);
  [DllImport("user32.dll")] public static extern bool SetForegroundWindow(IntPtr h);
  [DllImport("user32.dll")] public static extern IntPtr GetForegroundWindow();
  [DllImport("user32.dll")] public static extern bool BringWindowToTop(IntPtr h);
  [DllImport("user32.dll")] public static extern bool PostMessage(IntPtr h, uint msg, IntPtr wp, IntPtr lp);
  [DllImport("user32.dll")] public static extern IntPtr WindowFromPoint(System.Drawing.Point p);
  [DllImport("user32.dll")] public static extern bool PrintWindow(IntPtr h, IntPtr hdc, uint flags);
  [DllImport("user32.dll")] public static extern bool GetWindowRect(IntPtr h, out RECT r);
  [StructLayout(LayoutKind.Sequential)] public struct RECT { public int Left, Top, Right, Bottom; }
  [DllImport("user32.dll")] public static extern bool ClientToScreen(IntPtr h, ref System.Drawing.Point p);
  public delegate bool EnumProc(IntPtr h, IntPtr p);
  public const int SW_RESTORE = 9, SW_MAXIMIZE = 3;
  public const uint SWP_NOZORDER = 0x0004, SWP_SHOWWINDOW = 0x0040;
  public const uint WM_LBUTTONDOWN = 0x0201, WM_LBUTTONUP = 0x0202, WM_MOUSEMOVE = 0x0200;

  public static List<IntPtr> Find(string needle) {
    var found = new List<IntPtr>();
    EnumWindows(delegate(IntPtr h, IntPtr p) {
      if (!IsWindowVisible(h)) return true;
      int len = GetWindowTextLength(h);
      if (len == 0) return true;
      var sb = new StringBuilder(len + 1);
      GetWindowText(h, sb, sb.Capacity);
      if (sb.ToString().IndexOf(needle, StringComparison.OrdinalIgnoreCase) >= 0) found.Add(h);
      return true;
    }, IntPtr.Zero);
    return found;
  }
  public static string TitleOf(IntPtr h) {
    var sb = new StringBuilder(GetWindowTextLength(h) + 1);
    GetWindowText(h, sb, sb.Capacity);
    return sb.ToString();
  }
  [DllImport("user32.dll")] public static extern bool SetCursorPos(int x, int y);
  [DllImport("user32.dll")] public static extern void mouse_event(uint f, uint dx, uint dy, uint d, IntPtr e);
  public const uint LEFTDOWN = 0x0002, LEFTUP = 0x0004;
  public static void Move(int x, int y) { SetCursorPos(x, y); }
  public static void Click(int x, int y) {
    SetCursorPos(x, y); System.Threading.Thread.Sleep(120);
    mouse_event(LEFTDOWN, 0, 0, 0, IntPtr.Zero); System.Threading.Thread.Sleep(60);
    mouse_event(LEFTUP, 0, 0, 0, IntPtr.Zero);
  }
}
"@ -ReferencedAssemblies System.Drawing, System.Windows.Forms

# Screenshot pixels -> screen coordinates. See trap 1 in the header.
$VS = [System.Windows.Forms.SystemInformation]::VirtualScreen
function ToScreenX([int]$v) { return $v + $VS.X }
function ToScreenY([int]$v) { return $v + $VS.Y }

function Save-Shot([string]$path) {
  $b = [System.Windows.Forms.SystemInformation]::VirtualScreen
  $bmp = New-Object System.Drawing.Bitmap $b.Width, $b.Height
  $g = [System.Drawing.Graphics]::FromImage($bmp)
  $g.CopyFromScreen($b.X, $b.Y, 0, 0, $bmp.Size)
  $bmp.Save($path)
  "SHOT $path $($b.Width)x$($b.Height)"
}

if ($Action -eq "desktopshot") { Save-Shot $Shot; exit 0 }
if ($Action -eq "click" -or $Action -eq "movepointer" -or $Action -eq "type" -or $Action -eq "key") {
  $sx = ToScreenX $X; $sy = ToScreenY $Y
  switch ($Action) {
    "click"        { [SRWin]::Click($sx, $sy); "CLICK shot($X,$Y) -> screen($sx,$sy)" }
    "movepointer"  { [SRWin]::Move($sx, $sy);  "MOVE  shot($X,$Y) -> screen($sx,$sy)" }
    "type"         { [System.Windows.Forms.SendKeys]::SendWait($Text); "TYPE $Text" }
    "key"          { [System.Windows.Forms.SendKeys]::SendWait($Text); "KEY $Text" }
  }
  $p = [System.Windows.Forms.Cursor]::Position
  "POINTER screen=$($p.X),$($p.Y)  shot=$($p.X - $VS.X),$($p.Y - $VS.Y)"
  if ($p.X -lt $VS.X -or $p.X -ge ($VS.X + $VS.Width) -or $p.Y -lt $VS.Y -or $p.Y -ge ($VS.Y + $VS.Height)) {
    "OFF-SCREEN: the pointer is outside every display, so nothing was clicked."
    exit 3
  }
  Start-Sleep -Seconds $Settle
  if ($Shot) { Save-Shot $Shot }
  exit 0
}

$hits = [SRWin]::Find($Title)
if ($Action -eq "list") {
  [System.Windows.Forms.Screen]::AllScreens | ForEach-Object { "SCREEN $($_.DeviceName) $($_.Bounds)" }
  if ($hits.Count -eq 0) { "no window matching '$Title'" } else { $hits | ForEach-Object { "WINDOW $_ '$([SRWin]::TitleOf($_))'" } }
  exit 0
}
if ($hits.Count -eq 0) { "FAIL: no visible window matching '$Title'"; exit 2 }
$hwnd = $hits[0]   # NOT $h: PowerShell is case-insensitive and -H is the height

switch ($Action) {
  "move" {
    # Restore first: a MAXIMIZED window ignores a move and silently stays where it is.
    [void][SRWin]::ShowWindow($hwnd, [SRWin]::SW_RESTORE)
    [void][SRWin]::SetWindowPos($hwnd, [IntPtr]::Zero, $X, $Y, $W, $H, [SRWin]::SWP_NOZORDER -bor [SRWin]::SWP_SHOWWINDOW)

    # POLL the window's ACTUAL rectangle; do not sleep and assume.
    #
    # This block used to be two `Start-Sleep -Milliseconds 400` calls either side of the move, and
    # then it printed the position it had REQUESTED. Both halves were wrong. The sleep was a clock
    # standing in for "the window manager finished", so on a slower machine the move was reported
    # before it happened; and the message named the requested rectangle, so a move that was refused
    # outright still printed MOVED. A window manager can legitimately refuse or adjust a position
    # (snap, DPI, minimum size), which is exactly the case a requested-position message hides.
    $deadline = (Get-Date).AddMilliseconds(3000)
    $r = New-Object SRWin+RECT
    do {
      Start-Sleep -Milliseconds 50
      [void][SRWin]::GetWindowRect($hwnd, [ref]$r)
      $landed = ($r.Left -eq $X -and $r.Top -eq $Y)
    } until ($landed -or (Get-Date) -gt $deadline)

    # Report what the window ACTUALLY is, never what was asked for.
    "MOVED '$([SRWin]::TitleOf($hwnd))' requested ($X,$Y) ${W}x${H}"
    "ACTUAL  $($r.Left),$($r.Top) $($r.Right - $r.Left)x$($r.Bottom - $r.Top)"
    if (-not $landed) {
      "FAIL: the window did not land at the requested origin. The window manager refused or"
      "adjusted the move (snap, DPI scaling, or a minimum size), so treat this as NOT moved."
      exit 4
    }
  }
  "foreground" {
    # A click on an UNFOCUSED window is consumed by the focus change, so a control never sees it.
    # Measured 2026-07-26: clicks aimed at Altium's Panels button landed at the right screen
    # coordinate and did nothing, because a fullscreen game on the other monitor held the focus and
    # kept recapturing the cursor.
    #
    # Reports the foreground window BEFORE and AFTER, and fails if it did not change: Windows
    # refuses SetForegroundWindow from a process that does not own the current foreground, and it
    # refuses SILENTLY by returning false while everything looks fine.
    $before = [SRWin]::GetForegroundWindow()
    [void][SRWin]::ShowWindow($hwnd, [SRWin]::SW_RESTORE)
    [void][SRWin]::BringWindowToTop($hwnd)
    $ok = [SRWin]::SetForegroundWindow($hwnd)
    Start-Sleep -Milliseconds 250
    $after = [SRWin]::GetForegroundWindow()
    "FOREGROUND before=$before after=$after target=$hwnd setfg=$ok"
    if ($after -ne $hwnd) {
      "FAIL: the window did not take focus, so any click sent to it will be swallowed."
      exit 5
    }
  }
  "probe" {
    $r = New-Object SRWin+RECT
    [void][SRWin]::GetWindowRect($hwnd, [ref]$r)
    $o = New-Object System.Drawing.Point 0, 0
    [void][SRWin]::ClientToScreen($hwnd, [ref]$o)
    "WINDOWRECT $($r.Left),$($r.Top) - $($r.Right),$($r.Bottom)"
    "CLIENTORIGIN $($o.X),$($o.Y)"
    "CLIENTOFFSET_IN_WINDOWIMAGE $($o.X - $r.Left),$($o.Y - $r.Top)"
  }
  "shotwin" {
    # PrintWindow renders the window's OWN content, so a covered window still captures correctly
    # and nothing has to be raised. Raising it would steal focus, and a fullscreen game on the
    # other monitor can minimise when it loses focus - which is the whole thing being avoided.
    # PW_RENDERFULLCONTENT (2) is required for modern composited/DirectComposition surfaces; the
    # older PrintWindow(0) returns a blank or stale bitmap for them.
    $r = New-Object SRWin+RECT
    [void][SRWin]::GetWindowRect($hwnd, [ref]$r)
    $w = $r.Right - $r.Left; $ht = $r.Bottom - $r.Top
    $bmp = New-Object System.Drawing.Bitmap $w, $ht
    $g = [System.Drawing.Graphics]::FromImage($bmp)
    $hdc = $g.GetHdc()
    $okPW = [SRWin]::PrintWindow($hwnd, $hdc, 2)
    $g.ReleaseHdc($hdc)
    $bmp.Save($Shot)
    "SHOTWIN $Shot ${w}x${ht} printwindow=$okPW '$([SRWin]::TitleOf($hwnd))'"
  }
  "mclick" {
    # CLIENT coordinates of the target window. The pointer is never touched.
    # The sleeps below are INPUT PACING, not detection: a real click has a press-to-release
    # duration and a control that sees down+up in the same millisecond often ignores it. Nothing
    # here concludes anything from elapsed time.
    $lp = [IntPtr](($Y -shl 16) -bor ($X -band 0xFFFF))
    [void][SRWin]::PostMessage($hwnd, [SRWin]::WM_MOUSEMOVE, [IntPtr]::Zero, $lp)
    Start-Sleep -Milliseconds 80
    [void][SRWin]::PostMessage($hwnd, [SRWin]::WM_LBUTTONDOWN, [IntPtr]1, $lp)
    Start-Sleep -Milliseconds 60
    [void][SRWin]::PostMessage($hwnd, [SRWin]::WM_LBUTTONUP, [IntPtr]::Zero, $lp)
    "MCLICK client ($X,$Y) on '$([SRWin]::TitleOf($hwnd))' (pointer NOT moved)"
  }
  default { "unknown action: $Action"; exit 2 }
}
