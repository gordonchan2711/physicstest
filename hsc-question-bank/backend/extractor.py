"""
extractor.py — core extraction engine (question crop/stitch + mapping grid
parsing + paper auto-detection). Refactored from the standalone
hsc_extract.py CLI so the Flask backend can call it directly and get
structured Python data back instead of just writing files.
"""
import os
import re
import json

import pdfplumber
from pdf2image import convert_from_path
from PIL import Image

DPI = 200
SCALE = DPI / 72.0


# --------------------------------------------------------------------------
# Paper auto-detection (year / subject) — so provenance never depends on a
# human typing the right filename prefix.
# --------------------------------------------------------------------------

YEAR_SUBJECT_RE = re.compile(
    r'(20\d{2})\s+HIGHER SCHOOL CERTIFICATE EXAMINATION\s*\n?\s*([A-Za-z][A-Za-z0-9 ,&/\-]*)',
    re.IGNORECASE,
)


def detect_paper_info(pdf_path, fallback_name=None):
    """Best-effort (year, subject) detection from the exam PDF's title page."""
    year, subject = None, None
    try:
        with pdfplumber.open(pdf_path) as pdf:
            text = pdf.pages[0].extract_text() or ''
    except Exception:
        text = ''
    m = YEAR_SUBJECT_RE.search(text)
    if m:
        year = m.group(1)
        subject = m.group(2).strip().splitlines()[0].strip()
        # trim trailing junk words that sometimes ride along
        subject = re.split(r'\s{2,}|General\b', subject)[0].strip()
    if not year:
        ym = re.search(r'20\d{2}', text) or (re.search(r'20\d{2}', fallback_name or ''))
        year = ym.group(0) if ym else 'unknown-year'
    if not subject:
        subject = (fallback_name or 'unknown-subject').rsplit('.', 1)[0]
    return year, subject


# --------------------------------------------------------------------------
# Question boundary detection + crop/stitch
# --------------------------------------------------------------------------

def find_boundaries(pdf_path):
    boundaries = []
    with pdfplumber.open(pdf_path) as pdf:
        page_dims = []
        expected_section1 = 1
        for i, page in enumerate(pdf.pages):
            page_dims.append((page.width, page.height))
            words = page.extract_words(extra_attrs=['size', 'fontname'])
            for w in words:
                bold = 'Bold' in w['fontname']
                near_margin = w['x0'] < 75
                right_size = 11.5 <= w['size'] <= 12.5
                if not (bold and near_margin and right_size):
                    continue
                text = w['text']
                if text.isdigit() and int(text) == expected_section1 and expected_section1 <= 20:
                    boundaries.append({'question': int(text), 'page': i,
                                        'top': w['top'], 'section': 1})
                    expected_section1 += 1
                elif text == 'Question':
                    boundaries.append({'question': None, 'page': i,
                                        'top': w['top'], 'section': 2})

        for b in boundaries:
            if b['section'] != 2:
                continue
            words = pdf.pages[b['page']].extract_words(extra_attrs=['size', 'fontname'])
            for idx, w in enumerate(words):
                if w['text'] == 'Question' and abs(w['top'] - b['top']) < 0.5 and w['x0'] < 75:
                    if idx + 1 < len(words):
                        num_txt = re.sub(r'\D', '', words[idx + 1]['text'])
                        if num_txt:
                            b['question'] = int(num_txt)
                    break
    return boundaries, page_dims


def find_document_end(pdf_path, after_page):
    terminal_re = re.compile(r'^(end|section)$', re.IGNORECASE)
    with pdfplumber.open(pdf_path) as pdf:
        for p in range(after_page, min(after_page + 6, len(pdf.pages))):
            words = pdf.pages[p].extract_words(extra_attrs=['size', 'fontname'])
            for i, w in enumerate(words):
                if terminal_re.match(w['text']):
                    joined = ' '.join(x['text'] for x in words[i:i + 3]).lower()
                    if joined.startswith('end of paper') or joined.startswith('section ii extra'):
                        return p, w['top']
    return None, None


def build_regions(boundaries, page_dims, pdf_path=None):
    regions = []
    for idx, b in enumerate(boundaries):
        start_page, start_top = b['page'], b['top']
        if idx + 1 < len(boundaries):
            end_page, end_top = boundaries[idx + 1]['page'], boundaries[idx + 1]['top']
        else:
            end_page, end_top = start_page, None
            if pdf_path:
                found_page, found_top = find_document_end(pdf_path, start_page)
                if found_page is not None:
                    end_page, end_top = found_page, found_top

        segments = []
        if end_page == start_page:
            bottom = end_top if end_top is not None else page_dims[start_page][1]
            segments.append((start_page, start_top, bottom))
        else:
            segments.append((start_page, start_top, page_dims[start_page][1]))
            for p in range(start_page + 1, end_page):
                segments.append((p, 0, page_dims[p][1]))
            segments.append((end_page, 0, end_top))
        regions.append({'question': b['question'], 'section': b['section'],
                         'segments': segments})
    return regions


