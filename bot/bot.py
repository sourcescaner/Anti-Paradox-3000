import logging
import asyncio
import sys
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, LabeledPrice
from telegram.ext import (
    Application, CommandHandler, MessageHandler,
    CallbackQueryHandler, PreCheckoutQueryHandler, ContextTypes, filters
)
from config import TELEGRAM_TOKEN, MAX_PDF_SIZE_MB, MAX_FREE_ANALYSES, ADMIN_USER_IDS, DEFAULT_LANGUAGE, ANALYSES_PER_PACK, STARS_PER_PACK
from policy_loader import POLICY_VERSION
from analyzer import (analyze_article, PDFEmptyError, PDFReadError,
                       OpenAIRateLimitError, OpenAITimeoutError,
                       OpenAIConnectionError, OpenAIError)
from database import init_db, get_user, increment_used, add_paid, is_limit_reached, get_remaining, get_all_users

logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# Защита от дублей
processed_message_ids: set[int] = set()
processed_callback_ids: set[str] = set()

# Тест-мод (только для админов)
test_mode_users: set[int] = set()
test_mode_used: dict[int, int] = {}  # счётчик анализов внутри тест-сессии

# ─── СТАТИСТИКА (сбрасывается при перезапуске) ───────────────────────────────
from datetime import datetime

stats = {
    "started_at": datetime.now().strftime("%Y-%m-%d %H:%M"),
    "total_analyses": 0,
    "total_questions": 0,
    "total_errors": 0,
    "total_purchases": 0,
    "log": [],  # последние 50 событий: {time, user_id, event, detail}
}

def stats_log(user_id: int, event: str, detail: str = ""):
    """Записывает событие в лог статистики."""
    entry = {
        "time": datetime.now().strftime("%m-%d %H:%M"),
        "user_id": user_id,
        "event": event,
        "detail": detail,
    }
    stats["log"].append(entry)
    if len(stats["log"]) > 50:
        stats["log"].pop(0)
    logger.info(f"[STATS] {event} | user={user_id} | {detail}")


# ─── ПЕРЕВОДЫ ────────────────────────────────────────────────────────────────

