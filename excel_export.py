"""Excel export with charts and formatting"""
import io
import analytics
import database as db
import ui
import utils
from datetime import datetime
from openpyxl import Workbook
from openpyxl.styles import Font, PatternFill, Alignment, Border, Side
from openpyxl.chart import BarChart, PieChart, Reference
import logging

logger = logging.getLogger(__name__)

# Colors
HEADER_FILL = PatternFill(start_color="4472C4", end_color="4472C4", fill_type="solid")
HEADER_FONT = Font(bold=True, color="FFFFFF", size=12)
TOTAL_FILL = PatternFill(start_color="E7E6E6", end_color="E7E6E6", fill_type="solid")
TOTAL_FONT = Font(bold=True, size=11)
BORDER = Border(
    left=Side(style='thin'),
    right=Side(style='thin'),
    top=Side(style='thin'),
    bottom=Side(style='thin')
)

MONEY_FORMAT = utils.EXCEL_MONEY_FORMAT
PAY_FILL = PatternFill(start_color="FFC000", end_color="FFC000", fill_type="solid")


def _money_header(label):
    return f"{label} ({utils.CURRENCY_LABEL})"


def _header_row(ws, row, labels, width):
    """Style columns 1..width of `row` as a header; `labels` is {column: text}."""
    for col in range(1, width + 1):
        cell = ws.cell(row=row, column=col)
        cell.value = labels.get(col)
        cell.font = HEADER_FONT
        cell.fill = HEADER_FILL
        cell.alignment = Alignment(horizontal="center", vertical="center", wrap_text=True)
        cell.border = BORDER


def _payroll_row(ws, row, name, days, money, width, total=False):
    """One employee (or the JAMI line): name, days worked, and money columns.
    The last money column is what is still to pay, so it is the one marked."""
    ws.cell(row=row, column=1).value = name
    if days is not None:
        ws.cell(row=row, column=2).value = days
    for col, amount in money.items():
        ws.cell(row=row, column=col).value = round(amount, 2)
        ws.cell(row=row, column=col).number_format = MONEY_FORMAT
    pay_col = max(money)
    for col in range(1, width + 1):
        cell = ws.cell(row=row, column=col)
        cell.border = BORDER
        if total:
            cell.font = TOTAL_FONT
            cell.fill = TOTAL_FILL
    ws.cell(row=row, column=pay_col).font = TOTAL_FONT
    if total:
        ws.cell(row=row, column=pay_col).fill = PAY_FILL


def _payroll_table(ws, row, payroll, first_money_col, width, total_label):
    """Header, one row per employee and a JAMI row: name, days, then the money
    columns this month needs. Returns the row after the table."""
    columns = analytics.payroll_columns(payroll)
    money_cols = {first_money_col + i: key for i, (_, key) in enumerate(columns)}
    labels = {1: "Ism", 2: "Kunlar"}
    labels.update({first_money_col + i: _money_header(label) for i, (label, _) in enumerate(columns)})
    _header_row(ws, row, labels, width)
    row += 1
    for emp in payroll['employees']:
        _payroll_row(ws, row, emp['name'], emp['days'],
                     {col: emp[key] for col, key in money_cols.items()}, width)
        row += 1
    totals = payroll['totals']
    _payroll_row(ws, row, total_label, None,
                 {col: totals[key] for col, key in money_cols.items()}, width, total=True)
    return row + 1


def _add_payment_sheet(wb, payroll, start_date):
    """The answer to 'how much do I still owe everyone', on the sheet the file
    opens to, rather than below a hundred rows of days."""
    ws = wb.create_sheet("To'lov", 0)
    wb.active = 0
    columns = analytics.payroll_columns(payroll)
    width = 2 + len(columns)
    last = chr(ord('A') + width - 1)

    ws.merge_cells(f'A1:{last}1')
    title = ws['A1']
    title.value = f"💰 To'lov - {ui.fmt_month(start_date)}"
    title.font = Font(bold=True, size=14, color="FFFFFF")
    title.fill = PatternFill(start_color="203864", end_color="203864", fill_type="solid")
    title.alignment = Alignment(horizontal="center", vertical="center")
    ws.row_dimensions[1].height = 25

    row = _payroll_table(ws, 3, payroll, first_money_col=3, width=width, total_label="JAMI")

    ws.cell(row=row + 1, column=1).value = analytics.payroll_formula(columns)
    ws.cell(row=row + 1, column=1).font = Font(italic=True, color="808080")

    ws.column_dimensions['A'].width = 22
    ws.column_dimensions['B'].width = 9
    for i in range(len(columns)):
        ws.column_dimensions[chr(ord('C') + i)].width = 17


