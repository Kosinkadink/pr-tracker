$env:GITHUB_TOKEN = (Get-Content "$PSScriptRoot\githubtoken.txt" -Raw).Trim()
& "$PSScriptRoot\.venv\Scripts\python.exe" -m pr_tracker_tui @args