T = {
    "start_text": {
        "en": (
            "👋 Hello! I analyze scientific articles for logical errors and hidden switches "
            "between incompatible mathematical descriptions.\n\n"
            "📄 Send me a PDF article and choose the analysis mode:\n\n"
            "• *Classic* — logical and formal errors, neutral language\n"
            "• *RM mode* — using Relative Mathematics concepts\n\n"
            f"🆓 First {MAX_FREE_ANALYSES} analyses are free."
        ),
        "ru": (
            "👋 Привет! Я анализирую научные статьи на логические ошибки и скрытые переходы "
            "между несовместимыми описаниями.\n\n"
            "📄 Пришли мне PDF-файл статьи и выбери режим анализа:\n\n"
            "• *Классический* — логические и формальные ошибки, нейтральный язык\n"
            "• *С терминами ОМ* — с применением концепций относительной математики\n\n"
            f"🆓 Первые {MAX_FREE_ANALYSES} анализа бесплатно."
        ),
        "uk": (
            "👋 Привіт! Я аналізую наукові статті на логічні помилки та приховані переходи "
            "між несумісними описами.\n\n"
            "📄 Надішли мені PDF-файл статті та вибери режим аналізу:\n\n"
            "• *Класичний* — логічні та формальні помилки, нейтральна мова\n"
            "• *Режим RM* — з використанням концепцій відносної математики\n\n"
            f"🆓 Перші {MAX_FREE_ANALYSES} аналізи безкоштовно."
        ),
    },
    "no_pdf_hint": {
        "en": "📄 Send a PDF article to analyze.\nOr type /help to learn how to use the bot.",
        "ru": "📄 Пришли PDF-файл статьи для анализа.\nИли введи /help чтобы узнать как пользоваться ботом.",
        "uk": "📄 Надішли PDF-файл статті для аналізу.\nАбо введи /help щоб дізнатися як користуватися ботом.",
    },
    "not_pdf": {
        "en": "⚠️ Please send a PDF file.",
        "ru": "⚠️ Пожалуйста, отправь файл в формате PDF.",
        "uk": "⚠️ Будь ласка, надішли файл у форматі PDF.",
    },
    "too_large": {
        "en": f"⚠️ File is too large. Maximum {MAX_PDF_SIZE_MB} MB.",
        "ru": f"⚠️ Файл слишком большой. Максимум {MAX_PDF_SIZE_MB} МБ.",
        "uk": f"⚠️ Файл занадто великий. Максимум {MAX_PDF_SIZE_MB} МБ.",
    },
    "limit_reached": {
        "en": f"⚠️ You've used all {MAX_FREE_ANALYSES} free analyses.\n\nBuy a pack of {ANALYSES_PER_PACK} analyses for {STARS_PER_PACK} ⭐ Stars (~$1):",
        "ru": f"⚠️ Использованы все {MAX_FREE_ANALYSES} бесплатных анализа.\n\nКупи пакет из {ANALYSES_PER_PACK} анализов за {STARS_PER_PACK} ⭐ Stars (~$1):",
        "uk": f"⚠️ Використано всі {MAX_FREE_ANALYSES} безкоштовних аналізи.\n\nКупи пакет з {ANALYSES_PER_PACK} аналізів за {STARS_PER_PACK} ⭐ Stars (~$1):",
    },
    "buy_button": {
        "en": f"⭐ Buy {ANALYSES_PER_PACK} analyses for {STARS_PER_PACK} Stars",
        "ru": f"⭐ Купить {ANALYSES_PER_PACK} анализов за {STARS_PER_PACK} Stars",
        "uk": f"⭐ Купити {ANALYSES_PER_PACK} аналізів за {STARS_PER_PACK} Stars",
    },
    "session_expired": {
        "en": "⚠️ Session expired. Please send the PDF again.",
        "ru": "⚠️ Сессия истекла. Пришли PDF ещё раз.",
        "uk": "⚠️ Сесія закінчилась. Надішли PDF ще раз.",
    },
    "analyzing": {
        "en": "⏳ Starting *{mode}* analysis...\n\nThis will take 30–60 seconds.",
        "ru": "⏳ Запускаю *{mode}* анализ...\n\nЭто займёт 30–60 секунд.",
        "uk": "⏳ Запускаю *{mode}* аналіз...\n\nЦе займе 30–60 секунд.",
    },
    "result_header": {
        "en": "📊 *Analysis result* ({mode}) | {version} {flag}\n\n",
        "ru": "📊 *Результат анализа* ({mode}) | {version} {flag}\n\n",
        "uk": "📊 *Результат аналізу* ({mode}) | {version} {flag}\n\n",
    },
    "part": {
        "en": "*[Part {i}/{n}]*\n\n",
        "ru": "*[Часть {i}/{n}]*\n\n",
        "uk": "*[Частина {i}/{n}]*\n\n",
    },
    "hint": {
        "en": (
            "🔧 *What's next?*\n\n"
            "• Press a button to adjust conclusions\n"
            "• Or just type a question about the analysis, e.g.:\n"
            "  _\"what does switch S2 mean?\"_\n"
            "  _\"why is S1 an error?\"_\n"
            "  _\"suggest a fix for S3\"_"
        ),
        "ru": (
            "🔧 *Что дальше?*\n\n"
            "• Нажми кнопку чтобы скорректировать выводы\n"
            "• Или просто напиши вопрос по анализу, например:\n"
            "  _«что значит переключение S2?»_\n"
            "  _«почему S1 — это ошибка?»_\n"
            "  _«предложи конкретную правку для S3»_"
        ),
        "uk": (
            "🔧 *Що далі?*\n\n"
            "• Натисни кнопку щоб скоригувати висновки\n"
            "• Або просто напиши запитання по аналізу, наприклад:\n"
            "  _«що означає перехід S2?»_\n"
            "  _«чому S1 — це помилка?»_\n"
            "  _«запропонуй правку для S3»_"
        ),
    },
    "adjust_buttons": {
        "en": ["⬆️ Strengthen", "⬇️ Soften", "🔄 New analysis"],
        "ru": ["⬆️ Усилить выводы", "⬇️ Ослабить выводы", "🔄 Новый анализ"],
        "uk": ["⬆️ Посилити висновки", "⬇️ Пом'якшити висновки", "🔄 Новий аналіз"],
    },
    "remaining": {
        "en": "ℹ️ Free analyses remaining: {n}",
        "ru": "ℹ️ Осталось бесплатных анализов: {n}",
        "uk": "ℹ️ Залишилось безкоштовних аналізів: {n}",
    },
    "error_analysis": {
        "en": "❌ An error occurred during analysis. Please try again or contact the administrator.",
        "ru": "❌ Произошла ошибка при анализе. Попробуй ещё раз или обратись к администратору.",
        "uk": "❌ Сталася помилка під час аналізу. Спробуй ще раз або зверніться до адміністратора.",
    },
    "error_pdf_empty": {
        "en": f"📄 Could not extract text from the PDF (maximum {MAX_PDF_SIZE_MB} MB).\nThe file may contain only scanned images. Please provide a PDF with selectable text.",
        "ru": f"📄 Не удалось извлечь текст из PDF (максимум {MAX_PDF_SIZE_MB} МБ).\nВозможно файл содержит только сканированные изображения. Пришли PDF с выделяемым текстом.",
        "uk": f"📄 Не вдалося витягти текст з PDF (максимум {MAX_PDF_SIZE_MB} МБ).\nМожливо файл містить лише скановані зображення. Надішли PDF з виділюваним текстом.",
    },
    "error_pdf_read": {
        "en": "⚠️ Could not read the PDF file. It may be corrupted or password-protected. Please try a different file.",
        "ru": "⚠️ Не удалось прочитать PDF файл. Возможно он повреждён или защищён паролем. Попробуй другой файл.",
        "uk": "⚠️ Не вдалося прочитати PDF файл. Можливо він пошкоджений або захищений паролем. Спробуй інший файл.",
    },
    "error_rate_limit": {
        "en": "🚫 OpenAI request limit exceeded. Please wait 1 minute and try again.",
        "ru": "🚫 Превышен лимит запросов к OpenAI. Подожди 1 минуту и попробуй снова.",
        "uk": "🚫 Перевищено ліміт запитів до OpenAI. Зачекай 1 хвилину і спробуй знову.",
    },
    "error_timeout": {
        "en": "⏱ Analysis took too long and timed out. Please try again — shorter articles work better.",
        "ru": "⏱ Анализ занял слишком много времени. Попробуй ещё раз — с короткими статьями работает лучше.",
        "uk": "⏱ Аналіз зайняв занадто багато часу. Спробуй ще раз — з короткими статтями працює краще.",
    },
    "error_connection": {
        "en": "🌐 Could not connect to OpenAI. Please check your connection and try again.",
        "ru": "🌐 Не удалось подключиться к OpenAI. Проверь соединение и попробуй снова.",
        "uk": "🌐 Не вдалося підключитися до OpenAI. Перевір з'єднання і спробуй знову.",
    },
    "new_analysis": {
        "en": "🔄 Ready for a new analysis. Send a PDF file.",
        "ru": "🔄 Готов к новому анализу. Пришли PDF-файл статьи.",
        "uk": "🔄 Готовий до нового аналізу. Надішли PDF-файл статті.",
    },
    "no_previous": {
        "en": "⚠️ No previous analysis. Send a PDF first.",
        "ru": "⚠️ Нет предыдущего анализа. Пришли PDF снова.",
        "uk": "⚠️ Немає попереднього аналізу. Надішли PDF знову.",
    },
    "strengthen_label": {
        "en": "⬆️ Strengthened conclusions",
        "ru": "⬆️ Усиленные выводы",
        "uk": "⬆️ Посилені висновки",
    },
    "soften_label": {
        "en": "⬇️ Softened conclusions",
        "ru": "⬇️ Смягчённые выводы",
        "uk": "⬇️ Пом'якшені висновки",
    },
    "error_adjust": {
        "en": "❌ Error while adjusting conclusions.",
        "ru": "❌ Ошибка при корректировке выводов.",
        "uk": "❌ Помилка під час коригування висновків.",
    },
    "thinking": {
        "en": "💭 Thinking...",
        "ru": "💭 Думаю...",
        "uk": "💭 Думаю...",
    },
    "answer": {
        "en": "💬 *Answer:*\n\n",
        "ru": "💬 *Ответ:*\n\n",
        "uk": "💬 *Відповідь:*\n\n",
    },
    "error_qa": {
        "en": "❌ Could not answer the question. Please try again.",
        "ru": "❌ Не удалось ответить на вопрос. Попробуй ещё раз.",
        "uk": "❌ Не вдалося відповісти на запитання. Спробуй ще раз.",
    },
    "questions_limit": {
        "en": "❗ You've used all 10 questions for this analysis session.\n\nSend a new PDF to start a fresh session.",
        "ru": "❗ Использованы все 10 вопросов по этому анализу.\n\nОтправь новый PDF чтобы начать новую сессию.",
        "uk": "❗ Використано всі 10 запитань по цьому аналізу.\n\nНадішли новий PDF щоб почати нову сесію.",
    },
    "payment_title": {
        "en": f"{ANALYSES_PER_PACK} analyses — Anti-Paradox-3000",
        "ru": f"{ANALYSES_PER_PACK} анализов — Anti-Paradox-3000",
        "uk": f"{ANALYSES_PER_PACK} аналізів — Anti-Paradox-3000",
    },
    "payment_desc": {
        "en": f"A pack of {ANALYSES_PER_PACK} scientific article analyses.",
        "ru": f"Пакет из {ANALYSES_PER_PACK} анализов научных статей.",
        "uk": f"Пакет з {ANALYSES_PER_PACK} аналізів наукових статей.",
    },
    "payment_ok": {
        "en": f"✅ Payment received! {ANALYSES_PER_PACK} analyses added.\nSend a PDF — the bot is ready. 🚀",
        "ru": f"✅ Оплата получена! Добавлено {ANALYSES_PER_PACK} анализов.\nОтправляй PDF — бот готов к работе. 🚀",
        "uk": f"✅ Оплату отримано! Додано {ANALYSES_PER_PACK} аналізів.\nНадсилай PDF — бот готовий до роботи. 🚀",
    },
    "mode_label": {
        "classical": {"en": "Classic", "ru": "Классический", "uk": "Класичний"},
        "rm": {"en": "RM mode", "ru": "Режим RM", "uk": "Режим RM"},
    },
}


