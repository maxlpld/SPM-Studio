"""PowerPoint files: export an editable .pptx, import the text, pictures and shapes of a .pptx.

Uses ``python-pptx`` (installed with SPM Studio's ``[all]`` extras). Text boxes stay editable
text; LaTeX boxes become high-resolution pictures; GIFs stay animated pictures; videos are
embedded as movies; shapes stay shapes.
"""
from __future__ import annotations

import re
import tempfile
from pathlib import Path

from spm_studio.documents import deck as deck_model

PT_PER_EMU = 1 / 12700.0


class PptxUnavailable(RuntimeError):
    pass


def _pptx():
    try:
        import pptx  # noqa: F401
        return pptx
    except ImportError as exc:
        raise PptxUnavailable('PowerPoint export needs the python-pptx package. Update SPM Studio, or run '
                              '“pip install python-pptx” in its environment.') from exc


def _rgb(value, fallback='000000'):
    from pptx.dml.color import RGBColor
    value = (value or '').lstrip('#')
    if len(value) == 8:
        value = value[2:]
    if not re.fullmatch(r'[0-9A-Fa-f]{6}', value):
        value = fallback
    return RGBColor.from_string(value.upper())


def export_pptx(deck: dict, project_dir, destination, rasterize) -> Path:
    """``rasterize(item) -> Path`` gives a PNG for LaTeX boxes and SVG images (done by the Qt side)."""
    _pptx()
    from pptx import Presentation
    from pptx.util import Pt, Emu
    from pptx.enum.shapes import MSO_SHAPE, MSO_CONNECTOR
    from pptx.enum.text import PP_ALIGN, MSO_ANCHOR
    project_dir = Path(project_dir)
    w, h = float(deck['width']), float(deck['height'])
    prs = Presentation()
    prs.slide_width = Emu(int(w * 12700 * 10 / 7.5))     # 960 pt → 13.333 in (PowerPoint's 16:9)
    scale = prs.slide_width / (w * 12700)
    prs.slide_height = Emu(int(h * 12700 * scale))
    blank = prs.slide_layouts[6]
    theme = deck.get('theme', {})

    def emu(v):
        return Emu(int(float(v) * 12700 * scale))

    for slide_data in deck['slides']:
        slide = prs.slides.add_slide(blank)
        bg = slide_data.get('background_color') or theme.get('background_color')
        if bg:
            fill = slide.background.fill
            fill.solid()
            fill.fore_color.rgb = _rgb(bg, 'FFFFFF')
        for item in slide_data.get('items', []):
            kind = item['type']
            x, y, iw, ih = emu(item['x']), emu(item['y']), emu(item['w']), emu(item['h'])
            shape = None
            if kind == 'text':
                shape = slide.shapes.add_textbox(x, y, iw, ih)
                frame = shape.text_frame
                frame.word_wrap = True
                frame.vertical_anchor = {'middle': MSO_ANCHOR.MIDDLE, 'bottom': MSO_ANCHOR.BOTTOM}.get(
                    item.get('valign'), MSO_ANCHOR.TOP)
                _fill_text(frame, item.get('html', ''), theme, scale, Pt, PP_ALIGN)
                if item.get('fill_color'):
                    shape.fill.solid()
                    shape.fill.fore_color.rgb = _rgb(item['fill_color'])
            elif kind in ('latex',) or (kind == 'image' and str(item.get('src', '')).lower().endswith('.svg')):
                png = rasterize(item)
                if png:
                    shape = slide.shapes.add_picture(str(png), x, y, iw, ih)
            elif kind in ('image', 'gif'):
                source = project_dir / item.get('src', '')
                if source.is_file():
                    shape = slide.shapes.add_picture(str(source), x, y, iw, ih)
            elif kind == 'video':
                source = project_dir / item.get('src', '')
                if source.is_file():
                    poster = rasterize(item)
                    mime = {'.mp4': 'video/mp4', '.mov': 'video/quicktime', '.webm': 'video/webm',
                            '.avi': 'video/x-msvideo', '.m4v': 'video/mp4'}.get(source.suffix.lower(), 'video/unknown')
                    shape = slide.shapes.add_movie(str(source), x, y, iw, ih, poster_frame_image=str(poster) if poster else None,
                                                   mime_type=mime)
            elif kind == 'shape':
                form = item.get('shape', 'rect')
                if form in ('line', 'arrow'):
                    cy = emu(item['y'] + item['h'] / 2)
                    shape = slide.shapes.add_connector(MSO_CONNECTOR.STRAIGHT, x, cy, x + iw, cy)
                    shape.line.color.rgb = _rgb(item.get('line_color') or item.get('fill_color'), '1A1D22')
                    shape.line.width = Pt(max(1.0, float(item.get('line_width') or 3)) * scale)
                    if form == 'arrow':
                        _arrow_head(shape)
                else:
                    mso = {'ellipse': MSO_SHAPE.OVAL, 'rounded': MSO_SHAPE.ROUNDED_RECTANGLE,
                           'triangle': MSO_SHAPE.ISOSCELES_TRIANGLE}.get(form, MSO_SHAPE.RECTANGLE)
                    shape = slide.shapes.add_shape(mso, x, y, iw, ih)
                    if item.get('fill_color'):
                        shape.fill.solid()
                        shape.fill.fore_color.rgb = _rgb(item['fill_color'])
                    else:
                        shape.fill.background()
                    if item.get('line_color') and float(item.get('line_width') or 0) > 0:
                        shape.line.color.rgb = _rgb(item['line_color'])
                        shape.line.width = Pt(float(item['line_width']) * scale)
                    else:
                        shape.line.fill.background()
                    shape.shadow.inherit = False
                    if item.get('html'):
                        _fill_text(shape.text_frame, item['html'], theme, scale, Pt, PP_ALIGN)
            if shape is not None and item.get('rotation'):
                shape.rotation = float(item['rotation'])
        if slide_data.get('notes'):
            slide.notes_slide.notes_text_frame.text = slide_data['notes']
    destination = Path(destination)
    if destination.suffix.lower() != '.pptx':
        destination = destination.with_suffix('.pptx')
    prs.save(str(destination))
    return destination


