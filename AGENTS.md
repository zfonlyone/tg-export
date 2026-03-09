# AGENTS

## Security Baseline
- Never create, modify, or commit any secret file inside this repository.
- Never write real credentials into source files, examples, scripts, compose files, or docs.
- Treat all tokens, passwords, API keys, private keys, and session strings as prohibited content.

## Prohibited In-Repo Files
- `.env`, `.env.*`
- `*.pem`, `*.key`, `id_rsa`, `id_ed25519`, `authorized_keys`
- Telegram session exports or credential snapshots (for example: `session.json`, `token.txt`).

## Prohibited Actions For AI
- Do not run commands that print secret values (for example: `env`, `printenv`, `cat` on secret files).
- Do not add fallback defaults that look like real tokens/passwords.
- Do not auto-generate or inject credentials during code changes.

## Allowed Secret Handling
- Use placeholders only (for example: `your-token-here`, `example.com`).
- Keep runtime secrets outside the repo (system env, secret manager, or `/etc/...` path).
- For CI/CD, use platform secret storage only (GitHub Actions Secrets, etc.).

## Deployment Convention
- Dev repo path: `/root/code/docker/tg-export`
- Live deploy path: `/etc/tg-export`
- Public service chain: Cloudflare → Nginx (`/etc/nginx/sites-available/tg-export.181028.xyz`) → `127.0.0.1:9528` → Docker container `tg-export`
- Runtime `.env` must live in `/etc/tg-export/.env`, never in this repository.
- Do not assume repo changes are live until `/etc/tg-export` has been synced and the container recreated.

## Deploy / Verify Flow
1. Modify code in `/root/code/docker/tg-export`
2. Verify frontend build first:
   - `cd frontend && npm run build`
3. Commit changes in repo
4. Sync repo → live dir:
   - `rsync -a --delete --exclude '.git/' --exclude '__pycache__/' --exclude '*.pyc' --exclude '.env' --exclude 'data/' /root/code/docker/tg-export/ /etc/tg-export/`
5. Rebuild live service:
   - `cd /etc/tg-export && docker compose up -d --build`
6. Verify service really updated:
   - `docker compose ps`
   - `docker inspect tg-export --format 'started={{.State.StartedAt}} image={{.Image}}'`
   - `docker exec tg-export sh -lc 'sed -n "1,20p" /app/frontend/dist/index.html'`
   - `curl -sS http://127.0.0.1:9528/ | sed -n '1,20p'`
   - `curl -sS https://tg-export.181028.xyz/ | sed -n '1,20p'`

## White-Screen Triage
- Check public HTML / JS hash first (`index-*.js`, route chunk names)
- If container assets are old: rebuild failed or sync never happened
- If container assets are new but public assets are old: then suspect Cloudflare / proxy cache
- Also check for frontend runtime errors like missing Vue imports (`computed`) or route/root component failures

## Commit Gate
- Before committing, verify no secret-like content was introduced.
- If secret-like content is found, stop changes and replace with placeholders immediately.