def t(key: str, lang: str, **kwargs) -> str:
    """Возвращает перевод строки на нужный язык."""
    text = T.get(key, {}).get(lang) or T.get(key, {}).get("en", "")
    return text.format(**kwargs) if kwargs else text


def mode_name(mode: str, lang: str) -> str:
    """Возвращает локализованное название режима анализа."""
    return T["mode_label"].get(mode, T["mode_label"]["classical"]).get(lang, mode)


def detect_lang(tg_lang_code: str | None) -> str:
    """Определяет язык из Telegram language_code пользователя."""
    code = (tg_lang_code or "").lower()
    if code.startswith("ru"):
        return "ru"
    if code.startswith("uk"):
        return "uk"
    return "en"


async def send_long_text(target, text: str, parse_mode: str = None):
    """Отправляет длинный текст, разбивая по абзацам (не посреди строки).
    Тексты от OpenAI всегда отправляются без parse_mode во избежание 400-ошибок."""
    if len(text) <= 4000:
        await target.reply_text(text, parse_mode=parse_mode)
        return

    # Нарезаем по абзацам, не посреди строки
    paragraphs = text.split("\n\n")
    chunks = []
    current = ""
    for para in paragraphs:
        addition = ("\n\n" if current else "") + para
        if len(current) + len(addition) <= 3800:
            current += addition
        else:
            if current:
                chunks.append(current)
            # Если один абзац длиннее 3800 — режем по строкам
            if len(para) > 3800:
                lines = para.split("\n")
                sub = ""
                for line in lines:
                    if len(sub) + len(line) + 1 <= 3800:
                        sub += ("\n" if sub else "") + line
                    else:
                        if sub:
                            chunks.append(sub)
                        sub = line
                current = sub
            else:
                current = para
    if current:
        chunks.append(current)

    for chunk in chunks:
        await target.reply_text(chunk, parse_mode=parse_mode)


# ─── СТАТИЧНЫЕ ТЕКСТЫ /help и /about ────────────────────────────────────────

