const API = ''; // same-origin

let examFile = null;
let guideFile = null;
let allPapers = [];
let currentView = 'bank';

const VIEW_TITLES = {
  bank: 'Question Bank',
  mcOnly: 'Multiple Choice Only',
  byNumber: 'By Question Number',
  customTest: 'Custom Test',
  mockTest: 'Mock Test',
};

// ==========================================================================
// View switching
// ==========================================================================

function showView(view, opts = {}) {
  currentView = view;
  document.querySelectorAll('.view').forEach(el => { el.hidden = true; });
  const el = document.getElementById(`view-${view}`);
  if (el) el.hidden = false;

  document.getElementById('viewTitle').textContent =
    view === 'byNumber' && opts.questionNumber
      ? `Question ${opts.questionNumber} — all years`
      : VIEW_TITLES[view] || 'Question Bank';

  document.querySelectorAll('.nav-item[data-view]').forEach(btn => {
    btn.classList.toggle('active', btn.dataset.view === view);
  });
  const qSelect = document.getElementById('questionNumberSelect');
  if (view === 'byNumber' && opts.questionNumber) {
    qSelect.value = String(opts.questionNumber);
  } else {
    qSelect.value = '';
  }

  if (view === 'bank') loadQuestions();
  if (view === 'mcOnly') loadMcOnly();
  if (view === 'byNumber' && opts.questionNumber) loadByNumber(opts.questionNumber);
}

document.querySelectorAll('.nav-item[data-view]').forEach(btn => {
  btn.addEventListener('click', () => showView(btn.dataset.view));
});

// ==========================================================================
// Sidebar hide/show
// ==========================================================================

document.getElementById('sidebarHideBtn').addEventListener('click', () => {
  document.getElementById('sidebar').classList.add('hidden');
  document.getElementById('sidebarShowBtn').hidden = false;
});
document.getElementById('sidebarShowBtn').addEventListener('click', () => {
  document.getElementById('sidebar').classList.remove('hidden');
  document.getElementById('sidebarShowBtn').hidden = true;
});

// ==========================================================================
// Dropzones / upload (Question Bank view)
// ==========================================================================

function setupDropzone(zoneId, inputId, labelId, kind) {
  const zone = document.getElementById(zoneId);
  const input = document.getElementById(inputId);
  const label = document.getElementById(labelId);

  zone.addEventListener('click', () => input.click());
  input.addEventListener('change', () => handleFile(input.files[0], kind, label));

  ['dragenter', 'dragover'].forEach(evt =>
    zone.addEventListener(evt, e => { e.preventDefault(); zone.classList.add('dragover'); })
  );
  ['dragleave', 'drop'].forEach(evt =>
    zone.addEventListener(evt, e => { e.preventDefault(); zone.classList.remove('dragover'); })
  );
  zone.addEventListener('drop', e => {
    const file = e.dataTransfer.files[0];
    if (file) handleFile(file, kind, label);
  });
}

function handleFile(file, kind, labelEl) {
  if (!file) return;
  if (file.type !== 'application/pdf') {
    labelEl.textContent = 'Please choose a PDF file.';
    return;
  }
  labelEl.textContent = file.name;
  if (kind === 'exam') examFile = file;
  else guideFile = file;
  document.getElementById('processBtn').disabled = !examFile;
}

setupDropzone('examDrop', 'examInput', 'examFileName', 'exam');
setupDropzone('guideDrop', 'guideInput', 'guideFileName', 'guide');

document.getElementById('processBtn').addEventListener('click', async () => {
  const btn = document.getElementById('processBtn');
  const status = document.getElementById('statusLine');
  btn.disabled = true;
  status.className = 'status-line';
  status.textContent = 'Uploading and extracting — this can take a minute for long papers…';

  const form = new FormData();
  form.append('exam_pdf', examFile);
  if (guideFile) form.append('guidelines_pdf', guideFile);

  try {
    const res = await fetch(`${API}/api/upload`, { method: 'POST', body: form });
    const data = await res.json();
    if (!res.ok) throw new Error(data.error || 'Upload failed');

    status.className = 'status-line success';
    status.textContent = `Done — extracted ${data.question_count} questions from ${data.subject} ${data.year}.`;

    examFile = null; guideFile = null;
    document.getElementById('examFileName').textContent = '';
    document.getElementById('guideFileName').textContent = '';
    document.getElementById('examInput').value = '';
    document.getElementById('guideInput').value = '';

    await refreshGlobalState();
  } catch (err) {
    status.className = 'status-line error';
    status.textContent = `Error: ${err.message}`;
  } finally {
    document.getElementById('processBtn').disabled = !examFile;
  }
});