def _add_advances_sheet(wb, advances, start_date):
    ws = wb.create_sheet("Avanslar")

    ws.merge_cells('A1:E1')
    title = ws['A1']
    title.value = f"💸 Avanslar - {ui.fmt_month(start_date)}"
    title.font = Font(bold=True, size=14, color="FFFFFF")
    title.fill = PatternFill(start_color="203864", end_color="203864", fill_type="solid")
    title.alignment = Alignment(horizontal="center", vertical="center")
    ws.row_dimensions[1].height = 25

    _header_row(ws, 3, {1: "Sana", 2: "Vaqt", 3: "Ism", 4: _money_header("Summa"), 5: "Izoh"}, 5)
    row = 4
    for advance in advances:
        ws.cell(row=row, column=1).value = advance['date']
        ws.cell(row=row, column=1).number_format = 'DD.MM.YYYY'
        ws.cell(row=row, column=2).value = advance['created_at'].strftime('%H:%M')
        ws.cell(row=row, column=3).value = advance['full_name']
        ws.cell(row=row, column=4).value = advance['amount']
        ws.cell(row=row, column=4).number_format = MONEY_FORMAT
        ws.cell(row=row, column=5).value = advance['note'] or ""
        ws.cell(row=row, column=5).alignment = Alignment(wrap_text=True, vertical="top")
        for col in range(1, 6):
            ws.cell(row=row, column=col).border = BORDER
        row += 1

    ws.cell(row=row, column=3).value = "JAMI:"
    ws.cell(row=row, column=4).value = sum(a['amount'] for a in advances)
    ws.cell(row=row, column=4).number_format = MONEY_FORMAT
    for col in (3, 4):
        ws.cell(row=row, column=col).font = TOTAL_FONT

    for col, width in zip('ABCDE', (12, 8, 22, 14, 45)):
        ws.column_dimensions[col].width = width


