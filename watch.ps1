while ($true) {
  git add -A
  $diff = git status --porcelain
  if ($diff) {
    git commit -m ("auto: " + (Get-Date -Format "yyyy-MM-dd HH:mm:ss"))
    git pull --rebase 2>$null
    git push 2>$null
  }
  Start-Sleep -Seconds 10
}