// ==========================================================================
// Global state: papers, subject/year options, question-number sidebar list
// ==========================================================================

async function loadPapers() {
  const res = await fetch(`${API}/api/papers`);
  allPapers = await res.json();
  renderPapersStrip();
  populateSubjectYearSelects();
}

function renderPapersStrip() {
  const strip = document.getElementById('papersStrip');
  strip.innerHTML = '';
  allPapers.forEach(p => {
    const chip = document.createElement('div');
    chip.className = 'paper-chip';
    const untagged = !p.guidelines_filename;
    chip.innerHTML = `<span>${p.subject} ${p.year} · ${p.question_count}q</span>` +
      (untagged ? '<span class="paper-chip-warning" title="No marking guidelines uploaded — questions have no topic/module tags and won\'t show up in module-filtered views.">no tags</span>' : '');
    const del = document.createElement('button');
    del.textContent = '\u2715';
    del.title = 'Remove this paper';
    del.addEventListener('click', async () => {
      if (!confirm(`Remove ${p.subject} ${p.year} and all ${p.question_count} of its questions?`)) return;
      await fetch(`${API}/api/papers/${p.id}`, { method: 'DELETE' });
      await refreshGlobalState();
    });
    chip.appendChild(del);
    strip.appendChild(chip);
  });
}

function populateSubjectYearSelects() {
  const subjects = [...new Set(allPapers.map(p => p.subject))].sort();
  const years = [...new Set(allPapers.map(p => p.year))].sort().reverse();

  const subjectSelectIds = ['subjectFilter', 'mcSubjectFilter', 'customSubjectFilter', 'mockSubjectFilter'];
  const yearSelectIds = ['yearFilter', 'mcYearFilter', 'customYearFilter'];

  subjectSelectIds.forEach(id => {
    const sel = document.getElementById(id);
    const cur = sel.value;
    sel.innerHTML = '<option value="">All subjects</option>' +
      subjects.map(s => `<option value="${s}">${s}</option>`).join('');
    sel.value = cur;
  });
  yearSelectIds.forEach(id => {
    const sel = document.getElementById(id);
    const cur = sel.value;
    sel.innerHTML = '<option value="">All years</option>' +
      years.map(y => `<option value="${y}">${y}</option>`).join('');
    sel.value = cur;
  });
}

async function loadQuestionNumberSidebar() {
  const res = await fetch(`${API}/api/question-numbers`);
  const nums = await res.json();
  const sel = document.getElementById('questionNumberSelect');
  const cur = sel.value;
  sel.innerHTML = '<option value="">Select a question…</option>' +
    nums.map(n =>
      `<option value="${n.question_number}">Q${n.question_number} (${n.section === 1 ? 'MC' : 'Response'} · ${n.paper_count} paper${n.paper_count === 1 ? '' : 's'})</option>`
    ).join('');
  sel.value = cur;
}

document.getElementById('questionNumberSelect').addEventListener('change', e => {
  const val = e.target.value;
  if (val) showView('byNumber', { questionNumber: Number(val) });
});

async function refreshGlobalState() {
  await loadPapers();
  await loadQuestionNumberSidebar();
  await loadSamplePapers();
  if (currentView === 'bank') await loadQuestions();
  if (currentView === 'mcOnly') await loadMcOnly();
}

// ==========================================================================
// Bundled sample papers
// ==========================================================================

async function loadSamplePapers() {
  const res = await fetch(`${API}/api/sample-papers`);
  const samples = await res.json();
  const section = document.getElementById('samplesSection');
  const list = document.getElementById('samplesList');

  if (samples.length === 0) {
    section.hidden = true;
    return;
  }
  section.hidden = false;
  list.innerHTML = '';

  samples.forEach(s => {
    const card = document.createElement('div');
    card.className = 'sample-card';
    card.innerHTML = `
      <div>
        <span class="sample-card-name">${s.exam_filename}</span>
        <span class="sample-card-meta">${s.has_guidelines ? 'includes marking guidelines' : 'exam only'}</span>
      </div>
    `;
    const btn = document.createElement('button');
    btn.className = 'sample-load-btn';
    if (s.already_loaded) {
      btn.textContent = 'Loaded';
      btn.disabled = true;
    } else {
      btn.textContent = 'Load';
      btn.addEventListener('click', () => loadSample(s.exam_filename, btn));
    }
    card.appendChild(btn);
    list.appendChild(card);
  });
}

