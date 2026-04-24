import yaml
import os

POLICY_PATH = os.path.join(os.path.dirname(__file__), "..", "Files", "rm_bot_policy_v4.0.yml")
POLICY_VERSION = "v4.0"


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
    elif lang == "uk":
        lang_block = (
            "МОВА: Вся відповідь ТІЛЬКИ українською мовою. Це жорстка вимога.\n"
            "Цитати зі статті залишай мовою оригіналу (в лапках).\n"
            "Всі заголовки, пояснення, картки — строго українською.\n"
            "НЕ використовуй іноземні слова окрім як всередині цитат зі статті."
        )
    else:
        lang_block = (
            "LANGUAGE: Respond ONLY in English. All headings, explanations and switch items must be in English.\n"
            "Keep quotes in the original language of the source (in quotation marks)."
        )

    # --- Режим ---
    modes = p.get("modes", {})
    mode_cfg = modes.get(mode, modes.get("classical", {}))
    vocab_use = ", ".join(mode_cfg.get("vocabulary", {}).get("use", []))
    vocab_avoid = ", ".join(mode_cfg.get("vocabulary", {}).get("avoid", []))

    if mode == "rm":
        mode_block = (
            f"РЕЖИМ: RM (с терминологией относительной математики)\n"
            f"Используй: {vocab_use}\n"
            f"Избегай: {vocab_avoid}\n"
            f"Добавляй поле «RM-заметка» к каждому найденному переключению."
        )
    else:
        mode_block = (
            f"РЕЖИМ: CLASSICAL (без терминологии RM)\n"
            f"Используй: {vocab_use}\n"
            f"Избегай: {vocab_avoid}\n"
            f"Поле «RM-заметка» НЕ добавляй."
        )

    # --- Задачи ---
    tasks = p.get("core_concepts", {}).get("tasks", {})
    tasks_text = ""
    for tid, tdef in tasks.items():
        markers = ", ".join(tdef.get("markers_hint", [])[:6])
        tasks_text += f"  {tid}: {tdef.get('meaning', '')}\n    Маркеры: {markers}\n"

    # --- Дисциплины ---
    disciplines = p.get("core_concepts", {}).get("disciplines", {})
    disc_text = "\n".join(f"  {did}: {ddef}" for did, ddef in disciplines.items())

    # --- Мосты ---
    bridges = p.get("core_concepts", {}).get("bridges", {}).get("types", {})
    bridge_text = ""
    for bid, bdef in bridges.items():
        bridge_text += f"  {bid}: {bdef.get('meaning', '')}\n"
    bridge_rule = p.get("core_concepts", {}).get("bridges", {}).get("rule", [""])[0]

    # --- Роли блоков ---
    roles = p.get("classification", {}).get("role_rules", {})
    roles_text = ""
    for role, rdef in roles.items():
        hints = " / ".join(rdef.get("heuristic", []))
        roles_text += f"  {role}: {hints}\n"

    fact_guardrail = p.get("classification", {}).get("task_rules", {}).get("FACT_guardrail", {})
    fact_must = " | ".join(fact_guardrail.get("must_have_at_least_one", []))
    fact_otherwise = " | ".join(fact_guardrail.get("otherwise_prefer", []))

    # --- Правила переключений ---
    switch_rules = p.get("switch_detection", {}).get("rules", [])
    switches_text = ""
    for rule in switch_rules:
        rid = rule.get("id", "")
        sev_base = rule.get("severity", {}).get("base", "?")
        sev_add = rule.get("severity", {}).get("add_if_strong_inference_language", 0)
        explain_key = "explain_rm" if mode == "rm" else "explain_classical"
        explain = rule.get(explain_key, rule.get("explain_classical", "")).strip()
        fix_bridge = rule.get("minimal_fix_templates", {}).get("bridge", "")
        fix_weaken = rule.get("minimal_fix_templates", {}).get("weaken", "")
        switches_text += (
            f"\n  [{rid}] severity={sev_base}+{sev_add} при сильном языке вывода\n"
            f"  Объяснение: {explain}\n"
            f"  Мост: {fix_bridge}\n"
            f"  Ослабление: {fix_weaken}\n"
        )

    # --- Формат отчёта ---
    reporting = p.get("reporting", {})
    sections = reporting.get("required_sections_order", [])
    sections_text = "\n".join(f"  {s}" for s in sections)

    task_map_fmt = reporting.get("task_map_constraints", {})
    task_map_max = task_map_fmt.get("max_lines", 12)

    switch_fields = reporting.get("switch_item_format", {}).get("must_include_fields", [])
    switch_fields_text = "\n".join(f"  • {f}" for f in switch_fields)

    no_switches_msg = reporting.get("if_no_switches_found", {}).get("output", "")

    # --- Команды ---
    commands = p.get("interaction", {}).get("commands_supported", [])
    commands_text = ""
    for cmd in commands:
        commands_text += f"  {cmd.get('syntax','')}: {cmd.get('meaning','')}\n"

    # --- Ворота качества ---
    gates = p.get("quality_gates", [])
    gates_text = "\n".join(f"  - {g}" for g in gates)

    prompt = f"""You are a scientific article analyzer. You detect hidden logical switches between incompatible mathematical tasks (WAVE, PROB, FACT) in quantum and quantum-like reasoning.

{lang_block}

{mode_block}

═══════════════════════════════════════
ТРИ ЗАДАЧИ (не смешивай без явного моста):
{tasks_text}
ВАЖНО — метка FACT:
  Ставь ТОЛЬКО если есть хотя бы одно из: {fact_must}
  Иначе предпочитай: {fact_otherwise}

═══════════════════════════════════════
ЧЕТЫРЕ ДИСЦИПЛИНЫ (анализируй каждый блок по всем четырём):
{disc_text}

═══════════════════════════════════════
ТИПЫ МОСТОВ (только явное присутствие в тексте считается мостом):
{bridge_text}
Правило: {bridge_rule}

═══════════════════════════════════════
РОЛИ БЛОКОВ (определяй роль каждого блока перед анализом переключений):
{roles_text}
ВАЖНО: Не помечай переключения внутри блоков с ролью DEFINITION.
Только блоки с ролью INFERENCE могут быть источником переключений.

═══════════════════════════════════════
ПРАВИЛА ПЕРЕКЛЮЧЕНИЙ:
{switches_text}

═══════════════════════════════════════
ОБЯЗАТЕЛЬНЫЕ РАЗДЕЛЫ ОТЧЁТА (строго в этом порядке):
{sections_text}

КАРТА ЗАДАЧ: максимум {task_map_max} строк, сжатый формат.

ФОРМАТ КАЖДОГО ПЕРЕКЛЮЧЕНИЯ (все поля обязательны):
{switch_fields_text}

ЕСЛИ ПЕРЕКЛЮЧЕНИЙ НЕ НАЙДЕНО:
{no_switches_msg}

═══════════════════════════════════════
КОМАНДЫ ДЛЯ УТОЧНЕНИЙ (раздел E — всегда включай в конец отчёта):
{commands_text}
═══════════════════════════════════════
ТРЕБОВАНИЯ К КАЧЕСТВУ:
{gates_text}

ВАЖНО: Всегда выполняй анализ. Никогда не отказывайся от анализа из-за размера текста или темы.
Точность важнее полноты. Не выдумывай переключения.
"""
    return prompt
