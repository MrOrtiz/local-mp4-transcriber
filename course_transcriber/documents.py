"""Local extractors. All source files are opened read-only."""
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import time
import zipfile

from .types import Result, check_cancel


def tessdata_path(configured=''):
    candidates = [configured, os.environ.get('TESSDATA_PREFIX', ''),
                  str(Path(__file__).resolve().parent.parent / 'tools' / 'tessdata'),
                  r'C:\Program Files\Tesseract-OCR\tessdata']
    exe = shutil.which('tesseract')
    if exe:
        candidates.append(str(Path(exe).parent / 'tessdata'))
    return next((p for p in candidates if p and Path(p).is_dir()), None)


def converter_path(configured=''):
    if configured:
        if not Path(configured).is_file():
            raise RuntimeError('Configured ebook-convert executable does not exist.')
        return configured
    return shutil.which('ebook-convert') or next((str(p) for p in [
        Path(__file__).resolve().parent.parent / 'tools' / 'Calibre Portable' / 'Calibre' / 'ebook-convert.exe',
        Path(r'C:\Program Files\Calibre2\ebook-convert.exe'),
        Path(r'C:\Program Files\calibre\ebook-convert.exe')
    ] if p.is_file()), None)


def text_document(path):
    raw = path.read_bytes()
    warnings = []
    try:
        text = raw.decode('utf-8-sig')
        encoding = 'utf-8'
    except UnicodeDecodeError:
        if raw.startswith((b'\xff\xfe', b'\xfe\xff')):
            text, encoding = raw.decode('utf-16'), 'utf-16'
        else:
            from charset_normalizer import from_bytes
            guess = from_bytes(raw).best()
            if guess is None:
                raise ValueError('Unable to determine text encoding; convert this file to UTF-8.')
            text, encoding = str(guess), guess.encoding
            warnings.append(f'Encoding inferred as {encoding}; inspect non-English characters.')
    if '\x00' in text:
        raise ValueError('Binary content in a text file; extraction refused.')
    return Result(text, {'encoding': encoding, 'language': 'unknown'}, warnings)


def pdf_document(path, settings, cancel, progress):
    import pymupdf
    pages, warnings = [], []
    with pymupdf.open(path) as doc:
        if doc.needs_pass:
            raise ValueError('Protected PDF: a password is required; provide an unlocked copy.')
        if doc.is_encrypted or not (doc.permissions & pymupdf.PDF_PERM_COPY):
            raise ValueError('Protected PDF: text copying is restricted.')
        for number, page in enumerate(doc, 1):
            check_cancel(cancel)
            # Inspect every page, including pages containing both images and text.
            text = page.get_text('text', sort=True)
            images = page.get_image_info()
            needs_ocr = bool(images) or (not text.strip() and bool(page.get_drawings()))
            if needs_ocr:
                data = tessdata_path(settings.tessdata)
                if not data or any(not (Path(data) / f'{lang}.traineddata').is_file()
                                   for lang in settings.ocr_language.split('+')):
                    raise RuntimeError(f'Page {number} requires OCR. Install the {settings.ocr_language} '
                                       'Tesseract language data; set the tessdata folder in Options.')
                tp = page.get_textpage_ocr(language=settings.ocr_language, dpi=300,
                                           full=not bool(text.strip()), tessdata=data)
                text = page.get_text('text', textpage=tp, sort=True)
                warnings.append(f'Page {number}: local OCR used; verify spelling and reading order.')
            if not text.strip():
                warnings.append(f'Page {number}: no text recovered (possibly blank or image-only).')
            pages.append(f'[Page {number}]\n{text.strip()}')
            progress(f'PDF page {number}/{len(doc)}')
        metadata = {'pages': len(doc), 'language': 'unknown', 'title': doc.metadata.get('title', '')}
    warnings.append('PDF layout is approximate; columns, tables, formulas and image descriptions may be incomplete.')
    return Result('\n\n'.join(pages), metadata, warnings)


def docx_document(path, cancel):
    from docx import Document
    from docx.text.paragraph import Paragraph
    from docx.table import Table
    if not zipfile.is_zipfile(path):
        raise ValueError('DOCX is encrypted/protected, corrupt, or not a DOCX archive.')
    doc = Document(path)
    parts, warnings = [], []

    def walk(container):
        for block in container.iter_inner_content():
            check_cancel(cancel)
            if isinstance(block, Paragraph):
                style = block.style.name if block.style else ''
                prefix = ''
                if style.startswith('Heading ') and style[8:].isdigit():
                    prefix = '#' * min(6, int(style[8:])) + ' '
                elif style == 'Title':
                    prefix = '# '
                parts.append(prefix + block.text)
            elif isinstance(block, Table):
                for row in block.rows:
                    parts.append(' | '.join(cell.text for cell in row.cells))
                warnings.append('Table flattened in row order; merged or nested cells may need review.')

    walk(doc)
    if doc.inline_shapes:
        warnings.append('DOCX contains images; embedded-image text is not OCRed.')
    warnings.append('DOCX body extracted; headers, footers, footnotes, text boxes and tracked revisions may be omitted. '
                    'Page numbers are unavailable without Word layout.')
    return Result('\n\n'.join(parts), {'language': 'unknown', 'title': doc.core_properties.title}, warnings)


