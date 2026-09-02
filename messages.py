# Uzbek language constants — v5

MSG_WELCOME = "Assalomu alaykum! 'Keldi-ketdi' botiga xush kelibsiz.\nIltimos, telefon raqamingizni yuboring."
MSG_SEND_CONTACT = "📱 Telefon raqamni yuborish"
MSG_NOT_AUTHORIZED = "Kechirasiz, siz xodimlar ro'yxatida yo'qsiz. Rahbar bilan bog'laning."
MSG_AUTH_SUCCESS = "Xush kelibsiz, {name}!"
MSG_ALREADY_REGISTERED = "Siz allaqachon ro'yxatdan o'tgansiz."
MSG_ADMIN_WELCOME = "Xush kelibsiz, Administrator! Buyruq kuting."

# Employee Menu
BTN_CHECK_IN  = "Keldim"
BTN_CHECK_OUT = "Ketdim (+Hisobot)"
BTN_TODAY_STAT = "Bugungi hisob"
BTN_MONTH_STAT = "Oylik hisobot"

MSG_CHECKED_IN = "Siz ishga kelganingiz qayd etildi: {time}. Hayrli kun!"
MSG_CHECKED_IN_LATE = "Siz ishga kelganingiz qayd etildi: {time}.\n⚠️ <b>Diqqat!</b> Siz kechikdingiz. 09:00-10:00 oralig'i uchun sizga ish haqi yozilmadi."
MSG_CHECKED_OUT = "Siz ishdan ketganingiz qayd etildi: {time}.\n\n{details}\n\n💰 Bugungi ish haqingiz: {wage} $."

MSG_ALREADY_CHECKED_IN  = "Siz bugun allaqachon kelgansiz."
MSG_NOT_CHECKED_IN      = "Siz hali kelmagansiz, avval 'Keldim' tugmasini bosing."
MSG_ALREADY_CHECKED_OUT = "Siz bugun allaqachon ketgansiz."

# Admin Menu
BTN_ADMIN_TODAY       = "Bugun kim keldi"
BTN_ADMIN_MONTH       = "Oylik hisobot"
BTN_ADMIN_EMPLOYEES   = "Hodimlar"
BTN_ADMIN_CORRECTIONS = "🔔 Tuzatishlar"

BTN_ADMIN_ADD_EMP    = "➕ Xodim qo'shish"
BTN_ADMIN_DEL_EMP    = "❌ Xodim o'chirish"
BTN_ADMIN_EDIT_RATES = "💰 Stavkalarni o'zgartirish"

MSG_ENTER_SECRET   = "Admin bo'lish uchun maxfiy kodni kiriting:"
MSG_ADMIN_PROMOTED = "Tabriklaymiz! Siz endi administratorsiz."
MSG_WRONG_CODE     = "Kod noto'g'ri."

MSG_INPUT_PHONE = "Xodim telefon raqamini kiriting (masalan: 998901234567):"
MSG_INPUT_NAME  = "Xodim ismini kiriting:"

# ---- Salary type selection ----
MSG_SELECT_SALARY_TYPE = (
    "Ish haqi hisoblash turini tanlang:\n\n"
    "📊 <b>Tarif</b> — 4 ta vaqt oralig'i bo'yicha stavka\n"
    "📅 <b>Oylik maosh</b> — oylik belgilangan summa + qo'shimcha ish stavkasi\n"
    "⏱ <b>Minutlik stavka</b> — har bir daqiqa uchun belgilangan summa"
)
BTN_SALARY_TARIFF     = "📊 Tarif"
BTN_SALARY_MONTHLY    = "📅 Oylik maosh"
BTN_SALARY_PER_MINUTE = "⏱ Minutlik stavka"

# Tariff rates
MSG_INPUT_RATE_N        = "09:00 - 11:00 vaqt oralig'i uchun soatlik to'lovni kiriting ($):"
MSG_INPUT_RATE_M        = "11:00 - 16:00 vaqt oralig'i uchun soatlik to'lovni kiriting ($):"
MSG_INPUT_RATE_K        = "16:00 - 18:00 vaqt oralig'i uchun soatlik to'lovni kiriting ($):"
MSG_INPUT_RATE_OVERTIME = "18:00 dan keyingi vaqt uchun soatlik to'lovni kiriting ($):"

