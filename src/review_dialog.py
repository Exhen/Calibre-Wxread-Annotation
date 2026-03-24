from __future__ import annotations

import copy

from qt.core import (
    QAbstractItemView,
    QDialog,
    QDialogButtonBox,
    QHeaderView,
    QLabel,
    QComboBox,
    QPlainTextEdit,
    QTableWidget,
    QVBoxLayout,
    QWidget,
    QHBoxLayout,
)


def _format_annotation_display(source: dict) -> str:
    kind = source.get('kind')
    if kind == 'comment':
        parts = []
        if source.get('date'):
            parts.append(f"日期: {source['date']}")
        if source.get('comment'):
            parts.append(f"想法: {source['comment']}")
        if source.get('original_text'):
            parts.append(f"原文: {source['original_text']}")
        return '\n'.join(parts)
    return (source.get('highlighted_text') or '').strip()


def _candidate_combo_label(idx: int, cand: dict) -> str:
    ex = (cand.get('excerpt') or '').replace('\n', ' ').strip()
    if len(ex) > 90:
        ex = ex[:87] + '...'
    spine = cand.get('spine_index', 0) + 1
    name = cand.get('spine_name') or ''
    if name:
        short = name.rsplit('/', 1)[-1]
        return f'{idx + 1}. 第{spine}章 · {short} · {ex}'
    return f'{idx + 1}. 第{spine}章 · {ex}'


class ImportReviewDialog(QDialog):
    """导入后检查：第一列为标注摘要，第二列为书中匹配（多候选时为下拉框）。"""

    def __init__(self, parent, review_rows: list[dict], db_api, book_id: int, total_count: int | None = None):
        super().__init__(parent)
        n = total_count if total_count is not None else len(review_rows)
        self.setWindowTitle(f'导入标注 - 检查（共 {n} 条）')
        self.resize(920, 560)
        self._db_api = db_api
        self._book_id = book_id
        self._rows = review_rows
        self._combos: list[QComboBox | None] = []

        layout = QVBoxLayout(self)
        hint = QLabel(
            '以下为本次导入的标注。第二列为在电子书原文中匹配到的片段；'
            '若同一文本在书中出现多处，请在下拉框中选择正确位置，然后点「确定」将更新定位。',
            self,
        )
        hint.setWordWrap(True)
        layout.addWidget(hint)

        self._table = QTableWidget(len(review_rows), 2, self)
        self._table.setHorizontalHeaderLabels(['标注', '原文匹配'])
        try:
            self._table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
            self._table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        except AttributeError:
            self._table.horizontalHeader().setSectionResizeMode(0, QHeaderView.Stretch)
            self._table.horizontalHeader().setSectionResizeMode(1, QHeaderView.Stretch)
        self._table.verticalHeader().setVisible(False)
        try:
            self._table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        except AttributeError:
            self._table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        try:
            self._table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        except AttributeError:
            self._table.setSelectionBehavior(QAbstractItemView.SelectRows)

        for row_idx, row in enumerate(review_rows):
            text = _format_annotation_display(row['source'])
            te = QPlainTextEdit(self)
            te.setPlainText(text)
            te.setReadOnly(True)
            te.setMaximumHeight(140)
            self._table.setCellWidget(row_idx, 0, te)

            cands = row.get('candidates') or []
            w = QWidget(self)
            h = QHBoxLayout(w)
            h.setContentsMargins(4, 4, 4, 4)
            combo: QComboBox | None = None
            if not cands:
                lab = QLabel('未在书中匹配到原文（可能格式非 EPUB/KEPUB 或文本不一致）', self)
                lab.setWordWrap(True)
                lab.setStyleSheet('color: #d32f2f; font-weight: 600;')
                h.addWidget(lab)
                self._combos.append(None)
            elif len(cands) == 1:
                c0 = cands[0]
                ex = (c0.get('excerpt') or '').replace('\n', ' ').strip()
                lab = QLabel(ex if ex else '（已定位）', self)
                lab.setWordWrap(True)
                h.addWidget(lab)
                self._combos.append(None)
            else:
                combo = QComboBox(self)
                for i, c in enumerate(cands):
                    combo.addItem(_candidate_combo_label(i, c), i)
                combo.setCurrentIndex(int(row.get('chosen_index', 0)))
                combo.setMinimumWidth(400)
                h.addWidget(combo)
                self._combos.append(combo)

            self._table.setCellWidget(row_idx, 1, w)
            self._table.resizeRowToContents(row_idx)

        layout.addWidget(self._table)

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel,
            self,
        )
        buttons.accepted.connect(self._on_accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def _on_accept(self):
        for idx, row in enumerate(self._rows):
            combo = self._combos[idx]
            if combo is None:
                continue
            new_i = combo.currentIndex()
            old_i = int(row.get('chosen_index', 0))
            if new_i == old_i:
                continue
            cands = row.get('candidates') or []
            if new_i < 0 or new_i >= len(cands):
                continue
            cand = cands[new_i]
            if not cand.get('exact'):
                continue
            annot = copy.deepcopy(row['annot'])
            annot['spine_name'] = cand.get('spine_name', '')
            annot['spine_index'] = cand['spine_index']
            annot['start_cfi'] = cand['start_cfi']
            annot['end_cfi'] = cand['end_cfi']
            annot['toc_family_titles'] = cand.get('toc_family_titles', annot.get('toc_family_titles', []))
            fmt = row['fmt']
            self._db_api.merge_annotations_for_book(
                self._book_id,
                fmt,
                [annot],
                user_type='local',
                user='viewer',
            )
            row['chosen_index'] = new_i
            row['annot'] = annot
        self.accept()
