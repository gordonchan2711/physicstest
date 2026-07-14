"""
app.py — Flask backend for the HSC question bank app.

Endpoints:
  POST   /api/upload            multipart: exam_pdf (required), guidelines_pdf (optional)
  GET    /api/papers             list all uploaded papers
  DELETE /api/papers/<id>        remove a paper and its questions/images
  GET    /api/questions          list questions, filterable by ?subject=&year=&paper_id=
                                  &q=(topic search)&type=(mc|response)&modules=5,6
  GET    /api/question-numbers   distinct question numbers in the bank (for the
                                  sidebar's "by question number" list), optional ?subject=
  GET    /api/custom-test        same filters as /api/questions — used by the
                                  Custom Test builder view
  GET    /api/mock-test          random mock exam: ?mc=20&response=16&subject=&modules=5,6
  GET    /static/questions/...   serves extracted question images

Run locally:
    pip install -r requirements.txt
    python3 app.py
    -> http://localhost:5000

Data persists in backend/hsc_bank.db (SQLite) and backend/static/questions/
(image files). Both need to live on a persistent volume when deployed.
"""
import os
import re
import sqlite3
import json
import uuid
import random
import tempfile
import shutil
from datetime import datetime, timezone

from flask import Flask, request, jsonify, send_from_directory, g
from flask_cors import CORS

import extractor

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
FRONTEND_DIR = os.path.join(os.path.dirname(BASE_DIR), 'frontend')
DB_PATH = os.path.join(BASE_DIR, 'hsc_bank.db')
QUESTIONS_DIR = os.path.join(BASE_DIR, 'static', 'questions')
os.makedirs(QUESTIONS_DIR, exist_ok=True)

app = Flask(__name__, static_folder=None)
CORS(app)
app.config['MAX_CONTENT_LENGTH'] = 50 * 1024 * 1024  # 50MB upload cap


@app.route('/')
def serve_index():
    return send_from_directory(FRONTEND_DIR, 'index.html')


@app.route('/<path:filename>')
def serve_frontend_file(filename):
    # Serves style.css, app.js, manifest.json, sw.js, icons/... directly.
    # /static/questions/... is matched by the more specific route below
    # first, since Flask prefers the longer/more specific rule.
    if os.path.exists(os.path.join(FRONTEND_DIR, filename)):
        return send_from_directory(FRONTEND_DIR, filename)
    return jsonify({'error': 'not found'}), 404


def get_db():
    if 'db' not in g:
        g.db = sqlite3.connect(DB_PATH)
        g.db.row_factory = sqlite3.Row
    return g.db


@app.teardown_appcontext
def close_db(exception=None):
    db = g.pop('db', None)
    if db is not None:
        db.close()


def init_db():
    conn = sqlite3.connect(DB_PATH)
    conn.executescript('''
        CREATE TABLE IF NOT EXISTS papers (
            id TEXT PRIMARY KEY,
            subject TEXT NOT NULL,
            year TEXT NOT NULL,
            exam_filename TEXT,
            guidelines_filename TEXT,
            uploaded_at TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS questions (
            id TEXT PRIMARY KEY,
            paper_id TEXT NOT NULL REFERENCES papers(id) ON DELETE CASCADE,
            question_number INTEGER NOT NULL,
            section INTEGER,
            image_path TEXT NOT NULL,
            marks INTEGER,
            content TEXT,
            syllabus_outcomes TEXT
        );
    ''')
    # Migration for DBs created before answers were added.
    existing_cols = {row[1] for row in conn.execute('PRAGMA table_info(questions)').fetchall()}
    if 'answer_text' not in existing_cols:
        conn.execute('ALTER TABLE questions ADD COLUMN answer_text TEXT')
    if 'answer_image_path' not in existing_cols:
        conn.execute('ALTER TABLE questions ADD COLUMN answer_image_path TEXT')
    conn.commit()
    conn.close()


# --------------------------------------------------------------------------
# Routes
# --------------------------------------------------------------------------