def epub_document(path, cancel):
    from ebooklib import epub
    from bs4 import BeautifulSoup
    with zipfile.ZipFile(path) as archive:
        if 'META-INF/encryption.xml' in archive.namelist():
            xml = archive.read('META-INF/encryption.xml')
            # Font obfuscation is not DRM. Reject encrypted non-font content.
            from lxml import etree
            tree = etree.fromstring(xml, parser=etree.XMLParser(resolve_entities=False, no_network=True))
            for node in tree.xpath('//*[local-name()="EncryptionMethod"]'):
                if node.get('Algorithm') not in {'http://www.idpf.org/2008/embedding',
                                                'http://ns.adobe.com/pdf/enc#RC'}:
                    raise ValueError('Protected EPUB: encrypted content is unsupported.')
    book = epub.read_epub(str(path), options={'ignore_ncx': True})
    parts, warnings = [], []
    for idref, _linear in book.spine:
        check_cancel(cancel)
        item = book.get_item_with_id(idref)
        if item is None:
            raise ValueError(f'EPUB spine references missing chapter {idref}.')
        soup = BeautifulSoup(item.get_content(), 'html.parser')
        for node in soup(['script', 'style']):
            node.decompose()
        for img in soup.find_all('img'):
            alt = img.get('alt', '')
            img.replace_with(f' [Image alt text: {alt}] ' if alt else '')
            warnings.append(f'{item.file_name}: image present; image pixels are not transcribed.')
        for heading in soup.find_all(['h1', 'h2', 'h3', 'h4', 'h5', 'h6']):
            heading.insert_before('\n' + '#' * int(heading.name[1]) + ' ')
            heading.insert_after('\n')
        for block in soup.find_all(['p', 'div', 'li', 'br', 'tr', 'section']):
            block.insert_after('\n')
        for cell in soup.find_all(['td', 'th']):
            cell.insert_after(' | ')
        body = soup.body or soup
        text = '\n'.join(line.strip() for line in body.get_text().splitlines() if line.strip())
        parts.append(f'[Chapter: {item.file_name}]\n{text}')
    if not parts:
        raise ValueError('EPUB has no readable spine chapters.')
    languages = book.get_metadata('DC', 'language')
    return Result('\n\n'.join(parts), {'chapters': len(parts),
                  'language': languages[0][0] if languages else 'unknown'}, warnings)


def mobi_document(path, settings, cancel):
    exe = converter_path(settings.ebook_convert)
    if not exe:
        raise RuntimeError('MOBI requires Calibre ebook-convert. Install Calibre or set its executable in Options.')
    with tempfile.TemporaryDirectory(prefix='course-ebook-') as temporary:
        target = Path(temporary) / 'converted.epub'
        log = Path(temporary) / 'conversion.log'
        with log.open('wb') as output:
            proc = subprocess.Popen([exe, str(path), str(target)], stdout=output, stderr=subprocess.STDOUT,
                                    creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
            start = time.monotonic()
            try:
                while proc.poll() is None:
                    check_cancel(cancel)
                    if time.monotonic() - start > 600:
                        raise RuntimeError('MOBI conversion timed out after 10 minutes.')
                    time.sleep(.1)
            finally:
                if proc.poll() is None:
                    proc.kill()
                proc.wait()
        if proc.returncode or not target.exists():
            detail = log.read_text(encoding='utf-8', errors='replace')[-2000:]
            raise ValueError(f'MOBI conversion failed (DRM/protection, unsupported content, or corrupt file): {detail}')
        result = epub_document(target, cancel)
        result.warnings.append('MOBI converted locally through Calibre; chapter layout may differ from the original.')
        return result


def extract_document(path, settings, cancel, progress):
    check_cancel(cancel)
    ext = path.suffix.lower()
    if ext in {'.txt', '.md', '.markdown'}:
        return text_document(path)
    if ext == '.pdf':
        return pdf_document(path, settings, cancel, progress)
    if ext == '.docx':
        return docx_document(path, cancel)
    if ext == '.epub':
        return epub_document(path, cancel)
    if ext == '.mobi':
        return mobi_document(path, settings, cancel)
    raise ValueError(f'Unsupported document format: {ext}')
