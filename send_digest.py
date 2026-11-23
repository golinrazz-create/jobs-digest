import email
import imaplib
import json
import os
import re
import smtplib
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from datetime import datetime, timedelta, timezone
from email.header import decode_header
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent
DEFAULT_CONFIG_PATH = BASE_DIR / "config.env"
DEFAULT_STATE_PATH = BASE_DIR / "data" / "pipeline_state.json"

TG_HIGH_CHANNELS = [
    "@dddwork",
    "@normrabota",
    "@dnative_job",
    "@vdhl_good",
    "@zdemcv",
    "@morejobs",
    "@perezvonyu",
    "@digital_jobster",
    "@work_editor",
    "@textodromo",
    "@mediajobs_ru",
    "@marketing_jobs",
    "@forchiefs",
    "@self_ma",
    "@Work4writers",
    "@careerspace",
    "@digital_hr",
    "@jobpower",
    "@copywriter_vacancies",
    "@runello_rus_contentmanagement",
    "@norm_work",
    "@textmoney",
    "@journalist_jobs",
    "@media_jobs",
    "@communication_department",
    "@nikolas_page",
    "@workspace"
]
TG_MED_CHANNELS = [
    "@evacuatejobs",
    "@jobkz_1",
    "@careersber",
    "@tbank_team",
    "@alfadigital_jobs",
    "@foranalysts",
    "@sci_career",
    "@edujobs",
    "@motionhunter",
    "@theyseeku",
    "@budujobs",
    "@it_vakansii_jobs",
    "@work_finde",
    "@yojob",
    "@vacancysmm",
    "@normremote",
    "@goodpeople_pro"
]
WORKSPACE_RSS_URL = "http://feeds.feedburner.com/workspacevacancies"

NOISE_TITLE_PATTERNS = [
    r"\bстаж[её]р\b",
    r"\bintern\b",
    r"\bпродавец[- ]консультант\b",
    r"\bавитолог\b",
    r"\bхостес\b",
    r"\bтатуировщик\b",
    r"\bпарикмахер\b",
    r"\bколорист\b",
    r"\bмерчандайзер\b",
    r"\bофис[- ]менеджер\b",
    r"\bассистент руководителя\b",
    r"\bличный помощник\b",
    r"\bбизнес[- ]ассистент\b",
    r"\bтаможенный декларант\b",
    r"\bтендерный специалист\b",
    r"\bюрист\b",
    r"\bврач\b",
    r"\bучитель\b",
    r"\bинженер[- ]конструктор\b",
    r"\bинженер\b",
    r"\bмедиабайер\b",
    r"\bавтор студенческих работ\b",
    r"\bбухгалтер\b",
    r"\bхореограф\b",
    r"\bмедицинский эксперт\b",
    r"\bсистемный аналитик\b",
    r"\bадминистратор центра\b",
    r"\bстрахования\b",
    r"\bмонетизации сегментов\b",
    r"\bстример\b",
]

STRONG_ROLE_PATTERNS = [
    r"главн\w* редактор",
    r"шеф[- ]редактор",
    r"директор по контенту",
    r"контент[- ]директор",
    r"head of content",
    r"chief content officer",
    r"руководитель контент",
    r"продюсер контент",
    r"куратор контент",
    r"редактор",
    r"журналист",
    r"автор текстов",
    r"копирайтер",
    r"медиааналитик",
    r"аналитик",
]

MEDIA_CONTEXT_PATTERNS = [
    r"сми",
    r"медиа",
    r"редакц",
    r"контент",
    r"журналист",
    r"бренд[- ]медиа",
    r"стать",
    r"лонгрид",
    r"новост",
    r"текст",
    r"ии",
    r"ai",
    r"нейросет",
]


def load_env_file(env_path: str | Path = DEFAULT_CONFIG_PATH) -> Path:
    """Загружает переменные из config.env в os.environ без сторонних зависимостей."""
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


def _decode_mime_words(raw_val: str | None) -> str:
    if not raw_val:
        return ""
    parts = []
    for chunk, charset in decode_header(raw_val):
        if isinstance(chunk, bytes):
            parts.append(chunk.decode(charset or "utf-8", errors="replace"))
        else:
            parts.append(str(chunk))
    return "".join(parts).strip()


