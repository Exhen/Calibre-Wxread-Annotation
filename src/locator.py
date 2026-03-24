from __future__ import annotations

import html
import re
import xml.etree.ElementTree as ET
import zipfile
from io import BytesIO
from pathlib import PurePosixPath


WS_RE = re.compile(r'\s+')
SCRIPT_STYLE_RE = re.compile(r'(?is)<(script|style)\b[^>]*>.*?</\1>')
TAG_RE = re.compile(r'(?is)<[^>]+>')

# 单条标注在全书中最多保留的匹配候选数（避免极短原文导致海量命中）
MAX_ANNOTATION_MATCHES = 10


def _normalize_text(text: str) -> str:
    return WS_RE.sub(' ', (text or '')).strip()


def _html_to_plain_text(src: str) -> str:
    src = SCRIPT_STYLE_RE.sub(' ', src)
    src = TAG_RE.sub(' ', src)
    src = html.unescape(src)
    return _normalize_text(src)


def _ns(tag: str) -> str:
    return '{urn:oasis:names:tc:opendocument:xmlns:container}' + tag


def _opf_ns(tag: str) -> str:
    return '{http://www.idpf.org/2007/opf}' + tag


def _resolve_href(base: PurePosixPath, href: str) -> str:
    return str((base / href.split('#', 1)[0]).as_posix())


def _read_ncx_toc_map(zf: zipfile.ZipFile, ncx_path: str) -> dict[str, list[str]]:
    toc_map: dict[str, list[str]] = {}
    try:
        root = ET.fromstring(zf.read(ncx_path))
    except Exception:
        return toc_map

    ns = {'n': 'http://www.daisy.org/z3986/2005/ncx/'}
    base = PurePosixPath(ncx_path).parent

    def walk(nav_point, trail: list[str]):
        text_el = nav_point.find('./n:navLabel/n:text', ns)
        label = (text_el.text or '').strip() if text_el is not None else ''
        new_trail = trail + ([label] if label else [])

        content_el = nav_point.find('./n:content', ns)
        if content_el is not None:
            src = content_el.attrib.get('src', '')
            if src:
                key = _resolve_href(base, src)
                if key not in toc_map and new_trail:
                    toc_map[key] = new_trail

        for child in nav_point.findall('./n:navPoint', ns):
            walk(child, new_trail)

    nav_map = root.find('.//n:navMap', ns)
    if nav_map is None:
        return toc_map
    for np in nav_map.findall('./n:navPoint', ns):
        walk(np, [])
    return toc_map


def _read_toc_map(opf_root, opf_base: PurePosixPath, manifest: dict[str, str], zf: zipfile.ZipFile) -> dict[str, list[str]]:
    toc_map: dict[str, list[str]] = {}
    spine_el = opf_root.find(_opf_ns('spine'))
    if spine_el is None:
        return toc_map

    # EPUB2: <spine toc="ncx-id">
    toc_id = spine_el.attrib.get('toc')
    if toc_id and toc_id in manifest:
        toc_map.update(_read_ncx_toc_map(zf, manifest[toc_id]))

    # 兜底：扫描 manifest 里的 ncx 文件
    if not toc_map:
        manifest_el = opf_root.find(_opf_ns('manifest'))
        if manifest_el is not None:
            for item in manifest_el.findall(_opf_ns('item')):
                if item.attrib.get('media-type') == 'application/x-dtbncx+xml':
                    href = item.attrib.get('href', '')
                    if href:
                        toc_map.update(_read_ncx_toc_map(zf, str((opf_base / href).as_posix())))
                        break
    return toc_map


def _read_epub_spine_docs(epub_bytes: bytes) -> list[tuple[int, str, str]]:
    with zipfile.ZipFile(BytesIO(epub_bytes), 'r') as zf:
        container = ET.fromstring(zf.read('META-INF/container.xml'))
        rootfile = container.find(f'.//{_ns("rootfile")}')
        if rootfile is None:
            return []
        opf_path = rootfile.attrib.get('full-path')
        if not opf_path:
            return []

        opf_root = ET.fromstring(zf.read(opf_path))
        opf_base = PurePosixPath(opf_path).parent

        manifest: dict[str, str] = {}
        manifest_el = opf_root.find(_opf_ns('manifest'))
        if manifest_el is not None:
            for item in manifest_el.findall(_opf_ns('item')):
                item_id = item.attrib.get('id')
                href = item.attrib.get('href')
                if item_id and href:
                    manifest[item_id] = str((opf_base / href).as_posix())

        spine_docs: list[tuple[int, str, str]] = []
        spine_el = opf_root.find(_opf_ns('spine'))
        if spine_el is None:
            return []
        for idx, itemref in enumerate(spine_el.findall(_opf_ns('itemref'))):
            item_idref = itemref.attrib.get('idref')
            doc_path = manifest.get(item_idref or '')
            if not doc_path:
                continue
            try:
                raw = zf.read(doc_path)
            except KeyError:
                continue
            try:
                text = raw.decode('utf-8')
            except UnicodeDecodeError:
                text = raw.decode('utf-8', errors='ignore')
            spine_docs.append((idx, doc_path, _html_to_plain_text(text)))
        return spine_docs