async function loadSample(examFilename, btn) {
  btn.disabled = true;
  btn.textContent = 'Loading…';
  try {
    const res = await fetch(`${API}/api/load-sample`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ exam_filename: examFilename }),
    });
    const data = await res.json();
    if (!res.ok) throw new Error(data.error || 'Failed to load sample');
    await refreshGlobalState();
  } catch (err) {
    btn.disabled = false;
    btn.textContent = 'Load';
    alert(`Couldn't load ${examFilename}: ${err.message}`);
  }
}

// ==========================================================================
// Gallery card rendering (shared by every view)
// ==========================================================================

function renderCard(q) {
  const card = document.createElement('div');
  card.className = 'q-card';
  const hasAnswer = q.answer_text || q.answer_image_url;
  card.innerHTML = `
    <div class="q-thumb"><img loading="lazy" src="${API}${q.image_url}" alt="Question ${q.question_number}"></div>
    <div class="q-card-body">
      <div class="q-card-top">
        <span class="q-number">Q${q.question_number}</span>
        <span class="q-card-top-right">
          ${hasAnswer ? '<span class="q-answer-badge" title="Answer available">✓ answer</span>' : ''}
          ${q.marks ? `<span class="q-marks">${q.marks} mark${q.marks === 1 ? '' : 's'}</span>` : ''}
        </span>
      </div>
      <div class="q-source">${q.subject} · ${q.year}</div>
      <div class="q-tags">
        ${(q.content || []).slice(0, 2).map(c => `<span class="q-tag">${c}</span>`).join('')}
      </div>
    </div>
  `;
  card.addEventListener('click', () => openLightbox(q));
  return card;
}

function renderInto(containerId, questions, emptyMessage) {
  const container = document.getElementById(containerId);
  container.innerHTML = '';
  if (questions.length === 0) {
    const empty = document.createElement('p');
    empty.className = 'empty-state';
    empty.textContent = emptyMessage;
    container.appendChild(empty);
    return;
  }
  questions.forEach(q => container.appendChild(renderCard(q)));
}

// ==========================================================================
// VIEW: Question Bank (full gallery + filters)
// ==========================================================================

async function loadQuestions() {
  const params = new URLSearchParams();
  const subject = document.getElementById('subjectFilter').value;
  const year = document.getElementById('yearFilter').value;
  const topic = document.getElementById('topicSearch').value.trim();
  if (subject) params.set('subject', subject);
  if (year) params.set('year', year);
  if (topic) params.set('q', topic);

  const res = await fetch(`${API}/api/questions?${params.toString()}`);
  const questions = await res.json();
  renderInto('gallery', questions,
    allPapers.length === 0
      ? 'No questions yet. Upload a past paper above to start building your bank.'
      : 'No questions match these filters.');
  document.getElementById('totalCount').textContent =
    `${questions.length} question${questions.length === 1 ? '' : 's'} shown`;
}

['subjectFilter', 'yearFilter'].forEach(id =>
  document.getElementById(id).addEventListener('change', loadQuestions)
);
document.getElementById('topicSearch').addEventListener('input', debounce(loadQuestions, 300));
document.getElementById('clearFilters').addEventListener('click', () => {
  document.getElementById('subjectFilter').value = '';
  document.getElementById('yearFilter').value = '';
  document.getElementById('topicSearch').value = '';
  loadQuestions();
});

// ==========================================================================
// VIEW: Multiple Choice Only
// ==========================================================================

async function loadMcOnly() {
  const params = new URLSearchParams();
  params.set('type', 'mc');
  const subject = document.getElementById('mcSubjectFilter').value;
  const year = document.getElementById('mcYearFilter').value;
  const topic = document.getElementById('mcTopicSearch').value.trim();
  if (subject) params.set('subject', subject);
  if (year) params.set('year', year);
  if (topic) params.set('q', topic);

  const res = await fetch(`${API}/api/questions?${params.toString()}`);
  const questions = await res.json();
  renderInto('mcGallery', questions, 'No multiple-choice questions match these filters.');
}

