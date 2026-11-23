import json
import os
import smtplib
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent
DEFAULT_CONFIG_PATH = BASE_DIR / "config.env"


def load_env_file(env_path: str | Path = DEFAULT_CONFIG_PATH) -> Path:
    """Загружает переменные из файла config.env в os.environ без сторонних библиотек."""
    p = Path(env_path)
    if not p.is_absolute():
        p = BASE_DIR / p
    if not p.exists():
        raise FileNotFoundError(f"Не найден файл конфигурации: {p}")
    for raw_line in p.read_text(encoding="utf-8-sig").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        if key and key not in os.environ:
            os.environ[key] = value
    return p


def format_digest_html_and_text(strong_items: list[dict], borderline_items: list[dict], window_label: str) -> tuple[str, str]:
    """Формирует текстовую и HTML-версию письма для Gmail."""
    text_lines = [f"Дайджест вакансий ({window_label})", "=" * 40, ""]
    html_parts = [
        f"<h2>Дайджест вакансий ({window_label})</h2>",
        f"<p>Сильных совпадений: <b>{len(strong_items)}</b> | На заметку: <b>{len(borderline_items)}</b></p>",
    ]

    def _add_section(title: str, items: list[dict]) -> None:
        text_lines.append(title)
        text_lines.append("-" * 30)
        html_parts.append(f"<h3>{title}</h3>")
        if not items:
            text_lines.append("Нет новых позиций в этом окне.\n")
            html_parts.append("<p><i>Нет новых позиций в этом окне.</i></p>")
            return
        html_parts.append("<ul>")
        for idx, item in enumerate(items, 1):
            role = item.get("title", "Без названия")
            source = item.get("source", "")
            url = item.get("url", "")
            score = item.get("score", "—")
            flag = item.get("flag_status", "clean")
            country_note = item.get("country_tag", "")
            summary = item.get("summary", "")
            reasons = item.get("reasons", "")

            header = f"{idx}. {role} [{score}/10 | {flag}]"
            if country_note:
                header += f" ({country_note})"
            text_lines.append(header)
            if source:
                text_lines.append(f"   Источник: {source}")
            if summary:
                text_lines.append(f"   Суть: {summary}")
            if reasons:
                text_lines.append(f"   Детали/флаги: {reasons}")
            if url:
                text_lines.append(f"   Ссылка: {url}")
            text_lines.append("")

            link_html = f'<a href="{url}">{role}</a>' if url else role
            country_html = f" <b>[{country_note}]</b>" if country_note else ""
            html_parts.append(
                f"<li><b>{link_html}</b>{country_html} — оценка <b>{score}/10</b> ({flag})<br>"
                f"<small>Источник: {source}</small><br>"
                f"{summary}<br>"
                f"<i>{reasons}</i></li><br>"
            )
        html_parts.append("</ul>")

    _add_section("1. Сильное совпадение (8–10)", strong_items)
    _add_section("2. На заметку / спорные (5–7)", borderline_items)

    return "\n".join(text_lines), "\n".join(html_parts)


def send_gmail_digest(
    gmail_user: str,
    gmail_app_password: str,
    subject: str,
    text_body: str,
    html_body: str,
    recipient: str | None = None,
) -> None:
    """Отправляет письмо с дайджестом через SMTP Gmail."""
    to_addr = recipient or gmail_user
    clean_password = gmail_app_password.replace(" ", "")

    msg = MIMEMultipart("alternative")
    msg["Subject"] = subject
    msg["From"] = gmail_user
    msg["To"] = to_addr

    msg.attach(MIMEText(text_body, "plain", "utf-8"))
    msg.attach(MIMEText(html_body, "html", "utf-8"))

    with smtplib.SMTP_SSL("smtp.gmail.com", 465, timeout=20) as server:
        server.login(gmail_user, clean_password)
        server.sendmail(gmail_user, [to_addr], msg.as_string())


def send_telegram_notice(bot_token: str, chat_id: str, message: str) -> dict:
    """Отправляет короткое уведомление в Telegram через Bot API."""
    api_url = f"https://api.telegram.org/bot{bot_token}/sendMessage"
    payload = urllib.parse.urlencode(
        {
            "chat_id": chat_id,
            "text": message,
            "disable_web_page_preview": "true",
        }
    ).encode("utf-8")

    req = urllib.request.Request(api_url, data=payload, method="POST")
    with urllib.request.urlopen(req, timeout=15) as resp:
        return json.loads(resp.read().decode("utf-8"))


