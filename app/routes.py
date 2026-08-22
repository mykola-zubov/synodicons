import os
import re
import csv
import io
import json
import difflib
import markdown
from datetime import datetime
from flask import Blueprint, render_template, jsonify, request, Response, session
from .services.xml_processor import XmlProcessor, normalize_slavic_text

main_bp = Blueprint('main', __name__)

BASE_DIR = os.path.dirname(os.path.dirname(__file__))
ADMIN_PASSWORD = os.environ.get('ADMIN_PASSWORD', 'slepche2026')

MANUSCRIPTS = {
    'slepche_116': {
        'id': 'slepche_116',
        'title': 'Слепченски поменик (Одеський список 1/116)',
        'short_title': 'Одеський 1/116',
        'archive': 'ОННБ, Ркп 1/116 (XVI–XVII ст.)',
        'xml_path': os.path.join(BASE_DIR, 'data', 'slepche_116', 'Odesa_pomenik.xml'),
        'image_folder': 'slepche_116'
    },
    'slepche_1015': {
        'id': 'slepche_1015',
        'title': 'Слепченски поменик (Софійський список 1015)',
        'short_title': 'Софійський 1015',
        'archive': 'НБКМ, № 1015 (XVI–XVII ст.)',
        'xml_path': os.path.join(BASE_DIR, 'data', 'slepche_1015', 'Sofia_pomenik.xml'),
        'image_folder': 'slepche_1015'
    }
}

processors = {}
for mid, mdata in MANUSCRIPTS.items():
    if os.path.exists(mdata['xml_path']):
        processors[mid] = XmlProcessor(mdata['xml_path'])

def get_current_processor():
    ms_id = session.get('current_ms', 'slepche_116')
    if ms_id not in processors and 'slepche_116' in processors:
        ms_id = 'slepche_116'
    return processors.get(ms_id), MANUSCRIPTS.get(ms_id)

def record_visit():
    stats_file = os.path.join(BASE_DIR, 'data', 'site_stats.json')
    stats = {'total_views': 0, 'last_visit': ''}
    if os.path.exists(stats_file):
        try:
            with open(stats_file, 'r', encoding='utf-8') as f:
                stats = json.load(f)
        except Exception:
            pass
    stats['total_views'] = stats.get('total_views', 0) + 1
    stats['last_visit'] = datetime.now().strftime('%Y-%m-%d %H:%M')
    try:
        with open(stats_file, 'w', encoding='utf-8') as f:
            json.dump(stats, f, ensure_ascii=False, indent=2)
    except Exception:
        pass
    return stats['total_views']

@main_bp.route('/')
def index():
    total_views = record_visit()
    proc, ms_info = get_current_processor()
    pages = proc.get_pages_list() if proc else []
    is_admin = session.get('is_admin', False)
    return render_template(
        'editor.html',
        pages=pages,
        manuscripts=MANUSCRIPTS,
        current_ms=ms_info,
        active_ms_id=ms_info['id'] if ms_info else 'slepche_116',
        is_admin=is_admin,
        total_views=total_views
    )

@main_bp.route('/api/feedback', methods=['POST'])
def handle_feedback():
    data = request.json or {}
    name = data.get('name', '').strip()
    email = data.get('email', '').strip()
    subject = data.get('subject', 'Загальне запитання').strip()
    message = data.get('message', '').strip()
    context = data.get('context', '').strip()

    if not message:
        return jsonify({'status': 'error', 'message': 'Повідомлення не може бути порожнім'}), 400

    feedback_entry = {
        'date': datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
        'name': name or 'Анонімний дослідник',
        'email': email or 'Не вказано',
        'subject': subject,
        'context': context,
        'message': message
    }

    feedback_file = os.path.join(BASE_DIR, 'data', 'feedback_messages.json')
    messages = []
    if os.path.exists(feedback_file):
        try:
            with open(feedback_file, 'r', encoding='utf-8') as f:
                messages = json.load(f)
        except Exception:
            messages = []
            
    messages.append(feedback_entry)
    with open(feedback_file, 'w', encoding='utf-8') as f:
        json.dump(messages, f, ensure_ascii=False, indent=2)

    return jsonify({'status': 'success', 'message': 'Дякуємо! Ваше повідомлення передано автору.'})

