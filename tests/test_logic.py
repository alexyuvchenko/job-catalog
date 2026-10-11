from datetime import date
from http.cookiejar import Cookie

from core.classify import (
    accept_remote,
    dou_remote_mode,
    english_meets,
    evidence_sentence,
    is_it_role,
    parse_dou_date,
    parse_english,
    parse_relative_date,
    parse_salary,
    parse_years,
    salary_meets,
)
from core.models import Job
from network.browser import asks_for_human, is_browser_check
from network.client import Client
from sources.djinni import parse_djinni_html
from sources.dou import has_reservation_badge, parse_dou_html
from sources.jooble import job_from_card as jooble_job
from sources.robota import job_from_item
from sources.workua import job_from_card as work_job


class TestBrowserCheck:
    def test_human_check_is_recognized(self):
        assert asks_for_human("Just a moment...", "Verify you are human")
        assert asks_for_human("", "Підтвердьте, що ви людина")
        assert is_browser_check("Just a moment...")
        assert not (asks_for_human("Just a moment..."))
        assert not (is_browser_check("Python Developer — Jooble"))


class TestClassify:
    def test_engineering_roles_stay_and_hr_roles_go(self):
        kept = [
            "Senior Python Developer",
            "Technical Product Manager",
            "Embedded Linux Engineer / Yocto Engineer",
            "Бізнес-аналітик з бухгалтерського та фінансового обліку",
            "BIM Team Lead",
            "Fullstack Engineer (Banking)",
        ]
        dropped = [
            "Креативний маркетолог",
            "Talent Acquisition (RnD)",
            "Talent Sourcer",
            "Business Development Manager (BDM)",
            "Senior SEO Specialist",
            "Head of Accounts Receivable",
            "Head of HR Operations",
        ]
        for title in kept:
            assert is_it_role(title, "", "engineering"), title
        for title in dropped:
            assert not is_it_role(title, "", "engineering"), title
        assert is_it_role("Head of HR Operations", "", "all")

    def test_salary_ranges(self):
        assert parse_salary("до $2500") == (None, 2500, "USD")
        assert parse_salary("від $3000") == (3000, None, "USD")
        assert parse_salary("$3000–4000") == (3000, 4000, "USD")
        assert parse_salary("80 000 грн") == (80000, 80000, "UAH")

    def test_salary_filter_uses_the_top_of_the_range(self):
        low = _job(salary_min=1000, salary_max=1500, currency="USD")
        overlap = _job(salary_min=1000, salary_max=3000, currency="USD")
        unknown = _job()
        hryvnia = _job(salary_min=80000, salary_max=90000, currency="UAH")
        assert not (salary_meets(low, 2000))
        assert salary_meets(overlap, 2000)
        assert salary_meets(unknown, 2000)
        assert salary_meets(hryvnia, 2000)

    def test_english_and_years(self):
        assert parse_english("Англійська - B1") == "B1"
        assert parse_english("English - None") == "none"
        assert english_meets("B2", "B1")
        assert not (english_meets("A2", "B2"))
        assert english_meets("", "B2")
        assert not (english_meets("none", "B1"))
        assert parse_years("3 роки досвіду") == 3
        assert parse_years("5 years of experience") == 5

    def test_dou_date_rolls_back_a_future_month(self):
        today = date(2026, 10, 10)
        assert parse_dou_date("9 жовтня", today) == "2026-10-09"
        assert parse_dou_date("15 грудня", today) == "2025-12-15"
        assert parse_dou_date("9 жовтня 2024", today) == "2024-10-09"
        assert parse_relative_date("2026-10-08 16:40:04", today) == "2026-10-08"
        assert parse_relative_date("2 дні тому", today) == "2026-10-08"
        assert parse_relative_date("2 дня назад", today) == "2026-10-08"
        assert parse_relative_date("1 неделю назад", today) == "2026-10-03"
        assert parse_relative_date("3 недели назад", today) == "2026-09-19"

    def test_remote_modes(self):
        assert dou_remote_mode("віддалено") == "full"
        assert dou_remote_mode("Київ, Львів, віддалено") == "hybrid"
        assert dou_remote_mode("Київ") == "office"
        assert accept_remote("hybrid", full_remote_only=False)
        assert not (accept_remote("hybrid", full_remote_only=True))
        assert not (accept_remote("office", full_remote_only=False))

    def test_evidence_sentence(self):
        text = "Команда в Україні. Надаємо бронювання від мобілізації за наявності документів. Графік гнучкий."
        quote = evidence_sentence(text)
        assert "бронювання від мобілізації" in quote


