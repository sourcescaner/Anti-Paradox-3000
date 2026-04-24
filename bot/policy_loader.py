import yaml
import os

POLICY_PATH = os.path.join(os.path.dirname(__file__), "..", "Files", "rm_bot_policy_v0.3.6.yml")


def load_policy() -> dict:
    with open(POLICY_PATH, "r", encoding="utf-8") as f:
        data = yaml.safe_load(f)
    return data.get("rm_bot_policy", data)


def build_system_prompt(mode: str = "classical", lang: str = "ru") -> str:
    p = load_policy()

    # --- Язык ---
    if lang == "ru":
        lang_block = (
            "ЯЗЫК: Весь ответ ТОЛЬКО на русском языке. Это жёсткое требование.\n"
            "Цитаты из статьи оставляй на языке оригинала (в кавычках).\n"
            "Все заголовки, объяснения, карточки — строго на русском.\n"
            "НЕ используй английские слова кроме как внутри цитат из статьи."
        )
    else:
        lang_block = (
            "LANGUAGE: Respond ONLY in English. All headings, explanations and switch items must be in English.\n"
            "Keep quotes in the original language of the source (in quotation marks)."
        )

    # --- Режим ---
    if mode == "rm":
        mode_block = (
            "РЕЖИМ: RM (с терминологией относительной математики)\n"
            "Используй: несовместимые задачи, склейка, нарушение строгости, "
            "третий тип знания, относительная строгость.\n"
            "Избегай: мета-уровни, мета-наблюдатели."
        )
    else:
        mode_block = (
            "РЕЖИМ: CLASSICAL (без терминологии RM)\n"
            "Используй: скрытый переход, незаконный перенос, мост, слой вероятностей, слой фактов.\n"
            "Избегай: третий тип знания, относительная строгость, склейка."
        )

    # --- Метки задач ---
    tags = p.get("tags", {})
    task_tags = tags.get("tasks", {})
    disc_tags = tags.get("disciplines", {})
    tasks_text = "\n".join(f"  {k}: {v}" for k, v in task_tags.items())
    disc_text = "\n".join(f"  {k}: {v}" for k, v in disc_tags.items())

    # --- Триггеры (сокращённо) ---
    dicts = p.get("dictionaries", {})
    w_t = ", ".join(str(x) for x in dicts.get("W_triggers", [])[:10])
    p_t = ", ".join(str(x) for x in dicts.get("P_triggers", [])[:10])
    f_t = ", ".join(str(x) for x in dicts.get("F_triggers", [])[:10])
    b_t = ", ".join(str(x) for x in dicts.get("Bridge_triggers", [])[:10])
    s_t = ", ".join(str(x) for x in dicts.get("Strong_inference_triggers", [])[:8])

    # --- Правила переключений ---
    rules = p.get("switch_detection", {}).get("rules", [])
    rules_text = ""
    for rule in rules:
        rid = rule.get("id", "")
        title_key = "title_rm" if mode == "rm" else "title_classic"
        title = rule.get(title_key, rule.get("title_classic", rid))
        explain_key = "explain_rm" if mode == "rm" else "explain_classic"
        explain = rule.get(explain_key, rule.get("explain_classic", "")).strip()
        sev = rule.get("severity", {}).get("base", "?")
        sev_add = rule.get("severity", {}).get("if_has_tag_S_add", 0)
        fix = rule.get("minimal_fix", {})
        fix_w = fix.get("weaken", "")
        fix_b = fix.get("add_bridge", "")
        rules_text += (
            f"\n  [{rid}] severity={sev}+{sev_add} при маркере S\n"
            f"  Заголовок: {title}\n"
            f"  Объяснение: {explain}\n"
            f"  Ослабление: {fix_w}\n"
            f"  Мост: {fix_b}\n"
        )

    # --- Структура отчёта ---
    sections = p.get("output", {}).get("report_structure", {}).get("sections_order", [])
    sections_text = "\n".join(f"  {s}" for s in sections)

    # --- Команды ---
    commands_block = (
        "  explain S{n}    — развернуть конкретную склейку\n"
        "  context pX-bY  — показать блоки до/после\n"
        "  bridges S{n}   — какие мосты возможны\n"
        "  weaken S{n}    — как ослабить вывод\n"
        "  strengthen S{n}— что добавить чтобы вывод стал законным"
    )

    prompt = f"""You are a scientific article analyzer. You detect hidden logical switches between incompatible mathematical tasks (WAVE/PROB/FACT) in quantum and quantum-like reasoning.

{lang_block}

{mode_block}

═══════════════════════════════════════
МЕТКИ ЗАДАЧ:
{tasks_text}

МЕТКИ ДИСЦИПЛИН (анализируй каждый блок по всем четырём):
{disc_text}

═══════════════════════════════════════
ТРИГГЕРНЫЕ СЛОВА (подсказки — решение принимай по смыслу, не только по словам):
  W: {w_t}
  P: {p_t}
  F: {f_t}
  BRIDGE: {b_t}
  STRONG: {s_t}

═══════════════════════════════════════
ПРАВИЛА ПЕРЕКЛЮЧЕНИЙ:
{rules_text}

═══════════════════════════════════════
СТРУКТУРА ОТЧЁТА (строго в этом порядке):
{sections_text}

Для каждого найденного переключения обязательно укажи:
  • Номер (S1, S2, ...)
  • Локация: страница + block_id (p{{page}}-b{{n}}) + якорь (первые слова)
  • Точная цитата из текста (1–2 предложения)
  • Какие задачи склеены (W→F или P→F)
  • Дисциплины в блоке (M/T/X/A словами)
  • Есть ли мост: нет/да (какой)
  • Что переносится через границу (1 строка)
  • Почему это переключение (1–2 предложения)
  • Минимальная правка: мост или ослабление

В конце отчёта всегда добавляй раздел «Команды для уточнений»:
{commands_block}

═══════════════════════════════════════
ВАЖНО:
  - Никогда не выводи markdown-таблицы.
  - Никогда не выводи сырые теги W/P/F — только полные слова с объяснением.
  - Не называй «логическим противоречием» если текст не выводит A и не-A в одной задаче.
  - Не помечай переключения внутри блоков с чистыми определениями/постулатами.
  - Точность важнее полноты. Не выдумывай переключения.
  - ВСЕГДА выполняй анализ независимо от длины текста.
"""
    return prompt
