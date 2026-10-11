from __future__ import annotations

import re
from datetime import date, timedelta

from core.models import Job

# Roles that are not software/IT delivery. Matched against title and category only.
_NON_ENGINEERING = re.compile(
    r"(?i)(?:"
    r"\brecruiter\b|\brecruitment\b|\bsourcer\b|talent acquisition|talent partner|"
    r"head of hr|\bhr manager\b|\bhrbp\b|hr ops|hr operations|people partner|"
    r"people operations|\bкадр|\bрекрутер|\bсорсер|"
    r"\bmarketing\b|\bмаркетолог|\bsmm\b|seo specialist|media buyer|\bppc\b|"
    r"\bcopywriter\b|\bкопірайтер|"
    r"sales manager|account executive|business development|head of accounts|"
    r"accounts receivable|\baccountant\b|\bбухгалтер(?:а|у|ом|ів)?\b|\bюрист(?:а|у|ом)?\b|office manager|"
    r"офіс-менеджер|customer support|customer success|"
    r"\bfinance manager\b|\bfinancial controller\b|"
    r"кредитн(?:ий|ого)\s+аналітик|дизайнер інтер.?єр|дизайнер одяг|ландшафтн|"
    r"інженер[- ]?(?:механік|будівельник|енергетик|електрик|конструктор)|"
    r"охорона праці|call[- ]?cent(?:er|re)|оператор(?:ка)?.{0,24}чат|"
    r"менеджер чат"
    r")"
)

_ENGINEERING = re.compile(
    r"(?i)(?:"
    r"developer|engineer|розробник|програміст|"
    r"devops|devsecops|mlops|dataops|secops|gitops|\bsre\b|\bsdet\b|"
    r"\bqa\b|\baqa\b|\btester\b|тестувальн|автоматизатор|"
    r"\bdata\b|analyst|аналітик|scientist|architect|архітектор|"
    r"designer|дизайнер|product manager|product owner|продакт|"
    r"project manager|проджект|проєктний менеджер|\bscrum\b|scrum.?master|"
    r"delivery manager|release manager|"
    r"embedded|security|кібер|кібербезпек|інформаційн(?:ої|а)\s+безпек|захист інформації|"
    r"sysadmin|сисадмін|системн(?:ий|ого)?\s*адмін|"
    r"адмін(?:істратор)?(?:а|у)?\s*(?:мереж|бд|баз|linux|windows|систем|сайту|домену|1с|1c|bas)|"
    r"мережев|"
    r"\bdba\b|frontend|front-end|front end|backend|back-end|back end|"
    r"fullstack|full-stack|full stack|\bios\b|android|flutter|react native|"
    r"\bpython\b|\bjava\b|\bphp\b|\bnode\b|\breact\b|\bvue\b|angular|typescript|"
    r"golang|\bgolang\b|\brust\b|kotlin|swift|\.net|\bc\+\+|\bc#\b|csharp|"
    r"scala|\bruby\b|elixir|django|laravel|spring|next\.?js|nestjs|"
    r"\bml\b|\bllm\b|machine learning|computer vision|\bnlp\b|genai|\bai\b|"
    r"infrastructure|site reliability|observability|"
    r"it support|technical support|підтримк|help\s*desk|service\s*desk|servicedesk|"
    r"technical writer|технічний письмен|"
    r"\bsap\b|salesforce|sharepoint|\bcrm\b|\b1c\b|\b1с\b|\bbas\b|\berp\b|"
    r"бітрікс|bitrix|no-code|nocode|low-?code|\brpa\b|uipath|"
    r"firmware|yocto|\bbim\b|fpga|vhdl|\biot\b|схемотехн|електронщик|"
    r"tech lead|team lead|engineering manager|"
    r"head of (?:engineering|development|it|іт)|vp(?: of)? engineering|"
    r"\bcto\b|\bcio\b|\bciso\b|solution architect|enterprise architect|platform|"
    r"(?:^|[\s/(\-])(?:it|іт)(?:$|[\s/)\\-])|"
    r"іт[- ]?(?:фахівець|спеціаліст|інженер|менеджер|директор)|"
    r"it[- ]?(?:specialist|engineer|manager|director|admin)|"
    r"фахівець з інформаційн|"
    r"інженер(?:-?(?:програміст|розробник|тестувальник|електронщик)|"
    r"\s*(?:пз|програм|qa|мереж|систем|даних|безпек|підтримк|пк))|"
    r"системн(?:ий|ого)?\s+інженер|мережев(?:ий|ого)?\s+інженер|"
    r"програмн(?:ого|е)\s+забезпечен|\bsoftware\b|"
    r"верстальник|веб[- ]?(?:майстер|розроб|дизайн|інженер)|webmaster|"
    r"pentester|pentest|\bsoc\b|\bnoc\b|appsec|infosec|"
    r"cloud|\bk8s\b|kuber|\bdocker\b|"
    r"\bunity\b|unreal|gamedev|game dev|blockchain|solidity|web3|"
    r"\bbi\b|power bi|tableau|\bdwh\b|\betl\b|"
    r"oracle|postgres|mysql|mongodb|redis|"
    r"\blinux\b|\bwindows\b|vmware|cisco|mikrotik|"
    r"wordpress|drupal|magento|shopify|servicenow|\bjira\b|"
    r"javascript|\bhtml\b|\bcss\b|cobol|\babap\b|delphi|"
    r"ci/?cd|\bmobile\b|ux/?ui|\bux\b|\bui\b|"
    r"\bl[123]\b"
    r")"
)

