import logging
import asyncio
import sys
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    Application, CommandHandler, MessageHandler,
    CallbackQueryHandler, ContextTypes, filters
)
from config import TELEGRAM_TOKEN, MAX_PDF_SIZE_MB, MAX_FREE_ANALYSES, ADMIN_USER_IDS, DEFAULT_LANGUAGE
from policy_loader import POLICY_VERSION
from analyzer import analyze_article

logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# Простое хранилище счётчиков (в памяти; для продакшна нужна БД)
user_analysis_count: dict[int, int] = {}

# Защита от дублей
processed_message_ids: set[int] = set()
processed_callback_ids: set[str] = set()


# ─── КОМАНДЫ ────────────────────────────────────────────────────────────────

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data.clear()
    text = (
        "👋 Привет! Я анализирую научные статьи на логические ошибки и скрытые переходы между несовместимыми описаниями.\n\n"
        "📄 Пришли мне PDF-файл статьи и выбери режим анализа:\n\n"
        "• *Классический* — логические и формальные ошибки, нейтральный язык\n"
        "• *С терминами ОМ* — с применением концепций относительной математики\n\n"
        f"🆓 Первые {MAX_FREE_ANALYSES} анализа бесплатно."
    )
    await update.message.reply_text(text, parse_mode="Markdown")


async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = (
        "📖 *Как пользоваться ботом:*\n\n"
        "1. Отправь PDF-файл статьи\n"
        "2. Выбери язык и режим анализа\n"
        "3. Получи детальный отчёт\n"
        "4. Задай вопрос по результату — просто напиши текст\n\n"
        "*Команды:*\n"
        "/start — начало работы\n"
        "/help — эта справка\n"
        "/about — о методе анализа\n"
        "/new — начать новый анализ"
    )
    await update.message.reply_text(text, parse_mode="Markdown")


async def about_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = (
        "🔬 *О методе анализа*\n\n"
        "Бот ищет скрытые логические переходы между несовместимыми математическими описаниями:\n\n"
        "• *WAVE→FACT* — переход волновое описание → факт без явного моста\n"
        "• *PROB→FACT* — переход вероятность → факт без явного моста (измерения/регистрации)\n"
        "• *Переусиления* — слишком сильные выводы (must/uniquely) в смешанных утверждениях\n\n"
        "Метод основан на концепции относительной математики."
    )
    await update.message.reply_text(text, parse_mode="Markdown")


