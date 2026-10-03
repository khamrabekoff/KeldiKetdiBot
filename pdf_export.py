"""PDF export for reports"""
import html
import io
import logging
import os
from datetime import datetime, timedelta
import analytics
import database as db
import ui
import utils

logger = logging.getLogger(__name__)

try:
    from reportlab.lib.pagesizes import letter, A4
    from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
    from reportlab.lib.units import inch
    from reportlab.pdfbase import pdfmetrics
    from reportlab.pdfbase.ttfonts import TTFont
    from reportlab.platypus import SimpleDocTemplate, Table, TableStyle, Paragraph, Spacer, PageBreak
    from reportlab.lib import colors
    REPORTLAB_AVAILABLE = True
except ImportError:
    REPORTLAB_AVAILABLE = False
    logger.warning("reportlab not installed. PDF export will be disabled.")


def _money(amount):
    """The bare number. The unit lives in the column header instead, because
    repeating it in every cell does not fit the narrow money column."""
    return utils.format_money(amount, unit=False)


# Fonts that can draw Cyrillic, tried in order. Helvetica, reportlab's built-in,
# covers Latin only, so a name or an advance note typed in Cyrillic came out
# as black boxes. DejaVu is on PythonAnywhere; Arial covers runs on Windows.
FONT_CANDIDATES = [
    ('/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf',
     '/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf'),
    ('C:/Windows/Fonts/arial.ttf', 'C:/Windows/Fonts/arialbd.ttf'),
]
_fonts = None


def _unicode_fonts():
    """(regular, bold) font names, registered with reportlab on first use.
    Falls back to Helvetica - Latin only, but never a failed report."""
    global _fonts
    if _fonts:
        return _fonts
    for regular_path, bold_path in FONT_CANDIDATES:
        if not (os.path.exists(regular_path) and os.path.exists(bold_path)):
            continue
        try:
            pdfmetrics.registerFont(TTFont('KKSans', regular_path))
            pdfmetrics.registerFont(TTFont('KKSans-Bold', bold_path))
            _fonts = ('KKSans', 'KKSans-Bold')
            return _fonts
        except Exception as e:
            logger.warning(f"Could not register font {regular_path}: {e}")
    _fonts = ('Helvetica', 'Helvetica-Bold')
    return _fonts


def _bold_rows(indexes, bold_font):
    """Table cells are drawn as plain text - '<b>' would be printed literally -
    so bold goes through the table style instead."""
    return [('FONTNAME', (0, i), (-1, i), bold_font) for i in indexes]


def _payment_table(payroll, regular, bold_font):
    """Per employee: earned, advances (and carry and payments once months are
    settled in the bot), and what the admin still has to pay."""
    columns = analytics.payroll_columns(payroll)
    header_style = ParagraphStyle('PayHeader', fontName=bold_font, fontSize=9, leading=11,
                                  textColor=colors.whitesmoke, alignment=1)
    unit = f" ({utils.CURRENCY_LABEL})"
    data = [['Ism', 'Kunlar'] + [Paragraph(label + unit, header_style) for label, _ in columns]]
    for emp in payroll['employees']:
        data.append([emp['name'], str(emp['days'])] + [_money(emp[key]) for _, key in columns])
    totals = payroll['totals']
    data.append(['JAMI', ''] + [_money(totals[key]) for _, key in columns])

    money_width = min(1.35, 4.1 / len(columns))
    table = Table(data, colWidths=[1.5*inch, 0.6*inch] + [money_width*inch] * len(columns))
    table.setStyle(TableStyle([
        ('VALIGN', (0, 0), (-1, 0), 'MIDDLE'),
        ('FONTNAME', (0, 0), (-1, -1), regular),
        ('FONTNAME', (0, 0), (-1, 0), bold_font),
        ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor('#203864')),
        ('TEXTCOLOR', (0, 0), (-1, 0), colors.whitesmoke),
        ('ALIGN', (1, 0), (-1, -1), 'CENTER'),
        ('GRID', (0, 0), (-1, -1), 1, colors.black),
        ('ROWBACKGROUNDS', (0, 1), (-1, -2), [colors.white, colors.HexColor('#f0f0f0')]),
        ('FONTNAME', (-1, 1), (-1, -1), bold_font),
        ('FONTNAME', (0, -1), (-1, -1), bold_font),
        ('BACKGROUND', (0, -1), (-1, -1), colors.HexColor('#e7e6e6')),
        ('BACKGROUND', (-1, -1), (-1, -1), colors.HexColor('#ffc000')),
    ]))
    return table


