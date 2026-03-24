from calibre.customize import InterfaceActionBase


class AnnotationImporterPlugin(InterfaceActionBase):
    name = 'WxreadAnnotation'
    description = '导入微信读书标注'
    supported_platforms = ['windows', 'osx', 'linux']
    author = 'exhen'
    version = (0, 1, 0)
    minimum_calibre_version = (6, 0, 0)
    # 必须指向实际存在的 InterfaceAction 子类，否则 calibre 不会加载为工具栏/右键动作插件
    actual_plugin = 'calibre_plugins.wxread_annotation_plugin.action:AnnotationImportAction'
