from qt.core import (
    QDialog,
    QDialogButtonBox,
    QLabel,
    QPlainTextEdit,
    QVBoxLayout,
)


class PasteAnnotationsDialog(QDialog):
    def __init__(self, parent=None, book_info_text: str = ''):
        super().__init__(parent)
        self.setWindowTitle('导入标注')
        self.resize(760, 520)

        layout = QVBoxLayout(self)
        if book_info_text:
            info_label = QLabel(f'当前选中书籍：{book_info_text}', self)
            info_label.setWordWrap(True)
            layout.addWidget(info_label)
        layout.addWidget(QLabel('请粘贴标注原始文本：', self))

        self.text_edit = QPlainTextEdit(self)
        self.text_edit.setPlaceholderText(
            '请在微信读书网页版，点击导出笔记后，粘贴到这里，例如：\n'
            '《局外人》\n'
            '[法]阿尔贝·加缪\n'
            '1个笔记\n'
            '\n'
            '◆ 今天，妈妈死了。也许是在昨天，我搞不清。\n'
            '\n'
            '-- 来自微信读书'
        )
        layout.addWidget(self.text_edit)

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel,
            self,
        )
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    @property
    def raw_text(self):
        return self.text_edit.toPlainText().strip()
