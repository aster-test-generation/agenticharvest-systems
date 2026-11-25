#
# Copyright IBM Corp. 2026
# SPDX-License-Identifier: Apache-2.0
#

<#
Run an AgenticHarvest cross-system example with nothing installed but Podman or Docker.

  .\run.ps1 hire_to_onboard [--agent] [--keep]
  .\run.ps1 order_fulfillment [--agent] [--keep]
  .\run.ps1 check        start and provision the systems, report what they expose
  .\run.ps1 test         the live-system tests, inside the runner
  .\run.ps1 shell        a shell in the runner, everything installed
  .\run.ps1 stop         stop the systems (data is kept)
  .\run.ps1 reset        stop and delete all data

--agent needs an OpenAI-compatible endpoint: set $env:API_BASE, $env:API_KEY,
and $env:MODEL first, or put them in a .env file next to this script or in the
repo root.
#>
$ErrorActionPreference = "Stop"
$here = $PSScriptRoot

# Find the agenticharvest source. Inside an agenticharvest checkout this folder is
# examples\systems. Cloned on its own, this repo fetches agenticharvest (with the
# examples and this stack as its submodules) into .\.agenticharvest and runs from
# there. $env:AGENTICHARVEST_REPO and $env:AGENTICHARVEST_REF choose what is fetched.
function Test-AgenticHarvest($dir) {
    $file = Join-Path $dir "pyproject.toml"
    (Test-Path $file) -and (Select-String -Path $file -Pattern '^name = "agenticharvest"' -Quiet)
}
if (Test-AgenticHarvest (Join-Path $here "..\..")) {
    $root = (Resolve-Path (Join-Path $here "..\..")).Path
} else {
    $root = Join-Path $here ".agenticharvest"
    if (-not (Test-AgenticHarvest $root)) {
        if (-not (Get-Command git -ErrorAction SilentlyContinue)) { Write-Error "git is needed to fetch agenticharvest." }
        $repo = if ($env:AGENTICHARVEST_REPO) { $env:AGENTICHARVEST_REPO } else { "https://github.com/IBM/agenticharvest.git" }
        $ref = if ($env:AGENTICHARVEST_REF) { $env:AGENTICHARVEST_REF } else { "main" }
        Write-Host "Fetching agenticharvest ($repo, $ref) into $root ..."
        git clone --depth 1 --recurse-submodules --shallow-submodules --branch $ref $repo $root
        if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
    }
}
$env:AGENTICHARVEST_ROOT = $root
# Always use the stack definition inside that checkout, so the source and the
# compose file match.
$here = Join-Path $root "examples\systems"

# Podman or Docker, whichever is here.
if (Get-Command podman -ErrorAction SilentlyContinue) { $engine = "podman" }
elseif (Get-Command docker -ErrorAction SilentlyContinue) { $engine = "docker" }
else {
    Write-Error "Neither Podman nor Docker is installed. Install one (https://podman.io/docs/installation, or Docker Desktop), then run this again."
}
& $engine info *> $null
if ($LASTEXITCODE -ne 0) {
    $hint = if ($engine -eq "podman") { " Start it with: podman machine start" } else { "" }
    Write-Error "$engine is installed but not running.$hint"
}
$composeFile = Join-Path $here "compose.yaml"
function Compose { & $engine compose -f $composeFile @args; if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE } }

# LLM settings for --agent: the environment wins, then a .env in the folder the
# user ran from (an example's own run.ps1 passes it as AGENTICHARVEST_CALLER_DIR),
# next to this script, or in the agenticharvest root.
$caller = if ($env:AGENTICHARVEST_CALLER_DIR) { $env:AGENTICHARVEST_CALLER_DIR } else { (Get-Location).Path }
foreach ($file in @((Join-Path $caller ".env"), (Join-Path $here ".env"), (Join-Path $root ".env"))) {
    if (-not (Test-Path $file)) { continue }
    foreach ($key in @("API_BASE", "API_KEY", "MODEL")) {
        if ([Environment]::GetEnvironmentVariable($key)) { continue }
        $line = Select-String -Path $file -Pattern "^$key=(.*)$" | Select-Object -Last 1
        if ($line) {
            $value = $line.Matches[0].Groups[1].Value.Trim().Trim('"').Trim("'")
            if ($value) { [Environment]::SetEnvironmentVariable($key, $value) }
        }
    }
}

$command = if ($args.Count -gt 0) { $args[0] } else { "help" }
$rest = if ($args.Count -gt 1) { $args[1..($args.Count - 1)] } else { @() }

switch ($command) {
    { $_ -in "help", "-h", "--help" } { Get-Help $MyInvocation.MyCommand.Path -Full | Out-String | Write-Host; exit 0 }
    "stop"  { Compose --profile runner stop; exit 0 }
    "reset" { Compose --profile runner down -v; exit 0 }
}

# The examples' output goes to .\out next to the run.ps1 the user ran.
if (-not $env:AGENTICHARVEST_OUT) { $env:AGENTICHARVEST_OUT = Join-Path $caller "out" }
New-Item -ItemType Directory -Force -Path $env:AGENTICHARVEST_OUT | Out-Null

Write-Host "Starting the live systems with $engine (the first start pulls ~2 GB and takes a few minutes)..."
Compose up -d directus keycloak odoo-db odoo
Compose --profile runner build runner
& $engine compose -f $composeFile --profile runner run --rm runner $command @rest
exit $LASTEXITCODE
