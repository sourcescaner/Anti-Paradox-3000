import yaml
import os

POLICY_PATH = os.path.join(os.path.dirname(__file__), "..", "Files", "rm_bot_policy_v3.4.yml")


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
            "Используй: несовместимые задачи, разрыв, нарушение строгости, третий тип знания "
            "(как факт появления результата/метки), относительная строгость.\n"
            "Избегай: мета-уровни, мета-наблюдатели, каналы как концепция анализа.\n"
            "Добавляй поле rm_note к каждому найденному переключению."
        )
    else:
        mode_block = (
            "РЕЖИМ: CLASSICAL (без терминологии RM)\n"
            "Используй: task switch, bridge, illegitimate transfer, outcome-fact, "
            "probability layer, wave-description.\n"
            "Избегай: third type of knowledge, index of authorship, relative rigor.\n"
            "Поле rm_note НЕ добавляй."
        )

    # --- Основные концепции ---
    tasks = p.get("core_concepts", {}).get("tasks", {})
    tasks_text = ""
    for tid, tdef in tasks.items():
        markers = ", ".join(tdef.get("typical_markers", [])[:5])
        tasks_text += f"  {tid}: {tdef.get('meaning', '')}\n    Маркеры: {markers}\n"

    disciplines = p.get("core_concepts", {}).get("disciplines", {})
    disc_text = "\n".join(f"  {did}: {ddef}" for did, ddef in disciplines.items())

    bridges = p.get("core_concepts", {}).get("bridges", {}).get("types", {})
    bridge_text = ""
    for bid, bdef in bridges.items():
        bridge_text += f"  {bid}: {bdef.get('meaning', '')}\n"
    bridge_rule = p.get("core_concepts", {}).get("bridges", {}).get("rule", [""])[0]

    # --- Процедура ---
    procedure = p.get("procedure", [])
    proc_text = ""
    for step in procedure:
        proc_text += f"\n{step.get('step', '')}\n"
        for detail in step.get("details", []):
            proc_text += f"  • {detail}\n"

    # --- Формат вывода ---
    fmt = p.get("output_format", {})
    sections = fmt.get("required_sections", [])
    sections_text = "\n".join(f"  {s}" for s in sections)

    tmpl = fmt.get("switch_item_template", {}).get("fields", [])
    tmpl_text = ""
    for field in tmpl:
        if isinstance(field, dict):
            for k, v in field.items():
                tmpl_text += f"  {k}: {v}\n"

    # --- Ворота качества ---
    gates = p.get("quality_gates", [])
    gates_text = "\n".join(f"  - {g}" for g in gates)

    prompt = f"""You are a scientific article analyzer specializing in detecting hidden logical switches between incompatible mathematical tasks in quantum and quantum-like reasoning.

{lang_block}

{mode_block}

═══════════════════════════════════════
ТРИ ЗАДАЧИ (не смешивай без явного моста):
{tasks_text}
═══════════════════════════════════════
ЧЕТЫРЕ ДИСЦИПЛИНЫ (анализируй каждый блок по всем четырём):
{disc_text}

═══════════════════════════════════════
ТИПЫ МОСТОВ (только явное присутствие в тексте считается мостом):
{bridge_text}
Правило: {bridge_rule}

═══════════════════════════════════════
ПРОЦЕДУРА АНАЛИЗА:
{proc_text}
═══════════════════════════════════════
ОБЯЗАТЕЛЬНЫЕ РАЗДЕЛЫ ОТЧЁТА (строго в этом порядке):
{sections_text}

ШАБЛОН КАЖДОГО ПЕРЕКЛЮЧЕНИЯ:
{tmpl_text}
═══════════════════════════════════════
ТРЕБОВАНИЯ К КАЧЕСТВУ:
{gates_text}

Точность важнее полноты. Не выдумывай ошибки. Сообщай только то, что подтверждается структурой рассуждения в тексте.
"""
    return prompt
