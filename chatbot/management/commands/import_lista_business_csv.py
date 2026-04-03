"""
Import "Lista de business" CSV into Django Business rows (Portuguese labels → normalized US state + search tags).
Run: python manage.py import_lista_business_csv
     python manage.py import_lista_business_csv --path "C:/path/to/file.csv" --replace
"""
import csv
import re
import unicodedata
from pathlib import Path

from django.conf import settings
from django.core.management.base import BaseCommand
from django.utils import timezone

from chatbot.models import Business

LISTA_MARKER = "[ListaBusiness1]"

_US_STATE_BY_FOLDED = {
    "ALABAMA": "Alabama",
    "ALASKA": "Alaska",
    "ARIZONA": "Arizona",
    "ARKANSAS": "Arkansas",
    "CALIFORNIA": "California",
    "COLORADO": "Colorado",
    "CONNECTICUT": "Connecticut",
    "DELAWARE": "Delaware",
    "FLORIDA": "Florida",
    "GEORGIA": "Georgia",
    "HAWAII": "Hawaii",
    "IDAHO": "Idaho",
    "ILLINOIS": "Illinois",
    "INDIANA": "Indiana",
    "IOWA": "Iowa",
    "KANSAS": "Kansas",
    "KENTUCKY": "Kentucky",
    "LOUISIANA": "Louisiana",
    "MAINE": "Maine",
    "MARYLAND": "Maryland",
    "MASSACHUSETTS": "Massachusetts",
    "MICHIGAN": "Michigan",
    "MINNESOTA": "Minnesota",
    "MISSISSIPPI": "Mississippi",
    "MISSOURI": "Missouri",
    "MONTANA": "Montana",
    "NEBRASKA": "Nebraska",
    "NEVADA": "Nevada",
    "NEW HAMPSHIRE": "New Hampshire",
    "NEW JERSEY": "New Jersey",
    "NEW MEXICO": "New Mexico",
    "NEW YORK": "New York",
    "NORTH CAROLINA": "North Carolina",
    "NORTH DAKOTA": "North Dakota",
    "OHIO": "Ohio",
    "OKLAHOMA": "Oklahoma",
    "OREGON": "Oregon",
    "PENNSYLVANIA": "Pennsylvania",
    "RHODE ISLAND": "Rhode Island",
    "SOUTH CAROLINA": "South Carolina",
    "SOUTH DAKOTA": "South Dakota",
    "TENNESSEE": "Tennessee",
    "TEXAS": "Texas",
    "UTAH": "Utah",
    "VERMONT": "Vermont",
    "VIRGINIA": "Virginia",
    "WASHINGTON": "Washington",
    "WEST VIRGINIA": "West Virginia",
    "WISCONSIN": "Wisconsin",
    "WYOMING": "Wyoming",
    "DISTRICT OF COLUMBIA": "District of Columbia",
    "WASHINGTON DC": "District of Columbia",
    "DC": "District of Columbia",
}

_PHRASE_ALIASES = {
    "CAROLINA DO NORTE": "North Carolina",
    "CAROLINA DEL NORTE": "North Carolina",
    "CAROLINA DO SUL": "South Carolina",
    "CAROLINA DEL SUR": "South Carolina",
    "NOVA YORK": "New York",
    "NEW JERSEY": "New Jersey",
    "GEORGIA": "Georgia",
    "DISTRITO DE COLUMBIA": "District of Columbia",
}

_CATEGORY_EN_HINTS = (
    ("gastronom", "restaurant food dining bar cafe bakery churrascaria grill"),
    ("comercio", "retail shop store boutique commerce"),
    ("comércio", "retail shop store boutique commerce"),
    ("servico", "services professional business"),
    ("serviço", "services professional business"),
    ("saude", "health medical clinic doctor dentist"),
    ("saúde", "health medical clinic doctor dentist"),
    ("financeiro", "finance tax accounting financial"),
    ("odontologia", "dental dentist dentistry"),
    ("beleza", "beauty salon spa hair nails aesthetic"),
    ("evento", "events party planning entertainment"),
    ("juridico", "legal lawyer law attorney immigration"),
    ("jurídico", "legal lawyer law attorney immigration"),
    ("transporte", "moving transport delivery"),
    ("construcao", "construction remodeling contractor"),
    ("construção", "construction remodeling contractor"),
    ("agencias de seguros", "insurance agency agent"),
    ("fotografia", "photography photographer"),
)


