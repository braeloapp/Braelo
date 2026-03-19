"""
Load static/test data and client DOCX knowledge base into MongoDB (BraeloDB).
Run: python manage.py load_mongo_data [--translate] [--dry-run]
Uses config.settings (BASE_DIR, DOCX_DATA_DIR, MONGO_DB_URI, MONGO_DB_NAME, OPENAI_API_KEY).
"""
from datetime import datetime
from pathlib import Path
from django.conf import settings
from django.core.management.base import BaseCommand

from chatbot.management.commands.load_docx import (
    QUESTIONS_FILE,
    RESPOSTAS_PREFIX,
    get_paragraphs,
    get_questions,
    parse_qa_pairs,
    parse_qa_q_first,
    parse_question_answer_multiparagraph,
    parse_question_answer_paragraphs,
    translate_to_english,
)

RESPOSTAS_STATES = [
    "Arizona", "NY", "Texas", "Florida", "Colorado", "Illinois", "California", "Pennsylvania",
]
PALAVRAS_CHAVES_FILE = "Palavras chaves.docx"

TEST_USER_ID = "test-user"
TEST_STATE = "Arizona"
TEST_COUNTY = "Maricopa"
TEST_ZIP = "85001"
TEST_CITY = "Phoenix"
USER_LAT = 33.4484
USER_LON = -112.0740

SEED_BUSINESSES = [
    {"name": "Desert Legal Group", "category": "legal", "subcategory": "lawyer", "state": TEST_STATE, "city": TEST_CITY, "county": TEST_COUNTY, "zip_code": "85001", "latitude": 33.4490, "longitude": -112.0730, "languages": "en,es", "contact_info": "602-555-0100", "whatsapp_url": "https://wa.me/16025550100", "ad_package_name": "Premium", "impression_cap": 500, "impressions_used": 0, "rotation_index": 0, "is_active": True, "is_banned": False},
    {"name": "Sun Valley Tax Services", "category": "tax", "subcategory": "tax_preparer", "state": TEST_STATE, "city": TEST_CITY, "county": TEST_COUNTY, "zip_code": "85002", "latitude": 33.4550, "longitude": -112.0680, "languages": "en,es,pt", "contact_info": "602-555-0200", "whatsapp_url": "https://wa.me/16025550200", "ad_package_name": None, "impression_cap": 1000, "impressions_used": 0, "rotation_index": 0, "is_active": True, "is_banned": False},
    {"name": "Phoenix Immigration Help", "category": "immigration", "subcategory": "consultant", "state": TEST_STATE, "city": "Phoenix", "county": TEST_COUNTY, "zip_code": "85003", "latitude": 33.4460, "longitude": -112.0760, "languages": "en,es", "contact_info": "602-555-0300", "whatsapp_url": "", "ad_package_name": None, "impression_cap": 1000, "impressions_used": 0, "rotation_index": 0, "is_active": True, "is_banned": False},
    {"name": "Maricopa Real Estate", "category": "housing", "subcategory": "real_estate_agent", "state": TEST_STATE, "city": TEST_CITY, "county": TEST_COUNTY, "zip_code": "85004", "latitude": 33.4520, "longitude": -112.0700, "languages": "en,es,pt", "contact_info": "602-555-0400", "whatsapp_url": "https://wa.me/16025550400", "ad_package_name": None, "impression_cap": 1000, "impressions_used": 0, "rotation_index": 0, "is_active": True, "is_banned": False},
]


def seed_static_data(db, dry_run: bool):
    now = datetime.utcnow()
    if dry_run:
        return
    users = db.users
    ad_packages = db.ad_packages
    businesses = db.businesses
    ad_packages.delete_many({})
    ad_packages.insert_one({"name": "Premium", "priority": 10, "max_impressions": 500, "created_at": now})
    users.delete_many({"external_id": TEST_USER_ID})
    users.insert_one({
        "external_id": TEST_USER_ID, "language_preference": "en", "state": TEST_STATE, "city": TEST_CITY,
        "county": TEST_COUNTY, "zip_code": TEST_ZIP, "location_enabled": True, "latitude": USER_LAT, "longitude": USER_LON,
        "created_at": now, "updated_at": now, "is_banned": False,
    })
    businesses.delete_many({})
    for b in SEED_BUSINESSES:
        doc = {**b, "created_at": now}
        doc.pop("ad_package_name", None)
        if b.get("ad_package_name"):
            doc["ad_package_name"] = b["ad_package_name"]
        businesses.insert_one(doc)


def _parse_qa_for_doc(paras: list, questions: list, filename: str):
    if not paras:
        return []
    pairs = parse_qa_q_first(paras)
    if pairs:
        return pairs
    if questions and len(paras) == len(questions):
        return list(zip(questions, paras))
    pairs = parse_qa_pairs(paras)
    if pairs:
        return pairs
    pairs = parse_question_answer_multiparagraph(paras)
    if pairs:
        return pairs
    pairs = parse_question_answer_paragraphs(paras)
    if pairs:
        return pairs
    return [(p, p) for p in paras]


