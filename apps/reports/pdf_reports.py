"""Branded PDF report builder for HRMIS.

Pure ReportLab (no extra dependencies) and free of Django imports, so it can be tested on its own:
pass in the dictionary produced by views._data() and get PDF bytes back.

Design system
  * IOM-blue header band with the logo on page 1, slim band on later pages, "Page X of Y" footer
  * KPI cards, a callout of auto-written key messages, native bar / stacked-bar / column charts
  * Tables with wrapped text, right-aligned numbers, zebra rows and coloured status pills
"""
from __future__ import annotations

import math
import os
from io import BytesIO
from xml.sax.saxutils import escape

from reportlab.graphics.shapes import Drawing, Line, Rect, String
from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER, TA_RIGHT
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.lib.utils import ImageReader
from reportlab.pdfbase.pdfmetrics import stringWidth
from reportlab.pdfgen import canvas as rl_canvas
from reportlab.platypus import (BaseDocTemplate, CondPageBreak, Frame, HRFlowable, KeepTogether,
                                NextPageTemplate, PageTemplate, Paragraph, Spacer, Table, TableStyle)

# --------------------------------------------------------------------------------------
# Palette and layout constants
# --------------------------------------------------------------------------------------
IOM_BLUE = colors.HexColor('#003499')      # the flat blue inside the IOM logo file
INK = colors.HexColor('#0b1f4d')
MUTED = colors.HexColor('#5b6b8c')
LINE = colors.HexColor('#dde5f3')
MIST = colors.HexColor('#eaf0fa')
ZEBRA = colors.HexColor('#f7f9fd')
TRACK = colors.HexColor('#e6ecf6')
ACCENT = colors.HexColor('#f2a900')

# tone -> (foreground, background)
TONES = {
    'blue': ('#0033a0', '#eaf0fa'),
    'green': ('#16834a', '#e4f4ea'),
    'amber': ('#b87800', '#fdf1d6'),
    'red': ('#c43d3d', '#fbe8e8'),
    'grey': ('#5b6b8c', '#eef1f6'),
}

PAGE_W, PAGE_H = A4
MARGIN_X = 16 * mm
CONTENT_W = PAGE_W - 2 * MARGIN_X
FOOTER_H = 16 * mm
FIRST_BAND_H = 42 * mm
LATER_BAND_H = 12 * mm

STATUS_META = [          # key, label, colour (same colours as the map markers)
    ('REGISTERED', 'Registered', '#0033a0'),
    ('IN_PROGRESS', 'Under reconstruction', '#d18a00'),
    ('COMPLETED', 'Completed', '#16834a'),
    ('HANDED_OVER', 'Handed over', '#0f6b3d'),
    ('ON_HOLD', 'On hold', '#c43d3d'),
]

AUDIENCES = {
    'programme': ('Programme operational report', 'Operational report'),
    'management': ('Country Office management report', 'Management report'),
    'donor': ('Donor progress report', 'Donor report'),
}

# donor-facing wording for each follow-up category (no beneficiary-level detail in donor reports)
DONOR_RESPONSE = {
    'ON_HOLD': 'Reasons for the hold are reviewed and a recovery plan is agreed before work resumes.',
    'STALE': 'Site engineers are asked for an update and the next milestone date is confirmed.',
    'CHANGES': 'Engineers resubmit progress with supporting evidence after supervisor review.',
    'INSPECTION_REVIEW': 'Supervisors review the inspection outcomes and record their decision.',
    'INSPECTION_FAILED': 'Corrective works are carried out and a reinspection is arranged.',
    'DEFECT_OVERDUE': 'Corrective actions are tracked to completion and verified by inspectors.',
}


# --------------------------------------------------------------------------------------
# Small helpers
# --------------------------------------------------------------------------------------
def esc(value) -> str:
    return escape(str(value if value is not None else ''))