HELP_TEXT = {
    "en": (
        "📖 *How to use the bot:*\n\n"
        "1. Send a PDF article\n"
        "2. Choose analysis mode (Classic / RM)\n"
        "3. Get a detailed report\n"
        "4. Ask a follow-up question — just type it\n\n"
        "*Commands:*\n"
        "/start — welcome message\n"
        "/help — this help\n"
        "/about — about the analysis method\n"
        "/new — start a new analysis\n"
        "/en — switch to English 🇬🇧\n"
        "/ru — русский язык 🇷🇺\n"
        "/uk — українська мова 🇺🇦\n\n"
    ),
    "ru": (
        "📖 *Как пользоваться ботом:*\n\n"
        "1. Отправь PDF-файл статьи\n"
        "2. Выбери режим анализа (Классический / RM)\n"
        "3. Получи детальный отчёт\n"
        "4. Задай вопрос по результату — просто напиши текст\n\n"
        "*Команды:*\n"
        "/start — приветствие\n"
        "/help — эта справка\n"
        "/about — о методе анализа\n"
        "/new — начать новый анализ\n"
        "/en — switch to English 🇬🇧\n"
        "/ru — русский язык 🇷🇺\n"
        "/uk — українська мова 🇺🇦\n\n"
    ),
    "uk": (
        "📖 *Як користуватися ботом:*\n\n"
        "1. Надішли PDF-файл статті\n"
        "2. Вибери режим аналізу (Класичний / RM)\n"
        "3. Отримай детальний звіт\n"
        "4. Постав запитання по результату — просто напиши текст\n\n"
        "*Команди:*\n"
        "/start — привітання\n"
        "/help — ця довідка\n"
        "/about — про метод аналізу\n"
        "/new — почати новий аналіз\n"
        "/en — switch to English 🇬🇧\n"
        "/ru — русский язык 🇷🇺\n"
        "/uk — українська мова 🇺🇦\n\n"
    ),
}

ABOUT_TEXT = {
    "en": (
        f"🔬 *About the analysis method* (policy {POLICY_VERSION})\n\n"
        "The bot detects hidden logical switches between incompatible mathematical tasks:\n\n"
        "• *WAVE→FACT* — wave/branch description used as a factual claim without an explicit bridge\n"
        "• *PROB→FACT* — probability used to derive an outcome-fact without measurement/registration\n"
        "• *Pseudo-bridges* — 'collapse/projection' wording flagged as NOT a real bridge\n"
        "• *Overreaches* — necessity language (must/uniquely) near a hidden switch\n\n"
        "Based on the Relative Mathematics concept."
    ),
    "ru": (
        f"🔬 *О методе анализа* (политика {POLICY_VERSION})\n\n"
        "Бот ищет скрытые логические переходы между несовместимыми задачами:\n\n"
        "• *WAVE→FACT* — волновое описание используется как факт без явного моста\n"
        "• *PROB→FACT* — вероятность используется для вывода факта без регистрации\n"
        "• *Псевдо-мосты* — 'коллапс/проекция' не считается мостом и флагируется\n"
        "• *Переусиления* — язык необходимости (must/uniquely) рядом со скрытым переходом\n\n"
        "Метод основан на концепции относительной математики."
    ),
    "uk": (
        f"🔬 *Про метод аналізу* (політика {POLICY_VERSION})\n\n"
        "Бот шукає приховані логічні переходи між несумісними задачами:\n\n"
        "• *WAVE→FACT* — хвильовий опис використовується як факт без явного мосту\n"
        "• *PROB→FACT* — ймовірність використовується для виведення факту без реєстрації\n"
        "• *Псевдо-мости* — 'колапс/проекція' не вважається мостом\n"
        "• *Переперебільшення* — мова необхідності (must/uniquely) поруч із прихованим переходом\n\n"
        "Метод заснований на концепції відносної математики."
    ),
}


# ─── КОМАНДЫ ────────────────────────────────────────────────────────────────

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    # Сохраняем вручную выбранный язык — /start его не сбрасывает
    lang = context.user_data.get("lang") or detect_lang(update.effective_user.language_code)
    context.user_data.clear()
    context.user_data["lang"] = lang
    await update.message.reply_text(t("start_text", lang), parse_mode="Markdown")


async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    lang = context.user_data.get("lang", DEFAULT_LANGUAGE)
    text = HELP_TEXT.get(lang, HELP_TEXT["en"]) + f"_Policy: {POLICY_VERSION}_"
    await update.message.reply_text(text, parse_mode="Markdown")


async def about_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    lang = context.user_data.get("lang", DEFAULT_LANGUAGE)
    text = ABOUT_TEXT.get(lang, ABOUT_TEXT["en"])
    await update.message.reply_text(text, parse_mode="Markdown")


async def new_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    lang = context.user_data.get("lang", DEFAULT_LANGUAGE)
    context.user_data.clear()
    context.user_data["lang"] = lang  # сохраняем язык после очистки
    await update.message.reply_text(t("new_analysis", lang))