def _extract_email_text(msg: email.message.Message) -> str:
    texts: list[str] = []
    if msg.is_multipart():
        for part in msg.walk():
            ctype = part.get_content_type()
            disp = str(part.get("Content-Disposition", ""))
            if "attachment" in disp.lower():
                continue
            if ctype in ("text/plain", "text/html"):
                payload = part.get_payload(decode=True)
                if payload:
                    charset = part.get_content_charset() or "utf-8"
                    txt = payload.decode(charset, errors="replace")
                    if ctype == "text/html":
                        txt = re.sub(r"<[^>]+>", " ", txt)
                    texts.append(txt)
    else:
        payload = msg.get_payload(decode=True)
        if payload:
            charset = msg.get_content_charset() or "utf-8"
            txt = payload.decode(charset, errors="replace")
            if msg.get_content_type() == "text/html":
                txt = re.sub(r"<[^>]+>", " ", txt)
            texts.append(txt)
    joined = "\n".join(texts)
    return re.sub(r"[ \t]+", " ", joined)


def fetch_gmail_vacancies_12h(
    gmail_user: str,
    gmail_app_password: str,
    label_name: str = "Jobs_Digest",
    hours_window: int = 12,
) -> list[dict]:
    """Читает свежие письма с вакансиями из Gmail по IMAP за последние hours_window часов."""
    if not gmail_user or not gmail_app_password:
        return []

    imap_since_date = (datetime.now(timezone.utc) - timedelta(days=2)).strftime("%d-%b-%Y")
    clean_pass = gmail_app_password.replace(" ", "")
    items: list[dict] = []

    try:
        mail = imaplib.IMAP4_SSL("imap.gmail.com", 993, timeout=25)
        mail.login(gmail_user, clean_pass)

        folders_to_try = []
        if label_name:
            folders_to_try.append(f'"{label_name}"')
        folders_to_try.extend(["INBOX", '"[Gmail]/All Mail"', '"[Gmail]/Почта"'])

        msg_ids: list[bytes] = []
        for folder in folders_to_try:
            typ, _ = mail.select(folder, readonly=True)
            if typ != "OK":
                continue
            search_crit = f'(SINCE "{imap_since_date}")'
            typ, data = mail.search(None, search_crit)
            if typ == "OK" and data and data[0]:
                msg_ids = data[0].split()
                break

        for num in msg_ids[-40:]:
            typ, msg_data = mail.fetch(num, "(RFC822)")
            if typ != "OK" or not msg_data or not msg_data[0]:
                continue
            raw_bytes = msg_data[0][1]
            if not isinstance(raw_bytes, bytes):
                continue
            msg = email.message_from_bytes(raw_bytes)
            subject = _decode_mime_words(msg.get("Subject"))
            sender = _decode_mime_words(msg.get("From")).lower()

            if "резюме просмотрели" in subject.lower() or "linkedin" in sender:
                continue

            body_text = _extract_email_text(msg)
            urls = re.findall(r"https?://[^\s<>)']+", body_text)
            vacancy_urls = [
                u for u in urls
                if ("hh.ru/vacancy/" in u or "superjob.ru/vacancy/" in u or "/ml/r/" in u)
            ]

            hh_matches = re.findall(r"(https?://hh\.ru/vacancy/\d+[^\s<>)']*)", body_text)
            seen_in_mail = set()
            for vurl in (hh_matches or vacancy_urls[:8]):
                clean_url = vurl.split("?")[0].strip()
                if clean_url in seen_in_mail:
                    continue
                seen_in_mail.add(clean_url)
                vid_match = re.search(r"/vacancy/(\d+)", clean_url)
                vid_label = f"hh.ru #{vid_match.group(1)}" if vid_match else "Рассылка"
                items.append(
                    {
                        "title": f"{subject} ({vid_label})" if subject else vid_label,
                        "source": f"Gmail ({sender[:35]})",
                        "url": clean_url,
                        "summary": f"Найдено в рассылке «{subject}» за окно {hours_window} ч.",
                        "raw_text": f"{subject}\n{body_text[:1500]}",
                        "published_at": datetime.now(timezone.utc).isoformat(),
                    }
                )
        mail.logout()
    except Exception as exc:
        print(f"[warn] IMAP сбор не выполнен: {exc}")

    return items


def fetch_workspace_rss_12h(rss_url: str = WORKSPACE_RSS_URL, hours_window: int = 12) -> list[dict]:
    """Забирает свежие вакансии из RSS-ленты Workspace.ru."""
    items: list[dict] = []
    try:
        req = urllib.request.Request(rss_url, headers={"User-Agent": "Mozilla/5.0 JobsDigest/1.0"})
        with urllib.request.urlopen(req, timeout=20) as resp:
            xml_bytes = resp.read()
        root = ET.fromstring(xml_bytes)
        for entry in root.findall(".//item"):
            title = (entry.findtext("title") or "").strip()
            link = (entry.findtext("link") or "").strip()
            desc = re.sub(r"<[^>]+>", " ", (entry.findtext("description") or "")).strip()
            desc = re.sub(r"\s+", " ", desc)
            if title and link:
                items.append(
                    {
                        "title": title,
                        "source": "RSS Workspace.ru",
                        "url": link.split("?")[0].strip(),
                        "summary": desc[:320] if desc else "Вакансия из RSS-ленты Workspace.ru.",
                        "raw_text": f"{title}\n{desc}",
                        "published_at": datetime.now(timezone.utc).isoformat(),
                    }
                )
    except Exception as exc:
        print(f"[warn] RSS Workspace не загружен: {exc}")
    return items