def deliver_digest(
    strong_items: list[dict],
    borderline_items: list[dict],
    state_path: str | Path = BASE_DIR / "data" / "delivery_state.json",
    env_path: str | Path = DEFAULT_CONFIG_PATH,
    notify_when_empty: bool = True,
) -> dict:
    """
    Отправляет полный дайджест в Gmail и короткое уведомление в Telegram.
    Защищено от повторной отправки одного и того же 12-часового окна.
    """
    loaded_path = load_env_file(env_path)

    gmail_user = os.getenv("GMAIL_USER", "").strip()
    gmail_pass = os.getenv("GMAIL_APP_PASSWORD", "").strip()
    tg_token = os.getenv("TG_BOT_TOKEN", "").strip()
    tg_chat_id = os.getenv("TG_CHAT_ID", "").strip()

    now_utc = datetime.now(timezone.utc)
    slot_hour = "00" if now_utc.hour < 12 else "12"
    window_id = f"{now_utc.strftime('%Y-%m-%d')}_{slot_hour}h"
    window_label = now_utc.strftime("%d.%m.%Y %H:%M UTC")

    state_file = Path(state_path)
    if not state_file.is_absolute():
        state_file = BASE_DIR / state_file
    state: dict = {}
    if state_file.exists():
        state = json.loads(state_file.read_text(encoding="utf-8"))

    if not strong_items and not borderline_items:
        if notify_when_empty and tg_token and tg_chat_id and state.get("last_empty_window") != window_id:
            send_telegram_notice(
                tg_token,
                tg_chat_id,
                f"Дайджест вакансий ({window_label}): за последние 12 ч новых релевантных вакансий нет, письмо в Gmail не отправлялось.",
            )
            state["last_empty_window"] = window_id
            state_file.parent.mkdir(parents=True, exist_ok=True)
            state_file.write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8")
        return {"status": "empty", "window_id": window_id, "config_path": str(loaded_path)}

    subject = f"Дайджест вакансий (12 ч): {len(strong_items)} сильных, {len(borderline_items)} на заметку — {now_utc.strftime('%d.%m')}"
    text_body, html_body = format_digest_html_and_text(strong_items, borderline_items, window_label)

    if state.get("last_emailed_window") != window_id:
        if not gmail_user or not gmail_pass:
            raise RuntimeError(f"Не заданы GMAIL_USER или GMAIL_APP_PASSWORD в {loaded_path}")
        send_gmail_digest(gmail_user, gmail_pass, subject, text_body, html_body)
        state["last_emailed_window"] = window_id
        state_file.parent.mkdir(parents=True, exist_ok=True)
        state_file.write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8")

    if state.get("last_notified_window") != window_id:
        if not tg_token or not tg_chat_id:
            raise RuntimeError(f"Не заданы TG_BOT_TOKEN или TG_CHAT_ID в {loaded_path}")
        top_titles = [f"• {x.get('title', 'Вакансия')}" for x in (strong_items[:3] or borderline_items[:3])]
        tg_msg = (
            f"Дайджест вакансий отправлен в Gmail ({gmail_user}).\n"
            f"Сильных: {len(strong_items)} | На заметку: {len(borderline_items)}\n\n"
            + "\n".join(top_titles)
        )
        send_telegram_notice(tg_token, tg_chat_id, tg_msg)
        state["last_notified_window"] = window_id
        state_file.parent.mkdir(parents=True, exist_ok=True)
        state_file.write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8")

    return {
        "status": "delivered",
        "window_id": window_id,
        "config_path": str(loaded_path),
        "strong": len(strong_items),
        "borderline": len(borderline_items),
    }


if __name__ == "__main__":
    sample_strong = [
        {
            "title": "Тестовая проверка доставки дайджеста",
            "source": "JobDigest Test",
            "url": "https://mail.google.com",
            "score": 10,
            "flag_status": "clean",
            "summary": "Если вы видите это письмо в Gmail и уведомление в Telegram — связка доставки настроена и работает.",
            "reasons": "Проверка SMTP Gmail и Telegram Bot API.",
        }
    ]
    res = deliver_digest(sample_strong, [], state_path="data/test_delivery_state.json")
    print("Результат тестовой отправки:", res)