async def new_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data.clear()
    await update.message.reply_text("🔄 Готов к новому анализу. Пришли PDF-файл статьи.")


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

    if document.mime_type != "application/pdf":
        await update.message.reply_text("⚠️ Пожалуйста, отправь файл в формате PDF.")
        return

    if document.file_size > MAX_PDF_SIZE_MB * 1024 * 1024:
        await update.message.reply_text(f"⚠️ Файл слишком большой. Максимум {MAX_PDF_SIZE_MB} МБ.")
        return

    count = user_analysis_count.get(user_id, 0)
    if count >= MAX_FREE_ANALYSES and user_id not in ADMIN_USER_IDS:
        await update.message.reply_text(
            f"⚠️ Вы использовали все {MAX_FREE_ANALYSES} бесплатных анализа.\n"
            "💳 Для продолжения необходима подписка (скоро)."
        )
        return

    context.user_data["pending_pdf_id"] = document.file_id
    context.user_data["pending_pdf_name"] = document.file_name
    # Сбрасываем предыдущий результат при новом PDF
    context.user_data.pop("last_result", None)

    keyboard = [
        [
            InlineKeyboardButton("🇷🇺 Русский", callback_data="lang_ru"),
            InlineKeyboardButton("🇺🇦 Українська", callback_data="lang_uk"),
            InlineKeyboardButton("🇬🇧 English", callback_data="lang_en"),
        ],
        [
            InlineKeyboardButton("📋 Классический", callback_data="mode_classic"),
            InlineKeyboardButton("🔬 С терминами ОМ", callback_data="mode_rm"),
        ],
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)

    await update.message.reply_text(
        f"📄 Файл получен: *{document.file_name}*\n\n"
        f"1️⃣ Выбери язык ответа (по умолчанию — русский)\n"
        f"2️⃣ Выбери режим анализа:",
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
        await query.answer(f"Язык выбран: {label_map[query.data]}", show_alert=False)
        return

    user_id = update.effective_user.id
    mode = "classical" if query.data == "mode_classic" else "rm"
    mode_label = "Классический" if mode == "classical" else "С терминами относительной математики"

    pdf_id = context.user_data.get("pending_pdf_id")
    if not pdf_id:
        try:
            await query.edit_message_text("⚠️ Сессия истекла. Пришли PDF ещё раз.")
        except Exception:
            pass
        return

    if context.user_data.get("analyzing"):
        return
    context.user_data["analyzing"] = True

    try:
        await query.edit_message_text(
            f"⏳ Запускаю *{mode_label}* анализ...\n\nЭто займёт 30–60 секунд.",
            parse_mode="Markdown"
        )
    except Exception:
        pass

    try:
        file = await context.bot.get_file(pdf_id)
        pdf_bytes = await file.download_as_bytearray()

        lang = context.user_data.get("lang", DEFAULT_LANGUAGE)
        result = await analyze_article(bytes(pdf_bytes), mode=mode, lang=lang)

        user_analysis_count[user_id] = user_analysis_count.get(user_id, 0) + 1
        remaining = MAX_FREE_ANALYSES - user_analysis_count[user_id]

        context.user_data["last_result"] = result
        context.user_data["last_mode"] = mode
        context.user_data["last_lang"] = lang

        # Очищаем результат через 1 час
        context.job_queue.run_once(
            _clear_user_context,
            when=3600,
            data={"user_id": user_id, "chat_id": update.effective_chat.id},
            name=f"clear_{user_id}"
        )

        header = f"📊 *Результат анализа* ({mode_label}) | политика {POLICY_VERSION}\n\n"
        full_text = header + result

        if len(full_text) <= 4096:
            await query.message.reply_text(full_text, parse_mode="Markdown")
        else:
            chunks = [full_text[i:i+4000] for i in range(0, len(full_text), 4000)]
            for i, chunk in enumerate(chunks):
                prefix = f"*[Часть {i+1}/{len(chunks)}]*\n\n" if len(chunks) > 1 else ""
                await query.message.reply_text(prefix + chunk, parse_mode="Markdown")

        # Кнопки корректировки
        adjust_keyboard = InlineKeyboardMarkup([
            [
                InlineKeyboardButton("⬆️ Усилить выводы", callback_data="adjust_strengthen"),
                InlineKeyboardButton("⬇️ Ослабить выводы", callback_data="adjust_weaken"),
            ],
            [
                InlineKeyboardButton("🔄 Новый анализ", callback_data="new_analysis"),
            ]
        ])

        hint = (
            "🔧 *Что дальше?*\n\n"
            "• Нажми кнопку чтобы скорректировать выводы\n"
            "• Или просто напиши вопрос по анализу, например:\n"
            "  _«что значит переключение S2?»_\n"
            "  _«почему S1 — это ошибка?»_\n"
            "  _«предложи конкретную правку для S3»_"
        )
        await query.message.reply_text(hint, reply_markup=adjust_keyboard, parse_mode="Markdown")

        if remaining > 0:
            await query.message.reply_text(f"ℹ️ Осталось бесплатных анализов: {remaining}")

    except Exception as e:
        logger.error(f"Ошибка анализа: {e}")
        await query.message.reply_text(
            "❌ Произошла ошибка при анализе. Попробуй ещё раз или обратись к администратору."
        )
    finally:
        context.user_data["analyzing"] = False
        context.user_data.pop("pending_pdf_id", None)


# ─── УСИЛЕНИЕ / ОСЛАБЛЕНИЕ ВЫВОДОВ ──────────────────────────────────────────

async def handle_adjust(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    if query.data == "new_analysis":
        context.user_data.pop("last_result", None)
        context.user_data.pop("pending_pdf_id", None)
        await query.message.reply_text("🔄 Готов к новому анализу. Пришли PDF-файл статьи.")
        return

    last_result = context.user_data.get("last_result")
    lang = context.user_data.get("last_lang", DEFAULT_LANGUAGE)

    if not last_result:
        await query.message.reply_text("⚠️ Нет предыдущего анализа. Пришли PDF снова.")
        return

    direction = query.data

    if direction == "adjust_strengthen":
        instruction = (
            "На основе предыдущего анализа — усиль выводы там где есть достаточно оснований. "
            "Добавь конкретные примеры из текста. Укажи какие именно переходы наиболее критичны для логики статьи."
            if lang == "ru" else
            "Based on the previous analysis — strengthen the conclusions where there is sufficient evidence. "
            "Add specific examples from the text. Indicate which switches are most critical for the article's logic."
        )
        label = "⬆️ Усиленные выводы"
    else:
        instruction = (
            "На основе предыдущего анализа — смягчи выводы. "
            "Укажи где автор мог намеренно упрощать, где переходы допустимы в контексте статьи, "
            "и предложи минимальные правки которые делают рассуждение корректным."
            if lang == "ru" else
            "Based on the previous analysis — soften the conclusions. "
            "Indicate where the author may have intentionally simplified, where transitions are acceptable in context, "
            "and suggest minimal fixes that make the reasoning valid."
        )
        label = "⬇️ Смягчённые выводы"

    await query.message.reply_text(f"⏳ *{label}*...", parse_mode="Markdown")

    try:
        from analyzer import adjust_analysis
        result = await adjust_analysis(last_result, instruction, lang)

        full_text = f"*{label}*\n\n{result}"
        if len(full_text) <= 4096:
            await query.message.reply_text(full_text, parse_mode="Markdown")
        else:
            chunks = [full_text[i:i+4000] for i in range(0, len(full_text), 4000)]
            for i, chunk in enumerate(chunks):
                prefix = f"*[Часть {i+1}/{len(chunks)}]*\n\n" if len(chunks) > 1 else ""
                await query.message.reply_text(prefix + chunk, parse_mode="Markdown")
    except Exception as e:
        logger.error(f"Ошибка корректировки: {e}")
        await query.message.reply_text("❌ Ошибка при корректировке выводов.")


# ─── ВОПРОСЫ ПО АНАЛИЗУ (текстовые сообщения) ───────────────────────────────

async def handle_text_question(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Отвечает на вопросы пользователя по результату последнего анализа."""
    msg_id = update.message.message_id
    if msg_id in processed_message_ids:
        return
    processed_message_ids.add(msg_id)

    last_result = context.user_data.get("last_result")

    if not last_result:
        # Нет активного анализа — подсказываем что делать
        await update.message.reply_text(
            "📄 Пришли PDF-файл статьи для анализа.\n"
            "Или введи /help чтобы узнать как пользоваться ботом."
        )
        return

    question = update.message.text.strip()
    lang = context.user_data.get("last_lang", DEFAULT_LANGUAGE)

    thinking_msg = await update.message.reply_text("💭 Думаю...")

    try:
        from analyzer import ask_about_analysis
        answer = await ask_about_analysis(last_result, question, lang)

        await thinking_msg.delete()

        full_text = f"💬 *Ответ:*\n\n{answer}"
        if len(full_text) <= 4096:
            await update.message.reply_text(full_text, parse_mode="Markdown")
        else:
            chunks = [full_text[i:i+4000] for i in range(0, len(full_text), 4000)]
            for i, chunk in enumerate(chunks):
                prefix = f"*[Часть {i+1}/{len(chunks)}]*\n\n" if len(chunks) > 1 else ""
                await update.message.reply_text(prefix + chunk, parse_mode="Markdown")

    except Exception as e:
        logger.error(f"Ошибка Q&A: {e}")
        try:
            await thinking_msg.delete()
        except Exception:
            pass
        await update.message.reply_text("❌ Не удалось ответить на вопрос. Попробуй ещё раз.")


# ─── ЗАПУСК ──────────────────────────────────────────────────────────────────

def main():
    app = Application.builder().token(TELEGRAM_TOKEN).build()

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("help", help_command))
    app.add_handler(CommandHandler("about", about_command))
    app.add_handler(CommandHandler("new", new_command))
    app.add_handler(MessageHandler(filters.Document.ALL, handle_pdf))
    app.add_handler(CallbackQueryHandler(handle_adjust, pattern="^(adjust_|new_analysis)"))
    app.add_handler(CallbackQueryHandler(handle_mode_selection))
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