async def stats_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Показывает статистику — только для администратора."""
    user_id = update.effective_user.id
    if user_id not in ADMIN_USER_IDS:
        await update.message.reply_text("⛔ Команда доступна только администратору.")
        return

    # Собираем топ пользователей из БД
    all_users = await get_all_users()
    top_users = all_users[:5]
    top_text = "\n".join(
        f"  {u['user_id']}: {u['used']} исп. / {u['paid']} оплачено"
        for u in top_users
    ) or "  —"

    # Последние 10 событий
    recent = stats["log"][-10:]
    log_text = "\n".join(
        f"  [{e['time']}] {e['event']} | user={e['user_id']} | {e['detail']}"
        for e in reversed(recent)
    ) or "  —"

    in_testmode = "🧪 ВКЛ" if user_id in test_mode_users else "✅ ВЫКЛ"

    text = (
        f"📊 Статистика AntiParadox-3000\n"
        f"Политика: {POLICY_VERSION}\n"
        f"Запущен: {stats['started_at']}\n"
        f"Тест-мод: {in_testmode}\n\n"
        f"Всего анализов: {stats['total_analyses']}\n"
        f"Всего вопросов: {stats['total_questions']}\n"
        f"Ошибок анализа: {stats['total_errors']}\n"
        f"Покупок пакетов: {stats['total_purchases']}\n\n"
        f"Топ пользователей:\n{top_text}\n\n"
        f"Последние события:\n{log_text}"
    )

    # Панель кнопок для администратора
    admin_keyboard = InlineKeyboardMarkup([
        [
            InlineKeyboardButton("🧪 Включить тест-мод", callback_data="admin_testmode"),
            InlineKeyboardButton("✅ Выйти из тест-мода", callback_data="admin_adminmode"),
        ],
        [
            InlineKeyboardButton("➕ +1 анализ себе", callback_data="admin_addpaid_1"),
            InlineKeyboardButton("➕ +10 анализов себе", callback_data="admin_addpaid_10"),
        ],
        [
            InlineKeyboardButton("🔄 Обновить статистику", callback_data="admin_stats_refresh"),
        ],
    ])

    await update.message.reply_text(text, reply_markup=admin_keyboard)


async def testmode_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Включает тест-мод: снимает админ-привилегии, лимит = 1 анализ."""
    user_id = update.effective_user.id
    if user_id not in ADMIN_USER_IDS:
        return
    test_mode_users.add(user_id)
    test_mode_used[user_id] = 0  # сбрасываем счётчик сессии
    await update.message.reply_text(
        "🧪 Тест-мод включён.\n"
        "Ты теперь обычный пользователь с лимитом 1 анализ.\n"
        "Доступно: 1 анализ.\n"
        "Для возврата напиши /adminmode"
    )


async def adminmode_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Выключает тест-мод и возвращает админ-привилегии."""
    user_id = update.effective_user.id
    if user_id not in ADMIN_USER_IDS:
        return
    test_mode_users.discard(user_id)
    await update.message.reply_text("✅ Админ-мод восстановлен. Лимиты сняты.")


async def handle_admin_panel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обрабатывает кнопки админ-панели из /stats."""
    query = update.callback_query
    await query.answer()
    user_id = update.effective_user.id
    if user_id not in ADMIN_USER_IDS:
        return

    if query.data == "admin_testmode":
        test_mode_users.add(user_id)
        test_mode_used[user_id] = 0
        await query.message.reply_text(
            "🧪 Тест-мод включён. Лимит: 1 анализ.\nДля выхода — нажми /stats → Выйти из тест-мода"
        )

    elif query.data == "admin_adminmode":
        test_mode_users.discard(user_id)
        await query.message.reply_text("✅ Админ-мод восстановлен. Лимиты сняты.")

    elif query.data in ("admin_addpaid_1", "admin_addpaid_10"):
        amount = 1 if query.data == "admin_addpaid_1" else 10
        await add_paid(user_id, amount)
        remaining = await get_remaining(user_id)
        stats_log(user_id, "MANUAL_ADDPAID", f"target={user_id} amount={amount}")
        await query.message.reply_text(
            f"✅ Зачислено {amount} анализов.\nДоступно сейчас: {remaining}"
        )

    elif query.data == "admin_stats_refresh":
        # Переиспользуем логику stats_command
        await stats_command(update, context)


async def addpaid_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Вручную зачисляет анализы пользователю. Только для админа.
    Использование: /addpaid [user_id] [amount]
    Без аргументов — зачисляет 10 анализов себе."""
    user_id = update.effective_user.id
    if user_id not in ADMIN_USER_IDS:
        return
    args = context.args
    try:
        if len(args) == 0:
            target_id, amount = user_id, ANALYSES_PER_PACK
        elif len(args) == 1:
            target_id, amount = user_id, int(args[0])
        else:
            target_id, amount = int(args[0]), int(args[1])
        await add_paid(target_id, amount)
        remaining = await get_remaining(target_id)
        await update.message.reply_text(
            f"✅ Зачислено {amount} анализов пользователю {target_id}.\n"
            f"Всего доступно сейчас: {remaining}"
        )
        stats_log(user_id, "MANUAL_ADDPAID", f"target={target_id} amount={amount}")
    except (ValueError, IndexError):
        await update.message.reply_text(
            "❌ Использование: /addpaid [user_id] [amount]\n"
            "Примеры:\n  /addpaid → +10 себе\n  /addpaid 5 → +5 себе\n  /addpaid 123456 10 → +10 юзеру"
        )


async def lang_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Переключает язык по команде /en, /ru, /uk."""
    cmd = update.message.text.strip().lstrip("/").lower()
    lang_map = {"en": ("en", "🇬🇧 English"), "ru": ("ru", "🇷🇺 Русский"), "uk": ("uk", "🇺🇦 Українська")}
    if cmd in lang_map:
        context.user_data["lang"] = lang_map[cmd][0]
        context.user_data["last_lang"] = lang_map[cmd][0]
        await update.message.reply_text(f"Language set: {lang_map[cmd][1]}")


# ─── АВТООЧИСТКА КОНТЕКСТА ───────────────────────────────────────────────────

async def _clear_user_context(context: ContextTypes.DEFAULT_TYPE):
    """Очищает результат анализа конкретного пользователя через 1 час."""
    user_id = context.job.data["user_id"]
    user_data = context.application.user_data.get(user_id, {})
    user_data.pop("last_result", None)
    user_data.pop("last_mode", None)
    user_data.pop("last_lang", None)
    user_data.pop("pending_pdf_id", None)
    logger.info(f"Контекст пользователя {user_id} очищен по таймауту.")


# ─── ОБРАБОТКА PDF ───────────────────────────────────────────────────────────