def load_docx_into_mongo(db, translate: bool, dry_run: bool, command_stdout):
    from chatbot.services.knowledge_service import get_embedding

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
            if (d / QUESTIONS_FILE).exists() or (d / PALAVRAS_CHAVES_FILE).exists() or list(d.glob("Respostas *.docx")):
                data_dir = d
                break
    if data_dir is None:
        data_dir = docx_dir if (docx_dir and docx_dir.is_dir()) else (_parent / "documents" if (_parent / "documents").is_dir() else _backend_dir)
    command_stdout.write(f"Using data dir: {data_dir}")

    questions = []
    if (data_dir / QUESTIONS_FILE).exists():
        questions = get_questions(data_dir / QUESTIONS_FILE)
        command_stdout.write(f"Loaded {len(questions)} questions from {QUESTIONS_FILE}")

    doc_sources = []
    if (data_dir / PALAVRAS_CHAVES_FILE).exists():
        doc_sources.append((data_dir / PALAVRAS_CHAVES_FILE, "keywords", PALAVRAS_CHAVES_FILE))
    for state in RESPOSTAS_STATES:
        path = data_dir / f"{RESPOSTAS_PREFIX}{state}.docx"
        if path.exists():
            doc_sources.append((path, state, f"Respostas {state}.docx"))

    if not doc_sources:
        command_stdout.write("No DOCX data found. Put your files in one of these (outside braelo is fine):")
        command_stdout.write("  - DOCX_DATA_DIR from .env (e.g. DOCX_DATA_DIR=D:\\path\\to\\your\\documents)")
        command_stdout.write("  - braelo_backend/documents/  or  braelo_backend/data/  or  braelo_backend/chatbot_documents/")
        command_stdout.write("  - braelo/chatbot/data/  or  braelo/data/")
        command_stdout.write("Expected files: Respostas Arizona.docx, Respostas Texas.docx, etc.")
        return 0

    entries = []
    for path, region, document_source in doc_sources:
        paras = get_paragraphs(path)
        if not paras:
            continue
        pairs = _parse_qa_for_doc(paras, questions if region != "keywords" else [], document_source)
        for q, a in pairs:
            if q and (a or q):
                entries.append((region, q, a or q, document_source))
        command_stdout.write(f"  {document_source}: {len(pairs)} Q&A (region={region})")

    if not entries:
        return 0
    if not getattr(settings, "OPENAI_API_KEY", None):
        command_stdout.write("OPENAI_API_KEY not set. Embeddings will be empty; semantic search may be limited.")

    kb = db.knowledge_base
    if not dry_run:
        kb.delete_many({})
    added = 0
    for state, question, answer, document_source in entries:
        if translate:
            answer = translate_to_english(answer)
            if added == 0:
                command_stdout.write("Translating answers to English...")
        if dry_run:
            added += 1
            if added <= 3:
                command_stdout.write(f"  [dry-run] region={state}, doc={document_source}, q={question[:50]}...")
            continue
        emb = get_embedding(question)
        doc = {
            "state": state if state != "keywords" else None,
            "region": state,
            "county": None,
            "question": question,
            "answer": answer,
            "embedding": emb if emb else None,
            "document_source": document_source,
            "created_at": datetime.utcnow(),
        }
        kb.insert_one(doc)
        added += 1
        if added % 10 == 0:
            command_stdout.write(f"  Added {added}/{len(entries)}...")
    return added


class Command(BaseCommand):
    help = "Load static/test data and client DOCX knowledge base into MongoDB (BraeloDB), region-wise."

    def add_arguments(self, parser):
        parser.add_argument("--translate", action="store_true", help="Translate Spanish/Portuguese answers to English")
        parser.add_argument("--dry-run", action="store_true", help="Preview only, do not write to MongoDB")

    def handle(self, *args, **options):
        dry_run = options.get("dry_run", False)
        translate = options.get("translate", False)
        if dry_run:
            self.stdout.write("DRY RUN: no changes will be saved.")

        try:
            from chatbot.mongo_db import get_db, ensure_indexes
        except Exception as e:
            self.stderr.write(self.style.ERROR(f"MongoDB connection failed: {e}"))
            self.stderr.write("Ensure MongoDB is running and MONGO_URI/MONGO_DB_NAME are set in braelo .env.")
            return

        db = get_db()
        ensure_indexes()
        self.stdout.write("Seeding static/test data (user, ad_package, businesses)...")
        seed_static_data(db, dry_run)
        if not dry_run:
            self.stdout.write(self.style.SUCCESS("  Inserted test user, Premium ad package, 4 businesses."))
        self.stdout.write("Loading DOCX knowledge base (region-wise)...")
        added = load_docx_into_mongo(db, translate, dry_run, self.stdout)
        if dry_run:
            self.stdout.write(self.style.WARNING(f"Dry run: would insert {added} knowledge_base docs."))
        else:
            self.stdout.write(self.style.SUCCESS(f"Done. Inserted {added} knowledge_base docs (region-wise)."))
        self.stdout.write("Use USE_MONGO=true so the app reads from MongoDB.")
