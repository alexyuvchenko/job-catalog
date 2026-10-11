"""Interface text in Ukrainian and English.

Every key holds both languages side by side, so a missing translation shows up in a test
instead of on the page. Texts take ``{name}`` placeholders.
"""

from __future__ import annotations

from collections.abc import Callable

LANGUAGES = ("uk", "en")
DEFAULT_LANGUAGE = "uk"

_TEXT: dict[str, dict[str, str]] = {
    # Page
    "title": {
        "uk": "Віддалені IT-вакансії з бронюванням",
        "en": "Remote IT jobs with reservation",
    },
    "lede_catalog": {
        "uk": "Каталог віддалених IT-вакансій в Україні, де роботодавець заявляє бронювання від мобілізації. Список збирається з Djinni, DOU, Work.ua і Robota.ua і оновлюється сам. Jooble зараз вимкнено.",
        "en": "A catalog of remote IT jobs in Ukraine where the employer states it can reserve an employee from mobilization (бронювання). It is collected from Djinni, DOU, Work.ua and Robota.ua and updates itself. Jooble is paused for now.",
    },
    "lede_report": {
        "uk": "Пошук віддаленої роботи в IT в Україні на Djinni, DOU, Work.ua і Robota.ua серед вакансій, де роботодавець заявляє бронювання від мобілізації. Jooble зараз вимкнено.",
        "en": "Remote IT jobs in Ukraine from Djinni, DOU, Work.ua and Robota.ua where the employer states it can reserve an employee from mobilization. Jooble is paused for now.",
    },
    "banner_running": {
        "uk": "Зараз оновлюю каталог. Список на екрані лишається, а нові дані з’являться самі.",
        "en": "The catalog is refreshing. The list on screen stays, and new data will appear by itself.",
    },
    "empty_running": {
        "uk": "Каталог ще порожній. Перше оновлення вже йде.",
        "en": "The catalog is still empty. The first refresh is running.",
    },
    "empty_filters": {
        "uk": "Нічого не знайдено за цими умовами.",
        "en": "Nothing matches these conditions.",
    },
    "table_caption": {"uk": "Список вакансій", "en": "Job list"},
    "filter_list": {"uk": "Фільтр у списку", "en": "Filter the list"},
    "language_switch": {"uk": "Мова інтерфейсу", "en": "Interface language"},
    # Refresh status line
    "never_refreshed": {
        "uk": "Оновлення ще не завершувалось.",
        "en": "No refresh has finished yet.",
    },
    "refreshed_at": {"uk": "Оновлено {when}:", "en": "Updated {when}:"},
    "stat_added": {"uk": "додано {n}", "en": "added {n}"},
    "stat_changed": {"uk": "змінено {n}", "en": "changed {n}"},
    "stat_closed": {"uk": "знято {n}", "en": "closed {n}"},
    "next_refresh": {"uk": "Наступне оновлення о {when}.", "en": "Next refresh at {when}."},
    "in_catalog": {
        "uk": "У каталозі {active} актуальних{closed}.",
        "en": "{active} active in the catalog{closed}.",
    },
    "in_catalog_closed": {"uk": ", знятих {n}", "en": ", {n} closed"},
    "users_count": {"uk": "Користувачів: {n}.", "en": "{n} users."},
    # Filters
    "filters": {"uk": "Фільтри", "en": "Filters"},
    "filters_active": {"uk": "активних: {n}", "en": "{n} active"},
    "f_q": {"uk": "Посада або технологія", "en": "Role or technology"},
    "f_q_hint": {"uk": "python, devops, qa", "en": "python, devops, qa"},
    "f_source": {"uk": "Джерело", "en": "Source"},
    "all_sources": {"uk": "усі джерела", "en": "all sources"},
    "f_salary": {"uk": "Мін. зарплата, USD", "en": "Min. salary, USD"},
    "f_english": {"uk": "Англійська від", "en": "English level from"},
    "f_years": {"uk": "Досвід від, років", "en": "Experience from, years"},
    "f_mine": {"uk": "Мої позначки", "en": "My marks"},
    "f_rating": {"uk": "Моя оцінка від", "en": "My rating from"},
    "f_change": {"uk": "Зміни в останньому оновленні", "en": "Changes in the last refresh"},
    "f_language": {"uk": "Мова опису", "en": "Description language"},
    "f_per_page": {"uk": "На сторінці", "en": "Per page"},
    "f_full_remote": {
        "uk": "Лише повна віддаленка, без гібриду",
        "en": "Full remote only, no hybrid",
    },
    "f_inactive": {
        "uk": "Показати вакансії, яких уже немає в джерелах",
        "en": "Show vacancies that are no longer listed",
    },
    "any": {"uk": "будь-яка", "en": "any"},
    "all_changes": {"uk": "усі", "en": "all"},
    "mine_default": {"uk": "усі, крім «не для мене»", "en": "all except “not for me”"},
    "mine_all": {"uk": "усі, і «не для мене»", "en": "everything, with “not for me”"},
    "mine_favorites": {"uk": "обрані", "en": "favorites"},
    "mine_unviewed": {"uk": "не переглянуті", "en": "not viewed"},
    "mine_viewed": {"uk": "переглянуті", "en": "viewed"},
    "mine_rated": {"uk": "з оцінкою", "en": "rated"},
    "mine_hidden": {"uk": "«не для мене»", "en": "“not for me”"},
    "change_added": {"uk": "додані", "en": "added"},
    "change_changed": {"uk": "змінені", "en": "changed"},
    "change_closed": {"uk": "зняті", "en": "closed"},
    "lang_en": {"uk": "англійська", "en": "English"},
    "lang_uk": {"uk": "українська", "en": "Ukrainian"},
    "rating_from": {"uk": "{n} і вище", "en": "{n} and up"},
    "apply": {"uk": "Застосувати", "en": "Apply"},
    "reset": {"uk": "Скинути", "en": "Reset"},
    "refresh_now": {"uk": "Оновити зараз", "en": "Refresh now"},
    "refresh_running": {"uk": "Оновлення вже йде…", "en": "Refreshing…"},
    "refresh_local": {
        "uk": "Оновлення — лише на комп’ютері",
        "en": "Refresh works only on the computer",
    },
    # Table
    "th_date": {"uk": "Дата", "en": "Date"},
    "th_job": {"uk": "Вакансія", "en": "Job"},
    "th_company": {"uk": "Компанія", "en": "Company"},
    "th_format": {"uk": "Формат", "en": "Format"},
    "th_salary": {"uk": "Зарплата", "en": "Salary"},
    "th_reservation": {"uk": "Бронювання", "en": "Reservation"},
    "th_mine": {"uk": "Мої", "en": "Mine"},
    "tag_new": {"uk": "нова", "en": "new"},
    "tag_changed": {"uk": "змінено", "en": "changed"},
    "tag_closed": {"uk": "знято", "en": "closed"},
    "changed_fields": {"uk": "Змінилось: {fields}", "en": "Changed: {fields}"},
    "change_title": {"uk": "назва", "en": "title"},
    "change_company": {"uk": "компанія", "en": "company"},
    "change_location": {"uk": "місце", "en": "location"},
    "change_remote": {"uk": "формат", "en": "format"},
    "change_salary": {"uk": "зарплата", "en": "salary"},
    "change_reservation": {"uk": "бронювання", "en": "reservation"},
    "change_english": {"uk": "англійська", "en": "English"},
    "change_years": {"uk": "досвід", "en": "experience"},
    "change_category": {"uk": "категорія", "en": "category"},
    "change_active": {"uk": "знову в списку", "en": "back in the list"},
    "reservation_confirmed": {"uk": "підтверджено", "en": "confirmed"},
    "reservation_unverified": {"uk": "без бейджа", "en": "no badge"},
    "english_in_text": {"uk": "English {level}", "en": "English {level}"},
    "years_experience": {"uk": "{n} р. досвіду", "en": "{n} yrs experience"},
    "description_english": {"uk": "Опис англійською", "en": "Description is in English"},
    "remote_full": {"uk": "повна віддаленка", "en": "full remote"},
    "remote_remote": {"uk": "віддалено", "en": "remote"},
    "remote_hybrid": {"uk": "гібрид", "en": "hybrid"},
    "remote_office": {"uk": "офіс", "en": "office"},
    "remote_unknown": {"uk": "формат не вказано", "en": "format not stated"},
    "chip_error": {"uk": "помилка", "en": "error"},
    "chip_paused": {"uk": "вимкнено", "en": "paused"},
    # Marks
    "act_favorite": {"uk": "Обране", "en": "Favorite"},
    "act_hide": {"uk": "Не для мене", "en": "Not for me"},
    "act_viewed": {"uk": "Переглянуто", "en": "Viewed"},
    "act_rating": {"uk": "Моя оцінка", "en": "My rating"},
    "act_star": {"uk": "Оцінка {n} з 5", "en": "Rating {n} of 5"},
    "toast_hidden": {"uk": "Вакансію приховано", "en": "Job hidden"},
    "toast_undo": {"uk": "Скасувати", "en": "Undo"},
    "toast_error": {"uk": "Не вдалося зберегти позначку", "en": "Could not save the mark"},
    # Legend
    "legend_title": {"uk": "Позначки", "en": "Legend"},
    "legend_new": {
        "uk": "нова — з’явилась в останньому оновленні",
        "en": "new — appeared in the last refresh",
    },
    "legend_changed": {
        "uk": "змінено — змінились дані в останньому оновленні",
        "en": "changed — details changed in the last refresh",
    },
    "legend_closed": {
        "uk": "знято — вакансії вже немає в джерелі",
        "en": "closed — no longer listed at the source",
    },
    "legend_en": {"uk": "EN — опис англійською", "en": "EN — description is in English"},
    "legend_viewed": {
        "uk": "сірий фон — ви її вже відкривали",
        "en": "grey background — you already opened it",
    },
    # Paging
    "showing": {
        "uk": "Показано {first}–{last} із {total}",
        "en": "Showing {first}–{last} of {total}",
    },
    "showing_none": {"uk": "Нічого не показано", "en": "Nothing to show"},
    "new_note": {
        "uk": " · нових з останнього оновлення: {n}",
        "en": " · new in the last refresh: {n}",
    },
    "show_more": {"uk": "Показати ще {n}", "en": "Show {n} more"},
    "loading": {"uk": "Завантажую…", "en": "Loading…"},
    "load_error": {
        "uk": "Не вдалося завантажити. Спробуйте ще раз.",
        "en": "Could not load. Try again.",
    },
    "page_prev": {"uk": "Назад", "en": "Previous"},
    "page_next": {"uk": "Далі", "en": "Next"},
    "page_nav": {"uk": "Сторінки", "en": "Pages"},
    "page_of": {"uk": "Сторінка {page} із {pages}", "en": "Page {page} of {pages}"},
    # Footer
    "manual_title": {"uk": "Перевірити джерела вручну", "en": "Check the sources by hand"},
    "link_djinni": {
        "uk": "офіційний фільтр «Бронювання» і віддалена робота; у списку лишаються IT-посади",
        "en": "the official “Бронювання” filter plus remote work; the list keeps IT roles",
    },
    "link_dou": {
        "uk": "віддалені вакансії з офіційним бейджем «бронювання»; у списку лишаються IT-посади",
        "en": "remote jobs with the official бронювання badge; the list keeps IT roles",
    },
    "link_workua": {
        "uk": "віддалені вакансії з фільтром «Бронювання працівників»; у списку лишаються IT-посади з будь-якої сфери",
        "en": "remote jobs with the “Бронювання працівників” filter; the list keeps IT roles from any industry",
    },
    "link_robota": {
        "uk": "віддалені вакансії з позначкою бронювання; у списку лишаються IT-посади з будь-якої сфери",
        "en": "remote jobs marked as reservation; the list keeps IT roles from any industry",
    },
    "link_jooble": {
        "uk": "віддалені вакансії; у списку лишаються IT-посади, де в тексті є бронювання",
        "en": "remote jobs; the list keeps IT roles that state reservation in the text",
    },
    "note_catalog": {
        "uk": "Бронювання — це заява роботодавця, що посаду можна включити в бронювання військовозобов’язаних працівників. Це не автоматична відстрочка: потрібні актуальні військово-облікові документи, а рішення залежить від статусу компанії і чинного порядку. Умови варто підтвердити на співбесіді. Вакансія зникає з активного списку, коли її більше немає у джерелі під час чергового оновлення. Якщо сайт не відповів, попередні вакансії цього джерела залишаються. Work.ua і Robota.ua відкриваються через Chrome поза екраном. Jooble зараз не читається.",
        "en": "Бронювання (reservation) is the employer’s statement that the role can be included in the reservation of conscripted employees. It is not an automatic deferment: you still need current military-registration documents, and the outcome depends on the company’s status and the rules in force. Confirm the terms in the interview. A vacancy leaves the active list when it is no longer at its source during a refresh. If a site did not answer, its previous vacancies stay. Work.ua and Robota.ua are read through Chrome off-screen. Jooble is not fetched for now.",
    },
    "note_report": {
        "uk": "Бронювання — це заява роботодавця, що посаду можна включити в бронювання військовозобов’язаних працівників. Це не автоматична відстрочка: потрібні актуальні військово-облікові документи, а рішення залежить від статусу компанії і чинного порядку. Умови варто підтвердити на співбесіді. Work.ua і Robota.ua відкриваються через Chrome, бо інакше сайти не віддають сторінку. Вікно Chrome з’являється поза екраном на час пошуку. Jooble зараз не читається.",
        "en": "Бронювання (reservation) is the employer’s statement that the role can be included in the reservation of conscripted employees. It is not an automatic deferment: you still need current military-registration documents, and the outcome depends on the company’s status and the rules in force. Confirm the terms in the interview. Work.ua and Robota.ua are read through Chrome, because the sites refuse plain requests. The Chrome window stays off-screen during the search. Jooble is not fetched for now.",
    },
    "report_count": {"uk": "{n} вакансій", "en": "{n} jobs"},
    "report_new": {
        "uk": " · нових з минулого пошуку: {n}",
        "en": " · new since the last search: {n}",
    },
    "report_empty": {
        "uk": "Нічого не знайдено за цими умовами.",
        "en": "Nothing matches these conditions.",
    },
    # Accounts
    "login_title": {"uk": "Вхід", "en": "Sign in"},
    "register_title": {"uk": "Новий обліковий запис", "en": "Create an account"},
    "login_lead": {
        "uk": "Позначки, оцінки і фільтри зберігаються для цього облікового запису.",
        "en": "Marks, ratings, and filters are kept for this account.",
    },
    "register_lead": {
        "uk": "Каталог вакансій спільний. Ваші позначки, оцінки і фільтри бачите лише ви.",
        "en": "The job catalog is shared. Only you see your marks, ratings, and filters.",
    },
    "username": {"uk": "Ім’я", "en": "Username"},
    "password": {"uk": "Пароль", "en": "Password"},
    "password_again": {"uk": "Пароль ще раз", "en": "Password again"},
    "sign_in": {"uk": "Увійти", "en": "Sign in"},
    "sign_out": {"uk": "Вийти", "en": "Sign out"},
    "register_submit": {"uk": "Створити обліковий запис", "en": "Create account"},
    "need_account": {"uk": "Немає облікового запису?", "en": "No account yet?"},
    "have_account": {"uk": "Вже є обліковий запис?", "en": "Already have an account?"},
    "go_register": {"uk": "Створити", "en": "Create one"},
    "go_login": {"uk": "Увійти", "en": "Sign in"},
    "auth_failed": {"uk": "Невірне ім’я або пароль.", "en": "Unknown username or password."},
    "username_taken": {"uk": "Таке ім’я вже зайняте.", "en": "That username is already taken."},
    "username_invalid": {
        "uk": "Ім’я має містити від 1 до 64 символів.",
        "en": "Username must be from 1 to 64 characters.",
    },
    "password_invalid": {
        "uk": "Пароль має містити від 8 до 200 символів.",
        "en": "Password must be from 8 to 200 characters.",
    },
    "password_mismatch": {"uk": "Паролі не збігаються.", "en": "Passwords do not match."},
    "register_closed": {
        "uk": "Нові облікові записи зараз не створюються. Увійдіть, якщо запис уже є.",
        "en": "New accounts are not being created. Sign in if you already have one.",
    },
    "account_label": {"uk": "Обліковий запис", "en": "Account"},
    "auth_note": {
        "uk": "Бронювання — заява роботодавця, не автоматична відстрочка. Потрібні актуальні військово-облікові документи, а умови підтверджують на співбесіді.",
        "en": "Reservation (бронювання) is the employer’s statement, not an automatic deferment. Current military-registration documents are required, and the terms are confirmed in the interview.",
    },
    # Errors
    "error_title": {
        "uk": "Каталог тимчасово недоступний",
        "en": "The catalog is temporarily unavailable",
    },
    "error_body": {
        "uk": "Каталог тимчасово недоступний. Деталі є в журналі процесу.",
        "en": "The catalog is temporarily unavailable. Details are in the process log.",
    },
}

Translator = Callable[..., str]


def translator(language: str) -> Translator:
    chosen = language if language in LANGUAGES else DEFAULT_LANGUAGE

    def translate(key: str, **values: object) -> str:
        text = _TEXT[key][chosen]
        return text.format(**values) if values else text

    return translate


def keys() -> list[str]:
    return list(_TEXT)


def raw(key: str, language: str) -> str:
    return _TEXT[key][language]


def pick_language(query: str = "", cookie: str = "", accept: str = "", saved: str = "") -> str:
    """The language to show: an explicit choice, then the saved one, then the browser's."""
    for choice in (query, cookie, saved):
        if choice in LANGUAGES:
            return choice
    first = accept.split(",")[0].strip().lower() if accept else ""
    return "en" if first.startswith("en") else DEFAULT_LANGUAGE