def crop_and_stitch(regions, page_images, out_dir, prefix):
    os.makedirs(out_dir, exist_ok=True)
    results = []
    margin_px = int(6 * SCALE)
    left_px = int(45 * SCALE)
    for r in regions:
        crops = []
        for (p, top_pt, bottom_pt) in r['segments']:
            img = page_images[p]
            top_px = max(0, int(top_pt * SCALE) - margin_px)
            bottom_px = min(img.height, int(bottom_pt * SCALE) + margin_px)
            if bottom_px <= top_px:
                continue
            crop = img.crop((left_px, top_px, img.width - left_px // 2, bottom_px))
            crops.append(crop)
        if not crops:
            continue
        if len(crops) == 1:
            stitched = crops[0]
        else:
            width = max(c.width for c in crops)
            total_h = sum(c.height for c in crops)
            stitched = Image.new('RGB', (width, total_h), 'white')
            y = 0
            for c in crops:
                stitched.paste(c, (0, y))
                y += c.height
        fname = f"{prefix}_Q{r['question']}.png"
        stitched.save(os.path.join(out_dir, fname))
        results.append({'question': r['question'], 'section': r['section'],
                         'filename': fname})
    return results


def extract_questions(pdf_path, out_dir, prefix):
    boundaries, page_dims = find_boundaries(pdf_path)
    regions = build_regions(boundaries, page_dims, pdf_path=pdf_path)
    page_images = convert_from_path(pdf_path, dpi=DPI)
    return crop_and_stitch(regions, page_images, out_dir, prefix)


# --------------------------------------------------------------------------
# Mapping grid parsing
# --------------------------------------------------------------------------

QNUM_RE = re.compile(r'^(\d+)\s*((?:\([a-z]+\)\s*)*)$', re.IGNORECASE)
SUBPART_RE = re.compile(r'\(([a-z]+)\)', re.IGNORECASE)


def parse_question_label(label):
    label = label.strip().replace('\n', ' ')
    m = QNUM_RE.match(label)
    if not m:
        return None, []
    return int(m.group(1)), SUBPART_RE.findall(m.group(2))


def find_mapping_grid_pages(pdf):
    pages = []
    for i, page in enumerate(pdf.pages):
        text = page.extract_text() or ''
        if 'Mapping Grid' in text or (
            'Question' in text and 'Marks' in text and 'Syllabus outcomes' in text
        ):
            pages.append(i)
    return pages


def parse_mapping_grid(pdf_path):
    entries = []
    with pdfplumber.open(pdf_path) as pdf:
        pages = find_mapping_grid_pages(pdf)
        for i in pages:
            for table in pdf.pages[i].extract_tables():
                for row in table:
                    if not row or row[0] is None:
                        continue
                    if row[0].strip().lower() == 'question':
                        continue
                    qnum, subparts = parse_question_label(row[0])
                    if qnum is None:
                        continue
                    try:
                        marks = int(re.sub(r'\D', '', row[1])) if row[1] else None
                    except ValueError:
                        marks = None
                    content = (row[2] or '').replace('\n', ' ').strip()
                    outcomes_raw = (row[3] or '').replace('\n', ' ').strip()
                    outcomes = [o.strip() for o in outcomes_raw.split(',') if o.strip()]
                    entries.append({
                        'question': qnum, 'subparts': subparts,
                        'marks': marks, 'content': content,
                        'syllabus_outcomes': outcomes,
                    })
    return entries


def aggregate_tags_by_question(mapping_entries):
    """Mapping grid has one row per sub-part (21(a), 21(b), ...) but we
    extract one image per top-level question. Aggregate rows belonging to
    the same question into one tag-set for that image."""
    by_q = {}
    for e in mapping_entries:
        q = e['question']
        agg = by_q.setdefault(q, {'marks': 0, 'content': [], 'syllabus_outcomes': []})
        if e['marks']:
            agg['marks'] += e['marks']
        if e['content'] and e['content'] not in agg['content']:
            agg['content'].append(e['content'])
        for o in e['syllabus_outcomes']:
            if o not in agg['syllabus_outcomes']:
                agg['syllabus_outcomes'].append(o)
    return by_q


# --------------------------------------------------------------------------
# High-level entry point used by the Flask backend
# --------------------------------------------------------------------------

def process_paper(exam_pdf_path, guidelines_pdf_path, out_dir, exam_filename=None):
    """Runs the full pipeline and returns a structured result dict ready to
    be persisted by the backend:
      { 'year':..., 'subject':..., 'questions': [ {question, section,
        filename, marks, content, syllabus_outcomes}, ... ] }
    """
    year, subject = detect_paper_info(exam_pdf_path, fallback_name=exam_filename)
    prefix = f"{re.sub(r'[^A-Za-z0-9]+', '', subject).lower()}{year}"

    questions = extract_questions(exam_pdf_path, out_dir, prefix)

    tags_by_q = {}
    if guidelines_pdf_path:
        mapping_entries = parse_mapping_grid(guidelines_pdf_path)
        tags_by_q = aggregate_tags_by_question(mapping_entries)

    for q in questions:
        tags = tags_by_q.get(q['question'], {})
        q['marks'] = tags.get('marks')
        q['content'] = tags.get('content', [])
        q['syllabus_outcomes'] = tags.get('syllabus_outcomes', [])

    return {'year': year, 'subject': subject, 'prefix': prefix, 'questions': questions}