def _fold(s: str) -> str:
    if not s:
        return ""
    s = unicodedata.normalize("NFKD", s)
    s = "".join(c for c in s if not unicodedata.combining(c))
    return s.upper().strip()


def normalize_us_state(raw: str) -> str:
    if not raw or not str(raw).strip():
        return ""
    t = str(raw).strip()
    folded_phrase = _fold(t)
    if folded_phrase in _PHRASE_ALIASES:
        return _PHRASE_ALIASES[folded_phrase]
    for phrase, full in _PHRASE_ALIASES.items():
        if phrase in folded_phrase:
            return full
    if folded_phrase in _US_STATE_BY_FOLDED:
        return _US_STATE_BY_FOLDED[folded_phrase]
    parts = folded_phrase.split()
    if parts:
        w = parts[0]
        if w in _US_STATE_BY_FOLDED:
            return _US_STATE_BY_FOLDED[w]
    return t.title()[:64]


def _en_hints_for_category(cat: str, sub: str) -> str:
    blob = _fold(cat) + " " + _fold(sub)
    hints = []
    for needle, words in _CATEGORY_EN_HINTS:
        if _fold(needle) in blob.replace(" ", ""):
            hints.append(words)
        elif needle.lower() in (cat or "").lower() or needle.lower() in (sub or "").lower():
            hints.append(words)
    return " ".join(hints)


def _digits_phone(s: str) -> str:
    if not s:
        return ""
    d = re.sub(r"\D", "", s)
    if len(d) == 10:
        return d
    if len(d) == 11 and d.startswith("1"):
        return d[1:]
    return d


def _whatsapp_url(phone_digits: str) -> str:
    if len(phone_digits) == 10:
        return f"https://wa.me/1{phone_digits}"
    if len(phone_digits) >= 10:
        return f"https://wa.me/{phone_digits}"
    return ""


def _clean_cell(v) -> str:
    if v is None:
        return ""
    return str(v).replace("\x00", "").strip()


def _build_contact(social: str, phone: str, email: str, website: str) -> str:
    lines = [LISTA_MARKER, ""]
    if social:
        lines.append(f"Social: {social}")
    if phone and phone.lower() not in ("--", "não encontrado", "nao encontrado"):
        lines.append(f"Phone: {phone}")
    if email and email.strip() not in ("--", ""):
        lines.append(f"Email: {email}")
    if website:
        lines.append(f"Website: {website}")
    return "\n".join(lines).strip()


def _build_tags(cat: str, sub: str, tags_col: str) -> str:
    parts = []
    for chunk in (tags_col or "").replace("|", " ").split():
        if len(chunk) >= 2:
            parts.append(chunk.lower())
    if cat:
        parts.append(cat.lower())
    if sub:
        parts.append(sub.lower())
    hints = _en_hints_for_category(cat, sub)
    if hints:
        parts.extend(hints.split())
    return " ".join(dict.fromkeys(parts))


