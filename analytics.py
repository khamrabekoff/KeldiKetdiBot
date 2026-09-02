"""Analytics module for employee statistics and reporting"""
import database as db
from datetime import datetime, timedelta
from collections import defaultdict
import utils

def get_employee_stats(user_id, days=30):
    """Get detailed statistics for an employee"""
    try:
        now = utils.get_now()
        start_date = now.date() - timedelta(days=days)

        user = db.get_user(user_id)
        if not user:
            return None

        attendance = db.get_user_month_details(user_id, start_date)
        rates = db.get_db_rates(user_id)

        stats = {
            'name': user['full_name'],
            'phone': user['phone'],
            'total_days': 0,
            'total_hours': 0.0,
            'total_wage': 0.0,
            'avg_wage_per_day': 0.0,
            'days_worked': 0,
            'days_missed': (now.date() - start_date).days,
            'early_days': 0,
            'late_days': 0,
            'salary_type': rates.get('salary_type', 'tariff'),
        }

        early_count = 0
        late_count = 0

        for row in attendance:
            if row['check_in'] and row['check_out']:
                stats['days_worked'] += 1
                stats['total_wage'] += row['total_wage']

                hours = (row['check_out'] - row['check_in']).total_seconds() / 3600
                stats['total_hours'] += hours

                # Check if early/late
                start_time = row['check_in'].replace(hour=9, minute=0, second=0, microsecond=0)
                if row['check_in'] < start_time:
                    early_count += 1

                cutoff = row['check_in'].replace(hour=9, minute=15, second=0, microsecond=0)
                if row['check_in'] > cutoff and row['check_in'].hour < 12:
                    late_count += 1

        stats['early_days'] = early_count
        stats['late_days'] = late_count
        stats['days_missed'] = stats['days_missed'] - stats['days_worked']

        if stats['days_worked'] > 0:
            stats['avg_wage_per_day'] = round(stats['total_wage'] / stats['days_worked'], 2)
            stats['avg_hours_per_day'] = round(stats['total_hours'] / stats['days_worked'], 1)

        return stats
    except Exception as e:
        import logging
        logging.error(f"Error getting employee stats: {e}")
        return None


def get_all_employees_stats(days=30):
    """Get statistics for all employees"""
    try:
        conn = db.get_connection()
        c = conn.cursor()
        c.execute("SELECT id FROM users WHERE role='employee'")
        employees = c.fetchall()
        conn.close()

        all_stats = []
        for emp in employees:
            stats = get_employee_stats(emp['id'], days)
            if stats:
                all_stats.append(stats)

        return sorted(all_stats, key=lambda x: x['total_wage'], reverse=True)
    except Exception as e:
        import logging
        logging.error(f"Error getting all employees stats: {e}")
        return []


def format_stats(stats):
    """Format stats for display"""
    if not stats:
        return "❌ Нет данных"

    text = f"📊 <b>Статистика: {stats['name']}</b>\n\n"
    text += f"💼 <b>Тип зарплаты:</b> {stats['salary_type']}\n"
    text += f"📞 <b>Телефон:</b> {stats['phone']}\n\n"

    text += f"<b>═══ РАБОТА ═══</b>\n"
    text += f"📅 <b>Дней отработано:</b> {stats['days_worked']}\n"
    text += f"⏰ <b>Часов всего:</b> {stats['total_hours']:.1f}h\n"
    text += f"⌛ <b>В среднем в день:</b> {stats.get('avg_hours_per_day', 0):.1f}h\n\n"

    text += f"<b>═══ ЗАРПЛАТА ═══</b>\n"
    text += f"💰 <b>Общая:</b> ${stats['total_wage']:.2f}\n"
    text += f"💵 <b>В день (средн):</b> ${stats['avg_wage_per_day']:.2f}\n\n"

    text += f"<b>═══ ПУНКТУАЛЬНОСТЬ ═══</b>\n"
    text += f"✅ <b>Пришел рано:</b> {stats['early_days']} дней\n"
    text += f"⚠️ <b>Опоздал:</b> {stats['late_days']} дней\n"
    text += f"❌ <b>Пропущено:</b> {stats['days_missed']} дней\n"

    return text


def format_all_stats_summary(days=30):
    """Format summary stats for all employees"""
    all_stats = get_all_employees_stats(days)

    if not all_stats:
        return "❌ Нет данных для анализа"

    text = f"📊 <b>ОБЩАЯ СТАТИСТИКА ({days} дней)</b>\n\n"
    text += f"👥 <b>Всего сотрудников:</b> {len(all_stats)}\n\n"

    total_wage = sum(s['total_wage'] for s in all_stats)
    total_hours = sum(s['total_hours'] for s in all_stats)
    total_worked = sum(s['days_worked'] for s in all_stats)

    text += f"💰 <b>Всего зарплата:</b> ${total_wage:.2f}\n"
    text += f"⏰ <b>Всего часов:</b> {total_hours:.1f}h\n"
    text += f"📅 <b>Всего дней работы:</b> {total_worked}\n\n"

    text += f"<b>═══ РЕЙТИНГ ПО ЗАРПЛАТЕ ═══</b>\n"
    for i, stats in enumerate(all_stats[:3], 1):
        text += f"{i}. {stats['name']}: ${stats['total_wage']:.2f}\n"

    text += f"\n<b>═══ РЕЙТИНГ ПО ПУНКТУАЛЬНОСТИ ═══</b>\n"
    most_punctual = sorted(all_stats, key=lambda x: x['late_days'])[:3]
    for i, stats in enumerate(most_punctual, 1):
        text += f"{i}. {stats['name']}: {stats['late_days']} опозданий\n"

    return text


def get_daily_report(date_obj=None):
    """Get report for specific day"""
    if date_obj is None:
        date_obj = utils.get_now().date()

    rows = db.get_today_attendance(date_obj)

    if not rows:
        return f"❌ Нет данных на {date_obj}"

    text = f"📅 <b>Отчет на {date_obj.strftime('%d.%m.%Y')}</b>\n\n"

    total_wage = 0
    worked_count = 0

    for row in rows:
        name = row['full_name']
        check_in = row['check_in'].strftime('%H:%M') if row['check_in'] else "--"
        check_out = row['check_out'].strftime('%H:%M') if row['check_out'] else "--"
        wage = row['total_wage'] if row['total_wage'] else 0

        status = "✅" if row['check_out'] else "⏳"
        text += f"{status} {name}: {check_in} - {check_out} | ${wage:.2f}\n"

        if row['check_out']:
            total_wage += wage
            worked_count += 1

    text += f"\n<b>════════════</b>\n"
    text += f"👥 <b>Отработало:</b> {worked_count}\n"
    text += f"💰 <b>Всего пинцев:</b> ${total_wage:.2f}\n"

    return text
