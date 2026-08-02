git add -A

git commit -m "Accept JSON/form on /send-message, add Resend integration, update env" || git commit --allow-empty -m "chore: trigger push"

git push origin main