_ENGLISH = re.compile(r"(?i)(?:англійська|english)\s*[-–:]?\s*(A1|A2|B1|B2|C1|C2|none|немає)")
_YEARS = re.compile(r"(?i)(\d+(?:[.,]\d+)?)\s*\+?\s*(?:рок(?:и|ів)?|years?|yrs?)")
_SALARY_NUM = re.compile(r"\d[\d ]*")

_MONTHS = {
    "січня": 1,
    "лютого": 2,
    "березня": 3,
    "квітня": 4,
    "травня": 5,
    "червня": 6,
    "липня": 7,
    "серпня": 8,
    "вересня": 9,
    "жовтня": 10,
    "листопада": 11,
    "грудня": 12,
}

_ENGLISH_RANK = {"a1": 1, "a2": 2, "b1": 3, "b2": 4, "c1": 5, "c2": 6}

_EVIDENCE = re.compile(
    r"(?i)("
    r"бронювання від мобілізації|"
    r"можлив(?:ість|е) бронювання|"
    r"надаємо бронювання|"
    r"бронюємо|"
    r"бронювання військовозобов|"
    r"бронювання\s+(?:працівник|співробітник)\w*|"
    r"бронирован\w*\s+сотрудник\w*|"
    r"має можливість бронювати|"
    r"reserv(?:e|ing|ation) from (?:army )?mobilization|"
    r"military reservation|"
    r"possibility of military reservation|"
    r"official military deferment"
    r")"
)


_CYRILLIC = re.compile(r"[А-Яа-яЇїІіЄєҐґ]")
_LATIN = re.compile(r"[A-Za-z]")


def detect_language(text: str) -> str:
    """ "en" or "uk" for a description, or "" when it is too short or mixed to say.

    Ukrainian descriptions carry Latin tech words (Python, React), so only a text that is
    almost entirely Latin counts as English.
    """
    cyrillic = len(_CYRILLIC.findall(text or ""))
    latin = len(_LATIN.findall(text or ""))
    if cyrillic + latin < 40:
        return ""
    share = latin / (cyrillic + latin)
    if share >= 0.85:
        return "en"
    if share <= 0.4:
        return "uk"
    return ""


def is_it_role(title: str, category: str, focus: str) -> bool:
    if focus == "all":
        return True
    blob = f"{title} {category}"
    if _NON_ENGINEERING.search(blob):
        return False
    return _ENGINEERING.search(blob) is not None


def is_it_title(title: str) -> bool:
    """The vacancy title is an engineering or product IT role, ignoring company industry."""
    return is_it_role(title, "", "engineering")


def parse_english(text: str) -> str:
    match = _ENGLISH.search(text or "")
    if not match:
        return ""
    value = match.group(1).lower()
    if value in {"none", "немає"}:
        return "none"
    return value.upper()


def english_meets(level: str, minimum: str) -> bool:
    if not minimum:
        return True
    if not level:
        return True
    if level == "none":
        return False
    return _ENGLISH_RANK.get(level.lower(), 0) >= _ENGLISH_RANK[minimum.lower()]


def parse_years(text: str) -> float | None:
    match = _YEARS.search(text or "")
    if not match:
        return None
    return float(match.group(1).replace(",", "."))


def parse_salary(raw: str) -> tuple[int | None, int | None, str | None]:
    if not raw or not raw.strip():
        return None, None, None
    text = raw.replace("\xa0", " ").strip()
    upper = text.upper()
    lower = text.lower()
    if "$" in text or "USD" in upper:
        currency = "USD"
    elif "€" in text or "EUR" in upper:
        currency = "EUR"
    elif "₴" in text or "UAH" in upper or "грн" in lower:
        currency = "UAH"
    else:
        currency = None
    numbers = []
    for token in _SALARY_NUM.findall(text):
        digits = token.replace(" ", "")
        if not digits:
            continue
        value = int(digits)
        if value >= 100:
            numbers.append(value)
    if not numbers:
        return None, None, currency
    if lower.startswith("до") or "up to" in lower:
        return None, numbers[0], currency
    if lower.startswith("від") or lower.startswith("from"):
        return numbers[0], None, currency
    if len(numbers) >= 2:
        return numbers[0], numbers[1], currency
    return numbers[0], numbers[0], currency


