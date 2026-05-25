# Deploying Performance Partner

## Prerequisites
- Docker installed locally (for testing the image before push)
- A free account on Render, Railway, or Fly.io
- Your Anthropic API key

---

## 1. Generate a SECRET_KEY

Run once locally and keep the output:

```bash
python3 -c "import secrets; print(secrets.token_hex(32))"
```

---

## 2. Test the Docker image locally

```bash
docker build -t performancepartner .

docker run --rm -p 8000:8000 \
  -v $(pwd)/data:/data \
  -e SECRET_KEY=your-secret-key \
  -e DATABASE_PATH=/data/performancepartner.db \
  -e ANTHROPIC_API_KEY=sk-ant-... \
  performancepartner
```

Visit http://localhost:8000 — the app should boot, seed the admin account, and be ready.

---

## Option A — Render (recommended for simplicity)

1. Push this repo to GitHub (or GitLab).
2. Go to https://render.com → **New → Web Service** → connect your repo.
3. Settings:
   - **Runtime**: Docker
   - **Instance type**: Free (or Starter for always-on)
4. Add a **Persistent Disk**:
   - Mount path: `/data`
   - Size: 1 GB is plenty
5. Set environment variables in the Render dashboard:
   ```
   SECRET_KEY=<your-generated-key>
   DATABASE_PATH=/data/performancepartner.db
   ANTHROPIC_API_KEY=sk-ant-...
   ```
6. Click **Deploy**. Render builds the image and starts the service.

> **Note:** The free tier spins down after inactivity. Use Starter ($7/mo) for always-on.

---

## Option B — Railway

1. Push repo to GitHub.
2. Go to https://railway.app → **New Project → Deploy from GitHub repo**.
3. Railway auto-detects the Dockerfile.
4. Add a **Volume** in the service settings:
   - Mount path: `/data`
5. Set environment variables (same three as above).
6. Deploy.

---

## Option C — Fly.io

1. Install the Fly CLI: `brew install flyctl`
2. From the project directory:
   ```bash
   fly launch --no-deploy   # accept defaults, choose a region
   ```
3. Create a persistent volume:
   ```bash
   fly volumes create pp_data --size 1 --region <your-region>
   ```
4. Edit the generated `fly.toml` to mount the volume:
   ```toml
   [mounts]
     source = "pp_data"
     destination = "/data"
   ```
5. Set secrets:
   ```bash
   fly secrets set SECRET_KEY=... DATABASE_PATH=/data/performancepartner.db ANTHROPIC_API_KEY=sk-ant-...
   ```
6. Deploy:
   ```bash
   fly deploy
   ```

---

## Admin credentials (first boot)

On first startup the app creates:
- **Email**: `hmis@partnersincareoahu.org`
- **Password**: `changeme`

Change the password immediately after first login via Admin → Users → edit the admin account.

---

## Backups

The entire database is a single file at `DATABASE_PATH`. To back it up:

```bash
# On Render/Railway: download via their volume snapshot UI
# On Fly.io:
fly ssh console -C "cp /data/performancepartner.db /tmp/backup.db"
fly sftp get /tmp/backup.db ./backup-$(date +%Y%m%d).db
```