def num(value, default=0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def fit_text(text, font, size, max_width) -> str:
    text = str(text)
    if stringWidth(text, font, size) <= max_width:
        return text
    while text and stringWidth(text + '...', font, size) > max_width:
        text = text[:-1]
    return text.rstrip() + '...'


def delta(current, previous, good='up'):
    """Return (text, tone) describing the change between two counts."""
    current, previous = num(current), num(previous)
    if current == previous:
        return 'no change', 'grey'
    if previous == 0:
        text, up = f'+{current:.0f} (new)', True
    else:
        pct = (current - previous) / previous * 100
        text, up = f'{pct:+.0f}%', pct > 0
    if good == 'neutral':
        return text, 'grey'
    positive = up if good == 'up' else not up
    return text, 'green' if positive else 'amber'


def make_styles():
    base = getSampleStyleSheet()
    body = ParagraphStyle('body', parent=base['BodyText'], fontName='Helvetica', fontSize=9, leading=13.2,
                          textColor=INK, spaceAfter=4)
    cell = ParagraphStyle('cell', parent=body, fontSize=8, leading=10.6, spaceAfter=0)
    th = ParagraphStyle('th', parent=cell, fontName='Helvetica-Bold', textColor=colors.white, fontSize=7.6)
    return {
        'body': body,
        'small': ParagraphStyle('small', parent=body, fontSize=7.4, leading=10.4, textColor=MUTED, spaceAfter=0),
        'cell': cell,
        'cell_r': ParagraphStyle('cell_r', parent=cell, alignment=TA_RIGHT),
        'cell_c': ParagraphStyle('cell_c', parent=cell, alignment=TA_CENTER),
        'cell_muted': ParagraphStyle('cell_muted', parent=cell, textColor=MUTED, alignment=TA_CENTER),
        'th': th,
        'th_r': ParagraphStyle('th_r', parent=th, alignment=TA_RIGHT),
        'th_c': ParagraphStyle('th_c', parent=th, alignment=TA_CENTER),
        'h2': ParagraphStyle('h2', parent=body, fontName='Helvetica-Bold', fontSize=12.5, leading=16,
                             textColor=IOM_BLUE, spaceBefore=12, spaceAfter=2, keepWithNext=True),
        'h3': ParagraphStyle('h3', parent=body, fontName='Helvetica-Bold', fontSize=9.4, leading=12,
                             textColor=INK, spaceBefore=7, spaceAfter=4, keepWithNext=True),
        'kpi_value': ParagraphStyle('kpi_value', parent=body, fontName='Helvetica-Bold', fontSize=19, leading=22,
                                    spaceAfter=1),
        'kpi_label': ParagraphStyle('kpi_label', parent=body, fontSize=7.8, leading=10, textColor=MUTED, spaceAfter=0),
        'kpi_sub': ParagraphStyle('kpi_sub', parent=body, fontSize=7.2, leading=9.6, textColor=MUTED, spaceAfter=0,
                                  spaceBefore=2),
        'bullet': ParagraphStyle('bullet', parent=body, fontSize=8.8, leading=12.4, leftIndent=10, bulletIndent=0,
                                 spaceAfter=2),
        'callout_title': ParagraphStyle('callout_title', parent=body, fontName='Helvetica-Bold', fontSize=9,
                                        leading=12, spaceAfter=3),
    }


# --------------------------------------------------------------------------------------
# Building blocks
# --------------------------------------------------------------------------------------
def section(styles, number, title):
    rule = HRFlowable(width='100%', thickness=1.1, color=IOM_BLUE, spaceBefore=0, spaceAfter=6)
    rule.keepWithNext = True
    return [CondPageBreak(62 * mm), Paragraph(f'{number}. {esc(title)}', styles['h2']), rule]


def kpi_cards(styles, cards, width=CONTENT_W):
    """cards: [{'value','label','sub','tone'}]  (value/sub may contain simple markup)."""
    n = len(cards)
    gap = 3 * mm
    card_w = (width - gap * (n - 1)) / n
    cells, widths, cmds = [], [], [('VALIGN', (0, 0), (-1, -1), 'TOP')]
    for i, card in enumerate(cards):
        if i:
            cells.append('')
            widths.append(gap)
        fg = TONES[card.get('tone', 'blue')][0]
        content = [Paragraph(f'<font color="{fg}">{card["value"]}</font>', styles['kpi_value']),
                   Paragraph(esc(card['label']), styles['kpi_label'])]
        if card.get('sub'):
            content.append(Paragraph(card['sub'], styles['kpi_sub']))
        cells.append(content)
        widths.append(card_w)
        col = i * 2
        cmds += [('BOX', (col, 0), (col, 0), .6, LINE), ('LINEBEFORE', (col, 0), (col, 0), 3, colors.HexColor(fg)),
                 ('LEFTPADDING', (col, 0), (col, 0), 10), ('RIGHTPADDING', (col, 0), (col, 0), 6),
                 ('TOPPADDING', (col, 0), (col, 0), 8), ('BOTTOMPADDING', (col, 0), (col, 0), 8)]
        if i < n - 1:
            g = col + 1
            cmds += [('LEFTPADDING', (g, 0), (g, 0), 0), ('RIGHTPADDING', (g, 0), (g, 0), 0)]
    t = Table([cells], colWidths=widths)
    t.setStyle(TableStyle(cmds))
    return t


def callout(styles, title, bullets, tone='blue', width=CONTENT_W):
    fg, bg = TONES[tone]
    content = [Paragraph(f'<font color="{fg}">{esc(title)}</font>', styles['callout_title'])]
    content += [Paragraph(b, styles['bullet'], bulletText='\u2022') for b in bullets]
    t = Table([[content]], colWidths=[width])
    t.setStyle(TableStyle([
        ('BACKGROUND', (0, 0), (-1, -1), colors.HexColor(bg)),
        ('LINEBEFORE', (0, 0), (0, -1), 3, colors.HexColor(fg)),
        ('LEFTPADDING', (0, 0), (-1, -1), 12), ('RIGHTPADDING', (0, 0), (-1, -1), 12),
        ('TOPPADDING', (0, 0), (-1, -1), 8), ('BOTTOMPADDING', (0, 0), (-1, -1), 6),
    ]))
    return t


def data_table(styles, headers, rows, widths, align=None, empty_text='No items to report for this period.'):
    """rows: lists of str | {'text','tone','bold'}; text is escaped automatically."""
    align = align or ['L'] * len(headers)
    th = {'L': styles['th'], 'R': styles['th_r'], 'C': styles['th_c']}
    td = {'L': styles['cell'], 'R': styles['cell_r'], 'C': styles['cell_c']}
    data = [[Paragraph(esc(h), th[a]) for h, a in zip(headers, align)]]
    cmds = [('BACKGROUND', (0, 0), (-1, 0), IOM_BLUE), ('BOX', (0, 0), (-1, -1), .5, LINE),
            ('LINEBELOW', (0, 1), (-1, -1), .4, LINE), ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
            ('LEFTPADDING', (0, 0), (-1, -1), 6), ('RIGHTPADDING', (0, 0), (-1, -1), 6),
            ('TOPPADDING', (0, 0), (-1, -1), 4.5), ('BOTTOMPADDING', (0, 0), (-1, -1), 4.5)]
    tone_cmds = []
    if not rows:
        data.append([Paragraph(esc(empty_text), styles['cell_muted'])] + [''] * (len(headers) - 1))
        cmds += [('SPAN', (0, 1), (-1, 1)), ('TOPPADDING', (0, 1), (-1, 1), 9), ('BOTTOMPADDING', (0, 1), (-1, 1), 9)]
    for r, row in enumerate(rows, start=1):
        if r % 2 == 0:
            cmds.append(('BACKGROUND', (0, r), (-1, r), ZEBRA))
        out = []
        for c, (cell, a) in enumerate(zip(row, align)):
            if isinstance(cell, dict):
                text, tone, bold = esc(cell.get('text', '')), cell.get('tone'), cell.get('bold', bool(cell.get('tone')))
                if tone:
                    fg, bg = TONES[tone]
                    text = f'<font color="{fg}">{text}</font>'
                    tone_cmds.append(('BACKGROUND', (c, r), (c, r), colors.HexColor(bg)))
                if bold:
                    text = f'<b>{text}</b>'
            else:
                text = esc(cell)
            out.append(Paragraph(text, td[a]))
        data.append(out)
    t = Table(data, colWidths=widths, repeatRows=1, hAlign='LEFT')
    t.setStyle(TableStyle(cmds + tone_cmds))
    return t


def bar_list(rows, width=CONTENT_W, label_w=62 * mm, value_w=22 * mm, row_h=7.4 * mm, color=IOM_BLUE):
    """rows: [(label, percent 0-100, right-hand text)] -> horizontal progress bars."""
    h = row_h * max(len(rows), 1)
    d = Drawing(width, h)
    track_x, track_w, bar_h = label_w, width - label_w - value_w, 3.4 * mm
    for i, (label, value, text) in enumerate(rows):
        y = h - (i + 1) * row_h + (row_h - bar_h) / 2
        d.add(String(0, y + 0.5 * mm, fit_text(label, 'Helvetica', 8, label_w - 4 * mm), fontName='Helvetica',
                     fontSize=8, fillColor=INK))
        d.add(Rect(track_x, y, track_w, bar_h, rx=bar_h / 2, ry=bar_h / 2, fillColor=TRACK, strokeColor=None,
                   strokeWidth=0))
        fw = track_w * max(0.0, min(100.0, num(value))) / 100
        if fw > 0:
            d.add(Rect(track_x, y, max(fw, bar_h), bar_h, rx=bar_h / 2, ry=bar_h / 2, fillColor=color,
                       strokeColor=None, strokeWidth=0))
        d.add(String(width, y + 0.5 * mm, text, textAnchor='end', fontName='Helvetica-Bold', fontSize=8,
                     fillColor=INK))
    return d


def stacked_bar(segments, width=CONTENT_W, height=6.5 * mm):
    """segments: [(label, count, '#hex')]"""
    total = sum(num(v) for _, v, _ in segments)
    d = Drawing(width, height)
    d.add(Rect(0, 0, width, height, fillColor=TRACK, strokeColor=None, strokeWidth=0))
    x = 0.0
    for _, v, col in segments:
        if total and num(v) > 0:
            w = width * num(v) / total
            d.add(Rect(x, 0, w, height, fillColor=colors.HexColor(col), strokeColor=colors.white, strokeWidth=0.8))
            x += w
    return d


def legend(styles, segments, width=CONTENT_W):
    total = sum(num(v) for _, v, _ in segments)
    n = len(segments)
    sw = 4 * mm
    cell_w = width / n - sw
    cells, widths = [], []
    for label, v, col in segments:
        sq = Drawing(sw, 3 * mm)
        sq.add(Rect(0, 0, 2.6 * mm, 2.6 * mm, rx=0.6 * mm, ry=0.6 * mm, fillColor=colors.HexColor(col),
                    strokeColor=None, strokeWidth=0))
        pct = f'{num(v) / total * 100:.1f}%' if total else '0.0%'
        cells += [sq, Paragraph(f'<b>{esc(label)}</b><br/>{num(v):.0f} ({pct})', styles['small'])]
        widths += [sw, cell_w]
    t = Table([cells], colWidths=widths, hAlign='LEFT')
    t.setStyle(TableStyle([('VALIGN', (0, 0), (-1, -1), 'TOP'), ('LEFTPADDING', (0, 0), (-1, -1), 0),
                           ('RIGHTPADDING', (0, 0), (-1, -1), 2), ('TOPPADDING', (0, 0), (-1, -1), 4),
                           ('BOTTOMPADDING', (0, 0), (-1, -1), 0)]))
    return t


def column_chart(labels, series, width=CONTENT_W, height=46 * mm):
    """series: [(name, [values], '#hex')] -> grouped columns with grid lines and a legend."""
    d = Drawing(width, height)
    left, bottom, top, right = 9 * mm, 8 * mm, 7 * mm, 2 * mm
    plot_w, plot_h = width - left - right, height - bottom - top
    max_v = max([1] + [num(v) for _, vals, _ in series for v in vals])
    step = max(1, math.ceil(max_v / 4))
    axis_max = step * 4
    for k in range(5):
        y = bottom + plot_h * k / 4
        d.add(Line(left, y, width - right, y, strokeColor=LINE if k else colors.HexColor('#b9c7e6'), strokeWidth=.6))
        d.add(String(left - 2 * mm, y - 1 * mm, str(step * k), textAnchor='end', fontName='Helvetica', fontSize=6.5,
                     fillColor=MUTED))
    n = max(len(labels), 1)
    slot = plot_w / n
    group_w = slot * 0.72
    bar_w = group_w / max(len(series), 1)
    every = max(1, math.ceil(n / 12))
    for i, label in enumerate(labels):
        gx = left + i * slot + (slot - group_w) / 2
        for s, (_, vals, col) in enumerate(series):
            v = num(vals[i]) if i < len(vals) else 0
            bh = plot_h * v / axis_max
            if bh > 0:
                d.add(Rect(gx + s * bar_w, bottom, bar_w * 0.92, bh, fillColor=colors.HexColor(col),
                           strokeColor=None, strokeWidth=0))
        if i % every == 0:
            d.add(String(left + i * slot + slot / 2, bottom - 4.5 * mm, label, textAnchor='middle',
                         fontName='Helvetica', fontSize=6.5, fillColor=MUTED))
    lx = width - right
    for name, _, col in reversed(series):
        w = stringWidth(name, 'Helvetica', 7)
        lx -= w
        d.add(String(lx, height - 4.2 * mm, name, fontName='Helvetica', fontSize=7, fillColor=INK))
        lx -= 4 * mm
        d.add(Rect(lx, height - 4.4 * mm, 2.8 * mm, 2.8 * mm, rx=0.5 * mm, ry=0.5 * mm, fillColor=colors.HexColor(col),
                   strokeColor=None, strokeWidth=0))
        lx -= 4 * mm
    return d


def note_box(styles, text, width=CONTENT_W):
    t = Table([[Paragraph(text, styles['small'])]], colWidths=[width])
    t.setStyle(TableStyle([('BACKGROUND', (0, 0), (-1, -1), ZEBRA), ('BOX', (0, 0), (-1, -1), .5, LINE),
                           ('LEFTPADDING', (0, 0), (-1, -1), 9), ('RIGHTPADDING', (0, 0), (-1, -1), 9),
                           ('TOPPADDING', (0, 0), (-1, -1), 7), ('BOTTOMPADDING', (0, 0), (-1, -1), 7)]))
    return t


# --------------------------------------------------------------------------------------
# Page furniture (header band, footer, "Page X of Y")
# --------------------------------------------------------------------------------------
class _ReportCanvas(rl_canvas.Canvas):
    def __init__(self, *args, meta=None, **kwargs):
        super().__init__(*args, **kwargs)
        self._states = []
        self._meta = meta or {}

    def showPage(self):
        self._states.append(dict(self.__dict__))
        self._startPage()

    def save(self):
        total = len(self._states)
        for state in self._states:
            self.__dict__.update(state)
            self._decorate(total)
            super().showPage()
        super().save()

    # -- drawing ------------------------------------------------------------------
    def _logo(self, x, y, height):
        path = self._meta.get('logo_path')
        if path and os.path.exists(path):
            try:
                img = ImageReader(path)
                iw, ih = img.getSize()
                self.drawImage(img, x, y, width=iw / ih * height, height=height)
                return True
            except Exception:  # unreadable logo: fall back to text
                pass
        self.setFillColor(colors.white)
        self.setFont('Helvetica-Bold', 13)
        self.drawString(x, y + height / 2 - 4, 'IOM')
        return False

    def _decorate(self, total):
        m, page = self._meta, self._pageNumber
        self.saveState()
        if page == 1:
            self.setFillColor(IOM_BLUE)
            self.rect(0, PAGE_H - FIRST_BAND_H, PAGE_W, FIRST_BAND_H, stroke=0, fill=1)
            self.setFillColor(ACCENT)
            self.rect(0, PAGE_H - FIRST_BAND_H - 1.4 * mm, PAGE_W, 1.4 * mm, stroke=0, fill=1)
            self._logo(MARGIN_X, PAGE_H - 8 * mm - 15 * mm, 15 * mm)
            self.setFillColor(colors.HexColor('#c3d0ee'))
            self.setFont('Helvetica-Bold', 7.5)
            self.drawRightString(PAGE_W - MARGIN_X, PAGE_H - 12 * mm, m.get('tag', '').upper())
            self.drawRightString(PAGE_W - MARGIN_X, PAGE_H - 16.5 * mm, 'HOUSING RECONSTRUCTION  |  HRMIS')
            self.setFillColor(colors.white)
            self.setFont('Helvetica-Bold', 20)
            self.drawString(MARGIN_X, PAGE_H - 31 * mm, m.get('title', ''))
            self.setFillColor(colors.HexColor('#c3d0ee'))
            self.setFont('Helvetica', 9.5)
            self.drawString(MARGIN_X, PAGE_H - 37.5 * mm, m.get('subtitle', ''))
        else:
            self.setFillColor(IOM_BLUE)
            self.rect(0, PAGE_H - LATER_BAND_H, PAGE_W, LATER_BAND_H, stroke=0, fill=1)
            self._logo(MARGIN_X, PAGE_H - LATER_BAND_H + 2.25 * mm, 7.5 * mm)
            self.setFillColor(colors.white)
            self.setFont('Helvetica-Bold', 8)
            self.drawRightString(PAGE_W - MARGIN_X, PAGE_H - 7.6 * mm, m.get('title', ''))
            self.setFillColor(colors.HexColor('#c3d0ee'))
            self.setFont('Helvetica', 7)
            self.drawRightString(PAGE_W - MARGIN_X, PAGE_H - 10.4 * mm, m.get('period', ''))
        # footer
        self.setStrokeColor(LINE)
        self.setLineWidth(.6)
        self.line(MARGIN_X, 13 * mm, PAGE_W - MARGIN_X, 13 * mm)
        self.setFillColor(MUTED)
        self.setFont('Helvetica', 7)
        self.drawString(MARGIN_X, 8.4 * mm, 'HRMIS  |  IOM Micronesia Housing Reconstruction')
        self.drawCentredString(PAGE_W / 2 + 12 * mm, 8.4 * mm, m.get('generated', ''))
        self.drawRightString(PAGE_W - MARGIN_X, 8.4 * mm, f'Page {page} of {total}')
        self.restoreState()


# --------------------------------------------------------------------------------------
# Derived figures and auto-written messages
# --------------------------------------------------------------------------------------
def _derive(data, target):
    sc = data.get('status_counts') or {}
    ex = data.get('exceptions') or []
    d = {
        'total': int(num(data.get('total_houses'))),
        'coverage': num(data.get('coverage')),
        'progress': num(data.get('programme_progress')),
        'avg_progress': num(data.get('average_progress')),
        'in_progress': int(num(sc.get('IN_PROGRESS'))),
        'on_hold': int(num(sc.get('ON_HOLD'))),
        'completed': int(num(sc.get('COMPLETED')) + num(sc.get('HANDED_OVER'))),
        'approved': int(num(data.get('approved_updates'))),
        'pending': int(num(data.get('pending_updates'))),
        'changes': int(num(data.get('changes_requested'))),
        'prev_approved': int(num(data.get('previous_approved_updates'))),
        'prev_pending': int(num(data.get('previous_pending_updates'))),
        'prev_changes': int(num(data.get('previous_changes_requested'))),
        'insp_total': int(num(data.get('inspections_total'))),
        'insp_pass': int(num(data.get('inspections_pass'))),
        'insp_cond': int(num(data.get('inspections_conditional'))),
        'insp_fail': int(num(data.get('inspections_fail'))),
        'insp_pending': int(num(data.get('inspections_pending'))),
        'def_new': int(num(data.get('defects_new'))),
        'def_open': int(num(data.get('defects_open'))),
        'def_overdue': int(num(data.get('defects_overdue'))),
        'def_closed': int(num(data.get('defects_closed_period'))),
        'target': target,
        'exceptions': ex,
        'high': sum(1 for e in ex if e.get('priority') == 'HIGH'),
    }
    d['medium'] = len(ex) - d['high']
    d['stale'] = sum(1 for e in ex if e.get('category') == 'STALE')
    return d


def _key_messages(d):
    msgs = [f'<b>{d["total"]} of {d["target"]} target houses</b> are registered ({d["coverage"]:.1f}% of the '
            f'programme); verified physical progress stands at <b>{d["progress"]:.2f}%</b> of the target.']
    change, _ = delta(d['approved'], d['prev_approved'])
    if d['prev_approved']:
        msgs.append(f'<b>{d["approved"]}</b> progress update(s) were approved in the period, compared with '
                    f'{d["prev_approved"]} in the previous period ({change}).')
    else:
        msgs.append(f'<b>{d["approved"]}</b> progress update(s) were approved in the period; the previous '
                    f'comparable period had none.')
    if d['pending'] or d['changes']:
        msgs.append(f'<b>{d["pending"]}</b> submission(s) await supervisor review and <b>{d["changes"]}</b> were '
                    f'returned for changes.')
    if d['insp_total']:
        rate = d['insp_pass'] / d['insp_total'] * 100
        msgs.append(f'<b>{d["insp_total"]}</b> inspection(s) were carried out: {rate:.0f}% passed outright, '
                    f'{d["insp_cond"]} conditional and {d["insp_fail"]} failed.')
    if d['exceptions']:
        msgs.append(f'<b>{d["high"]}</b> high-priority and <b>{d["medium"]}</b> medium-priority follow-up item(s) '
                    f'need action.')
    else:
        msgs.append('No houses are currently flagged for follow-up.')
    if d['def_overdue']:
        msgs.append(f'<b>{d["def_overdue"]}</b> defect corrective action(s) are overdue ({d["def_open"]} defects open).')
    return msgs


def _status_segments(data):
    sc = data.get('status_counts') or {}
    return [(label, num(sc.get(key)), col) for key, label, col in STATUS_META]


def _trend(data):
    t = data.get('trend') or {}
    labels = t.get('labels') or []
    if not labels or not (any(t.get('submitted') or []) or any(t.get('approved') or [])):
        return None
    return labels, [('Submitted', t.get('submitted') or [], '#9fb3e0'), ('Approved', t.get('approved') or [], '#003499')]


def _common_blocks(styles, data, d):
    """Blocks shared by several reports. Each returns a list of flowables."""
    def status_distribution():
        segs = _status_segments(data)
        return [KeepTogether([Paragraph('House status distribution', styles['h3']), stacked_bar(segs),
                              legend(styles, segs)])]

    def activity_table():
        rows = []
        for label, cur, prev, good in (('Approved progress updates', d['approved'], d['prev_approved'], 'up'),
                                       ('Pending supervisor review', d['pending'], d['prev_pending'], 'down'),
                                       ('Changes requested', d['changes'], d['prev_changes'], 'down')):
            text, tone = delta(cur, prev, good)
            rows.append([label, str(prev), str(cur), {'text': text, 'tone': tone}])
        return KeepTogether([data_table(styles, ['Indicator', 'Previous period', 'Current period', 'Change'], rows,
                                        [70 * mm, 36 * mm, 36 * mm, 36 * mm], ['L', 'R', 'R', 'C'])])

    def trend_chart():
        tr = _trend(data)
        if not tr:
            return []
        labels, series = tr
        title = 'Progress submissions per week' if (data.get('trend') or {}).get('weekly') \
            else 'Progress submissions per day'
        return [KeepTogether([Paragraph(title, styles['h3']), column_chart(labels, series)])]

    def milestone_bars():
        rows = data.get('milestone_rows') or []
        if not rows:
            return [Paragraph('No active construction milestones are configured.', styles['small'])]
        total = max(d['total'], 1)
        out = []
        for i, r in enumerate(rows, start=1):
            weight = f' ({num(r.get("weight")):.0f}%)' if r.get('weight') is not None else ''
            out.append((f'{i}. {r["name"]}{weight}', num(r['average']),
                        f'{num(r["average"]):.1f}%  |  {int(num(r["updated_houses"]))}/{total}'))
        return [KeepTogether([bar_list(out, label_w=70 * mm, value_w=34 * mm)])]

    def inspection_quality():
        segs = [('Passed', d['insp_pass'], '#16834a'), ('Conditional', d['insp_cond'], '#d18a00'),
                ('Failed', d['insp_fail'], '#c43d3d')]
        out = []
        if d['insp_total']:
            out.append(KeepTogether([Paragraph('Inspection outcomes in the period', styles['h3']), stacked_bar(segs),
                                     legend(styles, segs, width=CONTENT_W * 0.66)]))
        else:
            out.append(Paragraph('No inspections were recorded in this period.', styles['body']))
        out += [Spacer(1, 3 * mm), kpi_cards(styles, [
            {'value': str(d['def_new']), 'label': 'New defects', 'tone': 'amber'},
            {'value': str(d['def_open']), 'label': 'Currently open', 'tone': 'blue'},
            {'value': str(d['def_overdue']), 'label': 'Overdue', 'tone': 'red' if d['def_overdue'] else 'green'},
            {'value': str(d['def_closed']), 'label': 'Verified closed in period', 'tone': 'green'}])]
        return out

    def island_table(with_progress=True):
        rows = data.get('island_rows') or []
        headers = ['Island', 'Registered', 'Under reconstruction', 'Completed / handed over']
        widths = [46 * mm, 30 * mm, 50 * mm, 52 * mm]
        align = ['L', 'R', 'R', 'R']
        if with_progress:
            headers.append('Avg. progress')
            widths = [38 * mm, 26 * mm, 40 * mm, 40 * mm, 34 * mm]
            align.append('R')
        body = []
        for r in rows:
            row = [r['name'], str(r['houses']), str(r['in_progress']), str(r['completed'])]
            if with_progress:
                row.append(f'{num(r.get("average_progress")):.1f}%')
            body.append(row)
        return data_table(styles, headers, body, widths, align, 'No island data for this selection.')

    def exception_summary(donor=False):
        summary = data.get('exception_summary') or []
        if donor:
            rows = [[r['issue'], str(r['count']), DONOR_RESPONSE.get(r.get('category'), r.get('action', ''))]
                    for r in summary]
            return data_table(styles, ['Challenge', 'Houses', 'Programme response'], rows,
                              [58 * mm, 20 * mm, 100 * mm], ['L', 'R', 'L'], 'No implementation challenges flagged.')
        rows = [[{'text': 'High' if r['priority'] == 'HIGH' else 'Medium',
                  'tone': 'red' if r['priority'] == 'HIGH' else 'amber'}, r['issue'], str(r['count']),
                 r.get('action', '')] for r in summary]
        return data_table(styles, ['Priority', 'Issue', 'Houses', 'Suggested follow-up'], rows,
                          [20 * mm, 62 * mm, 18 * mm, 78 * mm], ['C', 'L', 'R', 'L'], 'No follow-up items flagged.')

    def exception_detail(limit):
        ex = d['exceptions'][:limit]
        rows = [[{'text': 'High' if e.get('priority') == 'HIGH' else 'Medium',
                  'tone': 'red' if e.get('priority') == 'HIGH' else 'amber'},
                 e['house_id'], e['issue'], e['engineer'], e['action']] for e in ex]
        out = [data_table(styles, ['Priority', 'House ID', 'Issue', 'Assigned engineer', 'Suggested follow-up'], rows,
                          [18 * mm, 24 * mm, 46 * mm, 34 * mm, 56 * mm], ['C', 'L', 'L', 'L', 'L'],
                          'No houses are currently flagged.')]
        if len(d['exceptions']) > limit:
            out.append(Paragraph(f'Showing the {limit} highest-priority items of {len(d["exceptions"])}. '
                                 f'The full list is available in the HRMIS Reports page.', styles['small']))
        return out

    def engineer_table(limit):
        rows = (data.get('engineer_rows') or [])[:limit]
        body = [[r['name'], str(r['houses']), f'{num(r["average_progress"]):.1f}%', str(r['submissions']),
                 str(r['approved']), str(r['pending']), str(r['changes'])] for r in rows]
        return data_table(styles, ['Engineer', 'Houses', 'Avg. progress', 'Submitted', 'Approved', 'Pending', 'Changes'],
                          body, [52 * mm, 18 * mm, 26 * mm, 22 * mm, 22 * mm, 20 * mm, 18 * mm],
                          ['L', 'R', 'R', 'R', 'R', 'R', 'R'], 'No engineer assignments in this selection.')

    return {k: v for k, v in locals().items() if callable(v)}


METHODOLOGY = ('<b>Reporting methodology.</b> Official physical progress uses the latest supervisor-approved record for '
               'each active construction milestone. Programme progress is weighted by milestone weights and measured '
               'against the 700-house programme target. Pending and changes-requested submissions are excluded. '
               'Inspection and defect indicators are reported separately from construction progress. Previous-period '
               'figures compare an equal-length period immediately before the selected reporting period.')


# --------------------------------------------------------------------------------------
# The three reports
# --------------------------------------------------------------------------------------
def _programme_story(styles, data, d, b):
    s = []
    s += section(styles, 1, 'Operational snapshot')
    change, tone = delta(d['approved'], d['prev_approved'])
    s.append(kpi_cards(styles, [
        {'value': str(d['total']), 'label': 'Houses registered', 'sub': f'{d["coverage"]:.1f}% of {d["target"]} target'},
        {'value': str(d['in_progress']), 'label': 'Under reconstruction', 'tone': 'amber',
         'sub': f'{d["on_hold"]} on hold'},
        {'value': str(d['approved']), 'label': 'Updates approved in period', 'tone': 'green',
         'sub': f'<font color="{TONES[tone][0]}">{esc(change)}</font> vs previous period'},
        {'value': str(len(d['exceptions'])), 'label': 'Follow-up items',
         'tone': 'red' if d['high'] else 'blue', 'sub': f'{d["high"]} high priority'}]))
    s += [Spacer(1, 4 * mm), callout(styles, 'Key messages', _key_messages(d))]

    s += section(styles, 2, 'Reporting activity')
    s += b['trend_chart']()
    s += [Spacer(1, 2 * mm), b['activity_table']()]

    s += section(styles, 3, 'Houses requiring follow-up')
    s += [b['exception_summary'](), Spacer(1, 3 * mm)]
    s += b['exception_detail'](40)

    s += section(styles, 4, 'Inspection and defect workload')
    s += b['inspection_quality']()
    if d['insp_pending']:
        s.append(Paragraph(f'{d["insp_pending"]} inspection(s) are awaiting supervisor review.', styles['body']))

    s += section(styles, 5, 'Construction milestone snapshot')
    s += b['milestone_bars']()

    s += section(styles, 6, 'Engineer workload')
    s.append(b['engineer_table'](12))

    s += section(styles, 7, 'Priorities for the next period')
    prio = []
    if d['pending']:
        prio.append(f'Clear the <b>{d["pending"]}</b> progress submission(s) awaiting supervisor review.')
    if d['changes']:
        prio.append(f'Follow up with engineers on <b>{d["changes"]}</b> submission(s) returned for changes.')
    if d['insp_fail']:
        prio.append(f'Resolve findings from <b>{d["insp_fail"]}</b> failed inspection(s) and arrange reinspection.')
    if d['def_overdue']:
        prio.append(f'Close out <b>{d["def_overdue"]}</b> overdue defect corrective action(s).')
    if d['stale']:
        prio.append(f'Request site updates for <b>{d["stale"]}</b> house(s) with no approved update in 30+ days.')
    if d['on_hold']:
        prio.append(f'Confirm recovery plans for the <b>{d["on_hold"]}</b> house(s) on hold.')
    if not prio:
        prio.append('Continue timely progress submissions and scheduled quality inspections.')
    prio.append('Confirm an accountable staff member and target date for every action above.')
    s.append(callout(styles, 'Actions', prio, tone='blue'))
    return s


def _management_story(styles, data, d, b):
    s = []
    s += section(styles, 1, 'Executive summary')
    s.append(kpi_cards(styles, [
        {'value': str(d['total']), 'label': 'Houses registered', 'sub': f'{d["coverage"]:.1f}% of {d["target"]} target'},
        {'value': f'{d["progress"]:.2f}%', 'label': 'Programme physical progress', 'sub': 'verified, weighted'},
        {'value': str(d['in_progress']), 'label': 'Under reconstruction', 'tone': 'amber',
         'sub': f'{d["on_hold"]} on hold'},
        {'value': str(d['completed']), 'label': 'Completed / handed over', 'tone': 'green'}]))
    s += [Spacer(1, 4 * mm), callout(styles, 'Key messages', _key_messages(d)), Spacer(1, 2 * mm)]
    s.append(KeepTogether([Paragraph('Progress against the 700-house target', styles['h3']),
                           bar_list([('Registration coverage', d['coverage'], f'{d["coverage"]:.1f}%'),
                                     ('Verified physical progress', d['progress'], f'{d["progress"]:.2f}%')],
                                    label_w=62 * mm, value_w=20 * mm)]))
    s += b['status_distribution']()

    s += section(styles, 2, 'Period activity compared with the previous period')
    s += b['trend_chart']()
    s += [Spacer(1, 2 * mm), b['activity_table']()]

    s += section(styles, 3, 'Geographic coverage')
    s.append(b['island_table'](True))

    s += section(styles, 4, 'Milestone performance')
    s += b['milestone_bars']()

    s += section(styles, 5, 'Quality assurance and implementation risks')
    s += b['inspection_quality']()

    s += section(styles, 6, 'Implementation team')
    s.append(b['engineer_table'](8))

    s += section(styles, 7, 'Management attention required')
    s += [b['exception_summary'](), Spacer(1, 3 * mm)]
    if d['high']:
        s += [CondPageBreak(45 * mm), Paragraph('Highest-priority houses', styles['h3'])]
        top = [e for e in d['exceptions'] if e.get('priority') == 'HIGH']
        data_for_top = dict(data, exceptions=top)
        d_top = dict(d, exceptions=top)
        s += _common_blocks(styles, data_for_top, d_top)['exception_detail'](10)
    return s


def _donor_story(styles, data, d, b):
    s = []
    s += section(styles, 1, 'Results at a glance')
    s.append(Paragraph(
        f'HRMIS recorded <b>{d["total"]} houses</b> in the programme registry against a target of {d["target"]} '
        f'({d["coverage"]:.1f}% registration coverage). Verified physical progress stands at '
        f'<b>{d["progress"]:.2f}%</b>, based on supervisor-approved construction milestone records.', styles['body']))
    s.append(kpi_cards(styles, [
        {'value': str(d['total']), 'label': 'Houses registered', 'sub': f'target: {d["target"]}'},
        {'value': f'{d["progress"]:.2f}%', 'label': 'Physical progress'},
        {'value': str(d['in_progress']), 'label': 'Under reconstruction', 'tone': 'amber'},
        {'value': str(d['completed']), 'label': 'Completed / handed over', 'tone': 'green'}]))
    s += [Spacer(1, 3 * mm)]
    s.append(KeepTogether([Paragraph('Progress against the programme target', styles['h3']),
                           bar_list([('Registration coverage', d['coverage'], f'{d["coverage"]:.1f}%'),
                                     ('Verified physical progress', d['progress'], f'{d["progress"]:.2f}%')],
                                    label_w=62 * mm, value_w=20 * mm)]))
    s += b['status_distribution']()

    s += section(styles, 2, 'Construction progress by milestone')
    s += b['milestone_bars']()

    s += section(styles, 3, 'Geographic implementation coverage')
    s.append(b['island_table'](True))

    s += section(styles, 4, 'Reporting-period activity')
    s += b['trend_chart']()
    s += [Spacer(1, 2 * mm), b['activity_table']()]

    s += section(styles, 5, 'Quality assurance')
    s.append(Paragraph(
        f'The programme recorded <b>{d["insp_total"]}</b> inspection(s) in the period: {d["insp_pass"]} passed, '
        f'{d["insp_cond"]} passed with corrective actions and {d["insp_fail"]} failed. '
        f'{d["def_new"]} new defect(s) were recorded and {d["def_closed"]} were verified closed.', styles['body']))
    s += b['inspection_quality']()

    s += section(styles, 6, 'Implementation challenges and mitigation')
    s.append(Paragraph('Operational monitoring flags the items below for review. Programme teams follow up with '
                       'responsible staff and track corrective actions through HRMIS.', styles['body']))
    s.append(b['exception_summary'](donor=True))

    s += section(styles, 7, 'Priorities for the next reporting period')
    s.append(callout(styles, 'Planned focus', [
        'Continue reconstruction monitoring and timely engineering progress submissions.',
        'Complete the required quality inspections for each construction milestone.',
        'Follow up outstanding corrective actions and houses on hold until resolved.',
        'Maintain verified, evidence-based progress reporting against the programme target.']))
    return s


# --------------------------------------------------------------------------------------
# Public entry point
# --------------------------------------------------------------------------------------
def build_report_pdf(data, audience='management', *, generated_at=None, logo_path=None, target=700) -> bytes:
    if audience not in AUDIENCES:
        audience = 'management'
    title, tag = AUDIENCES[audience]
    start, end = data['start'], data['end']
    period = f'{start:%d %b %Y} - {end:%d %b %Y}'
    island_name = data.get('island_name')
    island_note = f'  |  {island_name}' if island_name else ''
    meta = {
        'title': title, 'tag': tag, 'logo_path': logo_path, 'period': period,
        'subtitle': f'Reporting period: {start:%d %B %Y} \u2013 {end:%d %B %Y}{island_note}',
        'generated': f'Generated {generated_at:%d %B %Y, %H:%M}' if generated_at else '',
    }
    styles = make_styles()
    d = _derive(data, target)
    blocks = _common_blocks(styles, data, d)

    buf = BytesIO()
    doc = BaseDocTemplate(buf, pagesize=A4, title=title, author='IOM Micronesia - HRMIS',
                          subject='Housing reconstruction programme monitoring',
                          leftMargin=MARGIN_X, rightMargin=MARGIN_X, topMargin=0, bottomMargin=FOOTER_H)
    frame_kw = dict(leftPadding=0, rightPadding=0, topPadding=0, bottomPadding=0)
    first = Frame(MARGIN_X, FOOTER_H, CONTENT_W, PAGE_H - FOOTER_H - FIRST_BAND_H - 9 * mm, id='first', **frame_kw)
    later = Frame(MARGIN_X, FOOTER_H, CONTENT_W, PAGE_H - FOOTER_H - LATER_BAND_H - 6 * mm, id='later', **frame_kw)
    doc.addPageTemplates([PageTemplate(id='first', frames=[first]), PageTemplate(id='later', frames=[later])])

    builder = {'programme': _programme_story, 'management': _management_story, 'donor': _donor_story}[audience]
    story = [NextPageTemplate('later')] + builder(styles, data, d, blocks)
    story += [Spacer(1, 6 * mm), note_box(styles, METHODOLOGY)]

    doc.build(story, canvasmaker=lambda *a, **k: _ReportCanvas(*a, meta=meta, **k))
    return buf.getvalue()
