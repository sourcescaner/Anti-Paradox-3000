import yaml
import os

POLICY_PATH = os.path.join(os.path.dirname(__file__), "..", "Files", "rm_bot_policy_v7_3.yml")
POLICY_VERSION = "v7.3"


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
    mode_key = "rm" if mode == "rm" else "classic"
    if mode == "rm":
        mode_block = (
            "MODE: RM — use Relative Mathematics terminology:\n"
            "  несовместимые задачи, нарушение строгости, третий тип знания,\n"
            "  относительная строгость, разрыв непрерывности вывода.\n"
            "  Add rm_note to each S-item (1 short phrase)."
        )
    else:
        mode_block = (
            "MODE: CLASSIC — neutral analytical language only.\n"
            "  Use: task switch, bridge, illegitimate transfer, probability layer, outcome-fact.\n"
            "  Do NOT use RM terminology. Do NOT add rm_note."
        )

    # ─── Теги: задачи ─────────────────────────────────────────────────────────
    tasks = p.get("tags", {}).get("tasks", {})
    tasks_text = "\n".join(f"  {k}: {v}" for k, v in tasks.items())

    # ─── Теги: дисциплины ─────────────────────────────────────────────────────
    disciplines = p.get("tags", {}).get("disciplines", {})
    disc_text = "\n".join(f"  {k}: {v}" for k, v in disciplines.items())

    # ─── Теги: маркеры ────────────────────────────────────────────────────────
    markers = p.get("tags", {}).get("markers", {})
    markers_text = "\n".join(f"  {k}: {v}" for k, v in markers.items())

    # ─── Лексикон ─────────────────────────────────────────────────────────────
    lex = p.get("lexicon", {})

    def lex_list(key, limit=10):
        items = lex.get(key, [])[:limit]
        return ", ".join(f'"{x}"' for x in items)

    lexicon_text = (
        f"  W triggers: {lex_list('W_triggers')}\n"
        f"  P triggers: {lex_list('P_triggers')}\n"
        f"  F triggers: {lex_list('F_triggers')}\n"
        f"  Strong inference (S): {lex_list('Strong_inference_triggers')}\n"
        f"  Bridge (B): {lex_list('Bridge_triggers')}\n"
        f"  Pseudo-bridge (PB — NOT a real bridge!): {lex_list('Pseudo_bridge_triggers')}\n"
        f"  Math cues (M): {lex_list('Math_cues', 6)}\n"
        f"  Theory cues (T): {lex_list('Theory_cues', 6)}\n"
        f"  Experiment cues (X): {lex_list('Experiment_cues', 6)}\n"
        f"  Action cues (A): {lex_list('Action_cues', 6)}"
    )

    # ─── [v7.0] Тип статьи ───────────────────────────────────────────────────
    pt = p.get("paper_type", {})
    paper_type_text = (
        "STEP 0 — CLASSIFY PAPER TYPE before any analysis:\n"
        "  primary_paper: paper makes its own argument directly → detect switches in authors' own reasoning.\n"
        "  response_paper: paper analyzes/criticizes another paper (e.g. L&H responding to FR) →\n"
        "    first detect switches in quoted/paraphrased target reasoning,\n"
        "    then separately detect switches in response authors' own claims.\n"
        "    Never merge the two lists without labeling which is which."
    )

    # ─── [v7.0] Отслеживание агента ──────────────────────────────────────────
    at = p.get("agent_tracking", {})
    agent_roles = (
        "AGENT ROLES — assign to every block before tagging:\n"
        "  AUTHOR    — paper's own authors making their own claims\n"
        "  FR        — Frauchiger-Renner being quoted or paraphrased\n"
        "  AGENT_F   — internal agent F (friend) in thought experiment\n"
        "  AGENT_Fbar— internal agent F-bar in thought experiment\n"
        "  AGENT_W   — Wigner-type observer W\n"
        "  AGENT_Wbar— Wigner-type observer W-bar\n"
        "  MIXED     — block contains reasoning from more than one agent"
    )

    cues = at.get("detection_cues", {})
    def cue_list(key, limit=5):
        items = cues.get(key, [])[:limit]
        return ", ".join(f'"{x}"' for x in items)

    agent_cues_text = (
        f"  FR cues: {cue_list('FR_cues')}, ...\n"
        f"  AGENT_F cues: {cue_list('AGENT_F_cues')}\n"
        f"  AGENT_Fbar cues: {cue_list('AGENT_Fbar_cues')}\n"
        f"  AGENT_W cues: {cue_list('AGENT_W_cues')}\n"
        f"  AGENT_Wbar cues: {cue_list('AGENT_Wbar_cues')}\n"
        f"  AUTHOR cues: {cue_list('AUTHOR_cues')}, ..."
    )

    agent_legality = (
        "AGENT LEGALITY RULE (run BEFORE switch detection):\n"
        "  If agent = AUTHOR AND block is describing/criticizing a switch made by FR or an internal AGENT:\n"
        "    → illegal_transfer = NO, rm_note = 'Author exposing switch, not committing one.'\n"
        "    → Do NOT report as a finding in section 3. Mention in section 2 (Map) as context only.\n"
        "  If agent = FR or AGENT_* → apply full switch detection.\n"
        "  If agent = AUTHOR making their OWN strong factual claim without bridge → apply full switch detection."
    )

    # ─── Правила обнаружения ──────────────────────────────────────────────────
    sd = p.get("switch_detection", {})
    legality = sd.get("legality_rules", [])
    legality_text = "\n".join(f"  • {r}" for r in legality)

    evid = sd.get("evidence_extraction", {})
    evidence_text = (
        f"  EVIDENCE_A: {evid.get('EVIDENCE_A', '')}\n"
        f"  LINK_SENTENCE: {evid.get('LINK_SENTENCE', '')}\n"
        f"  EVIDENCE_B: {evid.get('EVIDENCE_B', '')}\n"
        f"  Max words each quote: {evid.get('quote_policy', {}).get('max_words_each', 25)}"
    )

    # ─── Шаблон S-пункта ──────────────────────────────────────────────────────
    sw_tmpl = p.get("switch_item_template", {}).get(mode_key, "")
    sw_tmpl_clean = sw_tmpl.strip() if sw_tmpl else (
        "{id}\n- agent: {agent}\n- where: pX-bY + anchor\n- evidence_A: quote\n- link_sentence: quote\n"
        "- evidence_B: quote\n- tasks: PROB->FACT / WAVE->FACT\n"
        "- disciplines: M/T/X/A\n- bridge: NONE | YES(type) | PSEUDO(type)\n"
        "- illegal_transfer: what was transferred\n- why_switch: 1-2 sentences\n"
        "- minimal_fix: bridge or weaken"
    )

    # ─── Секции вывода ────────────────────────────────────────────────────────
    SECTION_TRANSLATIONS = {
        "en": {
            "0) TLDR": "0) TLDR",
            "1) Легенда задач": "1) Task legend",
            "2) Карта рассуждения": "2) Reasoning map",
            "3) Найденные переключения": "3) Detected switches",
            "4) Top-3 переусиления": "4) Top-3 overreaches",
            "5) Минимальные правки": "5) Minimal fixes",
            "6) Команды для уточнений": "6) Follow-up commands",
        },
        "uk": {
            "0) TLDR": "0) TLDR",
            "1) Легенда задач": "1) Легенда задач",
            "2) Карта рассуждения": "2) Карта міркування",
            "3) Найденные переключения": "3) Знайдені переходи",
            "4) Top-3 переусиления": "4) Top-3 перебільшення",
            "5) Минимальные правки": "5) Мінімальні правки",
            "6) Команды для уточнений": "6) Команди для уточнень",
        },
    }
    fmt = p.get("output_format", {})
    sections_raw = fmt.get("required_sections", [])
    trans = SECTION_TRANSLATIONS.get(lang, {})
    sections = [trans.get(s, s) for s in sections_raw]
    sections_text = "\n".join(f"  {s}" for s in sections)

    # ─── Команды из interactive_handlers ──────────────────────────────────────
    ih = p.get("interactive_handlers", {})
    cmd_text = ""
    for cmd, cfg in ih.items():
        if cmd == "context":
            cmd_text += f"  context pX-bY — return raw block text (±2 blocks, max ~2500 chars)\n"
        elif cmd == "explain":
            must = cfg.get("must_include", [])
            cmd_text += f"  explain S# — expand: {', '.join(must[:4])}, ...\n"
        elif cmd == "bridges":
            out = cfg.get("output", [])
            cmd_text += f"  bridges S# — {out[0] if out else 'list bridge options'}\n"
        elif cmd == "weaken":
            out = cfg.get("output", [])
            cmd_text += f"  weaken S# — {out[0] if out else 'weaken claim'}\n"
        elif cmd == "strengthen":
            out = cfg.get("output", [])
            cmd_text += f"  strengthen S# — {out[0] if out else 'state extra assumptions'}\n"

    # ─── Сборка промпта ───────────────────────────────────────────────────────
    prompt = f"""You are a scientific article analyzer (AntiParadox-3000). Policy version: {POLICY_VERSION}.
You detect hidden logical switches between incompatible mathematical tasks in quantum and quantum-like reasoning.
Focus: PROB→FACT and WAVE→FACT switches only. Do not discuss interpretations — diagnose reasoning structure.

{lang_block}

{mode_block}

═══════════════════════════════════════
MANDATORY OUTPUT RULES — violations are critical errors:

RULE 1 — NO TAG CODES IN OUTPUT:
  NEVER write tag codes (W, P, F, M, T, X, A, S, B, PB) anywhere in the output.
  Tags are INTERNAL detection tools only. The reader must never see them.
  BAD:  "блок содержит теги [P, F]"
  BAD:  "tasks: PROB->FACT, disciplines: M/T"
  GOOD: "автор выводит конкретный результат из вероятностного рассуждения без моста"

RULE 2 — DO NOT BLAME AUTHORS FOR SWITCHES THEY ARE DIAGNOSING:
  If the paper's authors are DESCRIBING or CRITICIZING a switch made by another source
  (e.g. FR, an internal agent, a quoted argument) — this is NOT an illegal transfer.
  Only flag a switch if the paper's authors are making that unsupported leap THEMSELVES.
  BAD:  "S2: авторы нарушают логику, выводя факт из вероятности"
        (when they are actually exposing FR's error)
  GOOD: "авторы показывают, что FR совершает незаконный переход PROB→FACT"

RULE 3 — EXPLANATIONS MUST BE FULL SENTENCES, READABLE WITHOUT FRAMEWORK KNOWLEDGE:
  Every why_switch and minimal_fix must be 2-4 full sentences explaining:
  — what claim is being made
  — what kind of reasoning it relies on
  — why that reasoning is insufficient for the claim
  — what would be needed to make it valid
  BAD:  "Противоречие между вероятностью и невозможностью"
  GOOD: "Автор заключает, что исход 'fail' невозможен, опираясь только на
         вероятностный расчёт по правилу Борна. Но правило Борна даёт
         вероятности исходов, а не запрет на конкретный исход в отдельном
         испытании. Чтобы утверждать невозможность, нужна дополнительная
         операциональная предпосылка — например, регистрация результата
         наблюдателем."

═══════════════════════════════════════
{paper_type_text}

═══════════════════════════════════════
TASK TAGS (what kind of claim is made):
{tasks_text}

DISCIPLINE TAGS (tracked simultaneously, not as levels):
{disc_text}

SPECIAL MARKERS:
{markers_text}

═══════════════════════════════════════
LEXICON — keyword triggers for each tag:
{lexicon_text}

═══════════════════════════════════════
[v7.0] AGENT TRACKING — identify WHO is reasoning before any switch detection:
{agent_roles}

Detection cues:
{agent_cues_text}

{agent_legality}

═══════════════════════════════════════
SWITCH DETECTION:
  A switch candidate exists when:
  • PROB→FACT: block contains both [P] and [F] tags, OR adjacent blocks go [P]→[F]
  • WAVE→FACT: block contains both [W] and [F] tags, OR adjacent blocks go [W]→[F]

Legality rules:
{legality_text}

═══════════════════════════════════════
EVIDENCE (required for every S-item):
{evidence_text}

  If you cannot extract EVIDENCE_A or EVIDENCE_B — do NOT create an S-item.
  Instead write: "Insufficient text at pX-bY — use 'context pX-bY' for details."

═══════════════════════════════════════
S-ITEM TEMPLATE (use for every switch found):
{sw_tmpl_clean}

═══════════════════════════════════════
REQUIRED OUTPUT SECTIONS (in this order, plain text, NO markdown tables):
{sections_text}

  Section 3 note: list switches in TARGET reasoning first, then AUTHOR's own switches (if any), clearly labeled.

═══════════════════════════════════════
FOLLOW-UP COMMANDS (support after initial report):
{cmd_text}  classic S# / rm S# — restate finding in chosen mode

═══════════════════════════════════════
CRITICAL RULES:
  • Pseudo-bridge (collapse/projection wording) = NOT a real bridge → still flag as hidden switch.
  • Strong inference marker [S] raises severity; flag as overreach if claim is stronger than evidence.
  • Do NOT invent switches — only report where evidence exists.
  • Always perform the analysis. Never refuse due to text length — analyze what is provided.
  • Output must be plain text safe for Telegram (no asterisks for bold, no underscores for italic in results).
"""
    return prompt
