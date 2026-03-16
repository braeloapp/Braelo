"""
Load client DOCX files into knowledge_base with embeddings (Django ORM).
Run: python manage.py load_docx [--translate] [--dry-run]
Uses config.settings (BASE_DIR, DOCX_DATA_DIR, OPENAI_API_KEY).
"""
import re
import json
from pathlib import Path
from django.core.management.base import BaseCommand
from django.conf import settings
from docx import Document

RESPOSTAS_PREFIX = "Respostas "
QUESTIONS_FILE = "Lista de Perguntas - IA.docx"


def get_paragraphs(doc_path: Path) -> list:
    doc = Document(doc_path)
    return [p.text.strip() for p in doc.paragraphs if p.text.strip()]


def get_questions(doc_path: Path) -> list:
    doc = Document(doc_path)
    questions = []
    for p in doc.paragraphs:
        t = p.text.strip()
        if t:
            questions.append(t)
    for table in doc.tables:
        for row in table.rows:
            for cell in row.cells:
                t = cell.text.strip()
                if t and t not in questions:
                    questions.append(t)
    return questions


def parse_qa_pairs(paragraphs: list) -> list:
    pairs = []
    i = 0
    while i < len(paragraphs):
        line = paragraphs[i]
        q_match = re.match(r"^(?:P|Pergunta|Q|Question)\s*[:\d.]*\s*(.+)", line, re.I) or re.match(r"^(.+)\?$", line)
        if q_match and i + 1 < len(paragraphs):
            pairs.append((q_match.group(1).strip(), paragraphs[i + 1].strip()))
            i += 2
            continue
        i += 1
    return pairs


def parse_question_answer_paragraphs(paragraphs: list) -> list:
    pairs = []
    i = 0
    while i < len(paragraphs):
        q = paragraphs[i].strip()
        if not q:
            i += 1
            continue
        if q.rstrip().endswith("?") and i + 1 < len(paragraphs):
            a = paragraphs[i + 1].strip()
            if a:
                pairs.append((q, a))
                i += 2
                continue
        pairs.append((q, q))
        i += 1
    return pairs


def _is_question_line(text: str) -> bool:
    t = text.strip()
    if not t:
        return False
    if t.rstrip().endswith("?"):
        return True
    if re.match(r"^\d+\.\s+", t):
        return True
    return False


def _starts_with_q(text: str) -> bool:
    t = text.strip()
    if not t:
        return False
    return t[0].upper() == "Q" and (len(t) == 1 or t[1] in (":", " ", "."))


def parse_qa_q_first(paragraphs: list) -> list:
    pairs = []
    last_question = None
    answer_lines = []
    for line in paragraphs:
        line = line.strip()
        if not line:
            continue
        if _starts_with_q(line):
            q_text = re.sub(r"^Q\s*[:\s.]*\s*", "", line, flags=re.I).strip() or line
            if last_question is not None:
                answer_text = "\n".join(answer_lines).strip()
                pairs.append((last_question, answer_text))
            last_question = q_text
            answer_lines = []
        else:
            answer_lines.append(line)
    if last_question is not None:
        pairs.append((last_question, "\n".join(answer_lines).strip()))
    return pairs


def parse_question_answer_multiparagraph(paragraphs: list) -> list:
    pairs = []
    i = 0
    while i < len(paragraphs):
        line = paragraphs[i].strip()
        if not line:
            i += 1
            continue
        if not _is_question_line(line):
            i += 1
            continue
        q = line
        answer_lines = []
        j = i + 1
        while j < len(paragraphs):
            next_line = paragraphs[j].strip()
            if not next_line:
                j += 1
                continue
            if _is_question_line(next_line):
                break
            answer_lines.append(next_line)
            j += 1
        full_answer = "\n".join(answer_lines).strip() if answer_lines else q
        pairs.append((q, full_answer))
        i = j if answer_lines else i + 1
    return pairs


def translate_to_english(text: str) -> str:
    if not text or not text.strip():
        return text or ""
    if not getattr(settings, "OPENAI_API_KEY", None):
        return text
    try:
        from openai import OpenAI
        client = OpenAI(api_key=settings.OPENAI_API_KEY)
        r = client.chat.completions.create(
            model=getattr(settings, "GPT_MODEL", "gpt-4o-mini"),
            messages=[
                {"role": "system", "content": "Translate the following text to English. Preserve meaning and structure. Output only the translation, no bullets or numbering unless in the original."},
                {"role": "user", "content": text[:6000]},
            ],
            temperature=0.2,
        )
        out = (r.choices[0].message.content or "").strip()
        return out if out else text
    except Exception:
        return text


