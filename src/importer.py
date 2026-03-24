from __future__ import annotations

import copy
from datetime import datetime, timezone
from uuid import uuid4

from calibre_plugins.wxread_annotation_plugin.locator import locate_annotation_candidates


def _normalize_text_for_merge(text: str) -> str:
    return ' '.join((text or '').split()).strip()


def _location_key(annot: dict):
    spine_name = annot.get('spine_name') or ''
    start_cfi = annot.get('start_cfi') or ''
    end_cfi = annot.get('end_cfi') or ''
    if spine_name and start_cfi and end_cfi:
        return ('loc', spine_name, start_cfi, end_cfi)
    spine_index = annot.get('spine_index')
    if start_cfi and end_cfi and spine_index is not None:
        return ('loc_idx', int(spine_index), start_cfi, end_cfi)
    return None


def _merge_highlight_text(existing_text: str, incoming_text: str) -> str:
    a = (existing_text or '').strip()
    b = (incoming_text or '').strip()
    if not a:
        return b
    if not b:
        return a
    if a == b:
        return a
    if a in b:
        return b
    if b in a:
        return a
    return f'{a}\n{b}'


def _merge_notes(existing_notes: str, incoming_notes: str) -> str:
    a = (existing_notes or '').strip()
    b = (incoming_notes or '').strip()
    if not a:
        return b
    if not b:
        return a
    if a == b:
        return a
    # 已有内容中不包含新内容则追加
    if b in a:
        return a
    if a in b:
        return b
    return f'{a}\n\n{b}'


def _merge_toc_titles(existing_titles, incoming_titles):
    seen = set()
    out = []
    for t in (existing_titles or []):
        ts = str(t).strip()
        if ts and ts not in seen:
            seen.add(ts)
            out.append(ts)
    for t in (incoming_titles or []):
        ts = str(t).strip()
        if ts and ts not in seen:
            seen.add(ts)
            out.append(ts)
    return out


def _merge_with_existing_annotations(db_api, book_id: int, fmt: str, annots_list: list[dict]) -> None:
    amap = db_api.annotations_map_for_book(book_id, fmt, user_type='local', user='viewer') or {}
    existing_highlights = amap.get('highlight') or []

    by_loc = {}
    by_text = {}
    for ex in existing_highlights:
        key = _location_key(ex)
        if key is not None and key not in by_loc:
            by_loc[key] = ex
        tkey = _normalize_text_for_merge(ex.get('highlighted_text') or '')
        if tkey and tkey not in by_text:
            by_text[tkey] = ex

    for annot in annots_list:
        matched = None
        key = _location_key(annot)
        if key is not None:
            matched = by_loc.get(key)
        if matched is None:
            tkey = _normalize_text_for_merge(annot.get('highlighted_text') or '')
            if tkey:
                matched = by_text.get(tkey)
        if matched is None:
            continue

        # 复用已存在 uuid，让 calibre 视为更新同一条高亮
        annot['uuid'] = matched.get('uuid', annot['uuid'])
        annot['highlighted_text'] = _merge_highlight_text(
            matched.get('highlighted_text') or '',
            annot.get('highlighted_text') or '',
        )
        annot['notes'] = _merge_notes(
            matched.get('notes') or '',
            annot.get('notes') or '',
        )
        annot['toc_family_titles'] = _merge_toc_titles(
            matched.get('toc_family_titles') or [],
            annot.get('toc_family_titles') or [],
        )


def _pick_book_format(db_api, book_id: int) -> str:
    formats = db_api.formats(book_id, verify_formats=False) or ()
    if not formats:
        raise RuntimeError('该书籍没有可用格式，无法写入标注。')

    preferred = ('EPUB', 'KEPUB', 'AZW3', 'MOBI', 'PDF')
    upper_formats = {f.upper() for f in formats}
    for fmt in preferred:
        if fmt in upper_formats:
            return fmt
    return next(iter(upper_formats))


def _coerce_to_calibre_annot(raw: dict) -> dict:
    now_iso = datetime.now(timezone.utc).isoformat()
    highlighted_text = (raw.get('highlighted_text') or '').strip()
    if not highlighted_text:
        raise ValueError('标注文本为空')

    # 依据 calibre.db.annotations.annot_db_data()：
    # highlight 至少需要 type=highlight 与 uuid 才会被接受写入。
    return {
        'type': 'highlight',
        'uuid': raw.get('uuid') or str(uuid4()),
        'timestamp': raw.get('timestamp') or now_iso,
        'highlighted_text': highlighted_text,
        'notes': raw.get('notes') or '',
        'start_cfi': raw.get('start_cfi', ''),
        'end_cfi': raw.get('end_cfi', ''),
        'spine_name': raw.get('spine_name', ''),
        'spine_index': raw.get('spine_index', 0),
        'toc_family_titles': raw.get('toc_family_titles', []),
        'style': raw.get(
            'style',
            {
                'type': 'builtin',
                'kind': 'color',
                'which': 'yellow',
            },
        ),
    }


def _build_annots_list(annotations: list[dict]) -> list[dict]:
    out: list[dict] = []
    for item in annotations:
        annot = _coerce_to_calibre_annot(item)
        out.append(annot)
    return out

def import_annotations_for_book(db_api, book_id: int, annotations: list[dict]) -> tuple[int, list[dict]]:
    """
    将解析后的标注导入指定书籍。

    使用 calibre 官方 API:
    - db_api.merge_annotations_for_book(book_id, fmt, annots_list, user_type='local', user='viewer')
    - 多候选定位默认取第一个精确匹配；导入后在检查窗口中可改选。

    返回 (导入条数, 供检查窗口使用的行列表)。
    """
    if not annotations:
        return 0, []

    fmt = _pick_book_format(db_api, book_id)
    annots_list = _build_annots_list(annotations)
    review_rows: list[dict] = []

    for i, annot in enumerate(annots_list):
        candidates = locate_annotation_candidates(db_api, book_id, fmt, annotations[i])
        chosen = candidates[0] if candidates else None
        if chosen and chosen.get('exact'):
            annot['spine_name'] = chosen.get('spine_name', annot.get('spine_name', ''))
            annot['spine_index'] = chosen['spine_index']
            annot['start_cfi'] = chosen['start_cfi']
            annot['end_cfi'] = chosen['end_cfi']
            annot['toc_family_titles'] = chosen.get('toc_family_titles', annot.get('toc_family_titles', []))

        review_rows.append(
            {
                'source': annotations[i],
                'annot': copy.deepcopy(annot),
                'candidates': list(candidates),
                'chosen_index': 0,
                'fmt': fmt,
            }
        )

    _merge_with_existing_annotations(db_api, book_id, fmt, annots_list)
    for i, row in enumerate(review_rows):
        row['annot'] = copy.deepcopy(annots_list[i])
    db_api.merge_annotations_for_book(book_id, fmt, annots_list, user_type='local', user='viewer')
    return len(annots_list), review_rows
