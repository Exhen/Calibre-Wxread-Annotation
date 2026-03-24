from __future__ import annotations

import re


COMMENT_HEADER_RE = re.compile(r'^(\d{4}/\d{2}/\d{2})发表想法$')
WXREAD_END_MARKER = '-- 来自微信读书'


def _strip_end_marker(text: str) -> str:
    if WXREAD_END_MARKER not in text:
        return text
    return text.split(WXREAD_END_MARKER, 1)[0]


def _split_annotation_blocks(text: str) -> list[list[str]]:
    blocks: list[list[str]] = []
    current: list[str] | None = None
    blank_streak = 0
    for raw_line in text.splitlines():
        line = raw_line.rstrip('\n')
        if line.startswith('◆'):
            if current:
                blocks.append(current)
            current = [line]
            blank_streak = 0
            continue
        if current is not None:
            if not line.strip():
                blank_streak += 1
                # 连续空行视为当前标注结束
                if blank_streak >= 2:
                    while current and not current[-1].strip():
                        current.pop()
                    if current:
                        blocks.append(current)
                    current = None
                    blank_streak = 0
                    continue
            else:
                blank_streak = 0
            current.append(line)
    if current:
        blocks.append(current)
    return blocks


def _trim_blank_edges(lines: list[str]) -> list[str]:
    start = 0
    end = len(lines)
    while start < end and not lines[start].strip():
        start += 1
    while end > start and not lines[end - 1].strip():
        end -= 1
    return lines[start:end]


def _join_lines(lines: list[str]) -> str:
    return '\n'.join(_trim_blank_edges(lines)).strip()


def _normalize_for_dedupe(text: str) -> str:
    """用于比较是否同一段原文/高亮（合并空白）。"""
    if not text:
        return ''
    return re.sub(r'\s+', ' ', text.strip())


def dedupe_annotations(parsed: list[dict]) -> list[dict]:
    """
    导入前去重：
    - 若某条为纯高亮，其文本与某条「评论类」的原文相同，则去掉该纯高亮（保留带想法的一条）。
    - 多条纯高亮文本相同，只保留第一条。
    """
    originals_from_comments: set[str] = set()
    for item in parsed:
        if item.get('kind') == 'comment':
            ot = item.get('original_text') or ''
            if ot.strip():
                originals_from_comments.add(_normalize_for_dedupe(ot))

    seen_highlight_keys: set[str] = set()
    out: list[dict] = []
    for item in parsed:
        if item.get('kind') == 'highlight':
            key = _normalize_for_dedupe(item.get('highlighted_text') or '')
            if not key:
                continue
            if key in originals_from_comments:
                continue
            if key in seen_highlight_keys:
                continue
            seen_highlight_keys.add(key)
            out.append(item)
        else:
            out.append(item)
    return out


def _parse_comment_block(header: str, body_lines: list[str]) -> dict:
    m = COMMENT_HEADER_RE.match(header)
    if not m:
        raise ValueError('invalid comment header')
    date = m.group(1)

    original_idx = -1
    for i, line in enumerate(body_lines):
        if line.startswith('原文：'):
            original_idx = i
            break

    if original_idx >= 0:
        comment_lines = body_lines[:original_idx]
        original_first = body_lines[original_idx][len('原文：'):].strip()
        original_tail = body_lines[original_idx + 1:]
        original_text = _join_lines(([original_first] if original_first else []) + original_tail)
    else:
        comment_lines = body_lines
        original_text = ''

    comment_text = _join_lines(comment_lines)
    return {
        'kind': 'comment',
        'date': date,
        'comment': comment_text,
        'original_text': original_text,
        'highlighted_text': original_text or comment_text,
        'notes': comment_text,
    }


def _parse_highlight_block(header: str, body_lines: list[str]) -> dict:
    text = _join_lines([header] + body_lines)
    return {
        'kind': 'highlight',
        'highlighted_text': text,
        'notes': '',
    }


def parse_raw_annotations(raw_text: str) -> list[dict]:
    """
    解析微信读书导出的标注文本。

    规则:
    - 所有 annotation 以 ◆ 开头
    - annotation 可能有多行
    - '-- 来自微信读书' 为固定结束标记
    - '◆ YYYY/MM/DD发表想法' 为评论类，格式: 日期/评论/原文
    - 无日期开头的 annotation 为纯高亮
    """
    text = _strip_end_marker(raw_text)
    blocks = _split_annotation_blocks(text)

    parsed: list[dict] = []
    for block in blocks:
        header = block[0][1:].strip()
        body = block[1:]
        if not header:
            continue
        if COMMENT_HEADER_RE.match(header):
            parsed.append(_parse_comment_block(header, body))
        else:
            parsed.append(_parse_highlight_block(header, body))
    return dedupe_annotations(parsed)