def _arrow_head(connector):
    from pptx.oxml.ns import qn
    line = connector.line._get_or_add_ln()
    tail = line.find(qn('a:tailEnd'))
    if tail is None:
        from lxml import etree
        tail = etree.SubElement(line, qn('a:tailEnd'))
    tail.set('type', 'triangle')


def _fill_text(frame, html, theme, scale, Pt, PP_ALIGN):
    """Paragraphs and runs (bold, italic, underline, size, colour) from Qt rich text."""
    from html.parser import HTMLParser
    frame.clear()
    paragraphs = []

    class Parser(HTMLParser):
        def __init__(self):
            super().__init__()
            self.stack = [{}]
            self.current = None
            self.in_body = 'body' not in html

        def handle_starttag(self, tag, attrs):
            attrs = dict(attrs)
            style = dict(self.stack[-1])
            css = attrs.get('style', '') or ''
            for key, value in re.findall(r'([\w-]+)\s*:\s*([^;]+)', css):
                style[key.strip()] = value.strip()
            if tag in ('b', 'strong'):
                style['font-weight'] = '700'
            if tag in ('i', 'em'):
                style['font-style'] = 'italic'
            if tag == 'u':
                style['text-decoration'] = 'underline'
            if tag == 'body':
                self.in_body = True
            if tag in ('p', 'li', 'h1', 'h2', 'h3'):
                self.current = {'runs': [], 'align': attrs.get('align') or style.get('text-align', ''),
                                'bullet': tag == 'li'}
                paragraphs.append(self.current)
            if tag == 'br' and self.current is not None:
                self.current['runs'].append(('\n', dict(style)))
            if tag not in ('br', 'meta', 'img'):
                self.stack.append(style)

        def handle_endtag(self, tag):
            if len(self.stack) > 1 and tag not in ('br', 'meta', 'img'):
                self.stack.pop()
            if tag in ('p', 'li', 'h1', 'h2', 'h3'):
                self.current = None

        def handle_data(self, data):
            if not self.in_body or not data.strip('\n'):
                return
            if self.current is None:
                self.current = {'runs': [], 'align': '', 'bullet': False}
                paragraphs.append(self.current)
            self.current['runs'].append((data, dict(self.stack[-1])))

    Parser().feed(html or '')
    if not paragraphs:
        paragraphs = [{'runs': [(deck_model.plain_text(html), {})], 'align': '', 'bullet': False}]
    for n, para in enumerate(paragraphs):
        p = frame.paragraphs[0] if n == 0 else frame.add_paragraph()
        p.alignment = {'center': PP_ALIGN.CENTER, 'right': PP_ALIGN.RIGHT, 'justify': PP_ALIGN.JUSTIFY}.get(
            para['align'], PP_ALIGN.LEFT)
        for text, style in para['runs']:
            prefix = '• ' if para['bullet'] and not p.runs else ''
            run = p.add_run()
            run.text = prefix + text.replace(' ', '\n')
            size = re.match(r'([\d.]+)\s*pt', style.get('font-size', ''))
            run.font.size = Pt(float(size.group(1)) * scale) if size else Pt(float(theme.get('body_size', 20)) * scale)
            if style.get('font-weight') and style['font-weight'] not in ('400', 'normal'):
                try:
                    run.font.bold = int(re.sub(r'\D', '', style['font-weight']) or 400) >= 600
                except ValueError:
                    run.font.bold = True
            if style.get('font-style') == 'italic':
                run.font.italic = True
            if 'underline' in style.get('text-decoration', ''):
                run.font.underline = True
            family = style.get('font-family', '').strip('\'"')
            if family:
                run.font.name = family.split(',')[0].strip('\'" ')
            color = style.get('color') or theme.get('text_color')
            if color:
                run.font.color.rgb = _rgb(color, '1A1D22')