def _advances_table(advances, regular, bold_font, note_style):
    data = [['Sana', 'Ism', f"Summa ({utils.CURRENCY_LABEL})", 'Izoh']]
    for advance in advances:
        note = Paragraph(html.escape(advance['note'] or ''), note_style)
        data.append([advance['date'].strftime('%d.%m.%Y'), advance['full_name'],
                     _money(advance['amount']), note])
    data.append(['', 'JAMI', _money(sum(a['amount'] for a in advances)), ''])

    table = Table(data, colWidths=[0.9*inch, 1.5*inch, 1.0*inch, 2.8*inch])
    table.setStyle(TableStyle([
        ('FONTNAME', (0, 0), (-1, -1), regular),
        ('FONTNAME', (0, 0), (-1, 0), bold_font),
        ('FONTNAME', (0, -1), (-1, -1), bold_font),
        ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor('#203864')),
        ('TEXTCOLOR', (0, 0), (-1, 0), colors.whitesmoke),
        ('ALIGN', (0, 0), (2, -1), 'CENTER'),
        ('VALIGN', (0, 0), (-1, -1), 'TOP'),
        ('GRID', (0, 0), (-1, -1), 1, colors.black),
    ]))
    return table


def create_monthly_pdf_report(start_date):
    """Monthly report: every day worked, then per employee what was earned,
    taken as advances and is still to be paid, then the advances themselves."""
    if not REPORTLAB_AVAILABLE:
        return None

    try:
        payroll = analytics.month_payroll(start_date)
        if not payroll['employees']:
            return None
        rows = payroll['rows']

        bio = io.BytesIO()
        doc = SimpleDocTemplate(bio, pagesize=A4, topMargin=0.5*inch, bottomMargin=0.5*inch)

        elements = []
        styles = getSampleStyleSheet()
        regular, bold_font = _unicode_fonts()

        # Title
        title_style = ParagraphStyle(
            'CustomTitle',
            parent=styles['Heading1'],
            fontName=bold_font,
            fontSize=24,
            textColor=colors.HexColor('#203864'),
            spaceAfter=30,
            alignment=1  # center
        )
        # Helvetica has no emoji; one in the title printed as a black box.
        title = Paragraph(f"Oylik Hisobot<br/>{ui.fmt_month(start_date)}", title_style)
        elements.append(title)
        elements.append(Spacer(1, 0.3*inch))

        # Create table data
        data = [['Ism', 'Sana', 'Kelish', 'Ketish', f"To'lov ({utils.CURRENCY_LABEL})"]]
        bold = []

        current_employee = None
        employee_subtotal = 0

        for row in rows:
            emp_name = row['full_name']

            if current_employee and current_employee != emp_name:
                # Add subtotal row
                bold.append(len(data))
                data.append([f'Jami {current_employee}', '', '', '', _money(employee_subtotal)])
                employee_subtotal = 0

            check_in = row['check_in'].strftime("%H:%M") if row['check_in'] else "--"
            check_out = row['check_out'].strftime("%H:%M") if row['check_out'] else "--"

            data.append([
                emp_name,
                str(row['date']),
                check_in,
                check_out,
                _money(row['total_wage'])
            ])

            employee_subtotal += row['total_wage'] or 0
            current_employee = emp_name

        # Final subtotal
        if current_employee:
            bold.append(len(data))
            data.append([f'Jami {current_employee}', '', '', '', _money(employee_subtotal)])

        # Add total
        bold.append(len(data))
        data.append(['', '', '', 'JAMI', _money(payroll['totals']['wage'])])

        # Create table (skipped when the month holds advances but no days)
        if rows:
            table = Table(data, colWidths=[1.5*inch, 1*inch, 0.8*inch, 0.8*inch, 1*inch])
            table.setStyle(TableStyle([
                ('FONTNAME', (0, 0), (-1, -1), regular),
                ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor('#203864')),
                ('TEXTCOLOR', (0, 0), (-1, 0), colors.whitesmoke),
                ('ALIGN', (0, 0), (-1, -1), 'CENTER'),
                ('FONTNAME', (0, 0), (-1, 0), bold_font),
                ('FONTSIZE', (0, 0), (-1, 0), 12),
                ('BOTTOMPADDING', (0, 0), (-1, 0), 12),
                ('GRID', (0, 0), (-1, -1), 1, colors.black),
                ('ROWBACKGROUNDS', (0, 1), (-1, -1), [colors.white, colors.HexColor('#f0f0f0')]),
            ] + _bold_rows(bold, bold_font)))

            elements.append(table)
            elements.append(Spacer(1, 0.3*inch))

        heading_style = ParagraphStyle('Section', parent=styles['Heading2'], fontName=bold_font,
                                       textColor=colors.HexColor('#203864'))
        elements.append(Paragraph("To'lov", heading_style))
        elements.append(_payment_table(payroll, regular, bold_font))
        hint_style = ParagraphStyle('Hint', parent=styles['Normal'], fontName=regular,
                                    fontSize=9, textColor=colors.grey)
        elements.append(Spacer(1, 0.05*inch))
        elements.append(Paragraph(analytics.payroll_formula(analytics.payroll_columns(payroll)), hint_style))
        elements.append(Spacer(1, 0.3*inch))

        if payroll['advances']:
            elements.append(Paragraph("Avanslar", heading_style))
            note_style = ParagraphStyle('Note', parent=styles['Normal'], fontName=regular, fontSize=9)
            elements.append(_advances_table(payroll['advances'], regular, bold_font, note_style))
            elements.append(Spacer(1, 0.3*inch))

        # Footer
        footer_style = ParagraphStyle(
            'Footer',
            parent=styles['Normal'],
            fontName=regular,
            fontSize=10,
            textColor=colors.grey,
            alignment=1
        )
        footer_text = Paragraph(
            f"Yaratilgan: {utils.get_now().strftime('%Y-%m-%d %H:%M:%S')}<br/>Keldi-Ketdi Bot v5.0",
            footer_style
        )
        elements.append(footer_text)

        doc.build(elements)
        bio.seek(0)
        return bio

    except Exception as e:
        logger.error(f"Error creating PDF report: {e}")
        return None


