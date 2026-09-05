import pytz
from datetime import datetime, time

TZ_UZ = pytz.timezone('Asia/Tashkent')

def get_now():
    """Get current time in Uzbekistan timezone"""
    return datetime.now(TZ_UZ).replace(tzinfo=None)


def calculate_wage(check_in, check_out, rates, month_ctx=None):
    """
    Вычисляет зарплату на основе типа оклада
    rates: dict с ключами 'salary_type', 'rate_n', 'rate_m', 'rate_k', 'rate_overtime', 'monthly_salary', 'overtime_hourly_rate', 'rate_per_minute', 'overtime_per_minute'
    month_ctx: календарный контекст месяца (см. workdays.month_calendar).
               Нужен только типу 'monthly'; передаётся, чтобы пересчёт целого
               месяца не читал календарь заново на каждый день.
    """
    if not check_in or not check_out:
        return 0, "", {}

    salary_type = rates.get('salary_type', 'tariff')

    if salary_type == 'per_minute':
        return _calculate_wage_per_minute(check_in, check_out, rates)
    elif salary_type == 'monthly':
        return _calculate_wage_monthly(check_in, check_out, rates, month_ctx)
    else:  # tariff
        return _calculate_wage_tariff(check_in, check_out, rates)


def _calculate_wage_per_minute(check_in, check_out, rates):
    """Расчет по минутам"""
    try:
        total_minutes = (check_out - check_in).total_seconds() / 60.0
        rate_per_minute = rates.get('rate_per_minute', 0)
        wage = round(total_minutes * rate_per_minute, 2)
        details = f"⏱ {total_minutes:.0f} daq × {rate_per_minute:g} so'm"
        return wage, details, {'minutes': total_minutes}
    except Exception as e:
        return 0, f"Ошибка расчета: {e}", {}


def _calculate_wage_monthly(check_in, check_out, rates, month_ctx=None):
    """Месячный оклад, разнесённый по минутам стандартного дня 09:00-18:00.

    Рабочие дни месяца (календарные минус воскресенья минус официальные
    выходные) превращают оклад в ставку за минуту. Минуты недоработки
    вычитаются по этой ставке, минуты переработки оплачиваются по ставке
    переработки — по умолчанию той же самой. Отработал стандартный день во все
    рабочие дни — за месяц вышел ровно оклад.

    В воскресенье и в официальный выходной стандартного дня нет, недорабатывать
    нечего: там каждая отработанная минута идёт как переработка.
    """
    try:
        import workdays

        ctx = month_ctx or workdays.month_context(check_in.date())
        base_rate = workdays.base_rate_per_minute(rates.get('monthly_salary', 0) or 0, ctx)
        overtime_rate = rates.get('overtime_per_minute') or base_rate

        if ctx['is_rest_day']:
            overtime_minutes = max(0.0, (check_out - check_in).total_seconds() / 60.0)
            wage = round(overtime_minutes * overtime_rate, 2)
            details = f"🌙 Dam olish kuni: {overtime_minutes:.0f} daq qo'shimcha"
            return wage, details, {'regular': 0.0, 'ot': wage,
                                   'overtime_minutes': overtime_minutes,
                                   'short_minutes': 0.0}

        work_start = check_in.replace(hour=ctx['work_start'].hour,
                                      minute=ctx['work_start'].minute,
                                      second=0, microsecond=0)
        work_end = check_in.replace(hour=ctx['work_end'].hour,
                                    minute=ctx['work_end'].minute,
                                    second=0, microsecond=0)

        overtime_minutes = (max(0.0, (work_start - check_in).total_seconds() / 60.0)
                            + max(0.0, (check_out - work_end).total_seconds() / 60.0))
        short_minutes = (max(0.0, (check_in - work_start).total_seconds() / 60.0)
                         + max(0.0, (work_end - check_out).total_seconds() / 60.0))

        standard_minutes = ctx['standard_minutes']
        paid_standard_minutes = max(0.0, standard_minutes - short_minutes)
        regular_wage = paid_standard_minutes * base_rate
        overtime_wage = overtime_minutes * overtime_rate
        total_wage = round(regular_wage + overtime_wage, 2)

        parts = [f"💼 {paid_standard_minutes:.0f}/{standard_minutes} daq"]
        if overtime_minutes:
            parts.append(f"+{overtime_minutes:.0f} daq qo'shimcha")
        if short_minutes:
            parts.append(f"-{short_minutes:.0f} daq kam")
        details = " · ".join(parts)

        return total_wage, details, {'regular': round(regular_wage, 2),
                                     'ot': round(overtime_wage, 2),
                                     'overtime_minutes': overtime_minutes,
                                     'short_minutes': short_minutes}
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
        details = f"N:{breakdown['n']:.0f} M:{breakdown['m']:.0f} K:{breakdown['k']:.0f} OT:{breakdown['ot']:.0f}"
        return total_wage, details, breakdown
    except Exception as e:
        return 0, f"Ошибка расчета: {e}", {}


def split_wage(total_wage, breakdown):
    """(base, overtime) for storage and reporting.

    The three salary types describe themselves differently, but each reports
    its overtime part under 'ot' (per-minute pay has none). Deriving the base
    by subtraction rather than re-adding the pieces guarantees the two halves
    always sum back to the stored total.
    """
    overtime = round(breakdown.get('ot', 0) or 0, 2)
    return round((total_wage or 0) - overtime, 2), overtime


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