def import_pptx(source, root) -> Path:
    """New presentation project from a .pptx (text boxes, pictures, basic shapes, notes)."""
    _pptx()
    from pptx import Presentation
    from pptx.enum.shapes import MSO_SHAPE_TYPE
    source = Path(source)
    prs = Presentation(str(source))
    width_pt = prs.slide_width * PT_PER_EMU
    factor = 960.0 / width_pt
    ratio = prs.slide_height / prs.slide_width
    size = min(deck_model.SLIDE_SIZES, key=lambda k: abs(deck_model.SLIDE_SIZES[k][1] / 960.0 - ratio))
    file = deck_model.create_project(root, source.stem, size=size)
    folder = file.parent
    deck = deck_model.load(file)
    deck['slides'] = []

    def box(shape):
        return (float(shape.left or 0) * PT_PER_EMU * factor, float(shape.top or 0) * PT_PER_EMU * factor,
                float(shape.width or 0) * PT_PER_EMU * factor, float(shape.height or 0) * PT_PER_EMU * factor)
    with tempfile.TemporaryDirectory() as tmp:
        for slide in prs.slides:
            out = deck_model.new_slide('blank', deck['theme'], (deck['width'], deck['height']))
            for shape in slide.shapes:
                try:
                    x, y, w, h = box(shape)
                    if shape.shape_type == MSO_SHAPE_TYPE.PICTURE:
                        image = shape.image
                        temp = Path(tmp) / f'picture_{len(out["items"])}.{image.ext}'
                        temp.write_bytes(image.blob)
                        rel = deck_model.add_media(folder, temp)
                        out['items'].append(deck_model.make_item(deck_model.media_kind(temp), x, y, w, h, src=rel,
                                                                 fit='stretch'))
                    elif shape.has_text_frame and shape.text_frame.text.strip():
                        html = ''.join(_paragraph_html(p, factor) for p in shape.text_frame.paragraphs)
                        role = 'title' if getattr(shape, 'is_placeholder', False) and \
                            'title' in str(shape.placeholder_format.type).lower() else 'body'
                        out['items'].append(deck_model.make_item('text', x, y, w, h, html=html, role=role))
                    elif shape.shape_type == MSO_SHAPE_TYPE.AUTO_SHAPE:
                        color = ''
                        try:
                            if shape.fill.type == 1:
                                color = '#' + str(shape.fill.fore_color.rgb)
                        except Exception:
                            pass
                        out['items'].append(deck_model.make_item('shape', x, y, w, h, shape='rect',
                                                                 fill_color=color or '#E9ECEF'))
                except Exception:
                    continue
            if slide.has_notes_slide:
                out['notes'] = slide.notes_slide.notes_text_frame.text
            deck['slides'].append(out)
    deck_model.save(deck, file)
    return file


def _paragraph_html(paragraph, factor):
    from html import escape
    name = str(paragraph.alignment or '').upper()
    align = 'center' if 'CENTER' in name else 'right' if 'RIGHT' in name else 'justify' if 'JUSTIFY' in name else 'left'
    runs = []
    for run in paragraph.runs:
        style = []
        if run.font.size:
            style.append(f'font-size:{run.font.size.pt * factor:.1f}pt')
        if run.font.bold:
            style.append('font-weight:700')
        if run.font.italic:
            style.append('font-style:italic')
        try:
            if run.font.color and run.font.color.type is not None and run.font.color.rgb is not None:
                style.append(f'color:#{run.font.color.rgb}')
        except AttributeError:
            pass
        runs.append(f'<span style="{";".join(style)}">{escape(run.text)}</span>')
    return f'<p align="{align}" style="margin:0">{"".join(runs) or "&nbsp;"}</p>'