# Monthly salary rates
MSG_INPUT_MONTHLY_SALARY   = (
    "Xodim uchun oylik maoshni kiriting ($):\n"
    "<i>Masalan: 500</i>"
)
MSG_INPUT_OVERTIME_HOURLY  = (
    "Ish soatidan tashqari vaqt (09:00 dan oldin yoki 18:00 dan keyin) uchun\n"
    "soatlik to'lovni kiriting ($):\n"
    "<i>Masalan: 2.5</i>"
)

# Per-minute rate
MSG_INPUT_RATE_PER_MINUTE  = (
    "Bir daqiqa uchun to'lovni kiriting ($):\n"
    "<i>Masalan: 0.036</i>"
)

MSG_EMP_ADDED = "Xodim qo'shildi!\nIsm: {name}\nTel: {phone}\nHisoblash turi: {salary_type}\n{rate_info}"
BTN_BACK = "Ortga"

# My Stats
BTN_MY_STATS = "💰 Mening Hisobim"
MSG_MY_STATS = (
    "📊 <b>Sizning hisobingiz</b> (Bu oy):\n\n"
    "📅 Ishlangan kunlar: {days}\n"
    "💰 Jami ish haqi: {earned} $\n\n"
    "<i>Eslatma: Bu summa toza hisoblanib, kechikkan vaqt uchun yozilmagan pullar inobatga olingan.</i>"
)

MSG_BROADCAST_USAGE = "Foydalanish: /broadcast [ID] [Xabar]"
MSG_BROADCAST_SENT  = "Xabar yuborildi."

MSG_EDIT_USAGE    = "Tahrirlash: /edit [ID] [YYYY-MM-DD] [09:00] [18:00]"
MSG_EDIT_SUCCESS  = "✅ Muvaffaqiyatli o'zgartirildi!\nYangi summa: {wage} $"
MSG_EDIT_ERROR    = "Xatolik: {e}"

# Easy Edit Menu
BTN_ADMIN_EDIT_RATES_MENU  = "💰 Stavkalarni o'zgartirish"
BTN_ADMIN_EDIT_ATT_MENU    = "📝 Vaqtni tahrirlash"
BTN_ADMIN_DELETE_EMP_MENU  = "❌ Xodimni o'chirish"

MSG_CHOOSE_ACTION  = "👤 {name} - nima qilmoqchisiz?"
MSG_CHOOSE_DATE    = "Qaysi kungi vaqtni o'zgartirmoqchisiz?"
MSG_INPUT_TIME_IN  = "Kelgan vaqtini kiriting (masalan 09:15):"
MSG_INPUT_TIME_OUT = "Ketgan vaqtini kiriting (masalan 18:30):"
MSG_EDIT_ATT_CONFIRM = "✅ Yangilandi: {date}\n{ci} - {co}\nYangi ish haqi: {wage} $"

# Correction Request
BTN_CORRECTION_REQUEST = "📝 Tuzatish so'rov"
MSG_COR_REQ_DATE     = "Qaysi sana uchun tuzatish kiritmoqchisiz?"
MSG_COR_REQ_TIME_IN  = "Haqiqiy kelgan vaqtini kiriting (masalan 09:00):"
MSG_COR_REQ_TIME_OUT = "Haqiqiy ketgan vaqtini kiriting (masalan 18:00):"
MSG_COR_REQ_CONFIRM  = "Tasdiqlaysizmi?\n\nSana: {date}\nKelish: {in_time}\nKetish: {out_time}"
MSG_COR_REQ_SENT     = "✅ So'rovingiz adminga yuborildi. Javobni kuting."
MSG_COR_REQ_ADMIN    = (
    "🆕 <b>Tuzatish so'rovi</b>\n\n"
    "👤 <b>Xodim</b>: {name}\n"
    "📅 <b>Sana</b>: {date}\n"
    "📥 <b>Yangi vaqt</b>: {in_time} - {out_time}\n"
    "⚠️ <b>Hozirgi holat</b>: {current}"
)
BTN_APPROVE    = "✅ Tasdiqlash"
BTN_REJECT     = "❌ Rad etish"
MSG_REQ_APPROVED = "✅ Sizning {date} sanasi uchun tuzatish so'rovingiz tasdiqlandi."
MSG_REQ_REJECTED = "❌ Sizning {date} sanasi uchun tuzatish so'rovingiz rad etildi."