def fetch_telegram_public_preview_12h(channels: list[str], hours_window: int = 12) -> list[dict]:
    """Собирает свежие публикации из публичных веб-превью (t.me/s/<channel>)."""
    items: list[dict] = []
    cutoff_utc = datetime.now(timezone.utc) - timedelta(hours=hours_window)

    for raw_ch in channels:
        ch = raw_ch.lstrip("@").strip()
        if not ch:
            continue
        url = f"https://t.me/s/{ch}"
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0 JobsDigest/1.0"})
            with urllib.request.urlopen(req, timeout=12) as resp:
                html = resp.read().decode("utf-8", errors="replace")

            msg_blocks = re.findall(r'<div class="tgme_widget_message_wrap[^"]*"[^>]*>(.*?)</div>\s*</div>\s*</div>', html, flags=re.S)
            if not msg_blocks:
                msg_blocks = re.findall(r'<div class="tgme_widget_message_text[^"]*"[^>]*>(.*?)</div>', html, flags=re.S)

            for blk in msg_blocks[-10:]:
                dt_match = re.search(r'datetime="([^"]+)"', blk)
                if dt_match:
                    try:
                        dt_val = datetime.fromisoformat(dt_match.group(1).replace("Z", "+00:00"))
                        if dt_val.tzinfo is None:
                            dt_val = dt_val.replace(tzinfo=timezone.utc)
                        if dt_val < cutoff_utc:
                            continue
                    except ValueError:
                        pass

                txt_match = re.search(r'<div class="tgme_widget_message_text[^"]*"[^>]*>(.*?)</div>', blk, flags=re.S)
                raw_html = txt_match.group(1) if txt_match else blk
                clean_txt = re.sub(r"<br\s*/?>", "\n", raw_html, flags=re.I)
                clean_txt = re.sub(r"<[^>]+>", " ", clean_txt)
                clean_txt = re.sub(r"[ \t]+", " ", clean_txt).strip()
                if not clean_txt:
                    continue

                first_line = next((ln.strip() for ln in clean_txt.splitlines() if ln.strip()), clean_txt[:90])
                post_link_m = re.search(rf"https?://t\.me/{re.escape(ch)}/\d+", blk)
                post_url = post_link_m.group(0) if post_link_m else f"https://t.me/{ch}"

                items.append(
                    {
                        "title": first_line[:110],
                        "source": f"Telegram @{ch}",
                        "url": post_url,
                        "summary": clean_txt[:300],
                        "raw_text": clean_txt,
                        "published_at": dt_match.group(1) if dt_match else datetime.now(timezone.utc).isoformat(),
                    }
                )
        except Exception:
            continue

    return items


def deduplicate_items(items: list[dict], seen_urls: set[str]) -> tuple[list[dict], set[str]]:
    """Удаляет дубликаты внутри запуска и уже отправленные ранее вакансии."""
    unique: list[dict] = []
    updated_seen = set(seen_urls)
    seen_keys_in_run: set[str] = set()

    for it in items:
        url = (it.get("url") or "").strip().lower()
        title_norm = re.sub(r"\s+", " ", (it.get("title") or "").strip().lower())
        key = url or title_norm
        if not key:
            continue
        if key in updated_seen or key in seen_keys_in_run:
            continue
        seen_keys_in_run.add(key)
        updated_seen.add(key)
        unique.append(it)

    return unique, updated_seen