def _iter_text_nodes_with_cfi(elem, elem_cfi: str):
    text_ordinal = 0
    element_ordinal = 0

    if elem.text:
        yield (elem.text, f'{elem_cfi}/{2 * text_ordinal + 1}')
        text_ordinal += 1

    for child in list(elem):
        element_ordinal += 1
        child_cfi = f'{elem_cfi}/{2 * element_ordinal}'
        yield from _iter_text_nodes_with_cfi(child, child_cfi)
        if child.tail:
            yield (child.tail, f'{elem_cfi}/{2 * text_ordinal + 1}')
            text_ordinal += 1


def _normalized_stream_with_mapping(xhtml_text: str) -> tuple[str, list[tuple[str, int]]]:
    try:
        root = ET.fromstring(xhtml_text)
    except ET.ParseError:
        plain = _normalize_text(_html_to_plain_text(xhtml_text))
        mapping = [('/2/1', i) for i in range(len(plain))]
        return plain, mapping

    # Document root -> html 元素的 cfi 第一步通常是 /2
    root_cfi = '/2'
    stream_chars: list[str] = []
    mapping: list[tuple[str, int]] = []
    prev_was_space = True

    for text, cfi in _iter_text_nodes_with_cfi(root, root_cfi):
        for idx, ch in enumerate(text):
            if ch.isspace():
                if not prev_was_space:
                    stream_chars.append(' ')
                    mapping.append((cfi, idx))
                prev_was_space = True
            else:
                stream_chars.append(ch)
                mapping.append((cfi, idx))
                prev_was_space = False

    normalized = ''.join(stream_chars).strip()
    if not normalized:
        return '', []

    # 同步裁剪 mapping（与 strip 后字符串对齐）
    left = 0
    right = len(stream_chars)
    while left < right and stream_chars[left] == ' ':
        left += 1
    while right > left and stream_chars[right - 1] == ' ':
        right -= 1
    return ''.join(stream_chars[left:right]), mapping[left:right]


def _find_exact_cfi_candidates(xhtml_text: str, needle: str, max_matches: int | None = None) -> list[dict]:
    normalized_needle = _normalize_text(needle)
    if not normalized_needle:
        return []

    normalized_text, mapping = _normalized_stream_with_mapping(xhtml_text)
    if not normalized_text or not mapping:
        return []

    limit = max_matches if max_matches is not None else 1_000_000
    candidates: list[dict] = []
    start = 0
    nlen = len(normalized_needle)
    while len(candidates) < limit:
        pos = normalized_text.find(normalized_needle, start)
        if pos < 0:
            break
        end_pos = pos + nlen - 1
        start_cfi, start_off = mapping[pos]
        end_cfi, end_off = mapping[end_pos]
        candidates.append(
            {
                'start_cfi': f'{start_cfi}:{start_off}',
                'end_cfi': f'{end_cfi}:{end_off + 1}',
                'excerpt': normalized_text[max(0, pos - 25): min(len(normalized_text), end_pos + 26)],
                'exact': True,
            }
        )
        start = pos + nlen
    return candidates


def locate_annotation_candidates(db_api, book_id: int, fmt: str, annotation: dict) -> list[dict]:
    if fmt.upper() not in ('EPUB', 'KEPUB'):
        return []

    source_text = _normalize_text(annotation.get('original_text') or annotation.get('highlighted_text') or '')
    if not source_text:
        return []

    epub_data = db_api.format(book_id, fmt, as_file=False)
    if not epub_data:
        return []

    candidates: list[dict] = []
    with zipfile.ZipFile(BytesIO(epub_data), 'r') as zf:
        # 读取 toc family 映射：spine 文件路径 -> [目录层级标题]
        toc_map: dict[str, list[str]] = {}
        try:
            container = ET.fromstring(zf.read('META-INF/container.xml'))
            rootfile = container.find(f'.//{_ns("rootfile")}')
            if rootfile is not None:
                opf_path = rootfile.attrib.get('full-path')
                if opf_path:
                    opf_root = ET.fromstring(zf.read(opf_path))
                    opf_base = PurePosixPath(opf_path).parent
                    manifest: dict[str, str] = {}
                    manifest_el = opf_root.find(_opf_ns('manifest'))
                    if manifest_el is not None:
                        for item in manifest_el.findall(_opf_ns('item')):
                            item_id = item.attrib.get('id')
                            href = item.attrib.get('href')
                            if item_id and href:
                                manifest[item_id] = str((opf_base / href).as_posix())
                    toc_map = _read_toc_map(opf_root, opf_base, manifest, zf)
        except Exception:
            toc_map = {}

        for spine_index, spine_name, chapter_text in _read_epub_spine_docs(epub_data):
            if len(candidates) >= MAX_ANNOTATION_MATCHES:
                break
            if not chapter_text or source_text not in chapter_text:
                continue
            try:
                raw = zf.read(spine_name)
            except KeyError:
                continue
            try:
                xhtml_text = raw.decode('utf-8')
            except UnicodeDecodeError:
                xhtml_text = raw.decode('utf-8', errors='ignore')

            remaining = MAX_ANNOTATION_MATCHES - len(candidates)
            for c in _find_exact_cfi_candidates(xhtml_text, source_text, max_matches=remaining):
                candidates.append(
                    {
                        'spine_index': spine_index,
                        'spine_name': spine_name,
                        'start_cfi': c['start_cfi'],
                        'end_cfi': c['end_cfi'],
                        'exact': c['exact'],
                        'excerpt': c['excerpt'],
                        'toc_family_titles': toc_map.get(spine_name, []),
                    }
                )
                if len(candidates) >= MAX_ANNOTATION_MATCHES:
                    break
    return candidates
