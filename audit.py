"""Audit logging for admin actions"""
import logging
import database as db
from datetime import datetime

logger = logging.getLogger(__name__)

# Action types
ACTION_TYPES = {
    'user_added': 'Добавлен сотрудник',
    'user_deleted': 'Удален сотрудник',
    'pending_user_deleted': 'Отменено приглашение',
    'rates_updated': 'Обновлены ставки',
    'attendance_manual': 'Вручную изменено время',
    'correction_approved': 'Тузатиш одобрена',
    'correction_rejected': 'Тузатиш отклонена',
    'admin_promoted': 'Назначен администратором',
    'broadcast_sent': 'Отправлено массовое сообщение',
    'report_generated': 'Создан отчет',
}


def log_action(admin_id, action_type, description, details=None):
    """Log an admin action"""
    try:
        admin = db.get_user(admin_id)
        admin_name = admin['full_name'] if admin else f"User {admin_id}"

        action_name = ACTION_TYPES.get(action_type, action_type)

        log_msg = f"[{action_name}] Админ: {admin_name} (ID:{admin_id}) | {description}"
        if details:
            log_msg += f" | {details}"

        logger.info(log_msg)

        # Also store in database as a setting for audit trail
        timestamp = datetime.now().isoformat()
        audit_key = f"audit_{timestamp}_{admin_id}"

        db.update_setting(audit_key, f"{action_name}|{admin_name}|{description}")
    except Exception as e:
        logger.error(f"Error logging action: {e}")


def log_employee_action(admin_id, employee_id, action_type, description, details=None):
    """Log an action on an employee"""
    try:
        admin = db.get_user(admin_id)
        employee = db.get_user(employee_id)

        admin_name = admin['full_name'] if admin else f"User {admin_id}"
        employee_name = employee['full_name'] if employee else f"User {employee_id}"

        action_name = ACTION_TYPES.get(action_type, action_type)

        log_msg = f"[{action_name}] Админ: {admin_name} | Ходим: {employee_name} | {description}"
        if details:
            log_msg += f" | {details}"

        logger.info(log_msg)

        timestamp = datetime.now().isoformat()
        audit_key = f"audit_{timestamp}_{admin_id}"
        db.update_setting(audit_key, f"{action_name}|{admin_name}→{employee_name}|{description}")
    except Exception as e:
        logger.error(f"Error logging employee action: {e}")


# Shortcuts for common actions
def log_user_added(admin_id, employee_name, phone):
    log_employee_action(admin_id, admin_id, 'user_added', f"Добавлен {employee_name}", f"Телефон: {phone}")


def log_rates_updated(admin_id, employee_id, salary_type):
    log_employee_action(admin_id, employee_id, 'rates_updated', f"Изменены ставки на {salary_type}", "")


def log_attendance_updated(admin_id, employee_id, date_str, time_in, time_out):
    log_employee_action(admin_id, employee_id, 'attendance_manual',
                       f"Вручную изменено время",
                       f"{date_str} {time_in}-{time_out}")


def log_correction_approved(admin_id, employee_id, date_str):
    log_employee_action(admin_id, employee_id, 'correction_approved',
                       f"Одобрена исправка",
                       f"Дата: {date_str}")


def log_correction_rejected(admin_id, employee_id, date_str):
    log_employee_action(admin_id, employee_id, 'correction_rejected',
                       f"Отклонена исправка",
                       f"Дата: {date_str}")


def log_broadcast(admin_id, recipient_count, message_preview):
    log_action(admin_id, 'broadcast_sent',
              f"Отправлено {recipient_count} сотрудникам",
              f"Сообщение: {message_preview[:50]}")