def iter_lista_business_dicts(path: Path, limit: int = 0):
    """
    Yield one dict per CSV row (normalized). Shared by SQL and Mongo import commands.
    Keys: name, category, subcategory, state, city, county, tags, contact_info, whatsapp_url
    """
    with open(path, newline="", encoding="utf-8-sig", errors="replace") as f:
        sample = f.read(4096)
        f.seek(0)
        try:
            dialect = csv.Sniffer().sniff(sample, delimiters=",;\t")
        except csv.Error:
            dialect = csv.excel
        reader = csv.reader(f, dialect)

        header_idx = None
        headers = None
        for i, row in enumerate(reader):
            if not row:
                continue
            if _clean_cell(row[0]).upper() == "NOME" or (
                len(row) > 8 and "ESTADO" in _clean_cell(row[7]).upper()
            ):
                header_idx = i
                headers = []
                used = set()
                for j, c in enumerate(row):
                    h = _clean_cell(c) or f"_col{j}"
                    while h in used:
                        h = f"{h}_{j}"
                    used.add(h)
                    headers.append(h)
                break
        else:
            return

        f.seek(0)
        for _ in range(header_idx + 1):
            next(f)
        dict_reader = csv.DictReader(f, fieldnames=headers)

        n = 0
        for row in dict_reader:
            nome = _clean_cell(row.get("NOME"))
            if not nome or nome.upper() == "NOME":
                continue
            estado = normalize_us_state(row.get("ESTADO") or "")
            county = _clean_cell(row.get("COUNTY"))[:128]
            cidade = _clean_cell(row.get("CIDADE"))[:128]
            categoria = _clean_cell(
                row.get("CATEGORIA")
                or row.get("CATEGORIA ")
                or next((row.get(k) for k in row if "CATEGORIA" in (k or "").upper()), "")
            )[:128]
            subcategoria = _clean_cell(row.get("SUBCATEGORIA") or "")[:128]
            tags_raw = _clean_cell(row.get("TAGS") or "")
            social = _clean_cell(row.get("SOCIAL MEDIA") or "")
            phone = _clean_cell(row.get("PHONE") or "")
            email = _clean_cell(row.get("EMAIL") or "")
            website = _clean_cell(row.get("WEBSITE") or "")

            contact = _build_contact(social, phone, email, website)
            tags = _build_tags(categoria, subcategoria, tags_raw)
            pd = _digits_phone(phone)
            wa = _whatsapp_url(pd)

            yield {
                "name": nome[:256],
                "category": categoria or None,
                "subcategory": subcategoria or None,
                "state": estado or None,
                "city": cidade or None,
                "county": county or None,
                "tags": (tags[:8000] if tags else None),
                "contact_info": contact,
                "whatsapp_url": wa or None,
            }
            n += 1
            if limit and n >= limit:
                break


class Command(BaseCommand):
    help = "Import Lista de business CSV into chatbot_businesses (Django ORM)."

    def add_arguments(self, parser):
        default_csv = Path(settings.BASE_DIR).parent / "Lista de business 1 - ListaBusiness1.csv"
        parser.add_argument(
            "--path",
            type=str,
            default=str(default_csv),
            help="Path to ListaBusiness1.csv",
        )
        parser.add_argument(
            "--replace",
            action="store_true",
            help=f"Delete existing rows whose contact_info starts with {LISTA_MARKER!r} before import.",
        )
        parser.add_argument(
            "--limit",
            type=int,
            default=0,
            help="Import at most N rows (0 = all).",
        )

    def handle(self, *args, **opts):
        path = Path(opts["path"])
        if not path.is_file():
            self.stderr.write(self.style.ERROR(f"CSV not found: {path}"))
            return

        if opts["replace"]:
            n_del, _ = Business.objects.filter(contact_info__startswith=LISTA_MARKER).delete()
            self.stdout.write(self.style.WARNING(f"Removed {n_del} existing Lista-marked businesses."))

        lim = int(opts["limit"] or 0)
        parsed = list(iter_lista_business_dicts(path, limit=lim))

        if not parsed:
            self.stderr.write(self.style.ERROR("No data rows parsed from CSV."))
            return

        rows_out = [
            Business(
                name=d["name"],
                category=d["category"],
                subcategory=d["subcategory"],
                state=d["state"],
                city=d["city"],
                county=d["county"],
                tags=d["tags"],
                contact_info=d["contact_info"],
                whatsapp_url=d["whatsapp_url"],
                languages="en,es,pt",
                is_active=True,
                is_banned=False,
                created_at=timezone.now(),
            )
            for d in parsed
        ]

        Business.objects.bulk_create(rows_out, batch_size=300)
        self.stdout.write(self.style.SUCCESS(f"Imported {len(rows_out)} businesses from {path}."))