@app.route('/api/upload', methods=['POST'])
def upload():
    exam_file = request.files.get('exam_pdf')
    guidelines_file = request.files.get('guidelines_pdf')
    if not exam_file:
        return jsonify({'error': 'exam_pdf file is required'}), 400

    paper_id = str(uuid.uuid4())[:8]
    tmp_dir = tempfile.mkdtemp(prefix='hsc_upload_')
    try:
        exam_path = os.path.join(tmp_dir, exam_file.filename)
        exam_file.save(exam_path)

        guidelines_path = None
        if guidelines_file and guidelines_file.filename:
            guidelines_path = os.path.join(tmp_dir, guidelines_file.filename)
            guidelines_file.save(guidelines_path)

        paper_out_dir = os.path.join(QUESTIONS_DIR, paper_id)
        os.makedirs(paper_out_dir, exist_ok=True)

        try:
            result = extractor.process_paper(
                exam_path, guidelines_path, paper_out_dir,
                exam_filename=exam_file.filename,
            )
        except Exception as e:
            shutil.rmtree(paper_out_dir, ignore_errors=True)
            return jsonify({'error': f'Extraction failed: {e}'}), 500

        db = get_db()
        db.execute(
            'INSERT INTO papers (id, subject, year, exam_filename, guidelines_filename, uploaded_at) '
            'VALUES (?, ?, ?, ?, ?, ?)',
            (paper_id, result['subject'], result['year'], exam_file.filename,
             guidelines_file.filename if guidelines_file else None,
             datetime.now(timezone.utc).isoformat())
        )
        for q in result['questions']:
            db.execute(
                'INSERT INTO questions (id, paper_id, question_number, section, image_path, '
                'marks, content, syllabus_outcomes, answer_text, answer_image_path) '
                'VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)',
                (str(uuid.uuid4())[:8], paper_id, q['question'], q['section'],
                 f"{paper_id}/{q['filename']}", q.get('marks'),
                 json.dumps(q.get('content', [])),
                 json.dumps(q.get('syllabus_outcomes', [])),
                 q.get('answer_text'),
                 f"{paper_id}/{q['answer_image']}" if q.get('answer_image') else None)
            )
        db.commit()

        return jsonify({
            'paper_id': paper_id,
            'subject': result['subject'],
            'year': result['year'],
            'question_count': len(result['questions']),
        })
    finally:
        shutil.rmtree(tmp_dir, ignore_errors=True)


@app.route('/api/papers', methods=['GET'])
def list_papers():
    db = get_db()
    rows = db.execute(
        'SELECT p.*, COUNT(q.id) as question_count FROM papers p '
        'LEFT JOIN questions q ON q.paper_id = p.id '
        'GROUP BY p.id ORDER BY p.uploaded_at DESC'
    ).fetchall()
    return jsonify([dict(r) for r in rows])


@app.route('/api/papers/<paper_id>', methods=['DELETE'])
def delete_paper(paper_id):
    db = get_db()
    db.execute('DELETE FROM questions WHERE paper_id = ?', (paper_id,))
    db.execute('DELETE FROM papers WHERE id = ?', (paper_id,))
    db.commit()
    shutil.rmtree(os.path.join(QUESTIONS_DIR, paper_id), ignore_errors=True)
    return jsonify({'ok': True})


MODULE_RE = re.compile(r'Mod(?:ule)?\s*(\d+)', re.IGNORECASE)


def extract_modules(content_list):
    """Pull out module numbers (e.g. 5, 6, 7, 8) referenced anywhere in a
    question's topic tags, e.g. 'Mod 7 Light: Wave model' -> [7]."""
    mods = set()
    for c in content_list or []:
        for m in MODULE_RE.findall(c):
            mods.add(int(m))
    return sorted(mods)


def query_questions(subject=None, year=None, paper_id=None, topic=None,
                     question_number=None, section=None, modules=None):
    """Core question lookup used by /api/questions, the by-number view,
    the custom test builder, and the mock test generator. `modules`, if
    given, is a list of ints and matches questions tagged with ANY of them."""
    db = get_db()
    clauses, params = [], []
    if subject:
        clauses.append('p.subject = ?')
        params.append(subject)
    if year:
        clauses.append('p.year = ?')
        params.append(year)
    if paper_id:
        clauses.append('p.id = ?')
        params.append(paper_id)
    if question_number:
        clauses.append('q.question_number = ?')
        params.append(question_number)
    if section:
        clauses.append('q.section = ?')
        params.append(section)
    if topic:
        clauses.append('(q.content LIKE ? OR q.syllabus_outcomes LIKE ?)')
        like = f"%{topic}%"
        params.extend([like, like])

    where = f"WHERE {' AND '.join(clauses)}" if clauses else ''
    rows = db.execute(
        f'SELECT q.*, p.subject, p.year FROM questions q '
        f'JOIN papers p ON p.id = q.paper_id {where} '
        f'ORDER BY q.question_number ASC, p.year ASC',
        params
    ).fetchall()

    out = []
    for r in rows:
        d = dict(r)
        d['content'] = json.loads(d['content'] or '[]')
        d['syllabus_outcomes'] = json.loads(d['syllabus_outcomes'] or '[]')
        d['image_url'] = f"/static/questions/{d['image_path']}"
        d['answer_image_url'] = f"/static/questions/{d['answer_image_path']}" if d.get('answer_image_path') else None
        d['modules'] = extract_modules(d['content'])
        if modules and not (set(d['modules']) & set(modules)):
            continue
        out.append(d)
    return out