class Command(BaseCommand):
    help = "Load client DOCX files into knowledge_base with embeddings (state/county, document_source). Optionally translate answers to English."

    def add_arguments(self, parser):
        parser.add_argument("--translate", action="store_true", help="Translate Spanish/Portuguese answers to English before storing")
        parser.add_argument("--dry-run", action="store_true", help="Show what would be loaded without saving")

    def handle(self, *args, **options):
        from chatbot.models import KnowledgeBase
        from chatbot.services.knowledge_service import get_embedding

        translate = options.get("translate", False)
        dry_run = options.get("dry_run", False)
        if dry_run:
            self.stdout.write("DRY RUN: no changes will be saved.")

        _backend_dir = Path(settings.BASE_DIR)
        _parent = _backend_dir.parent
        docx_dir = getattr(settings, "DOCX_DATA_DIR", None)
        if docx_dir is not None:
            docx_dir = Path(docx_dir) if not isinstance(docx_dir, Path) else docx_dir
        candidates = [
            docx_dir,
            _parent / "documents",
            _parent / "data",
            _parent / "chatbot_documents",
            _parent,
            _backend_dir / "chatbot" / "data",
            _backend_dir / "data",
            _backend_dir / "documents",
            _backend_dir,
        ]
        data_dir = None
        for d in candidates:
            if d is None:
                continue
            if isinstance(d, str):
                d = Path(d)
            if d.is_dir():
                if (d / QUESTIONS_FILE).exists() or list(d.glob("Respostas *.docx")):
                    data_dir = d
                    break
        if data_dir is None:
            data_dir = docx_dir if (docx_dir and docx_dir.is_dir()) else (_parent / "documents" if (_parent / "documents").is_dir() else _backend_dir)
        self.stdout.write(f"Using data dir: {data_dir}")

        questions_file = data_dir / QUESTIONS_FILE
        questions = []
        if questions_file.exists():
            questions = get_questions(questions_file)
            self.stdout.write(f"Loaded {len(questions)} questions from {QUESTIONS_FILE}")
        else:
            self.stdout.write(f"Questions file not found: {questions_file}")

        state_answers = {}
        for path in sorted(data_dir.glob("*.docx")):
            name = path.stem
            if name.startswith(RESPOSTAS_PREFIX):
                state = name[len(RESPOSTAS_PREFIX):].strip()
                paras = get_paragraphs(path)
                if not paras:
                    continue
                if questions and len(paras) == len(questions):
                    state_answers[state] = list(zip(questions, paras))
                else:
                    pairs = parse_qa_pairs(paras)
                    if pairs:
                        state_answers[state] = pairs
                    else:
                        pairs = parse_question_answer_multiparagraph(paras)
                        if pairs:
                            state_answers[state] = pairs
                        else:
                            pairs = parse_question_answer_paragraphs(paras)
                            if pairs:
                                state_answers[state] = pairs
                            else:
                                state_answers[state] = [(p, p) for p in paras]
                self.stdout.write(f"  {state}: {len(state_answers[state])} entries")

        if not state_answers and not questions:
            self.stdout.write("No DOCX data found. Set DOCX_DATA_DIR in .env to your folder (can be outside braelo), or use: braelo_backend/documents/, braelo/chatbot/data/, etc.")
            self.stdout.write("Expected: Lista de Perguntas - IA.docx, Respostas Arizona.docx, Respostas Texas.docx, etc.")
            return

        entries = []
        for state, qa_list in state_answers.items():
            for q, a in qa_list:
                if q and a:
                    entries.append((state, q, a))
        for q in questions:
            if q and not any(e[1] == q for e in entries):
                entries.append((None, q, "See state-specific answers or ask for your state."))

        if not getattr(settings, "OPENAI_API_KEY", None):
            self.stdout.write("OPENAI_API_KEY not set. Embeddings will be empty; semantic search will not work until you add key and re-run.")

        if not dry_run:
            existing = KnowledgeBase.objects.count()
            if existing > 0:
                KnowledgeBase.objects.all().delete()
                self.stdout.write(f"Cleared {existing} existing knowledge_base rows.")

        added = 0
        for state, question, answer in entries:
            if translate:
                answer = translate_to_english(answer)
                if added == 0:
                    self.stdout.write("Translating answers to English...")
            if dry_run:
                added += 1
                if added <= 3:
                    self.stdout.write(f"  [dry-run] state={state}, q={question[:50]}...")
                continue
            emb = get_embedding(question)
            emb_json = json.dumps(emb) if emb else None
            KnowledgeBase.objects.create(
                state=state,
                county=None,
                question=question,
                answer=answer,
                embedding_json=emb_json,
                document_source=state and f"Respostas {state}.docx" or "Lista de Perguntas - IA.docx",
            )
            added += 1
            if added % 10 == 0:
                self.stdout.write(f"  Added {added}/{len(entries)}...")

        if dry_run:
            self.stdout.write(self.style.WARNING(f"Dry run: would insert {added} rows."))
        else:
            self.stdout.write(self.style.SUCCESS(f"Done. Inserted {added} rows into knowledge_base."))
