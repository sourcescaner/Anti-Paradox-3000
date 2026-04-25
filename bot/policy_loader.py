import yaml
import os

POLICY_PATH = os.path.join(os.path.dirname(__file__), "..", "Files", "rm_bot_policy_v6.0.yml")
POLICY_VERSION = "v6.0"


def load_policy() -> dict:
    with open(POLICY_PATH, "r", encoding="utf-8") as f:
        data = yaml.safe_load(f)
    return data


def build_system_prompt(mode: str = "classical", lang: str = "en") -> str:
    p = load_policy()

    # ─── Язык ────────────────────────────────────────────────────────────────
    if lang == "ru":
        lang_block = (
            "ЯЗЫК: Весь ответ ТОЛЬКО на русском языке.\n"
            "Цитаты из статьи оставляй на языке оригинала (в кавычках).\n"
            "Все заголовки и объяснения — строго на русском."
        )
    elif lang == "uk":
        lang_block = (
            "МОВА: Вся відповідь ТІЛЬКИ українською мовою.\n"
            "Цитати зі статті залишай мовою оригіналу (в лапках).\n"
            "Всі заголовки та пояснення — строго українською."
        )
    else:
        lang_block = (
            "LANGUAGE: Respond ONLY in English.\n"
            "Keep quotes in the original language of the source (in quotation marks).\n"
            "All headings and explanations must be in English."
        )

    # ─── Режим ───────────────────────────────────────────────────────────────
    if mode == "rm":
        mode_block = (
            "MODE: RM — use Relative Mathematics terminology where applicable:\n"
            "  несовместимые задачи, нарушение строгости, третий тип знания (как факт появления результата),\n"
            "  относительная строгость, разрыв непрерывности вывода.\n"
            "  Add a short rm_note to each switch (1 phrase)."
        )
    else:
        mode_block = (
            "MODE: CLASSIC — neutral analytical language only.\n"
            "  Use: task switch, bridge, illegitimate transfer, probability layer, outcome-fact, wave-description.\n"
            "  Do NOT use RM terminology. Do NOT add rm_note fields."
        )

    # ─── Задачи (WAVE / PROB / FACT) ─────────────────────────────────────────
    tasks = p.get("core_model", {}).get("tasks", {})
    tasks_text = ""
    for tid, tdef in tasks.items():
        markers = ", ".join(tdef.get("markers", [])[:6])
        tasks_text += f"  {tid}: {tdef.get('meaning', '')}\n    Markers: {markers}\n"

    # ─── Дисциплины ───────────────────────────────────────────────────────────
    disciplines = p.get("core_model", {}).get("disciplines", {})
    disc_text = "\n".join(f"  {did}: {ddef}" for did, ddef in disciplines.items())

    # ─── Мосты ────────────────────────────────────────────────────────────────
    bridges = p.get("bridges", {})
    bridge_types = bridges.get("types", {})
    pseudo_markers = bridges.get("pseudo_bridge_markers", [])

    bridge_text = "  ACCEPTABLE BRIDGES:\n"
    for bid, bdef in bridge_types.items():
        markers = ", ".join(bdef.get("markers", [])[:4])
        bridge_text += f"    {bid}: {bdef.get('meaning', '')} | markers: {markers}\n"

    bridge_text += "\n  PSEUDO-BRIDGE WORDING (NOT a real bridge — flag as PSEUDO):\n"
    for pm in pseudo_markers:
        bridge_text += f"    • {pm}\n"

    # ─── Правила обнаружения ──────────────────────────────────────────────────
    det = p.get("detection_rules", {})
    inf_markers = ", ".join(det.get("inference_markers", []))
    fact_gate = "\n".join(f"  • {r}" for r in det.get("fact_gate_rule", []))
    switch_def = "\n".join(f"  • {s}" for s in det.get("switch_definition", []))

    # ─── Требование доказательств ─────────────────────────────────────────────
    evid = p.get("evidence_requirement_for_each_switch", {})
    must_include = "\n".join(f"  • {e}" for e in evid.get("must_include", []))
    if_missing = "\n".join(f"  • {e}" for e in evid.get("if_missing", []))

    # ─── Структура вывода ─────────────────────────────────────────────────────
    out = p.get("output", {})
    structure = out.get("structure", [])
    structure_text = "\n".join(f"  {s}" for s in structure)

    # ─── Шаблон S-пункта ──────────────────────────────────────────────────────
    sw_fields = p.get("switch_item_template", {}).get("fields", [])
    tmpl_text = "\n".join(f"  • {f}" for f in sw_fields)

    # ─── Команды ──────────────────────────────────────────────────────────────
    commands = p.get("commands", {})
    cmd_text = ""
    for cmd_name, cmd_def in commands.items():
        syntax = cmd_def.get("syntax", cmd_name)
        out_lines = cmd_def.get("output", "")
        if isinstance(out_lines, list):
            out_lines = out_lines[0]
        cmd_text += f"  {syntax} — {out_lines}\n"

    # ─── Сборка промпта ───────────────────────────────────────────────────────
    prompt = f"""You are a scientific article analyzer. You detect hidden logical switches between incompatible mathematical tasks (WAVE, PROB, FACT) in quantum and quantum-like reasoning. Policy version: {POLICY_VERSION}.

{lang_block}

{mode_block}

═══════════════════════════════════════
THREE TASKS:
{tasks_text}
═══════════════════════════════════════
FOUR DISCIPLINES:
{disc_text}

═══════════════════════════════════════
BRIDGES:
{bridge_text}

═══════════════════════════════════════
DETECTION RULES:
Inference markers (trigger search): {inf_markers}

FACT gate rule:
{fact_gate}

Switch definition:
{switch_def}

═══════════════════════════════════════
EVIDENCE REQUIREMENT (for every S-item):
{must_include}

If evidence is missing:
{if_missing}

═══════════════════════════════════════
OUTPUT STRUCTURE (required sections, in this order):
{structure_text}

SWITCH ITEM TEMPLATE (every S-item must include):
{tmpl_text}

═══════════════════════════════════════
FOLLOW-UP COMMANDS (support these after initial report):
{cmd_text}
═══════════════════════════════════════
IMPORTANT:
  • No markdown tables.
  • Each S-item must be 6–10 lines, not a wall of text.
  • Always perform the analysis. Never refuse due to text length.
  • Accuracy over completeness. Do NOT invent switches without evidence.
  • If you cannot quote a block (pX-bY), say so explicitly — do not hallucinate.
"""
    return prompt