def parse_modules_param():
    raw = request.args.get('modules', '')
    return [int(m) for m in raw.split(',') if m.strip().isdigit()] or None


def parse_type_param():
    """'mc' -> section 1 only, 'response' -> section 2 only, else None (both)."""
    t = (request.args.get('type') or '').lower()
    if t in ('mc', 'multiple_choice', 'multiple-choice'):
        return 1
    if t in ('response', 'short_answer', 'free_response'):
        return 2
    return None


@app.route('/api/questions', methods=['GET'])
def list_questions():
    qnum = request.args.get('question_number')
    results = query_questions(
        subject=request.args.get('subject') or None,
        year=request.args.get('year') or None,
        paper_id=request.args.get('paper_id') or None,
        topic=request.args.get('q') or None,
        question_number=int(qnum) if qnum and qnum.isdigit() else None,
        section=parse_type_param(),
        modules=parse_modules_param(),
    )
    return jsonify(results)


@app.route('/api/question-numbers', methods=['GET'])
def question_numbers():
    """Distinct question numbers present in the bank, with section + how
    many years/papers have that number — powers the sidebar's 'by number'
    list. Optionally scoped to ?subject=."""
    db = get_db()
    clauses, params = [], []
    if request.args.get('subject'):
        clauses.append('p.subject = ?')
        params.append(request.args['subject'])
    where = f"WHERE {' AND '.join(clauses)}" if clauses else ''
    rows = db.execute(
        f'SELECT q.question_number, q.section, COUNT(*) as paper_count '
        f'FROM questions q JOIN papers p ON p.id = q.paper_id {where} '
        f'GROUP BY q.question_number, q.section '
        f'ORDER BY q.question_number ASC',
        params
    ).fetchall()
    return jsonify([dict(r) for r in rows])


@app.route('/api/custom-test', methods=['GET'])
def custom_test():
    """Build a filtered question set: by module(s) and/or question type.
    ?modules=5,6&type=mc&subject=Physics&year=2020"""
    results = query_questions(
        subject=request.args.get('subject') or None,
        year=request.args.get('year') or None,
        topic=request.args.get('q') or None,
        section=parse_type_param(),
        modules=parse_modules_param(),
    )
    return jsonify(results)


@app.route('/api/mock-test', methods=['GET'])
def mock_test():
    """Generate a randomised mock exam: up to `mc` multiple-choice
    questions (default 20, matching a real HSC Section I) and up to
    `response` free-response questions (default 16, matching a real HSC
    Section II), drawn randomly from the whole bank (or a subject/module
    subset if given). If the bank has fewer than requested, returns
    whatever is available rather than erroring."""
    subject = request.args.get('subject') or None
    modules = parse_modules_param()
    mc_target = int(request.args.get('mc', 20))
    response_target = int(request.args.get('response', 16))

    mc_pool = query_questions(subject=subject, modules=modules, section=1)
    response_pool = query_questions(subject=subject, modules=modules, section=2)

    mc_selected = random.sample(mc_pool, min(mc_target, len(mc_pool)))
    response_selected = random.sample(response_pool, min(response_target, len(response_pool)))

    # Keep a sensible reading order rather than fully shuffled display order.
    mc_selected.sort(key=lambda q: (q['question_number'], q['year']))
    response_selected.sort(key=lambda q: (q['question_number'], q['year']))

    return jsonify({
        'multiple_choice': mc_selected,
        'response': response_selected,
        'multiple_choice_available': len(mc_pool),
        'response_available': len(response_pool),
    })


@app.route('/static/questions/<path:filepath>')
def serve_question_image(filepath):
    return send_from_directory(QUESTIONS_DIR, filepath)


@app.route('/api/health')
def health():
    return jsonify({'status': 'ok'})


init_db()


if __name__ == '__main__':
    app.run(debug=True, port=5000)
