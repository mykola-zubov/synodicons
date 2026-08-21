import os
import re
import json
import shutil
import tempfile
import glob
import unicodedata
from datetime import datetime
from lxml import etree

NS = {'tei': 'http://tei-c.org'}

def sanitize_lemma(text: str) -> str:
    """Очищає лему від пробілів та випадкових латинських літер-двійників (гомогліфів)."""
    if not text:
        return ""
    text = unicodedata.normalize('NFC', text.strip())
    homoglyphs = {
        'A': 'А', 'B': 'В', 'E': 'Е', 'K': 'К', 'M': 'М', 'H': 'Н',
        'O': 'О', 'P': 'Р', 'C': 'С', 'T': 'Т', 'X': 'Х',
        'a': 'а', 'e': 'е', 'o': 'о', 'p': 'р', 'c': 'с', 'x': 'х', 'y': 'у', 'i': 'і'
    }
    cleaned = "".join(homoglyphs.get(ch, ch) for ch in text)
    return cleaned[0].upper() + cleaned[1:] if len(cleaned) > 0 else cleaned

def normalize_slavic_text(text: str) -> str:
    """Нормалізує середньовічну південнослов'янську орфографію для пошуку та сортування."""
    if not text:
        return ""
    text = text.lower().strip()
    text = re.sub(r'[\u0300-\u036F\u0483-\u0489\u2e2f\':~.~+,\-–—\(\)\[\]]', '', text)
    replacements = {
        'ѡ': 'о', 'ѿ': 'от', 'ѣ': 'е', 'є': 'е', 'і': 'и',
        'ї': 'и', 'ѵ': 'и', 'ѷ': 'и', 'ы': 'и', 'й': 'и',
        'ꙗ': 'я', 'ѧ': 'я', 'ѩ': 'я', 'ѫ': 'у', 'ꙋ': 'у',
        'ѳ': 'ф', 'ѕ': 'з', 'ѯ': 'кс', 'ѱ': 'пс', 'ъ': '', 'ь': '', 'ј': 'й'
    }
    for char, repl in replacements.items():
        text = text.replace(char, repl)
    return text

def extract_status_and_role(node):
    """Відокремлює статус/титул від імені та автодетектує роль і стать."""
    status_text = ""
    clean_text = ""
    auto_role = ""
    auto_gender = ""
    if node is None:
        return clean_text, status_text, auto_role, auto_gender

    status_nodes = node.xpath('.//*[local-name()="status"]')
    if not status_nodes and node.tag.split('}')[-1] == 'status':
        status_nodes = [node]

    if status_nodes:
        status_node = status_nodes[0]
        status_text = "".join(status_node.itertext()).strip()
        text_parts = []
        for t in node.xpath('.//text()'):
            parent = t.getparent()
            if parent is not None and parent.tag.split('}')[-1] != 'status':
                text_parts.append(t)
        clean_text = "".join(text_parts).strip()
    else:
        clean_text = "".join(node.itertext()).strip()

    st_lower = status_text.lower()
    if any(w in st_lower for w in ['ере', 'поп', 'папа', 'архїеп', 'архиеп', 'протопоп', 'протосинкел']):
        auto_role = 'clergy'
        auto_gender = '1'
    elif any(w in st_lower for w in ['монах', 'мних', 'игумен', 'їгꙋмен', 'калоѵгер', 'іеромонах']):
        auto_role = 'monk'
        auto_gender = '1'
    elif any(w in st_lower for w in ['монахин', 'калоугриц']):
        auto_role = 'monk'
        auto_gender = '2'
    elif any(w in st_lower for w in ['цар', 'крал', 'деспот', 'кнез', 'бан', 'воивод']):
        auto_role = 'ruler'
        auto_gender = '1'
    elif any(w in st_lower for w in ['цариц', 'кралиц', 'деспин']):
        auto_role = 'ruler'
        auto_gender = '2'

    return clean_text, status_text, auto_role, auto_gender


