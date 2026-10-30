# ANONBOARD

Imageboard 스타일 인터넷 커뮤니티입니다.

## What's in the box

```
anonboard/
├── application.py                          Flask app (all routes + logic live on "/")
├── requirements.txt                         Flask, Pillow, gunicorn
├── Procfile                                 EB stuff ok
├── .ebextensions/01_static.config           serves /static via nginx directly
├── .platform/nginx/conf.d/...conf           raises upload size limit past nginx's 1MB default
├── .ebignore                                keeps local db/uploads out of deploys
├── templates/index.html                     the entire UI (one template, one page)
├── static/style.css
├── static/script.js                         optional JS: image expand + quote-insert
├── data/                                    SQLite database
└── uploads/                                 uploaded images + uploads/thumbs/
```


## 환경변수

| Variable | Default | Purpose |
|---|---|---|
| `ADMIN_KEY` | random, regenerated each restart | password typed into a post's "Del" box to delete it |
| `SITE_NAME` | `ANONBOARD` | big title at the top |
| `SITE_SUBTITLE` | `/b/ - Random` | subtitle under it |
| `MAX_FILE_SIZE` | `5242880` (5 MB) | max upload size in bytes — also update the nginx conf if you raise this a lot |
| `POST_COOLDOWN_SECONDS` | `15` | per-IP flood-protection cooldown between posts |
| `DATA_DIR` | `./data` | where `board.db` is stored |
| `UPLOAD_DIR` | `./uploads` | where uploaded images + thumbnails are stored |


- Flood detection ("wait before posting again") per IP
- Honeypot field to quietly drop simple bots
- Thumbnails with click-to-expand, EXIF auto-rotate on upload
- Classic `MM/DD/YY(Day)HH:MM:SS` timestamp format