@main_bp.route('/api/login', methods=['POST'])
def login_api():
    pwd = (request.json or {}).get('password', '')
    if pwd == ADMIN_PASSWORD:
        session['is_admin'] = True
        return jsonify({'status': 'success', 'is_admin': True})
    return jsonify({'status': 'error', 'message': 'Невірний пароль!'}), 403

@main_bp.route('/api/logout', methods=['POST'])
def logout_api():
    session.pop('is_admin', None)
    return jsonify({'status': 'success', 'is_admin': False})

@main_bp.route('/api/auth-status')
def auth_status_api():
    return jsonify({'is_admin': session.get('is_admin', False)})

@main_bp.route('/api/select-codex/<codex_id>')
def select_codex(codex_id):
    if codex_id in MANUSCRIPTS:
        if codex_id not in processors and os.path.exists(MANUSCRIPTS[codex_id]['xml_path']):
            processors[codex_id] = XmlProcessor(MANUSCRIPTS[codex_id]['xml_path'])
            
        if codex_id in processors:
            session['current_ms'] = codex_id
            return jsonify({'status': 'success', 'codex_id': codex_id})
    return jsonify({'status': 'error', 'message': 'Рукопис ще не підключено'}), 400

@main_bp.route('/api/page/<page_id>')
def get_page(page_id):
    proc, _ = get_current_processor()
    lines = proc.get_page_data(page_id) if proc else []
    return jsonify(lines)

@main_bp.route('/api/save', methods=['POST'])
def save_data():
    if not session.get('is_admin', False):
        return jsonify({'status': 'error', 'message': 'Потрібна авторизація для редагування'}), 403
        
    proc, _ = get_current_processor()
    if not proc:
        return jsonify({'status': 'error'}), 500
        
    req_data = request.json
    success = proc.update_entity(
        page_id=req_data['page_id'],
        line_id=req_data['line_id'],
        data={
            'entity_type': req_data.get('entity_type', 'person'),
            'text': req_data.get('text'),
            'lemma': req_data.get('lemma'),
            'gender': req_data.get('gender'),
            'role': req_data.get('role'),
            'hand': req_data.get('hand', 'h1'),
            'is_duplicate': req_data.get('is_duplicate', False)
        }
    )
    return jsonify({'status': 'success' if success else 'error'})

@main_bp.route('/api/set-duplicate', methods=['POST'])
def set_duplicate_api():
    if not session.get('is_admin', False):
        return jsonify({'status': 'error', 'message': 'Потрібна авторизація для маркування'}), 403
        
    proc, _ = get_current_processor()
    req_data = request.json
    success = proc.set_duplicate_status(req_data.get('page_id'), req_data.get('line_id'), req_data.get('is_duplicate', False))
    return jsonify({'status': 'success' if success else 'error'})

@main_bp.route('/api/batch-save', methods=['POST'])
def batch_save_data():
    if not session.get('is_admin', False):
        return jsonify({'status': 'error', 'message': 'Потрібна авторизація для пакетної розмітки'}), 403
        
    proc, _ = get_current_processor()
    req_data = request.json
    count = proc.batch_update_entities(
        target_text=req_data.get('text', ''),
        data={
            'lemma': req_data.get('lemma'),
            'gender': req_data.get('gender'),
            'role': req_data.get('role')
        }
    )
    return jsonify({'status': 'success', 'updated_count': count})

@main_bp.route('/api/global-search')
def global_search_api():
    proc, _ = get_current_processor()
    query = request.args.get('q', '')
    results = proc.global_search(query) if proc else []
    return jsonify(results)

@main_bp.route('/api/lemmas')
def get_lemmas_api():
    proc, _ = get_current_processor()
    lemmas = proc.get_lemmas_dict() if proc else []
    return jsonify(lemmas)

@main_bp.route('/api/all-entities')
def get_all_entities_api():
    proc, _ = get_current_processor()
    dataset = proc.export_dataset(deduplicate=False) if proc else []
    return jsonify(dataset)

@main_bp.route('/api/codex-structure')
def get_codex_structure_api():
    proc, _ = get_current_processor()
    return jsonify(proc.structure if proc else {})

@main_bp.route('/api/statistics')
def statistics_api():
    proc, _ = get_current_processor()
    dedup = request.args.get('dedup', '0') == '1'
    stats = proc.get_statistics(deduplicate=dedup) if proc else {}
    
    stats_file = os.path.join(BASE_DIR, 'data', 'site_stats.json')
    if os.path.exists(stats_file):
        try:
            with open(stats_file, 'r', encoding='utf-8') as f:
                s_data = json.load(f)
                stats['total_views'] = s_data.get('total_views', 1)
        except Exception:
            stats['total_views'] = 1
    return jsonify(stats)