class XmlProcessor:
    def __init__(self, xml_path, max_backups=50):
        self.xml_path = xml_path
        self.max_backups = max_backups
        self.backup_dir = os.path.join(os.path.dirname(self.xml_path), 'backups')
        self.tree = None
        self.root = None
        self.structure = self._load_structure()
        self.load_xml()
        self._ensure_initial_backup()

    def _load_structure(self):
        struct_path = os.path.join(os.path.dirname(self.xml_path), 'codex_structure.json')
        if os.path.exists(struct_path):
            try:
                with open(struct_path, 'r', encoding='utf-8') as f:
                    return json.load(f)
            except Exception as e:
                print(f"[ERROR] Не вдалося завантажити codex_structure.json: {e}")
        return {"sections": [], "categories": {}, "parallel_concordance": [], "page_overrides": {}}

    def load_xml(self):
        if os.path.exists(self.xml_path):
            parser = etree.XMLParser(remove_blank_text=False)
            self.tree = etree.parse(self.xml_path, parser)
            self.root = self.tree.getroot()
        else:
            raise FileNotFoundError(f"Файл {self.xml_path} не знайдено.")

    def _ensure_initial_backup(self):
        os.makedirs(self.backup_dir, exist_ok=True)
        existing_backups = glob.glob(os.path.join(self.backup_dir, "*.xml"))
        if not existing_backups and os.path.exists(self.xml_path):
            self._create_backup(prefix="initial_backup")

    def _create_backup(self, prefix="backup"):
        if not os.path.exists(self.xml_path):
            return
        os.makedirs(self.backup_dir, exist_ok=True)
        timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
        base_name = os.path.splitext(os.path.basename(self.xml_path))[0]
        backup_filename = f"{base_name}_{prefix}_{timestamp}.xml"
        backup_filepath = os.path.join(self.backup_dir, backup_filename)
        try:
            shutil.copy2(self.xml_path, backup_filepath)
        except Exception as e:
            print(f"[BACKUP ERROR] {e}")
        self._prune_old_backups()

    def _prune_old_backups(self):
        backups = sorted(glob.glob(os.path.join(self.backup_dir, "*.xml")), key=os.path.getmtime)
        while len(backups) > self.max_backups:
            oldest_file = backups.pop(0)
            try:
                os.remove(oldest_file)
            except Exception:
                pass

    def _get_folio_num(self, folio_str):
        m = re.search(r'\d+', str(folio_str))
        return int(m.group(0)) if m else 0

    def _resolve_image_filename(self, raw_img):
        """Автоматично знаходить файл зображення на диску."""
        if not raw_img:
            return None
        
        folder_name = os.path.basename(os.path.dirname(self.xml_path))
        base_dir = os.path.dirname(os.path.dirname(os.path.dirname(self.xml_path)))
        target_dir = os.path.join(base_dir, 'app', 'static', 'images', folder_name)

        if not os.path.exists(target_dir):
            return raw_img

        # 1. Прямий збіг
        if os.path.exists(os.path.join(target_dir, raw_img)):
            return raw_img

        # 2. Пошук файлу за номером
        clean_num = os.path.splitext(raw_img)[0].lstrip('0') or '0'
        for fname in os.listdir(target_dir):
            if fname.lower().endswith(f"_{raw_img.lower()}"):
                return fname
            parts = os.path.splitext(fname)[0].split('_')
            if len(parts) > 1 and parts[-1].lstrip('0') == clean_num:
                return fname

        return raw_img

    def get_pages_list(self):
        pages = []
        surfaces = self.root.xpath('//*[local-name()="surface"]')
        overrides = self.structure.get('page_overrides', {})
        seen_ids = set()

        for surf in surfaces:
            page_id = surf.get('{http://www.w3.org/XML/1998/namespace}id') or \
                      surf.get('{http://w3.org}id') or \
                      surf.get('id') or \
                      surf.get('xml:id')
            
            if not page_id:
                for k, v in surf.attrib.items():
                    if 'id' in k.lower():
                        page_id = v
                        break

            graphic = surf.xpath('.//*[local-name()="graphic"]')
            raw_img_url = graphic[0].get('url') if graphic else None
            img_url = self._resolve_image_filename(raw_img_url)
            
            text_regions = surf.xpath('.//*[local-name()="zone"][@rendition="TextRegion"]')
            subtypes = []
            for tr in text_regions:
                st = tr.get('subtype')
                if st and st not in subtypes:
                    subtypes.append(st)
            
            if len(subtypes) > 1:
                label = f"{subtypes[0]}–{subtypes[-1]}"
            elif len(subtypes) == 1:
                label = subtypes[0]
            else:
                label = page_id.replace('facs_', 'Лист ') if page_id else "Без номера"
            
            f_num = self._get_folio_num(label)

            if page_id in overrides:
                label = overrides[page_id].get('label', label)
                f_num = overrides[page_id].get('folio_num', f_num)
                if overrides[page_id].get('image'):
                    img_url = self._resolve_image_filename(overrides[page_id]['image'])
            elif label in overrides:
                target_label = overrides[label].get('label', label)
                f_num = overrides[label].get('folio_num', self._get_folio_num(target_label))
                label = target_label
            
            if page_id and page_id not in seen_ids:
                seen_ids.add(page_id)
                pages.append({
                    'id': page_id, 
                    'image': img_url,
                    'label': label,
                    'folio_num': f_num
                })

        for pid, pdata in overrides.items():
            if pid.startswith('extra_') and pid not in seen_ids:
                seen_ids.add(pid)
                pages.append({
                    'id': pid,
                    'image': self._resolve_image_filename(pdata.get('image', f"{pid}.jpg")),
                    'label': pdata.get('label', pid),
                    'folio_num': pdata.get('folio_num', self._get_folio_num(pdata.get('label', '1')))
                })

        pages.sort(key=lambda x: (x['folio_num'], x['id']))
        return pages

    def get_page_data(self, page_id):
        """Суворо ізолює рядки кожної окремої сторінки між її <pb> та наступним <pb>."""
        lines_data = []
        geo_map = {}
        folio_map = {}
        
        # 1. Знаходимо surface поточної сторінки
        current_surface = None
        for surf in self.root.xpath('//*[local-name()="surface"]'):
            s_id = surf.get('{http://www.w3.org/XML/1998/namespace}id') or surf.get('id') or surf.get('xml:id')
            if s_id == page_id:
                current_surface = surf
                break

        if current_surface is not None:
            for tr in current_surface.xpath('.//*[local-name()="zone"][@rendition="TextRegion"]'):
                tr_subtype = tr.get('subtype') or ''
                for zone in tr.xpath('.//*[local-name()="zone"][@rendition="Line"]'):
                    z_id = zone.get('{http://www.w3.org/XML/1998/namespace}id') or zone.get('id') or zone.get('xml:id')
                    points_str = zone.get('points')
                    if z_id:
                        geo_map[z_id] = self._parse_points(points_str)
                        if tr_subtype:
                            folio_map[z_id] = tr_subtype

            for zone in current_surface.xpath('.//*[local-name()="zone"][@rendition="Line"]'):
                z_id = zone.get('{http://www.w3.org/XML/1998/namespace}id') or zone.get('id') or zone.get('xml:id')
                if z_id and z_id not in geo_map:
                    geo_map[z_id] = self._parse_points(zone.get('points'))

        # 2. Знаходимо цільовий <pb> для цієї сторінки
        pb_list = self.root.xpath('//*[local-name()="pb"]')
        target_pb = None
        for pb in pb_list:
            facs_ref = (pb.get('facs') or '').replace('#', '')
            if facs_ref == page_id:
                target_pb = pb
                break

        # Якщо для цієї сторінки немає <pb> (наприклад, порожня обкладинка чи скан без рядків) — повертаємо 0 рядків!
        if target_pb is None:
            return lines_data

        # 3. Збираємо ТІЛЬКИ ті <lb>, які йдуть строго після target_pb до наступного <pb>
        valid_lbs = []
        started = False
        for el in self.root.xpath('//*[local-name()="pb" or local-name()="lb"]'):
            tag = el.tag.split('}')[-1]
            if tag == 'pb':
                if el == target_pb:
                    started = True
                elif started:
                    # Дійшли до наступного <pb> — зупиняємось!
                    break
            elif tag == 'lb' and started:
                valid_lbs.append(el)

        # 4. Обробляємо лише справжні рядки цієї сторінки
        for lb in valid_lbs:
            facs_ref = (lb.get('facs') or '').replace('#', '')
            line_number = lb.get('n') or "—"
            if not facs_ref:
                continue

            entity_type = "Текст"
            entity_text = ""
            status_title = ""
            lemma = ""
            gender = ""
            status_role = ""
            hand_layer = "primary"
            is_duplicate = False

            sibling = lb.getnext()
            target_node = sibling
            
            if sibling is not None and sibling.tag.split('}')[-1] in ['name', 'unclear', 'add']:
                child = sibling.xpath('.//*[local-name()="rs"]')
                if child:
                    target_node = child[0]

            if target_node is not None:
                tag_name = target_node.tag.split('}')[-1]
                entity_type = target_node.get('type') or tag_name
                
                clean_text, status_title, auto_role, auto_gender = extract_status_and_role(target_node)
                entity_text = clean_text or "".join(target_node.itertext()).strip()
                lemma = target_node.get('lemma', '')
                gender = target_node.get('sex', '') or auto_gender
                status_role = target_node.get('role', '') or auto_role

                raw_hand = (target_node.get('hand') or (sibling.get('hand') if sibling is not None else '') or '')
                if raw_hand:
                    hand_layer = raw_hand.replace('#', '')
                elif sibling is not None and sibling.tag.split('}')[-1] == 'add':
                    hand_layer = 'secondary'

                ana_attr = (target_node.get('ana') or (sibling.get('ana') if sibling is not None else '') or '')
                dup_attr = target_node.get('duplicate') or ''
                if '#duplicate' in str(ana_attr) or str(dup_attr).lower() == 'true':
                    is_duplicate = True

            if not entity_text:
                entity_text = (lb.tail or "").strip()

            line_folio = folio_map.get(facs_ref, "")

            lines_data.append({
                'line_id': facs_ref,
                'folio': line_folio,
                'line_number': line_number,
                'coordinates': geo_map.get(facs_ref, {'x': 0, 'y': 0, 'width': 0, 'height': 0}),
                'entity_type': entity_type,
                'status_title': status_title,
                'text': entity_text,
                'lemma': lemma,
                'gender': gender,
                'role': status_role,
                'hand': hand_layer,
                'is_duplicate': is_duplicate
            })
        return lines_data

    def update_entity(self, page_id, line_id, data):
        """Оновлює текст, наукові атрибути, TEI @hand та TEI @ana='#duplicate'."""
        pb_elements = self.root.xpath(f'//*[local-name()="pb"][@facs="#{page_id}" or @facs="{page_id}"]')
        if not pb_elements:
            return False
            
        lb_elements = pb_elements[0].xpath(f'./following-sibling::*//*[local-name()="lb"][@facs="#{line_id}" or @facs="{line_id}"]')
        if not lb_elements:
            lb_elements = self.root.xpath(f'//*[local-name()="lb"][@facs="#{line_id}" or @facs="{line_id}"]')
            if not lb_elements:
                return False
            
        lb = lb_elements[0]
        sibling = lb.getnext()
        
        target_rs = None
        is_existing_entity = False

        if sibling is not None and sibling.tag.split('}')[-1] in ['rs', 'name', 'unclear', 'placeName', 'persName', 'add']:
            is_existing_entity = True
            child = sibling.xpath('.//*[local-name()="rs"]')
            target_rs = child[0] if child else sibling

        new_entity_type = data.get('entity_type', 'person')

        if not is_existing_entity:
            raw_text = data.get('text') or (lb.tail or '').strip()
            lb.tail = '\n'
            new_rs = etree.Element('rs')
            new_rs.set('type', new_entity_type)
            new_rs.text = raw_text
            lb.addnext(new_rs)
            target_rs = new_rs
        else:
            if target_rs.tag.split('}')[-1] == 'rs':
                target_rs.set('type', new_entity_type)
            elif new_entity_type == 'unclear':
                target_rs.tag = 'unclear'
            else:
                target_rs.tag = 'rs'
                target_rs.set('type', new_entity_type)

        if target_rs is not None:
            if data.get('text') is not None and data['text'].strip() != "":
                new_text = data['text'].strip()
                status_nodes = target_rs.xpath('.//*[local-name()="status"]')
                if status_nodes:
                    status_nodes[0].tail = " " + new_text
                else:
                    target_rs.text = new_text

            if data.get('lemma') is not None:
                clean_l = sanitize_lemma(data['lemma'])
                if clean_l: target_rs.set('lemma', clean_l)
                elif 'lemma' in target_rs.attrib: del target_rs.attrib['lemma']
                    
            if data.get('gender') is not None:
                if data['gender']: target_rs.set('sex', data['gender'])
                elif 'sex' in target_rs.attrib: del target_rs.attrib['sex']
                    
            if data.get('role') is not None:
                if data['role']: target_rs.set('role', data['role'])
                elif 'role' in target_rs.attrib: del target_rs.attrib['role']

            if data.get('hand') is not None:
                h_val = data['hand'].strip()
                if h_val:
                    target_rs.set('hand', f"#{h_val}" if not h_val.startswith('#') else h_val)
                elif 'hand' in target_rs.attrib:
                    del target_rs.attrib['hand']

            if 'is_duplicate' in data:
                if data['is_duplicate']:
                    target_rs.set('ana', '#duplicate')
                elif 'ana' in target_rs.attrib:
                    ana_val = target_rs.get('ana', '').replace('#duplicate', '').strip()
                    if ana_val: target_rs.set('ana', ana_val)
                    else: del target_rs.attrib['ana']
            
            return self.save_xml()
        return False

    def set_duplicate_status(self, page_id, line_id, is_dup: bool):
        return self.update_entity(page_id, line_id, {'is_duplicate': is_dup})

    def batch_update_entities(self, target_text, data):
        if not target_text:
            return 0
        target_clean = target_text.strip()
        updated_count = 0
        clean_lemma = sanitize_lemma(data.get('lemma', ''))

        nodes = self.root.xpath('//*[local-name()="rs" or local-name()="name"]')
        for el in nodes:
            clean_text, _, _, _ = extract_status_and_role(el)
            text = clean_text or "".join(el.itertext()).strip()
            
            if text == target_clean:
                if clean_lemma: el.set('lemma', clean_lemma)
                if data.get('gender') is not None and data['gender']:
                    el.set('sex', data['gender'])
                if data.get('role') is not None and data['role']:
                    el.set('role', data['role'])
                updated_count += 1

        if updated_count > 0:
            self.save_xml()

        return updated_count

    def _parse_points(self, points_str):
        if not points_str:
            return {'x': 0, 'y': 0, 'width': 0, 'height': 0}
        try:
            pairs = points_str.strip().split()
            x_coords = [int(p.split(',')[0]) for p in pairs]
            y_coords = [int(p.split(',')[1]) for p in pairs]
            x_min, x_max = min(x_coords), max(x_coords)
            y_min, y_max = min(y_coords), max(y_coords)
            return {'x': x_min, 'y': y_min, 'width': x_max - x_min, 'height': y_max - y_min}
        except Exception:
            return {'x': 0, 'y': 0, 'width': 0, 'height': 0}

    def save_xml(self):
        self._create_backup()
        dir_name = os.path.dirname(self.xml_path) or '.'
        temp_file = None
        try:
            with tempfile.NamedTemporaryFile('wb', dir=dir_name, delete=False) as tf:
                temp_file = tf.name
                self.tree.write(tf, encoding='UTF-8', xml_declaration=True, pretty_print=False)
            os.replace(temp_file, self.xml_path)
            return True
        except Exception as e:
            print(f"[SAVE ERROR] {e}")
            if temp_file and os.path.exists(temp_file):
                os.remove(temp_file)
            return False

    def global_search(self, query):
        results = []
        if not query:
            return results
            
        raw_query = query.lower().strip()
        norm_query = normalize_slavic_text(query)
        
        def make_pattern(q):
            rq = re.escape(q).replace(r'\*', '.*').replace(r'\?', '.')
            return re.compile(rq, re.IGNORECASE)

        raw_pattern = make_pattern(raw_query)
        norm_pattern = make_pattern(norm_query) if norm_query else None

        pages_map = {p['id']: p['label'] for p in self.get_pages_list()}
        current_parent_surface_id = None
        
        for element in self.root.iter():
            local_name = element.tag.split('}')[-1]
            if local_name == "pb":
                current_parent_surface_id = (element.get('facs') or '').replace('#', '')
                continue
                
            elif local_name == "lb":
                if not current_parent_surface_id:
                    continue
                    
                facs_ref = (element.get('facs') or '').replace('#', '')
                line_number = element.get('n') or "—"
                if not facs_ref:
                    continue

                sibling_node = element.getnext()
                if sibling_node is not None and sibling_node.tag.split('}')[-1] in ['name', 'unclear', 'add']:
                    child = sibling_node.xpath('.//*[local-name()="rs"]')
                    if child: 
                        sibling_node = child[0]

                if sibling_node is not None:
                    clean_text, status_title, _, _ = extract_status_and_role(sibling_node)
                    text_raw = clean_text or "".join(sibling_node.itertext()).strip()
                    lemma = sibling_node.get('lemma', '')
                    entity_type = sibling_node.get('type') or sibling_node.tag.split('}')[-1]
                    
                    if not text_raw:
                        text_raw = (element.tail or "").strip()

                    text_norm = normalize_slavic_text(text_raw)
                    lemma_norm = normalize_slavic_text(lemma)
                    status_norm = normalize_slavic_text(status_title)

                    is_match = raw_pattern.search(text_raw.lower()) or raw_pattern.search(lemma.lower()) or raw_pattern.search(status_title.lower())
                    if not is_match and norm_pattern:
                        is_match = norm_pattern.search(text_norm) or norm_pattern.search(lemma_norm) or norm_pattern.search(status_norm)

                    if is_match:
                        results.append({
                            'page_id': current_parent_surface_id,
                            'page_label': pages_map.get(current_parent_surface_id, current_parent_surface_id),
                            'line_id': facs_ref,
                            'line_number': line_number,
                            'status_title': status_title,
                            'text': text_raw,
                            'lemma': lemma,
                            'entity_type': entity_type
                        })
                        
        return results

    def get_lemmas_dict(self):
        lemmas_map = {}
        elements = self.root.xpath('//*[@lemma]')
        for el in elements:
            raw_l = el.get('lemma') or ''
            clean_l = sanitize_lemma(raw_l)
            sex = (el.get('sex') or '').strip()
            if clean_l:
                if clean_l not in lemmas_map or (sex and not lemmas_map[clean_l]):
                    lemmas_map[clean_l] = sex

        macedonian_base_names = {
            'Аврам': '1', 'Адам': '1', 'Алекса': '1', 'Александар': '1', 'Алексиј': '1', 
            'Андон': '1', 'Андреј': '1', 'Атанас': '1', 'Богдан': '1', 'Богоја': '1', 
            'Божин': '1', 'Борис': '1', 'Ботоја': '1', 'Васил': '1', 'Велко': '1', 
            'Видан': '1', 'Владимир': '1', 'Влче': '1', 'Влко': '1', 'Влкан': '1', 
            'Георги': '1', 'Ѓорѓи': '1', 'Ѓоре': '1', 'Дабижив': '1', 'Дамјан': '1', 
            'Димитар': '1', 'Димо': '1', 'Дојчин': '1', 'Драган': '1', 'Душан': '1', 
            'Захариј': '1', 'Иван': '1', 'Илија': '1', 'Јаков': '1', 'Јован': '1', 
            'Кирил': '1', 'Климент': '1', 'Константин': '1', 'Костадин': '1', 'Крсте': '1', 
            'Кузман': '1', 'Лазар': '1', 'Маноил': '1', 'Марко': '1', 'Миле': '1', 
            'Митре': '1', 'Михаил': '1', 'Младен': '1', 'Наум': '1', 'Неделко': '1', 
            'Никола': '1', 'Новак': '1', 'Огнен': '1', 'Оливер': '1', 'Павле': '1', 
            'Пејо': '1', 'Петар': '1', 'Петко': '1', 'Петре': '1', 'Продан': '1', 
            'Раде': '1', 'Радослав': '1', 'Рале': '1', 'Ристе': '1', 'Сава': '1', 
            'Спасе': '1', 'Стале': '1', 'Станко': '1', 'Стефан': '1', 'Степан': '1', 
            'Стојан': '1', 'Танас': '1', 'Тодор': '1', 'Трајан': '1', 'Трајко': '1', 
            'Трпе': '1', 'Трифун': '1', 'Филип': '1', 'Христо': '1', 'Цветко': '1',
            'Ана': '2', 'Анастасија': '2', 'Ангелина': '2', 'Богдана': '2', 'Боја': '2', 
            'Васила': '2', 'Вела': '2', 'Велика': '2', 'Вида': '2', 'Владислава': '2', 
            'Гина': '2', 'Грозда': '2', 'Ѓурга': '2', 'Дафина': '2', 'Деспина': '2', 
            'Димитра': '2', 'Добра': '2', 'Дојка': '2', 'Драгана': '2', 'Евдокија': '2', 
            'Елена': '2', 'Елица': '2', 'Ерина': '2', 'Злата': '2', 'Зора': '2', 
            'Ивана': '2', 'Ирина': '2', 'Јана': '2', 'Јована': '2', 'Калина': '2', 
            'Кала': '2', 'Кира': '2', 'Кирана': '2', 'Комна': '2', 'Магда': '2', 
            'Манислава': '2', 'Мара': '2', 'Марија': '2', 'Мила': '2', 'Милена': '2', 
            'Милица': '2', 'Милка': '2', 'Митра': '2', 'Младена': '2', 'Неда': '2', 
            'Неделка': '2', 'Оливера': '2', 'Пеја': '2', 'Пејка': '2', 'Петра': '2', 
            'Петка': '2', 'Рада': '2', 'Радослава': '2', 'Роса': '2', 'Ружа': '2', 
            'Руса': '2', 'Стана': '2', 'Станка': '2', 'Стоја': '2', 'Стојанка': '2', 
            'Стојна': '2', 'Стојка': '2', 'Теодора': '2', 'Тода': '2', 'Цвета': '2'
        }
        for name, gender in macedonian_base_names.items():
            clean_name = sanitize_lemma(name)
            if clean_name not in lemmas_map:
                lemmas_map[clean_name] = gender

        return [{'lemma': k, 'gender': v} for k, v in sorted(lemmas_map.items(), key=lambda x: x[0].lower())]

    def export_dataset(self, deduplicate=False):
        dataset = []
        pages = self.get_pages_list()
        
        gender_labels = {'1': 'чол.', '2': 'жін.'}
        role_labels = {
            'clergy': 'священнослужитель', 'monk': 'монах', 
            'soldier': 'воїн', 'ruler': 'правитель', 'layperson': 'мирянин', '': 'визначити'
        }
        hand_labels = {
            'h1': 'Первинний (#h1)', 'primary': 'Первинний (#h1)',
            'h2': 'Приписка (#h2)', 'secondary': 'Приписка (#h2)'
        }

        sec_dict = {s['id']: s for s in self.structure.get('sections', [])}
        cat_dict = self.structure.get('categories', {})

        for p in pages:
            f_num = p['folio_num']
            current_sec = None
            for s in self.structure.get('sections', []):
                if s['folio_start_num'] <= f_num <= s['folio_end_num']:
                    current_sec = s
                    break
            
            cat_key = current_sec['category'] if current_sec else 'male_orig'
            cat_info = cat_dict.get(cat_key, {})
            
            if deduplicate and not cat_info.get('count_in_deduplication', True):
                continue

            lines = self.get_page_data(p['id'])
            for l in lines:
                if deduplicate and l.get('is_duplicate'):
                    continue

                exact_folio = l.get('folio') or p['label']
                raw_h = (l.get('hand') or 'primary').replace('#', '')

                dataset.append({
                    'page_id': p['id'],
                    'page_label': exact_folio,
                    'line_id': l['line_id'],
                    'line_number': l['line_number'],
                    'status_title': l.get('status_title', ''),
                    'text': l['text'],
                    'entity_type': l['entity_type'],
                    'lemma': l['lemma'],
                    'gender': gender_labels.get(l['gender'], l['gender']),
                    'role': role_labels.get(l['role'], l['role']),
                    'hand': hand_labels.get(raw_h, raw_h),
                    'is_duplicate': l.get('is_duplicate', False),
                    'codex_section': current_sec['title'] if current_sec else 'Оригінальний корпус'
                })
        return dataset

    def generate_anthroponyms_dictionary(self):
        dataset = self.export_dataset(deduplicate=False)
        lemmas_dict = {}

        for row in dataset:
            if row['entity_type'] != 'person':
                continue
            
            if row.get('is_duplicate'):
                continue

            lemma = row['lemma'] or row['text']
            lemma = sanitize_lemma(lemma)
            if not lemma:
                continue

            if lemma not in lemmas_dict:
                lemmas_dict[lemma] = {
                    'lemma': lemma,
                    'gender': row['gender'],
                    'total_count': 0,
                    'h1_count': 0,
                    'h2_count': 0,
                    'variants': {}
                }

            entry = lemmas_dict[lemma]
            entry['total_count'] += 1
            
            h_val = str(row.get('hand', '')).lower()
            if 'h1' in h_val or 'первинний' in h_val:
                entry['h1_count'] += 1
            else:
                entry['h2_count'] += 1

            var_text = row['text']
            if var_text not in entry['variants']:
                entry['variants'][var_text] = []
            entry['variants'][var_text].append(row['page_label'])

        result = []
        for lemma, data in sorted(lemmas_dict.items(), key=lambda x: normalize_slavic_text(x[0])):
            var_strings = []
            for var, folios in sorted(data['variants'].items(), key=lambda v: len(v[1]), reverse=True):
                uniq_folios = list(dict.fromkeys(folios))
                folios_str = ", ".join(uniq_folios[:8])
                if len(uniq_folios) > 8:
                    folios_str += f" та ще {len(uniq_folios)-8}"
                var_strings.append(f"{var} ({len(folios)}) [{folios_str}]")

            result.append({
                'lemma': data['lemma'],
                'gender': data['gender'],
                'total_count': data['total_count'],
                'h1_count': data['h1_count'],
                'h2_count': data['h2_count'],
                'variants_summary': "; ".join(var_strings)
            })

        return result

    def generate_toponyms_dictionary(self):
        dataset = self.export_dataset(deduplicate=False)
        toponyms_dict = {}

        for row in dataset:
            if row['entity_type'] != 'place':
                continue

            toponym = row['lemma'] or row['text']
            toponym = sanitize_lemma(toponym)
            if not toponym:
                continue

            if toponym not in toponyms_dict:
                toponyms_dict[toponym] = {
                    'toponym': toponym,
                    'total_count': 0,
                    'variants': {}
                }

            entry = toponyms_dict[toponym]
            entry['total_count'] += 1

            var_text = row['text']
            if var_text not in entry['variants']:
                entry['variants'][var_text] = []
            entry['variants'][var_text].append(row['page_label'])

        result = []
        for toponym, data in sorted(toponyms_dict.items(), key=lambda x: normalize_slavic_text(x[0])):
            var_strings = []
            all_folios = []
            for var, folios in sorted(data['variants'].items(), key=lambda v: len(v[1]), reverse=True):
                uniq_f = list(dict.fromkeys(folios))
                var_strings.append(f"{var} ({len(folios)})")
                all_folios.extend(uniq_f)

            uniq_all_folios = list(dict.fromkeys(all_folios))

            result.append({
                'toponym': data['toponym'],
                'total_count': data['total_count'],
                'variants_summary': ", ".join(var_strings),
                'folios_list': ", ".join(uniq_all_folios)
            })

        return result

    def get_statistics(self, deduplicate=False):
        dataset = self.export_dataset(deduplicate=deduplicate)
        total_items = len(dataset)
        
        lemmatized_count = sum(1 for item in dataset if item['lemma'])
        male_count = sum(1 for item in dataset if '1' in item['gender'] or 'чол' in str(item['gender']))
        female_count = sum(1 for item in dataset if '2' in item['gender'] or 'жін' in str(item['gender']))
        
        lemmas_counter = {}
        for item in dataset:
            l = item['lemma']
            if l:
                lemmas_counter[l] = lemmas_counter.get(l, 0) + 1
                
        top_lemmas = sorted(lemmas_counter.items(), key=lambda x: x[1], reverse=True)[:10]
        
        return {
            'total_items': total_items,
            'lemmatized_count': lemmatized_count,
            'progress_percent': round((lemmatized_count / total_items * 100), 1) if total_items > 0 else 0,
            'male_count': male_count,
            'female_count': female_count,
            'top_lemmas': top_lemmas,
            'is_deduplicated': deduplicate
        }