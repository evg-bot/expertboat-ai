param(
    [string]$Message = "update"
)

git status

git add .

$changes = git status --porcelain
if (-not $changes) {
    Write-Host "Нет изменений для коммита."
} else {
    git commit -m $Message
}

git push origin main
