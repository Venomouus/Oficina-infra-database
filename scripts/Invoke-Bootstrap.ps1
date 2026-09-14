[CmdletBinding()]
param(
    [Parameter(Mandatory)][string]$Contract,
    [Parameter(Mandatory)][ValidateSet('staging', 'producao')][string]$Environment,
    [Parameter(Mandatory)][ValidateSet('prepare', 'grants')][string]$Phase,
    [Parameter(Mandatory)][string]$SslRootCert
)
$ErrorActionPreference = 'Stop'
$scriptPath = Join-Path $PSScriptRoot '../bootstrap/bootstrap.py'
if (!(Test-Path -LiteralPath $Contract -PathType Leaf)) { throw 'Contrato JSON nao encontrado.' }
if (!(Test-Path -LiteralPath $SslRootCert -PathType Leaf)) { throw 'CA do RDS nao encontrada.' }
Get-Command python, psql -ErrorAction Stop | Out-Null
$previous = @{}
try {
    foreach ($name in @('ADMIN', 'APP', 'AUTH', 'MIGRATIONS')) {
        $key = 'BOOTSTRAP_' + $name + '_PASSWORD'
        $previous[$key] = [Environment]::GetEnvironmentVariable($key, 'Process')
        if ([string]::IsNullOrEmpty($previous[$key])) {
            $secureValue = Read-Host "Senha $name do ambiente $Environment (obtida do segredo correspondente)" -AsSecureString
            $buffer = [Runtime.InteropServices.Marshal]::SecureStringToBSTR($secureValue)
            try {
                [Environment]::SetEnvironmentVariable($key, [Runtime.InteropServices.Marshal]::PtrToStringBSTR($buffer), 'Process')
            } finally {
                [Runtime.InteropServices.Marshal]::ZeroFreeBSTR($buffer)
                $secureValue.Dispose()
            }
        }
    }
    & python $scriptPath --contract $Contract --environment $Environment --phase $Phase --ssl-root-cert $SslRootCert
    if ($LASTEXITCODE -ne 0) { throw 'Bootstrap falhou. Corrija a causa antes de prosseguir.' }
} finally {
    foreach ($key in $previous.Keys) {
        [Environment]::SetEnvironmentVariable($key, $previous[$key], 'Process')
    }
}