class TestParsers:
    def test_djinni_jsonld_survives_brackets_in_the_description(self):
        html = """
        <span class="fs-1 fw-bold text-muted">12</span>
        <script type="application/ld+json">
        [{
          "@type": "JobPosting",
          "identifier": 10,
          "title": "Python Developer",
          "url": "https://djinni.co/jobs/10-python/",
          "description": "Use list[int] and надаємо бронювання.",
          "datePosted": "2026-10-09T10:00:00",
          "category": "Python",
          "jobLocationType": "TELECOMMUTE",
          "hiringOrganization": {"name": "Example", "sameAs": "https://example.com"},
          "experienceRequirements": {"monthsOfExperience": 36},
          "baseSalary": {"currency": "USD", "value": {"minValue": 3000, "maxValue": 4000}}
        }]
        </script>
        <div id="job-item-10" class="job-item card">
          <div class="fw-medium d-flex">
            <span class="text-nowrap">Тільки віддалено</span>
            <span class="location-text">Україна</span>
            <span class="text-nowrap">Англійська - B2</span>
          </div>
        </div>
        """
        jobs, total = parse_djinni_html(html)
        assert total == 12
        assert len(jobs) == 1
        job = jobs[0]
        assert job.title == "Python Developer"
        assert job.company == "Example"
        assert job.remote == "full"
        assert job.salary_min == 3000
        assert job.salary_max == 4000
        assert job.years == 3
        assert job.english == "B2"
        assert job.reservation == "confirmed"
        assert job.published == "2026-10-09"
        assert "бронювання" in job.evidence

    def test_djinni_remote_filter_keeps_a_job_without_an_explicit_label(self):
        html = """
        <script type="application/ld+json">
        [{"@type": "JobPosting", "identifier": 11, "title": "Go Engineer",
          "url": "https://djinni.co/jobs/11-go/", "description": "backend",
          "hiringOrganization": {"name": "Acme"}}]
        </script>
        <div id="job-item-11" class="job-item">
          <div class="fw-medium"><span class="location-text">Україна</span></div>
        </div>
        """
        jobs, _ = parse_djinni_html(html)
        assert jobs[0].remote == "remote"

    def test_dou_card_and_badge(self):
        html = """
        <li class="l-vacancy __hot">
          <div class="date">9 жовтня</div>
          <div class="title">
            <a class="vt" href="https://jobs.dou.ua/companies/acme/vacancies/55/?from=list_hot">Python Engineer</a>
            <strong>в <a class="company" href="https://jobs.dou.ua/companies/acme/vacancies/">Acme</a></strong>
            <span class="salary">$3000–4000</span>
            <span class="cities bi bi-geo-alt-fill"> віддалено</span>
          </div>
          <div class="sh-info">Backend role.</div>
        </li>
        """
        jobs = parse_dou_html(html)
        assert len(jobs) == 1
        assert jobs[0].job_id == "55"
        assert jobs[0].url == "https://jobs.dou.ua/companies/acme/vacancies/55/"
        assert jobs[0].company == "Acme"
        assert jobs[0].remote == "full"
        assert jobs[0].salary_min == 3000
        assert jobs[0].reservation == "unverified"
        badge = '<a class="badge" href="https://jobs.dou.ua/vacancies/?search=бронювання&from=badge">бронювання</a>'
        assert has_reservation_badge(badge)
        assert not (has_reservation_badge("<p>система бронювання квитків</p>"))

    def test_workua_keeps_only_the_reservation_badge(self):
        today = date(2026, 10, 10)
        kept = work_job(
            {
                "href": "/jobs/7748901/",
                "title": "Junior Site Reliability Engineer",
                "company": "Nix",
                "lines": ["Nix", "Дистанційно", "Досвід від 1 року · Стандартний графік: 5/2"],
                "published": "2026-10-08 16:40:04",
                "salary": "",
                "snippet": "Ми шукаємо Junior Site Reliability Engineer.",
                "reserved": True,
            }
        )
        assert kept is not None
        assert kept.source == "Work.ua"
        assert kept.remote == "full"
        assert kept.years == 1
        assert kept.published == "2026-10-08"
        assert kept.reservation == "confirmed"
        assert (
            work_job(
                {
                    "href": "/jobs/1/",
                    "title": "Python Developer",
                    "company": "Acme",
                    "lines": ["Київ, дистанційно"],
                    "published": "",
                    "salary": "",
                    "snippet": "",
                    "reserved": False,
                }
            )
            is None
        )
        hybrid = work_job(
            {
                "href": "/jobs/2/",
                "title": "Python Developer",
                "company": "Acme",
                "lines": ["Київ, дистанційно"],
                "published": "",
                "salary": "до 2000 $",
                "snippet": "",
                "reserved": True,
            }
        )
        assert hybrid is not None
        assert hybrid.remote == "hybrid"
        assert hybrid.salary_max == 2000
        assert hybrid.currency == "USD"
        assert parse_relative_date("2 дні тому", today) == "2026-10-08"

    def test_robota_requires_remote_schedule(self):
        job = job_from_item(
            {
                "id": 11368370,
                "title": "Розробник Odoo, Python Developer",
                "sortDateText": "2 дні тому",
                "description": "Python та Odoo.",
                "city": {"name": "Київ"},
                "company": {"id": 198563, "name": "EBS"},
                "salary": {"amountFrom": 0, "amountTo": 0, "comment": ""},
                "badges": [{"name": "Бронирование сотрудников"}],
                "schedules": [{"id": "3", "name": "remote"}, {"id": "8", "name": "hybrid"}],
            }
        )
        assert job is not None
        assert job.url == "https://robota.ua/company198563/vacancy11368370"
        assert job.remote == "hybrid"
        assert job.reservation == "confirmed"
        assert "Бронирование" in job.evidence
        anonymous = job_from_item(
            {
                "id": 11366974,
                "title": "OSINT-аналітик",
                "schedules": [{"name": "remote"}],
                "company": None,
            }
        )
        assert anonymous is not None
        assert anonymous.url == "https://robota.ua/company0/vacancy11366974"
        office = job_from_item(
            {
                "id": 1,
                "title": "Python Developer",
                "schedules": [{"name": "office"}],
                "company": {"id": 2, "name": "Acme"},
            }
        )
        assert office is None

    def test_jooble_keeps_a_card_only_when_the_text_states_reservation(self):
        kept = jooble_job(
            {
                "title": "Python Developer",
                "href": "https://ua.jooble.org/jdp/9988?p=1",
                "text": "Python Developer\n3 000 - 5 000 $\nEBS\nВіддалено\n10 днів тому\nНадаємо бронювання працівників.",
            }
        )
        assert kept is not None
        assert kept.job_id == "9988"
        assert kept.company == "EBS"
        assert kept.salary_min == 3000
        assert kept.salary_max == 5000
        assert kept.currency == "USD"
        assert kept.remote == "full"
        dropped = jooble_job(
            {
                "title": "Senior Accounting Manager",
                "href": "https://ua.jooble.org/desc/42",
                "text": "Senior Accounting Manager\nБухгалтерія\nВіддалено",
            }
        )
        assert dropped is None
        assert evidence_sentence("можливість бронювання працівників")
        tagged = jooble_job(
            {
                "title": "Data Scientist",
                "href": "https://ua.jooble.org/desc/77",
                "text": "Data Scientist\nOM Defence Systems\nВіддалено\n4 дні тому\nБронювання\nВіддалена робота",
            }
        )
        assert tagged is not None
        assert tagged.evidence == "Бронювання"
        assert tagged.company == "OM Defence Systems"
        assert tagged.location == "Віддалено"
        noisy = jooble_job(
            {
                "title": "Data Scientist",
                "href": "https://ua.jooble.org/desc/78",
                "text": (
                    "Data Scientist\n"
                    "6 жовтня 2026 бронювання Data Scientist віддалено Key Responsibilities for the role\n"
                    "OM Defence Systems\nВіддалено\n4 дні тому\nБронювання"
                ),
            }
        )
        assert noisy is not None
        assert noisy.location == "Віддалено"
        assert noisy.company == "OM Defence Systems"


