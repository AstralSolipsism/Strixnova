param(
    [Parameter(Mandatory = $true)][string]$PythonPath,
    [Parameter(Mandatory = $true)][string]$ProjectDir,
    [Parameter(Mandatory = $true)][string]$InstallationRoot,
    [string]$SkillsDir,
    [switch]$ReplaceSkill
)

$ErrorActionPreference = 'Stop'
$installer = Join-Path $PSScriptRoot 'install.py'
$installArguments = @('-I', '-S', $installer, '--project-dir', $ProjectDir, '--installation-root', $InstallationRoot)
if ($SkillsDir) { $installArguments += @('--skills-dir', $SkillsDir) }
if ($ReplaceSkill) { $installArguments += '--replace-skill' }
& $PythonPath @installArguments
exit $LASTEXITCODE