# ЗАХИЩЕНЕ ВИВАНТАЖЕННЯ ПОВНОГО ДАТАСЕТУ (Тільки для автора)
@main_bp.route('/api/export/csv')
def export_csv_api():
    if not session.get('is_admin', False):
        return "<h3>🔒 Доступ обмежено</h3><p>Повний датасет пам'ятки доступний для вивантаження лише авторизованому автору.</p>", 403

    proc, ms_info = get_current_processor()
    dedup = request.args.get('dedup', '0') == '1'
    dataset = proc.export_dataset(deduplicate=dedup)
    
    output = io.StringIO()
    output.write('\ufeff')
    
    writer = csv.writer(output, delimiter=';')
    writer.writerow([
        'Архівний лист', 'Номер рядка', 'Текст у рукописі', 
        'Тип сутності', 'Лема', 'Стать', 'Соціальний статус', 'Шар письма (TEI Hand)', 'Дубль', 'Розділ кодика'
    ])
    
    for row in dataset:
        writer.writerow([
            row['page_label'], row['line_number'], row['text'],
            row['entity_type'], row['lemma'], row['gender'],
            row['role'], row['hand'], 'ДУБЛЬ' if row.get('is_duplicate') else 'НІ', row['codex_section']
        ])
        
    output.seek(0)
    filename = f"{ms_info['id']}_Deduplicated_Corpus.csv" if dedup else f"{ms_info['id']}_Full_Corpus.csv"
    return Response(
        output.getvalue(),
        mimetype="text/csv",
        headers={"Content-Disposition": f"attachment;filename={filename}"}
    )

# ЗАХИЩЕНЕ ВИВАНТАЖЕННЯ СЛОВНИКА АНТРОПОНІМІВ (Тільки для автора)
@main_bp.route('/api/export/anthroponyms')
def export_anthroponyms_csv():
    if not session.get('is_admin', False):
        return "<h3>🔒 Доступ обмежено</h3><p>Частотний словник антропонімів перебуває на стадії наукового опрацювання автором. Вивантаження заблоковано для публічного доступу.</p>", 403

    proc, ms_info = get_current_processor()
    dictionary = proc.generate_anthroponyms_dictionary()
    output = io.StringIO()
    output.write('\ufeff')
    
    writer = csv.writer(output, delimiter=';')
    writer.writerow([
        'Лема (Канонічна форма)', 'Стать', 'Загальна частота', 
        'Первинний шар (#h1)', 'Приписки (#h2)', 
        'Варіанти написання в рукописі (частота та аркуші)'
    ])
    
    for row in dictionary:
        writer.writerow([
            row['lemma'], row['gender'], row['total_count'],
            row['h1_count'], row['h2_count'], row['variants_summary']
        ])
        
    output.seek(0)
    return Response(
        output.getvalue(),
        mimetype="text/csv",
        headers={"Content-Disposition": f"attachment;filename={ms_info['id']}_Anthroponyms_Dictionary.csv"}
    )

# ЗАХИЩЕНЕ ВИВАНТАЖЕННЯ СЛОВНИКА ТОПОНІМІВ (Тільки для автора)
@main_bp.route('/api/export/toponyms')
def export_toponyms_csv():
    if not session.get('is_admin', False):
        return "<h3>🔒 Доступ обмежено</h3><p>Словник топонімів перебуває на стадії наукового опрацювання автором. Вивантаження заблоковано для публічного доступу.</p>", 403

    proc, ms_info = get_current_processor()
    dictionary = proc.generate_toponyms_dictionary()
    output = io.StringIO()
    output.write('\ufeff')
    
    writer = csv.writer(output, delimiter=';')
    writer.writerow([
        'Нормалізований топонім', 'Загальна кількість згадок', 
        'Варіанти фіксації в рукописі', 'Усі аркуші кодика'
    ])
    
    for row in dictionary:
        writer.writerow([
            row['toponym'], row['total_count'],
            row['variants_summary'], row['folios_list']
        ])
        
    output.seek(0)
    return Response(
        output.getvalue(),
        mimetype="text/csv",
        headers={"Content-Disposition": f"attachment;filename={ms_info['id']}_Toponyms_Dictionary.csv"}
    )