async def handle_pdf(update: Update, context: ContextTypes.DEFAULT_TYPE):
    msg_id = update.message.message_id
    if msg_id in processed_message_ids:
        return
    processed_message_ids.add(msg_id)

    user_id = update.effective_user.id
    document = update.message.document

    # Язык: из сохранённых настроек или авто-определение из профиля Telegram
    lang = context.user_data.get("lang") or detect_lang(update.effective_user.language_code)

    if document.mime_type != "application/pdf":
        await update.message.reply_text(t("not_pdf", lang))
        return

    if document.file_size > MAX_PDF_SIZE_MB * 1024 * 1024:
        await update.message.reply_text(t("too_large", lang))
        return

    # Проверка лимита (тест-мод: лимит 1 анализ в сессии, без БД)
    if user_id in test_mode_users:
        if test_mode_used.get(user_id, 0) >= 1:
            keyboard = InlineKeyboardMarkup([[
                InlineKeyboardButton(t("buy_button", lang), callback_data="buy_pack")
            ]])
            await update.message.reply_text(
                f"🧪 [ТЕСТ-МОД] {t('limit_reached', lang)}",
                reply_markup=keyboard
            )
            return
    elif await is_limit_reached(user_id):
        keyboard = InlineKeyboardMarkup([[
            InlineKeyboardButton(t("buy_button", lang), callback_data="buy_pack")
        ]])
        await update.message.reply_text(t("limit_reached", lang), reply_markup=keyboard)
        return

    context.user_data["pending_pdf_id"] = document.file_id
    context.user_data["pending_pdf_name"] = document.file_name
    context.user_data.pop("last_result", None)
    context.user_data["lang"] = lang  # фиксируем язык

    stats_log(user_id, "PDF_RECEIVED", document.file_name)

    lang_flag = {"ru": "🇷🇺", "uk": "🇺🇦", "en": "🇬🇧"}.get(lang, "🇬🇧")

    panel_text = {
        "ru": f"📄 *{document.file_name}*\n\nЯзык определён автоматически: {lang_flag}\nИзменить ↑ или выбери режим анализа ↓",
        "uk": f"📄 *{document.file_name}*\n\nМову визначено автоматично: {lang_flag}\nЗмінити ↑ або вибери режим аналізу ↓",
        "en": f"📄 *{document.file_name}*\n\nLanguage auto-detected: {lang_flag}\nChange if needed ↑ then choose analysis mode ↓",
    }

    mode_buttons = {
        "ru": [InlineKeyboardButton("📋 Классический", callback_data="mode_classic"),
               InlineKeyboardButton("🔬 Режим RM", callback_data="mode_rm")],
        "uk": [InlineKeyboardButton("📋 Класичний", callback_data="mode_classic"),
               InlineKeyboardButton("🔬 Режим RM", callback_data="mode_rm")],
        "en": [InlineKeyboardButton("📋 Classic", callback_data="mode_classic"),
               InlineKeyboardButton("🔬 RM mode", callback_data="mode_rm")],
    }

    keyboard = [
        [
            InlineKeyboardButton("🇬🇧 English", callback_data="lang_en"),
            InlineKeyboardButton("🇺🇦 Українська", callback_data="lang_uk"),
            InlineKeyboardButton("🇷🇺 Русский", callback_data="lang_ru"),
        ],
        mode_buttons.get(lang, mode_buttons["en"]),
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)

    await update.message.reply_text(
        panel_text.get(lang, panel_text["en"]),
        reply_markup=reply_markup,
        parse_mode="Markdown"
    )


# ─── ВЫБОР РЕЖИМА / ЯЗЫКА ────────────────────────────────────────────────────

