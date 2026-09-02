import pytz
from datetime import datetime, time

TZ_UZ = pytz.timezone('Asia/Tashkent')

def get_now():
    """Get current time in Uzbekistan timezone"""
    return datetime.now(TZ_UZ).replace(tzinfo=None)


def calculate_wage(check_in, check_out, rates):
    """
    Вычисляет зарплату на основе типа оклада
    rates: dict с ключами 'salary_type', 'rate_n', 'rate_m', 'rate_k', 'rate_overtime', 'monthly_salary', 'overtime_hourly_rate', 'rate_per_minute'
    """
    if not check_in or not check_out:
        return 0, "", {}

    salary_type = rates.get('salary_type', 'tariff')

    if salary_type == 'per_minute':
        return _calculate_wage_per_minute(check_in, check_out, rates)
    elif salary_type == 'monthly':
        return _calculate_wage_monthly(check_in, check_out, rates)
    else:  # tariff
        return _calculate_wage_tariff(check_in, check_out, rates)


def _calculate_wage_per_minute(check_in, check_out, rates):
    """Расчет по минутам"""
    try:
        total_minutes = (check_out - check_in).total_seconds() / 60.0
        rate_per_minute = rates.get('rate_per_minute', 0)
        wage = round(total_minutes * rate_per_minute, 2)
        details = f"⏱ {total_minutes:.0f} мин × {rate_per_minute}$/мин"
        return wage, details, {'minutes': total_minutes}
    except Exception as e:
        return 0, f"Ошибка расчета: {e}", {}


def _calculate_wage_monthly(check_in, check_out, rates):
    """Расчет для месячного оклада"""
    try:
        monthly_salary = rates.get('monthly_salary', 0)
        overtime_hourly_rate = rates.get('overtime_hourly_rate', 0)

        work_start = check_in.replace(hour=9, minute=0, second=0, microsecond=0)
        work_end = check_in.replace(hour=18, minute=0, second=0, microsecond=0)

        regular_wage = 0
        overtime_wage = 0

        if check_in < work_start:
            early_hours = (work_start - check_in).total_seconds() / 3600
            overtime_wage += early_hours * overtime_hourly_rate

        if check_out > work_end:
            late_hours = (check_out - work_end).total_seconds() / 3600
            overtime_wage += late_hours * overtime_hourly_rate

        regular_hours = min(8, (min(check_out, work_end) - max(check_in, work_start)).total_seconds() / 3600)
        if regular_hours > 0:
            regular_wage = (monthly_salary / 20 / 8) * regular_hours

        total_wage = round(regular_wage + overtime_wage, 2)
        details = f"💼 Base: {regular_wage:.2f}$ + OT: {overtime_wage:.2f}$"
        return total_wage, details, {'regular': regular_wage, 'ot': overtime_wage}
    except Exception as e:
        return 0, f"Ошибка расчета: {e}", {}


def _calculate_wage_tariff(check_in, check_out, rates):
    """Расчет по тарифам (4 периода)"""
    try:
        rate_n = rates.get('rate_n', 0)  # 09:00-11:00
        rate_m = rates.get('rate_m', 0)  # 11:00-16:00
        rate_k = rates.get('rate_k', 0)  # 16:00-18:00
        rate_overtime = rates.get('rate_overtime', 0)  # После 18:00

        total_wage = 0.0
        breakdown = {'n': 0, 'm': 0, 'k': 0, 'ot': 0}

        periods = [
            (9, 11, rate_n, 'n'),
            (11, 16, rate_m, 'm'),
            (16, 18, rate_k, 'k'),
        ]

        for start_h, end_h, rate, key in periods:
            period_start = check_in.replace(hour=start_h, minute=0, second=0, microsecond=0)
            period_end = check_in.replace(hour=end_h, minute=0, second=0, microsecond=0)

            overlap_start = max(check_in, period_start)
            overlap_end = min(check_out, period_end)

            if overlap_start < overlap_end:
                hours = (overlap_end - overlap_start).total_seconds() / 3600
                wage = round(hours * rate, 2)
                total_wage += wage
                breakdown[key] = wage

        if check_out > check_out.replace(hour=18, minute=0):
            ot_start = max(check_in, check_out.replace(hour=18, minute=0))
            ot_hours = (check_out - ot_start).total_seconds() / 3600
            ot_wage = round(ot_hours * rate_overtime, 2)
            total_wage += ot_wage
            breakdown['ot'] = ot_wage

        total_wage = round(total_wage, 2)
        details = f"N:{breakdown['n']:.1f}$ M:{breakdown['m']:.1f}$ K:{breakdown['k']:.1f}$ OT:{breakdown['ot']:.1f}$"
        return total_wage, details, breakdown
    except Exception as e:
        return 0, f"Ошибка расчета: {e}", {}


def format_currency(amount):
    """Format amount as currency"""
    return f"{amount:.2f} $"


def validate_phone(phone):
    """Validate phone number"""
    clean_phone = phone.replace("+", "").replace(" ", "").replace("-", "").strip()
    if len(clean_phone) < 9:
        return None
    return clean_phone


def validate_time(time_str):
    """Validate time format HH:MM"""
    try:
        datetime.strptime(time_str, "%H:%M")
        return True
    except:
        return False


def validate_float(value_str):
    """Validate and convert to float"""
    try:
        val = float(value_str)
        if val < 0:
            return None
        return val
    except:
        return None
