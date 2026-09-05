"""PDF export for reports"""
import io
import logging
from datetime import datetime, timedelta
import database as db

logger = logging.getLogger(__name__)

try:
    from reportlab.lib.pagesizes import letter, A4
    from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
    from reportlab.lib.units import inch
    from reportlab.platypus import SimpleDocTemplate, Table, TableStyle, Paragraph, Spacer, PageBreak
    from reportlab.lib import colors
    REPORTLAB_AVAILABLE = True
except ImportError:
    REPORTLAB_AVAILABLE = False
    logger.warning("reportlab not installed. PDF export will be disabled.")


def create_monthly_pdf_report(start_date):
    """Create PDF monthly report"""
    if not REPORTLAB_AVAILABLE:
        return None

    try:
        rows = db.get_month_attendance_details(start_date)
        if not rows:
            return None

        bio = io.BytesIO()
        doc = SimpleDocTemplate(bio, pagesize=A4, topMargin=0.5*inch, bottomMargin=0.5*inch)

        elements = []
        styles = getSampleStyleSheet()

        # Title
        title_style = ParagraphStyle(
            'CustomTitle',
            parent=styles['Heading1'],
            fontSize=24,
            textColor=colors.HexColor('#203864'),
            spaceAfter=30,
            alignment=1  # center
        )
        title = Paragraph(f"📊 Oylik Hisobot<br/>{start_date.strftime('%B %Y')}", title_style)
        elements.append(title)
        elements.append(Spacer(1, 0.3*inch))

        # Employee summary
        employee_totals = {}
        for row in rows:
            emp_name = row['full_name']
            if emp_name not in employee_totals:
                employee_totals[emp_name] = 0
            employee_totals[emp_name] += row['total_wage']

        # Create table data
        data = [['Ism', 'Sana', 'Kelish', 'Ketish', 'To\'lov ($)']]

        current_employee = None
        employee_subtotal = 0

        for row in rows:
            emp_name = row['full_name']

            if current_employee and current_employee != emp_name:
                # Add subtotal row
                data.append([f'<b>Jami {current_employee}</b>', '', '', '', f'<b>${employee_subtotal:.2f}</b>'])
                employee_subtotal = 0

            check_in = row['check_in'].strftime("%H:%M") if row['check_in'] else "--"
            check_out = row['check_out'].strftime("%H:%M") if row['check_out'] else "--"

            data.append([
                emp_name,
                str(row['date']),
                check_in,
                check_out,
                f"${row['total_wage']:.2f}"
            ])

            employee_subtotal += row['total_wage']
            current_employee = emp_name

        # Final subtotal
        if current_employee:
            data.append([f'<b>Jami {current_employee}</b>', '', '', '', f'<b>${employee_subtotal:.2f}</b>'])

        # Add total
        total_wage = sum(employee_totals.values())
        data.append(['', '', '', '<b>JAMI</b>', f'<b>${total_wage:.2f}</b>'])

        # Create table
        table = Table(data, colWidths=[1.5*inch, 1*inch, 0.8*inch, 0.8*inch, 1*inch])
        table.setStyle(TableStyle([
            ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor('#203864')),
            ('TEXTCOLOR', (0, 0), (-1, 0), colors.whitesmoke),
            ('ALIGN', (0, 0), (-1, -1), 'CENTER'),
            ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
            ('FONTSIZE', (0, 0), (-1, 0), 12),
            ('BOTTOMPADDING', (0, 0), (-1, 0), 12),
            ('GRID', (0, 0), (-1, -1), 1, colors.black),
            ('ROWBACKGROUNDS', (0, 1), (-1, -1), [colors.white, colors.HexColor('#f0f0f0')]),
        ]))

        elements.append(table)
        elements.append(Spacer(1, 0.3*inch))

        # Footer
        footer_style = ParagraphStyle(
            'Footer',
            parent=styles['Normal'],
            fontSize=10,
            textColor=colors.grey,
            alignment=1
        )
        footer_text = Paragraph(
            f"Yaratilgan: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}<br/>Keldi-Ketdi Bot v5.0",
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

        now = datetime.now()
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
            ['Asosiy to\'lov', f"${stats.get('total_base', 0):.2f}"],
            ['Qo\'shimcha', f"${stats.get('total_overtime', 0):.2f}"],
            ['Jami to\'lov', f"${stats['total_wage']:.2f}"],
            ['O\'rtacha to\'lov/kun', f"${stats['avg_wage_per_day']:.2f}"],
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

        detail_data = [['Sana', 'Kelish', 'Ketish', 'Soatlar', 'To\'lov']]
        for att in attendance:
            if att['check_in'] and att['check_out']:
                hours = (att['check_out'] - att['check_in']).total_seconds() / 3600
                detail_data.append([
                    str(att['date']),
                    att['check_in'].strftime("%H:%M"),
                    att['check_out'].strftime("%H:%M"),
                    f"{hours:.1f}",
                    f"${att['total_wage']:.2f}"
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