def score_item_against_profile(item: dict) -> dict:
    """Оценивает вакансию по профилю редактора/медиаменеджера/контент-лида."""
    text_blob = f"{item.get('title', '')} {item.get('summary', '')} {item.get('raw_text', '')}".lower()
    title_low = (item.get("title") or "").lower()

    if any(re.search(pat, title_low, flags=re.I) for pat in NOISE_TITLE_PATTERNS):
        return {**item, "score": 2, "bucket": "skip", "flag_status": "stop_factor", "reasons": "Отсеяно по стоп-фактору роли/направления."}

    role_hits = sum(1 for pat in STRONG_ROLE_PATTERNS if re.search(pat, text_blob, flags=re.I))
    media_hits = sum(1 for pat in MEDIA_CONTEXT_PATTERNS if re.search(pat, text_blob, flags=re.I))

    score = 4 + min(role_hits * 2, 4) + min(media_hits, 2)
    if "санкт-петербург" in text_blob or "спб" in text_blob or "удален" in text_blob or "удалён" in text_blob or "remote" in text_blob:
        score = min(10, score + 1)

    has_other_city = any(c in text_blob for c in ["сочи", "краснодар", "екатеринбург", "новосибирск", "казань", "саратов", "орел", "орёл", "тамбов"])
    has_remote = any(r in text_blob for r in ["удален", "удалён", "remote", "дистанц"])
    has_spb = any(s in text_blob for s in ["санкт-петербург", "спб", "петербург"])

    if has_other_city and not has_remote and not has_spb:
        score = max(5, min(6, score))
        flag_status = "high_alert"
        reasons = "Указан другой город без явной отметки удалёнки — проверить формат работы."
    elif "москва" in text_blob and not has_remote and not has_spb:
        flag_status = "check_details"
        reasons = "Указана Москва — уточнить формат работы (удалёнка или очно) и условия."
    else:
        flag_status = "check_details"
        reasons = "Подходит по профилю; стоит уточнить детали задач и вилку оплаты."

    bucket = "skip"
    if score >= 8:
        bucket = "strong"
    elif score >= 5:
        bucket = "borderline"

    return {
        **item,
        "score": score,
        "bucket": bucket,
        "flag_status": flag_status,
        "reasons": reasons,
    }


def collect_and_score_12h(
    env_path: str | Path = DEFAULT_CONFIG_PATH,
    state_path: str | Path = DEFAULT_STATE_PATH,
    include_medium_tg: bool = True,
    hours_window: int = 12,
) -> tuple[list[dict], list[dict], dict]:
    """Собирает свежие вакансии из Gmail, RSS Workspace и Telegram за hours_window часов и оценивает их."""
    load_env_file(env_path)

    gmail_user = os.getenv("GMAIL_USER", "").strip()
    gmail_pass = os.getenv("GMAIL_APP_PASSWORD", "").strip()
    gmail_label = os.getenv("GMAIL_LABEL", "Jobs_Digest").strip()

    state_file = Path(state_path)
    if not state_file.is_absolute():
        state_file = BASE_DIR / state_file

    state: dict = {"seen_urls": []}
    if state_file.exists():
        try:
            state = json.loads(state_file.read_text(encoding="utf-8"))
        except Exception:
            state = {"seen_urls": []}

    seen_set = set(state.get("seen_urls") or [])

    tg_list = list(TG_HIGH_CHANNELS)
    if include_medium_tg:
        tg_list.extend(TG_MED_CHANNELS)

    raw_items: list[dict] = []
    raw_items.extend(fetch_gmail_vacancies_12h(gmail_user, gmail_pass, gmail_label, hours_window=hours_window))
    raw_items.extend(fetch_workspace_rss_12h(WORKSPACE_RSS_URL, hours_window=hours_window))
    raw_items.extend(fetch_telegram_public_preview_12h(tg_list, hours_window=hours_window))

    unique_items, updated_seen = deduplicate_items(raw_items, seen_set)

    strong_items: list[dict] = []
    borderline_items: list[dict] = []
    skipped_count = 0

    for raw_it in unique_items:
        scored = score_item_against_profile(raw_it)
        if scored["bucket"] == "strong":
            strong_items.append(scored)
        elif scored["bucket"] == "borderline":
            borderline_items.append(scored)
        else:
            skipped_count += 1

    state["seen_urls"] = list(updated_seen)[-1500:]
    state_file.parent.mkdir(parents=True, exist_ok=True)
    state_file.write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8")

    stats = {
        "raw_collected": len(raw_items),
        "unique_new": len(unique_items),
        "strong": len(strong_items),
        "borderline": len(borderline_items),
        "skipped": skipped_count,
    }
    return strong_items, borderline_items, stats


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
            summary = item.get("summary", "")
            reasons = item.get("reasons", "")

            text_lines.append(f"{idx}. {role} [{score}/10 | {flag}]")
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
            html_parts.append(
                f"<li><b>{link_html}</b> — оценка <b>{score}/10</b> ({flag})<br>"
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
    """Отправляет полный дайджест в Gmail и короткое уведомление в Telegram."""
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
    strong, borderline, stats = collect_and_score_12h(hours_window=12, include_medium_tg=True)
    print("Статистика сбора и отбора:", stats)
    res = deliver_digest(strong, borderline)
    print("Результат доставки:", res)
