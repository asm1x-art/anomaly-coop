# PGO (profile-guided optimisation) build of AnomalyDX11.exe, an option off the usual build. The DX11 build compiles
# everything with /GL already, so PGO is two relinks of the exe, no recompile:
#   1. pgo.ps1 gen   -> _build\pgo\AnomalyDX11.exe instrumented (+ .pgd); copy it and pgort140.dll into a test copy's
#                       bin and play it: load a save, fights with stalkers and mutants, a level change, quit the game
#                       normally (the profile AnomalyDX11!N.pgc is written next to the exe on exit)
#   2. pgo.ps1 use <folder with the .pgc files> -> _build\pgo\AnomalyDX11.exe optimised by the profile
# Measured 2026-11-02 (10 alternating runs): about 4% off the average frame, in the game logic (scheduler, AI); the
# render about the same. Code not run in training is compiled for size: the training should cover what is played.
# After code changes run the usual build first; retrain after big changes (changed functions lose their profile).
# Needs a finished usual build (MSBuild DX11|x64): its link command is taken from the build's tlog.
param([Parameter(Mandatory = $true)][ValidateSet("gen", "use")][string]$step, [string]$pgc_dir)

$ErrorActionPreference = "Stop"
$root = Resolve-Path "$PSScriptRoot\..\.."
$out = Join-Path $root "_build\pgo"
$tlog = Join-Path $root "_build\intermediate\ReleaseR4\xrEngine\xrEngine.tlog\link.command.1.tlog"
$vs = "G:\Microsoft Visual Studio\2022\Community"
$vcvars = Join-Path $vs "VC\Auxiliary\Build\vcvars64.bat"
New-Item -ItemType Directory -Force $out | Out-Null

# the usual build's link command: the tlog's lines after the first (one argument a line), its output moved to _build\pgo
$lines = Get-Content $tlog -Encoding Unicode | Select-Object -Skip 1
$cmd = ($lines -join "`n")
$cmd = $cmd -replace '/OUT:"[^"]*"', "/OUT:`"$out\AnomalyDX11.exe`""
$cmd = $cmd -replace '/PDB:"[^"]*"', "/PDB:`"$out\AnomalyDX11.pdb`""
$cmd = $cmd -replace '/LTCGOUT:"[^"]*"\s*', ''
$cmd = $cmd -replace '/LTCG:INCREMENTAL', ''
$pgd = "$out\AnomalyDX11.pgd"
if ($step -eq "gen") {
	$cmd = $cmd.Replace('/LTCG ', "/LTCG /GENPROFILE:PGD=`"$pgd`" ")
} else {
	if (-not $pgc_dir) { throw "use <folder with the .pgc files>" }
	Get-ChildItem "$pgc_dir\AnomalyDX11!*.pgc" | Copy-Item -Destination $out -Force
	$cmd = $cmd.Replace('/LTCG ', "/LTCG /USEPROFILE:PGD=`"$pgd`" ")
}
$rsp = "$out\link_$step.rsp"
[IO.File]::WriteAllText($rsp, $cmd, (New-Object Text.UTF8Encoding $false))

if ($step -eq "gen") { $pre = "" } else { $pre = "pgomgr /merge `"$out\AnomalyDX11.pgd`" && " }
# vcvars complains about vswhere on stderr, harmless; PowerShell would stop on it
$ErrorActionPreference = "Continue"
cmd /c "`"$vcvars`" >nul 2>nul && $pre cd /d `"$root\src\xrEngine`" && link.exe @`"$rsp`" 2>&1"
if ($LASTEXITCODE -ne 0) { throw "link failed: $LASTEXITCODE" }
if ($step -eq "gen") {
	Copy-Item "$out\AnomalyDX11.exe" "$out\AnomalyDX11_instrumented.exe" -Force
	$rt = Get-ChildItem "$vs\VC\Tools\MSVC\*\bin\Hostx64\x64\pgort140.dll" | Select-Object -Last 1
	"instrumented: $out\AnomalyDX11.exe; put it with $($rt.FullName) into the test copy's bin"
} else {
	"optimised: $out\AnomalyDX11.exe"
}