def create_monthly_report_excel(start_date, filename=None):
    """Monthly report: every day worked, then per employee what was earned,
    taken as advances and is still to be paid, plus a sheet of the advances."""
    try:
        payroll = analytics.month_payroll(start_date)
        if not payroll['employees']:
            return None
        rows = payroll['rows']

        wb = Workbook()
        ws = wb.active
        ws.title = "Oylik Hisobot"

        # Title
        ws.merge_cells('A1:G1')
        title = ws['A1']
        title.value = f"📊 Oylik Hisobot - {ui.fmt_month(start_date)}"
        title.font = Font(bold=True, size=14, color="FFFFFF")
        title.fill = PatternFill(start_color="203864", end_color="203864", fill_type="solid")
        title.alignment = Alignment(horizontal="center", vertical="center")
        ws.row_dimensions[1].height = 25

        # Headers
        headers = ["Ism", "Sana", "Kelish", "Ketish", "Turi", "Tafsilot",
                   f"Jami ({utils.CURRENCY_LABEL})"]
        for col, header in enumerate(headers, 1):
            cell = ws.cell(row=3, column=col)
            cell.value = header
            cell.font = HEADER_FONT
            cell.fill = HEADER_FILL
            cell.alignment = Alignment(horizontal="center", vertical="center")
            cell.border = BORDER

        # Data
        row_num = 4

        for row in rows:
            rates = {
                'salary_type': row['salary_type'] if row['salary_type'] else 'tariff',
                'rate_n': row['rate_n'] if row['rate_n'] else 0,
                'rate_m': row['rate_m'] if row['rate_m'] else 0,
                'rate_k': row['rate_k'] if row['rate_k'] else 0,
                'rate_overtime': row['rate_overtime'] if row['rate_overtime'] else 0,
                'monthly_salary': row['monthly_salary'] if row['monthly_salary'] else 0,
                'overtime_hourly_rate': row['overtime_hourly_rate'] if row['overtime_hourly_rate'] else 0,
                'rate_per_minute': row['rate_per_minute'] if row['rate_per_minute'] else 0,
                'overtime_per_minute': row['overtime_per_minute'] if row['overtime_per_minute'] else 0,
            }

            check_in = row['check_in']
            check_out = row['check_out']
            stype = rates['salary_type']
            stype_label = "Tarif" if stype == 'tariff' else ("Oylik" if stype == 'monthly' else "Minutlik")

            tafsilot = ""
            if check_in and check_out:
                from utils import calculate_wage
                _, _, breakdown = calculate_wage(check_in, check_out, rates)
                total = row['total_wage']
                if stype == 'per_minute':
                    total_mins = (check_out - check_in).total_seconds() / 60.0
                    tafsilot = f"{total_mins:.0f}min × {utils.format_rate(rates['rate_per_minute'])}"
                elif stype == 'monthly':
                    tafsilot = (f"Base: {utils.format_money(breakdown.get('regular', 0))}, "
                                f"OT: {utils.format_money(breakdown.get('ot', 0))}")
                else:
                    tafsilot = f"N:{breakdown['n']:.0f} M:{breakdown['m']:.0f} K:{breakdown['k']:.0f} OT:{breakdown['ot']:.0f}"
            else:
                total = 0
                tafsilot = "Not finished"

            # Row data
            ws.cell(row=row_num, column=1).value = row['full_name']
            ws.cell(row=row_num, column=2).value = row['date']
            ws.cell(row=row_num, column=3).value = check_in.strftime("%H:%M") if check_in else ""
            ws.cell(row=row_num, column=4).value = check_out.strftime("%H:%M") if check_out else ""
            ws.cell(row=row_num, column=5).value = stype_label
            ws.cell(row=row_num, column=6).value = tafsilot
            ws.cell(row=row_num, column=7).value = total

            # Format row
            for col in range(1, 8):
                cell = ws.cell(row=row_num, column=col)
                cell.border = BORDER
                if col == 7:
                    cell.number_format = MONEY_FORMAT
                    cell.alignment = Alignment(horizontal="right")

            row_num += 1

        # Summary section: earned, advances, still to pay
        row_num += 1
        ws.merge_cells(f'A{row_num}:G{row_num}')
        summary_title = ws[f'A{row_num}']
        summary_title.value = "UMUMIY TO'LOV"
        summary_title.font = TOTAL_FONT
        summary_title.fill = TOTAL_FILL
        summary_title.alignment = Alignment(horizontal="center")

        # Money columns end at G, the day table's money column
        _payroll_table(ws, row_num + 1, payroll, first_money_col=8 - len(analytics.payroll_columns(payroll)),
                       width=7, total_label="JAMI:")

        _add_payment_sheet(wb, payroll, start_date)
        if payroll['advances']:
            _add_advances_sheet(wb, payroll['advances'], start_date)

        # Column widths
        ws.column_dimensions['A'].width = 20
        ws.column_dimensions['B'].width = 12
        ws.column_dimensions['C'].width = 10
        ws.column_dimensions['D'].width = 10
        ws.column_dimensions['E'].width = 12
        ws.column_dimensions['F'].width = 35
        ws.column_dimensions['G'].width = 12

        # Create chart
        if payroll['employees']:
            chart_sheet = wb.create_sheet("Chart")

            # Prepare data for chart
            chart_sheet['A1'].value = "Ism"
            chart_sheet['B1'].value = f"Jami ({utils.CURRENCY_LABEL})"

            row_num = 2
            for emp in payroll['employees']:
                chart_sheet[f'A{row_num}'].value = emp['name']
                chart_sheet[f'B{row_num}'].value = emp['wage']
                row_num += 1

            # Create chart
            chart = BarChart()
            chart.type = "col"
            chart.style = 10
            chart.title = "Oylik to'lovlar"
            chart.y_axis.title = f"To'lov ({utils.CURRENCY_LABEL})"
            chart.x_axis.title = 'Xodimlar'

            data = Reference(chart_sheet, min_col=2, min_row=1, max_row=row_num-1)
            categories = Reference(chart_sheet, min_col=1, min_row=2, max_row=row_num-1)

            chart.add_data(data, titles_from_data=True)
            chart.set_categories(categories)
            chart.height = 12
            chart.width = 20

            chart_sheet.add_chart(chart, "A5")

        # Save to bytes
        bio = io.BytesIO()
        wb.save(bio)
        bio.seek(0)

        return bio
    except Exception as e:
        logger.error(f"Error creating Excel report: {e}")
        return None


