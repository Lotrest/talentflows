import logging
import random
import string
from datetime import datetime, timezone, timedelta
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText

import aiosmtplib

from app.core.config import settings

logger = logging.getLogger(__name__)

OTP_LENGTH = 6
OTP_TTL_MINUTES = 15


def generate_otp() -> str:
    return "".join(random.choices(string.digits, k=OTP_LENGTH))


def otp_expires_at() -> datetime:
    return datetime.now(timezone.utc) + timedelta(minutes=OTP_TTL_MINUTES)


YANDEX_DOMAINS = {"yandex.ru", "yandex.com", "yandex.by", "yandex.kz", "yandex.ua", "ya.ru"}
MAILRU_DOMAINS = {"mail.ru", "bk.ru", "inbox.ru", "list.ru", "internet.ru"}


def _build_provider(host: str, port: int, user: str, password: str,
                    from_addr: str, from_name: str, label: str) -> dict:
    return {"host": host, "port": port, "user": user, "password": password,
            "from_addr": from_addr or user, "from_name": from_name, "label": label}


def _yandex_provider() -> dict | None:
    if settings.smtp_host and settings.smtp_user:
        return _build_provider(
            settings.smtp_host, settings.smtp_port,
            settings.smtp_user, settings.smtp_password,
            settings.smtp_from, settings.smtp_from_name, "yandex",
        )
    return None


def _mailru_provider() -> dict | None:
    if settings.smtp2_host and settings.smtp2_user:
        return _build_provider(
            settings.smtp2_host, settings.smtp2_port,
            settings.smtp2_user, settings.smtp2_password,
            settings.smtp2_from, settings.smtp2_from_name, "mailru",
        )
    return None


def _smtp_providers_for(recipient: str) -> list[dict]:
    """Order providers so the one matching recipient's domain goes first."""
    domain = recipient.split("@")[-1].lower()
    yandex = _yandex_provider()
    mailru = _mailru_provider()

    if domain in YANDEX_DOMAINS:
        ordered = [yandex, mailru]
    elif domain in MAILRU_DOMAINS:
        ordered = [mailru, yandex]
    else:
        ordered = [yandex, mailru]

    return [p for p in ordered if p is not None]


async def _send(to: str, subject: str, html: str) -> bool:
    providers = _smtp_providers_for(to)
    if not providers:
        logger.warning("No SMTP configured — skipping email to %s subject='%s'", to, subject)
        return False

    for p in providers:
        msg = MIMEMultipart("alternative")
        msg["Subject"] = subject
        msg["From"] = f"{p['from_name']} <{p['from_addr']}>"
        msg["To"] = to
        msg.attach(MIMEText(html, "html", "utf-8"))

        try:
            await aiosmtplib.send(
                msg,
                hostname=p["host"],
                port=p["port"],
                username=p["user"],
                password=p["password"],
                use_tls=False,
                start_tls=True,
            )
            logger.info("email sent via %s: to=%s subject='%s'", p["label"], to, subject)
            return True
        except Exception:
            logger.warning("email failed via %s (%s:%s) — trying next", p["label"], p["host"], p["port"])

    logger.error("all SMTP providers failed: to=%s subject='%s'", to, subject)
    return False


async def send_verification_code(to: str, code: str) -> bool:
    html = f"""
    <div style="font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',sans-serif;
                max-width:480px;margin:0 auto;padding:40px 32px;background:#fff;">
        <h2 style="color:#1a1a1a;margin:0 0 16px;">Подтверждение email</h2>
        <p style="color:#444;margin:0 0 24px;">Ваш код подтверждения для TalentFlows:</p>
        <div style="font-size:40px;font-weight:700;letter-spacing:10px;
                    background:#f5f5f0;padding:20px;border-radius:10px;
                    text-align:center;margin:0 0 24px;color:#1a1a1a;">
            {code}
        </div>
        <p style="color:#666;margin:0 0 8px;">Код действителен {OTP_TTL_MINUTES} минут.</p>
        <p style="color:#999;font-size:12px;margin:0;">
            Если вы не регистрировались — просто проигнорируйте это письмо.
        </p>
    </div>
    """
    return await _send(to, "Код подтверждения — TalentFlows", html)