def create_employee_pdf_report(user_id, days=30):
    """Create PDF report for single employee"""
    if not REPORTLAB_AVAILABLE:
        return None

    try:
        from analytics import get_employee_stats

        stats = get_employee_stats(user_id, days)
        if not stats:
            return None

        now = utils.get_now()
        start_date = now.date() - timedelta(days=days)
        attendance = db.get_user_month_details(user_id, start_date)

        bio = io.BytesIO()
        doc = SimpleDocTemplate(bio, pagesize=A4)
        elements = []
        styles = getSampleStyleSheet()

        # Title
        title_style = ParagraphStyle(
            'Title',
            parent=styles['Heading1'],
            fontSize=20,
            textColor=colors.HexColor('#203864'),
            spaceAfter=20
        )
        title = Paragraph(f"📊 {stats['name']} - Tafsiliy Hisobot", title_style)
        elements.append(title)

        # Employee info
        info_data = [
            ['Ism:', stats['name']],
            ['Telefon:', stats['phone']],
            ['Ish turi:', stats['salary_type']],
            ['Davrr:', f"{days} kun"],
        ]
        info_table = Table(info_data, colWidths=[1.5*inch, 3*inch])
        info_table.setStyle(TableStyle([
            ('BACKGROUND', (0, 0), (0, -1), colors.HexColor('#e0e0e0')),
            ('FONTNAME', (0, 0), (0, -1), 'Helvetica-Bold'),
            ('ALIGN', (0, 0), (-1, -1), 'LEFT'),
            ('GRID', (0, 0), (-1, -1), 1, colors.grey),
        ]))
        elements.append(info_table)
        elements.append(Spacer(1, 0.2*inch))

        # Stats
        stats_data = [
            ['Ishlagan kunlar', str(stats['days_worked'])],
            ['Jami soatlar', f"{stats['total_hours']:.1f}h"],
            ['O\'rtacha soat/kun', f"{stats.get('avg_hours_per_day', 0):.1f}h"],
            ["Asosiy to'lov", utils.format_money(stats.get('total_base', 0))],
            ["Qo'shimcha", utils.format_money(stats.get('total_overtime', 0))],
            ["Jami to'lov", utils.format_money(stats['total_wage'])],
            ["O'rtacha to'lov/kun", utils.format_money(stats['avg_wage_per_day'])],
            ['Opozdilar', str(stats['late_days'])],
        ]
        stats_table = Table(stats_data, colWidths=[2*inch, 2*inch])
        stats_table.setStyle(TableStyle([
            ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor('#4472C4')),
            ('TEXTCOLOR', (0, 0), (-1, 0), colors.whitesmoke),
            ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
            ('ALIGN', (0, 0), (-1, -1), 'CENTER'),
            ('GRID', (0, 0), (-1, -1), 1, colors.grey),
            ('ROWBACKGROUNDS', (0, 1), (-1, -1), [colors.white, colors.HexColor('#f5f5f5')]),
        ]))
        elements.append(stats_table)
        elements.append(Spacer(1, 0.3*inch))

        # Details
        heading = Paragraph("Kunlik Tafsilotlar", styles['Heading2'])
        elements.append(heading)
        elements.append(Spacer(1, 0.1*inch))

        detail_data = [['Sana', 'Kelish', 'Ketish', 'Soatlar', f"To'lov ({utils.CURRENCY_LABEL})"]]
        for att in attendance:
            if att['check_in'] and att['check_out']:
                hours = (att['check_out'] - att['check_in']).total_seconds() / 3600
                detail_data.append([
                    str(att['date']),
                    att['check_in'].strftime("%H:%M"),
                    att['check_out'].strftime("%H:%M"),
                    f"{hours:.1f}",
                    _money(att['total_wage'])
                ])

        detail_table = Table(detail_data, colWidths=[1*inch, 0.9*inch, 0.9*inch, 0.8*inch, 1*inch])
        detail_table.setStyle(TableStyle([
            ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor('#203864')),
            ('TEXTCOLOR', (0, 0), (-1, 0), colors.whitesmoke),
            ('ALIGN', (0, 0), (-1, -1), 'CENTER'),
            ('GRID', (0, 0), (-1, -1), 1, colors.grey),
            ('ROWBACKGROUNDS', (0, 1), (-1, -1), [colors.white, colors.HexColor('#f9f9f9')]),
        ]))
        elements.append(detail_table)

        doc.build(elements)
        bio.seek(0)
        return bio

    except Exception as e:
        logger.error(f"Error creating employee PDF: {e}")
        return None
