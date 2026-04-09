from __future__ import annotations

from calibre.gui2 import error_dialog, info_dialog, question_dialog
from calibre.gui2.actions import InterfaceAction
from qt.core import QIcon, QPixmap

from calibre_plugins.wxread_annotation_plugin.dialog import PasteAnnotationsDialog
from calibre_plugins.wxread_annotation_plugin.importer import (
    commit_annotations_for_book,
    import_annotations_for_book,
)
from calibre_plugins.wxread_annotation_plugin.parser import parse_raw_annotations
from calibre_plugins.wxread_annotation_plugin.review_dialog import ImportReviewDialog


class AnnotationImportAction(InterfaceAction):
    name = '导入标注'
    # 先给一个内置图标兜底，后续再尝试覆盖为插件自带 SVG
    action_spec = ('导入标注', 'highlight.png', '将外部标注文本导入当前选中书籍', None)
    _PLUGIN_ICON_RELPATH = 'logo.svg'

    def genesis(self):
        self.qaction.setIconText('导入微信读书标注')
        try:
            res = self.load_resources([self._PLUGIN_ICON_RELPATH])
            data = res.get(self._PLUGIN_ICON_RELPATH)
            if data:
                pix = QPixmap()
                if pix.loadFromData(data):
                    icon = QIcon(pix)
                    self.qaction.setIcon(icon)
                    if hasattr(self, 'menuless_qaction'):
                        self.menuless_qaction.setIcon(icon)
        except Exception:
            # 图标加载失败时保持无图标，不影响功能
            pass
        self.qaction.triggered.connect(self.import_annotations)


    def import_annotations(self):
        ids = self.gui.library_view.get_selected_ids()
        if not ids:
            return error_dialog(self.gui, '导入标注', '请先在书库中选中一本书。', show=True)
        if len(ids) > 1:
            return error_dialog(self.gui, '导入标注', '一次只能导入一本书，请只保留一本被选中。', show=True)

        book_id = ids[0]
        db = self.gui.current_db.new_api
        book_info_text = self._book_info_text(db, book_id)

        dlg = PasteAnnotationsDialog(self.gui, book_info_text=book_info_text)
        if dlg.exec() != dlg.DialogCode.Accepted:
            return

        raw_text = dlg.raw_text
        if not raw_text:
            return error_dialog(self.gui, '导入标注', '未检测到粘贴内容。', show=True)

        try:
            annotations = parse_raw_annotations(raw_text)
            if not annotations:
                return error_dialog(self.gui, '导入标注', '解析结果为空，请检查标注文本格式。', show=True)

            imported_count, review_rows = import_annotations_for_book(db, book_id, annotations)
        except Exception as e:
            return error_dialog(
                self.gui,
                '导入标注失败',
                '导入过程中发生错误。',
                det_msg=str(e),
                show=True,
            )

        if review_rows:
            review = ImportReviewDialog(self.gui, review_rows, total_count=imported_count)
            if review.exec() != review.DialogCode.Accepted:
                return info_dialog(
                    self.gui,
                    '导入标注',
                    '已取消导入，本次没有写入任何标注。',
                    show=True,
                )
        committed = commit_annotations_for_book(db, book_id, review_rows)
        info_dialog(
            self.gui,
            '导入标注',
            f'已导入 {committed} 条标注。',
            show=True,
        )

    def _book_info_text(self, db, book_id: int) -> str:
        try:
            mi = db.get_metadata(book_id)
        except Exception:
            return f'ID {book_id}'
        title = (getattr(mi, 'title', '') or '').strip() or f'ID {book_id}'
        authors = getattr(mi, 'authors', ()) or ()
        author_text = '、'.join(a for a in authors if a)
        if author_text:
            return f'{title}（{author_text}）'
        return title