async def send_new_vacancies_digest(
    to: str, name: str | None, count: int, top_vacancies: list[dict]
) -> bool:
    greeting = f"Привет, {name}!" if name else "Привет!"
    if count == 1:
        word = "вакансия"
    elif 2 <= count <= 4:
        word = "вакансии"
    else:
        word = "вакансий"

    rows_html = ""
    for v in top_vacancies[:3]:
        salary = ""
        if v.get("salary_from"):
            salary = f" &nbsp;·&nbsp; от {v['salary_from']:,}₽".replace(",", " ")
        score_badge = ""
        if v.get("score") is not None:
            score_badge = (
                f'<span style="background:#d4f4a0;padding:2px 8px;border-radius:12px;'
                f'font-size:12px;">{v["score"]}%</span>'
            )
        rows_html += f"""
        <tr>
            <td style="padding:10px 0;border-bottom:1px solid #eee;">
                <strong style="color:#1a1a1a;">{v.get("title","")}</strong><br>
                <span style="color:#666;font-size:13px;">{v.get("company","")}{salary}</span>
            </td>
            <td style="padding:10px 0;border-bottom:1px solid #eee;
                       text-align:right;vertical-align:middle;">
                {score_badge}
            </td>
        </tr>"""

    table_html = (
        f'<table style="width:100%;border-collapse:collapse;margin:20px 0;">'
        f"{rows_html}</table>"
        if rows_html
        else ""
    )

    html = f"""
    <div style="font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',sans-serif;
                max-width:520px;margin:0 auto;padding:40px 32px;background:#fff;">
        <h2 style="color:#1a1a1a;margin:0 0 12px;">Новые вакансии найдены</h2>
        <p style="color:#444;margin:0 0 8px;">
            {greeting} За последние часы найдено&nbsp;
            <strong>{count}&nbsp;{word}</strong> под ваш профиль.
        </p>
        {table_html}
        <a href="{settings.frontend_url}/dashboard/vacancies"
           style="display:inline-block;background:#a3e635;color:#1a1a1a;
                  padding:12px 24px;border-radius:8px;text-decoration:none;
                  font-weight:600;margin-top:8px;">
            Смотреть вакансии →
        </a>
        <p style="color:#bbb;font-size:11px;margin-top:32px;">
            TalentFlows &nbsp;·&nbsp;
            <a href="{settings.frontend_url}/dashboard/settings"
               style="color:#bbb;">Настройки уведомлений</a>
        </p>
    </div>
    """
    subject = f"Найдено {count} {word} под ваш профиль — TalentFlows"
    return await _send(to, subject, html)


async def send_application_sent(
    to: str, name: str | None, vacancy_title: str, company: str
) -> bool:
    greeting = f"Привет, {name}!" if name else "Привет!"
    html = f"""
    <div style="font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',sans-serif;
                max-width:480px;margin:0 auto;padding:40px 32px;background:#fff;">
        <h2 style="color:#1a1a1a;margin:0 0 16px;">Отклик отправлен ✓</h2>
        <p style="color:#444;margin:0 0 20px;">{greeting}</p>
        <div style="background:#f5f5f0;padding:16px 20px;border-radius:8px;margin:0 0 24px;">
            <strong style="color:#1a1a1a;">{vacancy_title}</strong><br>
            <span style="color:#666;">{company}</span>
        </div>
        <a href="{settings.frontend_url}/dashboard/applications"
           style="display:inline-block;background:#a3e635;color:#1a1a1a;
                  padding:12px 24px;border-radius:8px;text-decoration:none;
                  font-weight:600;">
            Все отклики →
        </a>
    </div>
    """
    return await _send(to, f"Отклик отправлен: {vacancy_title} — {company}", html)
