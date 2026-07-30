---
name: ship
description: Full deployment pipeline: test, commit, push, deploy. Git best practices, branching, PRs, CI/CD. Use when shipping code, setting up pipelines, or managing git workflows.
allowed-tools: run_command file_ops
---

# Ship

End-to-end deployment: from code commit to production.

## Phase 1: Pre-Flight Checks

Before any deployment:
1. Run tests — `npm test`, `pytest`, `go test ./...`
2. Run linter — `npm run lint`, `ruff check`, `golangci-lint run`
3. Check for uncommitted changes — `git status`
4. Verify no secrets in diff — `git diff` for hardcoded tokens

## Phase 2: Git Workflow

### Commit Messages (Conventional Commits)
```
<type>(<scope>): <description>

[optional body]

[optional footer]
```

Types:
- `feat` — new feature
- `fix` — bug fix
- `refactor` — code restructure (no behavior change)
- `docs` — documentation only
- `test` — adding/updating tests
- `chore` — build, CI, tooling
- `perf` — performance improvement
- `security` — security fix

Examples:
```
feat(auth): add OAuth2 login flow
fix(api): handle null response from /users
refactor(db): extract query builder to separate module
```

### Branching
```
main          ← production
  └── feat/xyz   ← feature branch
  └── fix/abc    ← bugfix branch
```

- `main` is always deployable
- Feature branches for non-trivial changes
- Delete branches after merge

### Pull Request
- Title matches commit type + scope
- Description explains WHAT and WHY (not HOW)
- Link to issue/ticket if applicable
- Request review from code owner

## Phase 3: Deploy

### Static Sites (Vercel/Netlify/GitHub Pages)
```bash
npm run build
npx vercel --prod
# or
netlify deploy --prod
```

### Docker
```bash
docker build -t myapp:latest .
docker push registry/myapp:latest
```

### Node.js (PM2/systemd)
```bash
npm install --production
pm2 restart myapp
# or
sudo systemctl restart myapp
```

### Python (systemd/gunicorn)
```bash
pip install -r requirements.txt
sudo systemctl restart myapp
```

## Phase 4: Verify

After deploy:
1. Check health endpoint — `curl https://myapp.com/health`
2. Check logs — `docker logs`, `pm2 logs`, `journalctl -u myapp`
3. Smoke test critical paths
4. Monitor error rates for 15 minutes

## Phase 5: Rollback (If Needed)

If something breaks:
```bash
# Docker
docker rollback myapp:previous-tag

# PM2
pm2 deploy myapp revert 1

# Git
git revert HEAD
git push
```

## Guidelines
- Never force push to main
- Small, frequent deploys > large, rare deploys
- If in doubt, rollback — don't debug in production
- Document what went wrong in post-mortem
