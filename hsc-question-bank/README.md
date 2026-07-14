# HSC Question Bank

Drop in a past paper (and optionally its marking guidelines), and it extracts
every question as a standalone image, auto-tags it with topic/marks/syllabus
codes, and adds it to a persistent, filterable question bank.

## Quick start (local dev)

```bash
cd backend
pip install -r requirements.txt

# pdf2image needs poppler on your system too:
#   macOS:   brew install poppler
#   Ubuntu:  sudo apt install poppler-utils
#   Windows: download poppler binaries and add to PATH

python3 app.py
```

Open **http://localhost:5000** — Flask serves both the API and the frontend
from the same process, so there's nothing else to run.

## How it works

- `backend/extractor.py` — the extraction engine. Detects question
  boundaries from bold-text coordinates in the PDF (validated against 2019,
  2020, and 2023 HSC Physics papers), crops + stitches multi-page questions
  into single images, parses the marking guidelines' "Mapping Grid" table,
  and auto-detects the paper's year/subject from its own title page (so
  provenance never depends on a human typing the right filename).
- `backend/app.py` — Flask API. `/api/upload` runs the extraction and
  persists results to SQLite (`hsc_bank.db`) + saves images under
  `backend/static/questions/<paper_id>/`. Also serves the frontend.
- `frontend/` — a small PWA (installable, works offline for the app shell)
  that uploads papers and shows the growing question bank as a filterable
  gallery.

## Data persistence

Everything lives in two places, both of which need to be on a persistent
volume if/when you deploy this somewhere:

- `backend/hsc_bank.db` — SQLite database (papers + questions metadata)
- `backend/static/questions/` — the extracted question images

## Deploying later

This is a single Flask app serving both API and static frontend, so it
deploys like any standard Flask app:

```bash
pip install gunicorn
gunicorn -w 2 -b 0.0.0.0:8000 app:app
```

A few things to set up on whatever platform you use:
- Mount a persistent volume for `backend/hsc_bank.db` and
  `backend/static/questions/` — without it, every deploy wipes your
  question bank.
- Install poppler-utils in the deploy image (needed by `pdf2image`).
- Turn `debug=True` off in `app.py`'s `if __name__ == '__main__':` block
  before shipping (gunicorn ignores it anyway, but worth removing).
- If you outgrow SQLite (many concurrent uploads), swap it for Postgres —
  the queries in `app.py` are plain SQL, so the migration is mechanical.

## Known limitations / things to spot-check on a new subject

- Boundary detection relies on the standard NESA exam template (bold text,
  ~12pt, left margin ~70.7pt). Most subjects share this, but it's worth
  spot-checking a new subject's first upload against the actual paper.
- Only tested on Physics so far. Subjects with heavy code blocks or tables
  in Section I (e.g. Software Engineering) may need the crop margins in
  `extractor.py` (`margin_px`, `left_px`) tuned.
- Auto-detected subject names come straight off the title page text, so
  formatting quirks (e.g. a subject name with unusual punctuation) could
  produce a slightly odd-looking tag — check `/api/papers` after upload if
  something looks off.
