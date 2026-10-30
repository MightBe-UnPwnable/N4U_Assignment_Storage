# ANONBOARD

A crude, single-page, anonymous imageboard in the old-school style. No login,
no separate pages — posting, replying, and browsing all happen on "/".

## What's in the box

```
anonboard/
├── application.py                          Flask app (all routes + logic live on "/")
├── requirements.txt                         Flask, Pillow, gunicorn
├── Procfile                                 tells EB how to run it (gunicorn)
├── .ebextensions/01_static.config           serves /static via nginx directly
├── .platform/nginx/conf.d/...conf           raises upload size limit past nginx's 1MB default
├── .ebignore                                keeps local db/uploads out of deploys
├── templates/index.html                     the entire UI (one template, one page)
├── static/style.css                         the crude/old look — sharp corners, tables
├── static/script.js                         optional JS: image expand + quote-insert
├── data/                                    SQLite database lives here (created on first run)
└── uploads/                                 uploaded images + uploads/thumbs/ live here
```

## Running it locally first

```bash
pip install -r requirements.txt
ADMIN_KEY=pick-something-only-you-know python3 application.py
```

Visit `http://localhost:5000`. If you don't set `ADMIN_KEY`, the app makes up a
random one each start and prints it to the console — fine for poking around,
but set it explicitly so it doesn't change every restart.

## Deploying to Elastic Beanstalk

**Console (simplest):** zip the contents of this folder (not the folder itself
— the zip's root should contain `application.py`, not `anonboard/application.py`),
then in the EB console: Create environment → Web server environment → Platform:
**Python** → Upload your code → pick the zip.

**EB CLI:**
```bash
eb init -p python-3.12 anonboard
eb create anonboard-env
eb setenv ADMIN_KEY=pick-something-only-you-know SITE_NAME="/b/" SITE_SUBTITLE="- Random"
eb deploy
eb open
```

Set `ADMIN_KEY` (and anything else you want to override) as an EB environment
property — via `eb setenv`, or Console → Configuration → Software → Environment
properties. Don't commit real secrets into the config files.

## Environment variables (all optional)

| Variable | Default | Purpose |
|---|---|---|
| `ADMIN_KEY` | random, regenerated each restart | password typed into a post's "Del" box to delete it |
| `SITE_NAME` | `ANONBOARD` | big title at the top |
| `SITE_SUBTITLE` | `/b/ - Random` | subtitle under it |
| `MAX_FILE_SIZE` | `5242880` (5 MB) | max upload size in bytes — also update the nginx conf if you raise this a lot |
| `POST_COOLDOWN_SECONDS` | `15` | per-IP flood-protection cooldown between posts |
| `DATA_DIR` | `./data` | where `board.db` is stored |
| `UPLOAD_DIR` | `./uploads` | where uploaded images + thumbnails are stored |

## Storage: read this before you rely on it

This uses SQLite + local disk for simplicity — no RDS or S3 setup needed to get
running. That comes with two real limits:

1. **Single instance only.** SQLite and local files aren't shared across
   instances, so this won't work correctly behind a load balancer with more
   than one instance running.
2. **Ephemeral across deploys.** Elastic Beanstalk swaps in a fresh copy of
   your app directory on every `eb deploy`, so anything written to `data/` or
   `uploads/` at runtime is lost the *next* time you deploy new code (it
   survives ordinary restarts/reboots of the same running instance, just not
   a redeploy).

For a small/personal board this is often fine. If you want posts and images to
survive redeploys and scale past one instance, the real fix is to point
`DATA_DIR`/`UPLOAD_DIR` at S3 (or move the DB to RDS) — a bigger change than
this project takes on by default, happy to help build that out if you want it.

## Moderation

There's no janitor panel, just a delete box next to every post: type the
`ADMIN_KEY` password into it and hit **Del** to remove that post (or, for a
thread's OP, the whole thread). If you're actually putting this in front of
the public, decide on a moderation routine before you announce it — anonymous
boards get tested immediately, and in the US there are legal reporting
obligations around CSAM specifically (see 18 U.S.C. § 2258A) that apply to
anyone operating a public file-upload board, not just big platforms.

## Notable "authentic" details implemented

- Post numbers, `>>123` quote-links (click to jump, ref list shown as
  "Replies:" under the quoted post), and `>greentext`
- "sage" in the Email field replies without bumping the thread
- Flood detection ("wait before posting again") per IP
- Honeypot field to quietly drop simple bots
- Thumbnails with click-to-expand, EXIF auto-rotate on upload
- Classic `MM/DD/YY(Day)HH:MM:SS` timestamp format