async def handle_mode_selection(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query

    cb_id = query.id
    if cb_id in processed_callback_ids:
        await query.answer()
        return
    processed_callback_ids.add(cb_id)

    await query.answer()

    if query.data in ("lang_ru", "lang_uk", "lang_en"):
        lang_map = {"lang_ru": "ru", "lang_uk": "uk", "lang_en": "en"}
        label_map = {"lang_ru": "🇷🇺 Русский", "lang_uk": "🇺🇦 Українська", "lang_en": "🇬🇧 English"}
        context.user_data["lang"] = lang_map[query.data]
        await query.answer(f"Language: {label_map[query.data]}", show_alert=False)
        return

    user_id = update.effective_user.id
    lang = context.user_data.get("lang", DEFAULT_LANGUAGE)
    mode = "classical" if query.data == "mode_classic" else "rm"
    mode_lbl = mode_name(mode, lang)

    pdf_id = context.user_data.get("pending_pdf_id")
    if not pdf_id:
        try:
            await query.edit_message_text(t("session_expired", lang))
        except Exception:
            pass
        return

    if context.user_data.get("analyzing"):
        return
    context.user_data["analyzing"] = True

    try:
        await query.edit_message_text(
            t("analyzing", lang, mode=mode_lbl),
            parse_mode="Markdown"
        )
    except Exception:
        pass

    try:
        file = await context.bot.get_file(pdf_id)
        pdf_bytes = await file.download_as_bytearray()

        result = await analyze_article(bytes(pdf_bytes), mode=mode, lang=lang)

        # Тест-мод: считаем локально, не пишем в БД
        if user_id in test_mode_users:
            test_mode_used[user_id] = test_mode_used.get(user_id, 0) + 1
            remaining = 0  # в тест-моде показываем кнопку покупки
        else:
            await increment_used(user_id)
            remaining = await get_remaining(user_id)

        context.user_data["last_result"] = result
        context.user_data["last_mode"] = mode
        context.user_data["last_lang"] = lang
        context.user_data["question_count"] = 0

        stats["total_analyses"] += 1
        pdf_name = context.user_data.get("pending_pdf_name", "unknown")
        stats_log(user_id, "ANALYSIS_DONE", f"mode={mode} lang={lang} file={pdf_name}")

        # Очищаем результат через 1 час (если job-queue установлен)
        if context.job_queue:
            context.job_queue.run_once(
                _clear_user_context,
                when=3600,
                data={"user_id": user_id, "chat_id": update.effective_chat.id},
                name=f"clear_{user_id}"
            )

        lang_flag = {"ru": "🇷🇺", "uk": "🇺🇦", "en": "🇬🇧"}.get(lang, "🇬🇧")
        header = t("result_header", lang, mode=mode_lbl, version=POLICY_VERSION, flag=lang_flag)
        # Заголовок — наш текст, с Markdown. Результат от OpenAI — plain text (без parse_mode)
        await query.message.reply_text(header.strip(), parse_mode="Markdown")
        await send_long_text(query.message, result)

        # Кнопки корректировки
        btns = T["adjust_buttons"].get(lang, T["adjust_buttons"]["en"])
        adjust_keyboard = InlineKeyboardMarkup([
            [
                InlineKeyboardButton(btns[0], callback_data="adjust_strengthen"),
                InlineKeyboardButton(btns[1], callback_data="adjust_weaken"),
            ],
            [
                InlineKeyboardButton(btns[2], callback_data="new_analysis"),
            ]
        ])

        await query.message.reply_text(t("hint", lang), reply_markup=adjust_keyboard, parse_mode="Markdown")

        is_testmode = user_id in test_mode_users
        if is_testmode:
            # В тест-моде показываем кнопку покупки (как обычный юзер с нулём анализов)
            keyboard = InlineKeyboardMarkup([[
                InlineKeyboardButton(t("buy_button", lang), callback_data="buy_pack")
            ]])
            await query.message.reply_text(
                f"🧪 [ТЕСТ-МОД] {t('limit_reached', lang)}",
                reply_markup=keyboard
            )
        elif remaining > 0 and user_id not in ADMIN_USER_IDS:
            await query.message.reply_text(t("remaining", lang, n=remaining))
        elif remaining == 0 and user_id not in ADMIN_USER_IDS:
            keyboard = InlineKeyboardMarkup([[
                InlineKeyboardButton(t("buy_button", lang), callback_data="buy_pack")
            ]])
            await query.message.reply_text(t("limit_reached", lang), reply_markup=keyboard)

    except PDFEmptyError:
        stats["total_errors"] += 1
        stats_log(user_id, "ANALYSIS_ERROR", "PDF empty/scanned")
        await query.message.reply_text(t("error_pdf_empty", lang))
    except PDFReadError as e:
        stats["total_errors"] += 1
        stats_log(user_id, "ANALYSIS_ERROR", f"PDF read error: {str(e)[:60]}")
        await query.message.reply_text(t("error_pdf_read", lang))
    except OpenAIRateLimitError:
        stats["total_errors"] += 1
        stats_log(user_id, "ANALYSIS_ERROR", "OpenAI rate limit")
        await query.message.reply_text(t("error_rate_limit", lang))
    except OpenAITimeoutError:
        stats["total_errors"] += 1
        stats_log(user_id, "ANALYSIS_ERROR", "OpenAI timeout")
        await query.message.reply_text(t("error_timeout", lang))
    except OpenAIConnectionError:
        stats["total_errors"] += 1
        stats_log(user_id, "ANALYSIS_ERROR", "OpenAI connection error")
        await query.message.reply_text(t("error_connection", lang))
    except Exception as e:
        logger.error(f"Ошибка анализа: {e}")
        stats["total_errors"] += 1
        stats_log(user_id, "ANALYSIS_ERROR", str(e)[:80])
        await query.message.reply_text(t("error_analysis", lang))
    finally:
        context.user_data["analyzing"] = False
        context.user_data.pop("pending_pdf_id", None)


# ─── УСИЛЕНИЕ / ОСЛАБЛЕНИЕ ВЫВОДОВ ──────────────────────────────────────────

async def handle_adjust(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    lang = context.user_data.get("last_lang", context.user_data.get("lang", DEFAULT_LANGUAGE))

    if query.data == "new_analysis":
        context.user_data.pop("last_result", None)
        context.user_data.pop("pending_pdf_id", None)
        await query.message.reply_text(t("new_analysis", lang))
        return

    last_result = context.user_data.get("last_result")

    if not last_result:
        await query.message.reply_text(t("no_previous", lang))
        return

    direction = query.data

    if direction == "adjust_strengthen":
        instruction = (
            "Based on the previous analysis — strengthen the conclusions where there is sufficient evidence. "
            "Add specific examples from the text. Indicate which switches are most critical for the article's logic."
        )
        label = t("strengthen_label", lang)
    else:
        instruction = (
            "Based on the previous analysis — soften the conclusions. "
            "Indicate where the author may have intentionally simplified, where transitions are acceptable in context, "
            "and suggest minimal fixes that make the reasoning valid."
        )
        label = t("soften_label", lang)

    await query.message.reply_text(f"⏳ *{label}*...", parse_mode="Markdown")

    try:
        from analyzer import adjust_analysis
        result = await adjust_analysis(last_result, instruction, lang)

        await query.message.reply_text(f"*{label}*", parse_mode="Markdown")
        await send_long_text(query.message, result)
    except Exception as e:
        logger.error(f"Ошибка корректировки: {e}")
        await query.message.reply_text(t("error_adjust", lang))


# ─── ВОПРОСЫ ПО АНАЛИЗУ (текстовые сообщения) ───────────────────────────────

async def handle_text_question(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Отвечает на вопросы пользователя по результату последнего анализа."""
    msg_id = update.message.message_id
    if msg_id in processed_message_ids:
        return
    processed_message_ids.add(msg_id)

    last_result = context.user_data.get("last_result")
    lang = context.user_data.get("last_lang", context.user_data.get("lang", DEFAULT_LANGUAGE))

    if not last_result:
        await update.message.reply_text(t("no_pdf_hint", lang))
        return

    q_count = context.user_data.get("question_count", 0)
    if q_count >= 10:
        await update.message.reply_text(t("questions_limit", lang))
        return

    question = update.message.text.strip()
    context.user_data["question_count"] = q_count + 1
    stats["total_questions"] += 1
    stats_log(update.effective_user.id, "QUESTION", f"q{q_count+1}: {question[:60]}")
    thinking_msg = await update.message.reply_text(t("thinking", lang))

    try:
        from analyzer import ask_about_analysis
        answer = await ask_about_analysis(last_result, question, lang)

        await thinking_msg.delete()

        await update.message.reply_text(t("answer", lang), parse_mode="Markdown")
        await send_long_text(update.message, answer)

    except Exception as e:
        logger.error(f"Ошибка Q&A: {e}")
        try:
            await thinking_msg.delete()
        except Exception:
            pass
        await update.message.reply_text(t("error_qa", lang))


# ─── МОНЕТИЗАЦИЯ (Telegram Stars) ────────────────────────────────────────────

async def handle_buy(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Отправляет инвойс на покупку пакета анализов."""
    query = update.callback_query

    cb_id = query.id
    if cb_id in processed_callback_ids:
        await query.answer()
        return
    processed_callback_ids.add(cb_id)

    await query.answer()
    lang = context.user_data.get("lang", DEFAULT_LANGUAGE)
    try:
        chat_id = update.effective_chat.id
        user_id_log = update.effective_user.id
        logger.info(f"[PAYMENT] Sending invoice to chat_id={chat_id} user_id={user_id_log}")
        invoice_msg = await context.bot.send_invoice(
            chat_id=chat_id,
            title=t("payment_title", lang),
            description=t("payment_desc", lang),
            payload="analyses_pack_10",
            currency="XTR",
            prices=[LabeledPrice(t("payment_title", lang), STARS_PER_PACK)]
        )
        logger.info(f"[PAYMENT] Invoice sent OK to chat_id={chat_id}, message_id={invoice_msg.message_id}")
        await context.bot.send_message(
            chat_id=chat_id,
            text=f"⬆️ Выше — счёт на оплату. Нажми кнопку Pay внутри него."
        )
    except Exception as e:
        logger.error(f"[PAYMENT] Invoice error: {e}")
        await query.message.reply_text(f"❌ Ошибка при создании счёта: {e}")


async def pre_checkout(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Подтверждает платёж (обязательно для Telegram Stars)."""
    pq = update.pre_checkout_query
    logger.info(f"[PAYMENT] PreCheckout from user={pq.from_user.id} payload={pq.invoice_payload} amount={pq.total_amount} currency={pq.currency}")
    await pq.answer(ok=True)
    logger.info(f"[PAYMENT] PreCheckout answered OK for user={pq.from_user.id}")


async def successful_payment(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Начисляет анализы после успешной оплаты."""
    sp = update.message.successful_payment
    logger.info(f"[PAYMENT] SuccessfulPayment from user={update.effective_user.id} payload={sp.invoice_payload} amount={sp.total_amount} currency={sp.currency}")
    user_id = update.effective_user.id
    lang = context.user_data.get("lang", DEFAULT_LANGUAGE)
    try:
        await add_paid(user_id, ANALYSES_PER_PACK)
        logger.info(f"Пользователь {user_id} купил пакет {ANALYSES_PER_PACK} анализов.")
        stats["total_purchases"] += 1
        stats_log(user_id, "PURCHASE", f"{ANALYSES_PER_PACK} analyses for {STARS_PER_PACK} Stars")
        await update.message.reply_text(t("payment_ok", lang))
    except Exception as e:
        logger.error(f"Payment processing error: {e}")
        await update.message.reply_text(f"❌ Ошибка при зачислении: {e}")


# ─── ЗАПУСК ──────────────────────────────────────────────────────────────────

async def on_startup(app):
    """Инициализация БД при старте бота."""
    await init_db()
    logger.info("База данных инициализирована")


def main():
    app = Application.builder().token(TELEGRAM_TOKEN).post_init(on_startup).build()

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("help", help_command))
    app.add_handler(CommandHandler("about", about_command))
    app.add_handler(CommandHandler("new", new_command))
    app.add_handler(CommandHandler("stats", stats_command))
    app.add_handler(CommandHandler("testmode", testmode_command))
    app.add_handler(CommandHandler("adminmode", adminmode_command))
    app.add_handler(CommandHandler("addpaid", addpaid_command))
    app.add_handler(CommandHandler("en", lang_command))
    app.add_handler(CommandHandler("ru", lang_command))
    app.add_handler(CommandHandler("uk", lang_command))
    app.add_handler(MessageHandler(filters.Document.ALL, handle_pdf))
    app.add_handler(CallbackQueryHandler(handle_buy, pattern="^buy_pack$"))
    app.add_handler(CallbackQueryHandler(handle_admin_panel, pattern="^admin_"))
    app.add_handler(CallbackQueryHandler(handle_adjust, pattern="^(adjust_|new_analysis)"))
    app.add_handler(CallbackQueryHandler(handle_mode_selection))
    app.add_handler(PreCheckoutQueryHandler(pre_checkout))
    app.add_handler(MessageHandler(filters.SUCCESSFUL_PAYMENT, successful_payment))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_text_question))

    logger.info("Бот запущен...")
    app.run_polling(drop_pending_updates=True)


if __name__ == "__main__":
    # Фикс для Windows (Python 3.12+)
    if sys.platform == "win32":
        asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
    main()
