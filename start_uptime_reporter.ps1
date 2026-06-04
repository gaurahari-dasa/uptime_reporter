$root   = $PSScriptRoot
$python = Join-Path $root ".venv\Scripts\pythonw.exe"
$script = Join-Path $root "uptime_reporter.py"

# Pass any arguments through (e.g. --notify 8h)
Start-Process -FilePath $python `
              -ArgumentList (@($script) + $args) `
              -WorkingDirectory $root `
              -WindowStyle Hidden