def create_employee_detailed_excel(user_id, days=30, filename=None):
    """Create detailed report for single employee"""
    try:
        from analytics import get_employee_stats
        from datetime import timedelta

        stats = get_employee_stats(user_id, days)
        if not stats:
            return None

        now = datetime.now()
        start_date = now.date() - timedelta(days=days)

        attendance = db.get_user_month_details(user_id, start_date)

        wb = Workbook()
        ws = wb.active
        ws.title = "Xodim Tafsiloti"

        # Header
        ws.merge_cells('A1:D1')
        title = ws['A1']
        title.value = f"📊 {stats['name']} - Tafsiliy Hisobot"
        title.font = HEADER_FONT
        title.fill = HEADER_FILL
        ws.row_dimensions[1].height = 20

        # Employee info
        row = 3
        ws[f'A{row}'].value = "Ism:"
        ws[f'B{row}'].value = stats['name']
        row += 1
        ws[f'A{row}'].value = "Telefon:"
        ws[f'B{row}'].value = stats['phone']
        row += 1
        ws[f'A{row}'].value = "Ish turi:"
        ws[f'B{row}'].value = stats['salary_type']
        row += 2

        # Stats summary
        ws[f'A{row}'].value = "STATISTIKA:"
        ws[f'A{row}'].font = Font(bold=True, size=11)
        row += 1
        ws[f'A{row}'].value = "Ishlagan kunlar:"
        ws[f'B{row}'].value = stats['days_worked']
        row += 1
        ws[f'A{row}'].value = "Jami soatlar:"
        ws[f'B{row}'].value = stats['total_hours']
        ws[f'B{row}'].number_format = '0.0'
        row += 1
        ws[f'A{row}'].value = "O'rtacha soat/kun:"
        ws[f'B{row}'].value = stats.get('avg_hours_per_day', 0)
        ws[f'B{row}'].number_format = '0.0'
        row += 1
        ws[f'A{row}'].value = "Jami to'lov:"
        ws[f'B{row}'].value = stats['total_wage']
        ws[f'B{row}'].number_format = MONEY_FORMAT
        ws[f'B{row}'].font = Font(bold=True, size=11)
        row += 1
        ws[f'A{row}'].value = "O'rtacha to'lov/kun:"
        ws[f'B{row}'].value = stats['avg_wage_per_day']
        ws[f'B{row}'].number_format = MONEY_FORMAT
        row += 2

        # Detail table
        row += 1
        headers = ["Sana", "Kelish", "Ketish", "Soatlar", f"To'lov ({utils.CURRENCY_LABEL})"]
        for col, header in enumerate(headers, 1):
            cell = ws.cell(row=row, column=col)
            cell.value = header
            cell.font = HEADER_FONT
            cell.fill = HEADER_FILL

        row += 1
        for att in attendance:
            if att['check_in'] and att['check_out']:
                hours = (att['check_out'] - att['check_in']).total_seconds() / 3600

                ws[f'A{row}'].value = att['date']
                ws[f'B{row}'].value = att['check_in'].strftime("%H:%M")
                ws[f'C{row}'].value = att['check_out'].strftime("%H:%M")
                ws[f'D{row}'].value = hours
                ws[f'D{row}'].number_format = '0.00'
                ws[f'E{row}'].value = att['total_wage']
                ws[f'E{row}'].number_format = MONEY_FORMAT

                row += 1

        ws.column_dimensions['A'].width = 12
        ws.column_dimensions['B'].width = 10
        ws.column_dimensions['C'].width = 10
        ws.column_dimensions['D'].width = 10
        ws.column_dimensions['E'].width = 12

        bio = io.BytesIO()
        wb.save(bio)
        bio.seek(0)

        return bio
    except Exception as e:
        logger.error(f"Error creating employee report: {e}")
        return None