['mcSubjectFilter', 'mcYearFilter'].forEach(id =>
  document.getElementById(id).addEventListener('change', loadMcOnly)
);
document.getElementById('mcTopicSearch').addEventListener('input', debounce(loadMcOnly, 300));
document.getElementById('mcClearFilters').addEventListener('click', () => {
  document.getElementById('mcSubjectFilter').value = '';
  document.getElementById('mcYearFilter').value = '';
  document.getElementById('mcTopicSearch').value = '';
  loadMcOnly();
});

// ==========================================================================
// VIEW: By Question Number
// ==========================================================================

async function loadByNumber(qnum) {
  document.getElementById('byNumberSubtitle').textContent =
    `Every year's version of Question ${qnum}, side by side.`;
  const res = await fetch(`${API}/api/questions?question_number=${qnum}`);
  const questions = await res.json();
  renderInto('byNumberGallery', questions, `No questions numbered ${qnum} found.`);
}

// ==========================================================================
// VIEW: Custom Test
// ==========================================================================

const customState = { modules: new Set(), type: '' };

document.querySelectorAll('#moduleToggles .chip-toggle').forEach(btn => {
  btn.addEventListener('click', () => {
    const mod = btn.dataset.module;
    btn.classList.toggle('active');
    if (btn.classList.contains('active')) customState.modules.add(mod);
    else customState.modules.delete(mod);
  });
});
document.querySelectorAll('#typeToggles .chip-toggle').forEach(btn => {
  btn.addEventListener('click', () => {
    document.querySelectorAll('#typeToggles .chip-toggle').forEach(b => b.classList.remove('active'));
    btn.classList.add('active');
    customState.type = btn.dataset.type;
  });
});

document.getElementById('customTestGenerate').addEventListener('click', async () => {
  const params = new URLSearchParams();
  if (customState.modules.size > 0) params.set('modules', [...customState.modules].join(','));
  if (customState.type) params.set('type', customState.type);
  const subject = document.getElementById('customSubjectFilter').value;
  const year = document.getElementById('customYearFilter').value;
  if (subject) params.set('subject', subject);
  if (year) params.set('year', year);

  const res = await fetch(`${API}/api/custom-test?${params.toString()}`);
  const questions = await res.json();
  document.getElementById('customTestSummary').textContent =
    `${questions.length} question${questions.length === 1 ? '' : 's'} match your filters.`;
  renderInto('customTestGallery', questions, 'No questions match these filters. Try widening your selection.');

  const btn = document.getElementById('customAnswerKeyBtn');
  const panel = document.getElementById('customAnswerKeyPanel');
  panel.hidden = true;
  btn.textContent = 'Show answer key';
  btn.hidden = questions.length === 0;
  wireAnswerKeyToggle('customAnswerKeyBtn', 'customAnswerKeyPanel', () => questions);
});

// ==========================================================================
// VIEW: Mock Test
// ==========================================================================

const mockState = { modules: new Set() };

document.querySelectorAll('#mockModuleToggles .chip-toggle').forEach(btn => {
  btn.addEventListener('click', () => {
    const mod = btn.dataset.module;
    btn.classList.toggle('active');
    if (btn.classList.contains('active')) mockState.modules.add(mod);
    else mockState.modules.delete(mod);
  });
});

document.getElementById('mockTestGenerate').addEventListener('click', async () => {
  const params = new URLSearchParams();
  params.set('mc', '20');
  params.set('response', '16');
  if (mockState.modules.size > 0) params.set('modules', [...mockState.modules].join(','));
  const subject = document.getElementById('mockSubjectFilter').value;
  if (subject) params.set('subject', subject);

  const res = await fetch(`${API}/api/mock-test?${params.toString()}`);
  const data = await res.json();

  document.getElementById('mockEmptyState').hidden = true;
  document.getElementById('mockTestResult').hidden = false;

  document.getElementById('mcSectionCount').textContent =
    `(${data.multiple_choice.length} of ${data.multiple_choice_available} available)`;
  document.getElementById('respSectionCount').textContent =
    `(${data.response.length} of ${data.response_available} available)`;

  renderInto('mockMcGallery', data.multiple_choice, 'No multiple-choice questions available for these filters.');
  renderInto('mockRespGallery', data.response, 'No response questions available for these filters.');

  const mockAnswerKeyPanel = document.getElementById('mockAnswerKeyPanel');
  mockAnswerKeyPanel.hidden = true;
  document.getElementById('mockAnswerKeyBtn').textContent = 'Show answer key';
  wireAnswerKeyToggle('mockAnswerKeyBtn', 'mockAnswerKeyPanel',
    () => [...data.multiple_choice, ...data.response]);
});