@main_bp.route('/api/collation')
def collation_api():
    proc, _ = get_current_processor()
    orig_folio = request.args.get('orig', '').strip()
    copy_folio = request.args.get('copy', '').strip()
    only_person = request.args.get('only_person', '1') == '1'
    
    pages = proc.get_pages_list()
    orig_page = next((p for p in pages if orig_folio in p['label']), None)
    copy_page = next((p for p in pages if copy_folio in p['label']), None)
    
    orig_lines = proc.get_page_data(orig_page['id']) if orig_page else []
    copy_lines = proc.get_page_data(copy_page['id']) if copy_page else []
    
    if orig_folio:
        orig_filtered = [l for l in orig_lines if not l.get('folio') or orig_folio in l.get('folio')]
        if orig_filtered: orig_lines = orig_filtered

    if copy_folio:
        copy_filtered = [l for l in copy_lines if not l.get('folio') or copy_folio in l.get('folio')]
        if copy_filtered: copy_lines = copy_filtered

    if only_person:
        orig_lines = [l for l in orig_lines if l.get('entity_type') == 'person']
        copy_lines = [l for l in copy_lines if l.get('entity_type') == 'person']

    def clean_key(text):
        t = re.sub(r'^(кѵр|кир|кѷр)\s+', '', text.strip(), flags=re.IGNORECASE)
        return normalize_slavic_text(t)

    orig_keys = [clean_key(l['text']) for l in orig_lines]
    copy_keys = [clean_key(l['text']) for l in copy_lines]

    matcher = difflib.SequenceMatcher(None, orig_keys, copy_keys)
    aligned_rows = []

    for tag, i1, i2, j1, j2 in matcher.get_opcodes():
        if tag == 'equal':
            for o_idx, c_idx in zip(range(i1, i2), range(j1, j2)):
                aligned_rows.append({
                    'orig': orig_lines[o_idx],
                    'copy': copy_lines[c_idx],
                    'orig_page_id': orig_page['id'] if orig_page else '',
                    'copy_page_id': copy_page['id'] if copy_page else '',
                    'status': 'match'
                })
        elif tag == 'replace':
            max_sub = max(i2 - i1, j2 - j1)
            for step in range(max_sub):
                o_l = orig_lines[i1 + step] if (i1 + step) < i2 else None
                c_l = copy_lines[j1 + step] if (j1 + step) < j2 else None
                aligned_rows.append({
                    'orig': o_l,
                    'copy': c_l,
                    'orig_page_id': orig_page['id'] if orig_page else '',
                    'copy_page_id': copy_page['id'] if copy_page else '',
                    'status': 'diff'
                })
        elif tag == 'delete':
            for o_idx in range(i1, i2):
                aligned_rows.append({
                    'orig': orig_lines[o_idx],
                    'copy': None,
                    'orig_page_id': orig_page['id'] if orig_page else '',
                    'copy_page_id': copy_page['id'] if copy_page else '',
                    'status': 'omitted_in_copy'
                })
        elif tag == 'insert':
            for c_idx in range(j1, j2):
                aligned_rows.append({
                    'orig': None,
                    'copy': copy_lines[c_idx],
                    'orig_page_id': orig_page['id'] if orig_page else '',
                    'copy_page_id': copy_page['id'] if copy_page else '',
                    'status': 'added_in_copy'
                })
            
    return jsonify({
        'orig_folio': orig_folio,
        'copy_folio': copy_folio,
        'aligned_rows': aligned_rows
    })

from markdown.extensions.toc import slugify_unicode

@main_bp.route('/docs/<doc_name>')
def show_docs(doc_name):
    """Відображає файли документації з повною підтримкою кириличних якорів та виносок."""
    doc_path = os.path.join(BASE_DIR, 'docs', f"{doc_name}.md")
    if not os.path.exists(doc_path):
        return f"Документ {doc_name}.md не знайдено", 404
        
    with open(doc_path, 'r', encoding='utf-8') as f:
        md_text = f.read()
        
    # Увімкнено підтримку українських/македонських літер у посиланнях змісту
    html_content = markdown.markdown(
        md_text, 
        extensions=['tables', 'fenced_code', 'toc', 'footnotes'],
        extension_configs={
            'toc': {
                'slugify': slugify_unicode
            }
        }
    )
    return render_template('doc_page.html', content=html_content)