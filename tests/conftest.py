from pathlib import Path
from zipfile import ZipFile
import pytest


@pytest.fixture
def make_epub(tmp_path):
    def make(name="sample.epub", chapters=None):
        chapters = chapters or [("second.xhtml", "第二章", "春眠不覺曉。" * 50),
                                 ("first.xhtml", "第一章", "Hello 世界 " * 80)]
        path = tmp_path / name
        with ZipFile(path, "w") as z:
            z.writestr("META-INF/container.xml", '<container><rootfiles><rootfile full-path="OPS/package.opf"/></rootfiles></container>')
            items = ''.join(f'<item id="c{i}" href="{file}" media-type="application/xhtml+xml"/>' for i, (file, _, _) in enumerate(chapters))
            refs = ''.join(f'<itemref idref="c{i}"/>' for i in range(len(chapters)))
            z.writestr("OPS/package.opf", f'<package xmlns:dc="http://purl.org/dc/elements/1.1/"><metadata><dc:title>真正書名</dc:title><dc:creator>作者</dc:creator></metadata><manifest>{items}<item id="nav" href="nav.xhtml" properties="nav" media-type="application/xhtml+xml"/></manifest><spine>{refs}</spine></package>')
            links = ''.join(f'<li><a href="{file}#body">目錄 {title}</a></li>' for file, title, _ in chapters)
            z.writestr("OPS/nav.xhtml", f'<html xmlns:epub="http://www.idpf.org/2007/ops"><nav epub:type="toc"><ol>{links}</ol></nav></html>')
            for file, title, text in chapters:
                z.writestr(f"OPS/{file}", f'<html><head><title>ignore</title><style>ignore</style></head><body><h1>{title}</h1><p id="body">{text}</p><script>ignore</script></body></html>')
        return path
    return make