// ==========================================================================
// Compiled answer key (shared by Custom Test and Mock Test)
// ==========================================================================

function buildAnswerKeyHTML(questions) {
  const mcQs = questions.filter(q => q.section === 1).sort((a, b) => a.question_number - b.question_number);
  const respQs = questions.filter(q => q.section === 2).sort((a, b) => a.question_number - b.question_number);

  if (mcQs.length === 0 && respQs.length === 0) {
    return '<p class="empty-state">No questions to show answers for.</p>';
  }

  let html = '';

  if (mcQs.length > 0) {
    html += '<h3 class="answer-key-heading">Section I answers</h3>';
    html += '<div class="answer-key-mc-grid">';
    mcQs.forEach(q => {
      html += `<div class="answer-key-mc-item"><span>Q${q.question_number}</span><span class="answer-letter-small">${q.answer_text || '—'}</span></div>`;
    });
    html += '</div>';
  }

  if (respQs.length > 0) {
    html += '<h3 class="answer-key-heading">Section II answers</h3>';
    respQs.forEach(q => {
      html += `<div class="answer-key-response-item">
        <h4>Question ${q.question_number} — ${q.subject} ${q.year}</h4>
        ${q.answer_image_url
          ? `<img src="${API}${q.answer_image_url}" alt="Marking guidelines for Question ${q.question_number}">`
          : '<p class="answer-key-missing">No marking guidelines available for this question.</p>'}
      </div>`;
    });
  }

  return html;
}

function wireAnswerKeyToggle(btnId, panelId, getQuestions) {
  const btn = document.getElementById(btnId);
  const panel = document.getElementById(panelId);
  btn.onclick = () => {
    const revealing = panel.hidden;
    panel.hidden = !revealing;
    btn.textContent = revealing ? 'Hide answer key' : 'Show answer key';
    if (revealing) {
      panel.innerHTML = buildAnswerKeyHTML(getQuestions());
    }
  };
}

// ==========================================================================
// Lightbox
// ==========================================================================

function openLightbox(q) {
  document.getElementById('lightboxImg').src = `${API}${q.image_url}`;
  const outcomes = (q.syllabus_outcomes || []).join(', ') || '—';
  const topics = (q.content || []).join(' · ') || '—';
  document.getElementById('lightboxMeta').innerHTML = `
    <strong>${q.subject} ${q.year} — Question ${q.question_number}</strong><br>
    Marks: ${q.marks ?? '—'}<br>
    Topic: ${topics}<br>
    Syllabus outcomes: ${outcomes}
  `;

  const answerBtn = document.getElementById('answerToggleBtn');
  const answerPanel = document.getElementById('answerPanel');
  answerPanel.hidden = true;
  answerPanel.innerHTML = '';
  answerBtn.textContent = 'Show answer';

  const hasAnswer = q.answer_text || q.answer_image_url;
  answerBtn.hidden = !hasAnswer;

  if (hasAnswer) {
    answerBtn.onclick = () => {
      const revealing = answerPanel.hidden;
      answerPanel.hidden = !revealing;
      answerBtn.textContent = revealing ? 'Hide answer' : 'Show answer';
      if (revealing && !answerPanel.innerHTML) {
        if (q.answer_text) {
          answerPanel.innerHTML = `<div class="answer-panel-mc">Correct answer: <span class="answer-letter">${q.answer_text}</span></div>`;
        } else if (q.answer_image_url) {
          answerPanel.innerHTML = `<img src="${API}${q.answer_image_url}" alt="Marking guidelines for Question ${q.question_number}">`;
        }
      }
    };
  }

  document.getElementById('lightbox').hidden = false;
}
document.getElementById('lightboxClose').addEventListener('click', () => {
  document.getElementById('lightbox').hidden = true;
});
document.getElementById('lightbox').addEventListener('click', e => {
  if (e.target.id === 'lightbox') document.getElementById('lightbox').hidden = true;
});

// ==========================================================================
// Utilities
// ==========================================================================

function debounce(fn, ms) {
  let t;
  return (...args) => { clearTimeout(t); t = setTimeout(() => fn(...args), ms); };
}

// ==========================================================================
// Init
// ==========================================================================

(async function init() {
  await refreshGlobalState();
  showView('bank');
})();