class TestClientCookies:
    def test_csrf_cookie_is_chosen_for_the_request_host(self):
        client = Client()
        client._cookies.set_cookie(_cookie("djinni.co", "djinni-token"))
        client._cookies.set_cookie(_cookie(".dou.ua", "dou-token"))
        assert client.cookie("csrftoken", "jobs.dou.ua") == "dou-token"
        assert client.cookie("csrftoken", "djinni.co") == "djinni-token"


def _cookie(domain: str, value: str) -> Cookie:
    return Cookie(
        version=0,
        name="csrftoken",
        value=value,
        port=None,
        port_specified=False,
        domain=domain,
        domain_specified=True,
        domain_initial_dot=domain.startswith("."),
        path="/",
        path_specified=True,
        secure=True,
        expires=None,
        discard=True,
        comment=None,
        comment_url=None,
        rest={},
    )


def _job(**overrides) -> Job:
    data = dict(
        source="Djinni",
        job_id="1",
        title="Python Developer",
        company="Example",
        company_url="",
        url="https://example.com/1",
        location="Україна",
        remote="full",
        salary_min=None,
        salary_max=None,
        currency=None,
        salary_text="",
        category="Python",
        english="B2",
        years=3,
        published="2026-10-09",
        reservation="confirmed",
        evidence="",
        snippet="",
    )
    data.update(overrides)
    return Job(**data)
