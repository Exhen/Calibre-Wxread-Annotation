import os
import shutil
import zipfile


def _should_skip_file(filename: str) -> bool:
    if filename.endswith(".pyc") or filename.endswith(".pyo"):
        return True
    return False


def zip_dir(input_path, output_file):
    output_zip = zipfile.ZipFile(output_file, "w", zipfile.ZIP_DEFLATED)
    for path, dir_names, file_names in os.walk(input_path):
        # 不进入 __pycache__ 等目录
        dir_names[:] = [d for d in dir_names if d != "__pycache__" and not d.startswith(".")]
        # 原路径修复: src/foo -> foo（避免 zip 内出现 /foo 导致路径与 load_resources 不一致）
        parsed_path = path.replace(input_path, "").lstrip(os.sep + "/\\")
        for filename in file_names:
            if _should_skip_file(filename):
                continue
            full_path = os.path.join(path, filename)
            print("zip adding file %s" % full_path)
            output_zip.write(full_path, os.path.join(parsed_path, filename))
    output_zip.close()


if __name__ == "__main__":
    input_path = "src"
    out_path = "out"
    output_file = out_path + "/WxreadAnnotation.zip"
    if os.path.exists(out_path):
        print('clean path %s' % out_path)
        shutil.rmtree(out_path)
    os.mkdir(out_path)
    zip_dir(input_path, output_file)
