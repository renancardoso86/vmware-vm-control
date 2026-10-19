# vmware-vm-control: download the official embeddable Python (Windows x64) on first start, for installs that
# do not carry the bundled one (marketplace / Claude Code from the Git repository) on PCs without Python.
# Checks: SHA-256 pinned in python-embed.txt, and python.exe signed by the Python Software Foundation.
# Writes nothing to stdout (stdout is the MCP channel of the caller); exit code 0 = ready.
param([Parameter(Mandatory = $true)][string]$Dest)
$ErrorActionPreference = 'Stop'
function Say($m) { [Console]::Error.WriteLine("vmware-vm-control: $m") }
try {
    $pin = @{}
    Get-Content (Join-Path $PSScriptRoot 'python-embed.txt') | Where-Object { $_ -match '^\s*(\w+)\s*=\s*(\S+)' } |
        ForEach-Object { $pin[$Matches[1]] = $Matches[2] }
    $ver = $pin['version']; $sha = $pin['sha256']
    if (-not $ver -or -not $sha) { throw 'python-embed.txt has no version/sha256' }
    $arch = if ([Environment]::Is64BitOperatingSystem) { 'amd64' } else { throw '32-bit Windows is not supported by the downloaded Python' }
    $url = "https://www.python.org/ftp/python/$ver/python-$ver-embed-$arch.zip"
    [Net.ServicePointManager]::SecurityProtocol = [Net.ServicePointManager]::SecurityProtocol -bor [Net.SecurityProtocolType]::Tls12
    $tmp = Join-Path ([IO.Path]::GetTempPath()) ("vmctl-python-" + [Guid]::NewGuid().ToString('N'))
    New-Item -ItemType Directory $tmp | Out-Null
    $zip = Join-Path $tmp 'python.zip'
    Say "no Python found - downloading the official embeddable Python $ver from python.org (about 12 MB, first start only)"
    $ProgressPreference = 'SilentlyContinue'
    Invoke-WebRequest -UseBasicParsing -Uri $url -OutFile $zip
    $got = (Get-FileHash -Algorithm SHA256 $zip).Hash.ToLower()
    if ($got -ne $sha.ToLower()) { throw "SHA-256 mismatch for $url (got $got)" }
    $out = Join-Path $tmp 'python'
    Expand-Archive -Path $zip -DestinationPath $out
    $sig = Get-AuthenticodeSignature (Join-Path $out 'python.exe')
    if ($sig.Status -ne 'Valid' -or $sig.SignerCertificate.Subject -notmatch 'Python Software Foundation') {
        throw "python.exe signature check failed ($($sig.Status))"
    }
    if (Test-Path $Dest) { Remove-Item -Recurse -Force $Dest }
    New-Item -ItemType Directory -Force (Split-Path -Parent $Dest) | Out-Null
    Move-Item $out $Dest
    Remove-Item -Recurse -Force $tmp
    Say "Python $ver ready in $Dest"
    exit 0
} catch {
    Say ("could not download Python: " + $_.Exception.Message + ". Install Python 3 from python.org, or install the plugin from the release package (it bundles Python).")
    exit 1
}
