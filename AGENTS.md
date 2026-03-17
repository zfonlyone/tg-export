# AGENTS

## Security Baseline
- **不要直接修改env中的密钥和容器密钥，需要得到我的同意才可以。**
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
- Dev repo path: `/root/code/tg-export`
- Live deploy path: `/etc/tg-export`
- Public service chain: Cloudflare → Nginx (`/etc/nginx/sites-available/tg-export.181028.xyz`) → `127.0.0.1:9528` → Docker container `tg-export`
- Runtime `.env` must live in `/etc/tg-export/.env`, never in this repository.
- Writable runtime config must live in `/etc/tg-export/config/runtime.env`.
- Persistent data must live in `/etc/tg-export/data`.
- Do not assume repo changes are live until `sudo ./scripts/deploy.sh` has completed.
- Never modify source code under `/etc/tg-export`; the deploy script will remove runtime code copies.

## Deploy / Verify Flow
1. Modify code in `/root/code/tg-export`
2. Verify frontend build first:
   - `cd frontend && npm run build`
3. Deploy from the source repo:
   - `sudo ./scripts/deploy.sh`
4. Verify service really updated from the live dir:
   - `docker compose ps`
   - `docker inspect tg-export --format 'started={{.State.StartedAt}} image={{.Image}}'`
   - `docker exec tg-export sh -lc 'sed -n "1,20p" /app/frontend/dist/index.html'`
   - `curl -sS http://127.0.0.1:9528/ | sed -n '1,20p'`
   - `curl -sS https://tg-export.181028.xyz/ | sed -n '1,20p'`
5. If you only changed runtime config:
   - edit `/etc/tg-export/.env` or `/etc/tg-export/config/runtime.env`
   - run `cd /etc/tg-export && docker compose --env-file .env up -d`

## White-Screen Triage
- Check public HTML / JS hash first (`index-*.js`, route chunk names)
- If container assets are old: rebuild failed or sync never happened
- If container assets are new but public assets are old: then suspect Cloudflare / proxy cache
- Also check for frontend runtime errors like missing Vue imports (`computed`) or route/root component failures

## Commit Gate
- Before committing, verify no secret-like content was introduced.
- If secret-like content is found, stop changes and replace with placeholders immediately.