def salary_meets(job: Job, minimum: int | None) -> bool:
    if not minimum:
        return True
    if job.currency not in {None, "USD"}:
        return True
    if job.salary_min is None and job.salary_max is None:
        return True
    ceiling = job.salary_max if job.salary_max is not None else job.salary_min
    floor = job.salary_min if job.salary_min is not None else job.salary_max
    if ceiling is not None and ceiling < minimum:
        return False
    if job.salary_max is None and floor is not None and floor < minimum:
        return False
    return True


def parse_relative_date(text: str, today: date | None = None) -> str:
    raw = (text or "").replace("\xa0", " ").strip().lower()
    if not raw:
        return ""
    today = today or date.today()
    iso = re.search(r"(\d{4})-(\d{2})-(\d{2})", raw)
    if iso:
        try:
            return date(int(iso.group(1)), int(iso.group(2)), int(iso.group(3))).isoformat()
        except ValueError:
            return ""
    if "сьогодні" in raw or "сегодня" in raw:
        return today.isoformat()
    if "вчора" in raw or "вчера" in raw:
        return (today - timedelta(days=1)).isoformat()
    weeks = re.search(r"(\d+)\s*(?:тижн|недел)", raw)
    if weeks:
        return (today - timedelta(days=7 * int(weeks.group(1)))).isoformat()
    months = re.search(r"(\d+)\s*(?:місяц|месяц)", raw)
    if months:
        return (today - timedelta(days=30 * int(months.group(1)))).isoformat()
    match = re.search(r"(\d+)\s*(?:дн|день|дня|дні)", raw)
    if match:
        return (today - timedelta(days=int(match.group(1)))).isoformat()
    return parse_dou_date(raw, today)


def parse_dou_date(text: str, today: date | None = None) -> str:
    raw = (text or "").replace("\xa0", " ").strip()
    if not raw:
        return ""
    today = today or date.today()
    match = re.search(
        r"(\d{1,2})\s+([а-яіїєґ]+)(?:\s+(\d{4}))?",
        raw,
        flags=re.IGNORECASE,
    )
    if not match:
        return ""
    day = int(match.group(1))
    month = _MONTHS.get(match.group(2).lower())
    if not month or not 1 <= day <= 31:
        return ""
    if match.group(3):
        year = int(match.group(3))
    else:
        year = today.year
        try:
            parsed = date(year, month, day)
        except ValueError:
            return ""
        if parsed > today + timedelta(days=2):
            year -= 1
    try:
        return date(year, month, day).isoformat()
    except ValueError:
        return ""


def evidence_sentence(text: str) -> str:
    if not text:
        return ""
    compact = re.sub(r"\s+", " ", text).strip()
    match = _EVIDENCE.search(compact)
    if not match:
        return ""
    start = max(0, match.start() - 80)
    end = min(len(compact), match.end() + 120)
    snippet = compact[start:end].strip()
    if start > 0:
        snippet = "…" + snippet
    if end < len(compact):
        snippet = snippet + "…"
    return snippet


def remote_mode_from_meta(meta: str, location: str) -> str:
    blob = f"{meta} {location}".lower()
    if "гібрид" in blob or "hybrid" in blob:
        return "hybrid"
    if "тільки віддалено" in blob or "full remote" in blob or "remote only" in blob:
        return "full"
    if "офіс" in blob and "віддален" not in blob and "remote" not in blob:
        return "office"
    if "віддален" in blob or "remote" in blob or "весь світ" in blob:
        return "remote"
    return "unknown"


def dou_remote_mode(cities: str) -> str:
    text = (cities or "").lower()
    if "віддален" not in text and "remote" not in text:
        return "office"
    # A city next to "віддалено" means the employer lists an office and remote work.
    without_remote = re.sub(r"віддалено|remote|за кордоном", "", text)
    without_remote = re.sub(r"[,·\s]+", "", without_remote)
    if without_remote:
        return "hybrid"
    return "full"


def accept_remote(mode: str, full_remote_only: bool) -> bool:
    if mode in {"office", "unknown"}:
        return False
    if full_remote_only:
        return mode == "full"
    return mode in {"full", "remote", "hybrid"}
