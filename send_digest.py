import email
import html as html_lib
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

NON_VACANCY_TITLE_PATTERNS = [
    r"стать аналитиком данных всего за",
    r"выспался\. создал чат-бота",
    r"\b2-дневный интенсив\b",
    r"старт конкурса",
    r"открытом вебинаре",
    r"вебинар по менторству",
    r"онлайн-конференция",
    r"трендс 2027",
    r"встречаемся на ai appsec",
    r"список резюме",
    r"дайджест резюме",
    r"они уже здесь",
    r"разыскивается работодатель",
    r"всем привет! моё имя",
    r"неделя в цифрах",
    r"почти два месяца не писал сюда",
    r"а к ним в команду можно\?",
    r"кажется, у снега сегодня первый рабочий день",
    r"«я устал, я ухожу…»",
    r"5 слов, которые портят ваше резюме",
    r"быть представителем интереснее, чем кажется",
    r"пост альфа-банка",
    r"сегодня весь день гуляем по офису",
    r"пахать 5/2 за 80к в месяц",
    r"год слушала, что не справляюсь",
    r"пять красных флагов на собесе",
    r"аузан уходит из деканов",
    r"перешла из «фрутоняни» в группу компаний",
    r"завершил экспедиционные съемки",
    r"ai-first: от экспериментов к практике",
    r"можно ли заменить ментора нейросетью",
    r"какие филиалы сети стоит продвигать",
    r"40 ux-решений для приложения",
    r"как работает массовая рассылка",
    r"зачем брендам объединять мини-игры",
    r"чем измерять успех b2b-маркетинга",
    r"как настроить мониторинг сайта",
    r"за что платить блогеру",
    r"как проверить ит-подрядчика",
    r"как узнать, сколько продаж добавила реклама",
    r"ии, найди мне нормальный референс",
    r"какие навыки сегодня нужны специалистам",
    r"рнф провел вебинар",
    r"хочу поделиться интересной возможностью для тех, кто работает с 3d",
]

NON_VACANCY_EXACT_TITLES = [
    "вдхл - вакансии для хороших людей",
    "джобстер digital | маркетинг | вакансии и резюме",
    "digitalhr (диджиталлэйчар): работа | вакансии | рекрутинг | стартапы",
    "remocate: релокация, удалёнка, работа и вакансии",
    "jobkz: вакансии / работа в казахстане",
    "finder.work: работа и вакансии",
]

HARD_STOP_ROLE_PATTERNS = [
    r"\bhead of sales\b",
    r"\bsales director\b",
    r"\bsales manager\b",
    r"\bsdr manager\b",
    r"\bsales development\b",
    r"\bcloser\b",
    r"менеджер по продажам",
    r"руководитель отдела продаж",
    r"директор по продажам",
    r"коммерческий директор",
    r"агент по привлечению клиентов",
    r"специалист по продажам",
    r"аккаунт[- ]менеджер",
    r"\baccount manager\b",
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
    r"\bмедиабайер\b",
    r"\bавтор студенческих работ\b",
    r"\bбухгалтер\b",
    r"\bхореограф\b",
    r"\bстример\b",
    r"строительном проекте",
]

ROLE_TIER_1_PATTERNS = [
    r"head of content",
    r"chief content officer",
    r"директор по контенту",
    r"контент[- ]директор",
    r"главн\w* редактор",
    r"шеф[- ]редактор",
    r"глава контент[- ]завод",
    r"руководитель контент[- ]завод",
    r"продюсер контент[- ]завод",
    r"куратор контент[- ]завод",
    r"руководитель направлени\w* контент",
    r"руководитель отдел\w* контент",
    r"руководитель группы медиааналитик",
    r"заведующий редакцией",
]

ROLE_TIER_2_PATTERNS = [
    r"выпускающий редактор",
    r"редактор сми",
    r"редактор медиапроект",
    r"редактор новостей",
    r"редактор сайта",
    r"ai[- ]редактор",
    r"редактор[- ]копирайтер",
    r"автор лонгридов",
    r"обозреватель",
    r"журналист",
    r"медиааналитик",
    r"контент[- ]продюсер",
    r"продюсер блогеров",
    r"редактор",
]

ROLE_TIER_3_PATTERNS = [
    r"копирайтер",
    r"автор текстов",
    r"сценарист",
    r"контент[- ]менеджер",
    r"контент[- ]мейкер",
    r"контент[- ]креатор",
    r"контент[- ]маркетолог",
    r"pr[- ]и контент",
    r"smm",
    r"influence[- ]менеджер",
    r"обучени\w* нейросетей",
    r"ai[- ]тренер",
]

NON_CONTENT_LOW_ROLE_PATTERNS = [
    r"таргетолог",
    r"платному трафику",
    r"google ads",
    r"дизайнер",
    r"designer",
    r"видеограф",
    r"монтаж[её]р",
    r"vfx",
    r"переводчик",
    r"data scientist",
    r"product analyst",
    r"продуктовый аналитик",
    r"retention",
    r"support manager",
    r"координатор промокампаний",
    r"менеджер продукта",
    r"\bcio\b",
    r"экономист",
    r"директор службы доставки",
    r"клиентского сервиса",
    r"баинг[- ]менеджер",
]

PURE_MARKETING_PENALTY_PATTERNS = [
    r"контент[- ]маркетинг",
    r"контент[- ]маркетолог",
    r"продающ\w* текст",
    r"воронка\w* продаж",
    r"лидогенерац",
    r"перформанс",
    r"performance",
    r"наклейк\w* логотип",
    r"smm[- ]менеджер",
    r"smm[- ]специалист",
    r"smm для артиста",
    r"в smm-агентство",
]

DIGEST_POST_PATTERNS = [
    r"подборка вакансий",
    r"подборка:",
    r"лучшее за неделю",
    r"вакансии в мтс",
    r"подборка 01\.tech",
    r"подборка c-level",
    r"вакансии в продажах",
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


def _safe_decode_bytes(payload: bytes | str | None, charset: str | None = None) -> str:
    if payload is None:
        return ""
    if isinstance(payload, str):
        return payload
    enc = (charset or "utf-8").strip()
    if enc.lower() in ("unknown-8bit", "unknown8bit", "x-unknown", "default_charset"):
        enc = "latin-1"
    try:
        return payload.decode(enc, errors="replace")
    except LookupError:
        return payload.decode("latin-1", errors="replace")


def _decode_mime_words(raw_val: str | None) -> str:
    if not raw_val:
        return ""
    parts = []
    for chunk, charset in decode_header(raw_val):
        if isinstance(chunk, bytes):
            parts.append(_safe_decode_bytes(chunk, charset))
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
                    txt = _safe_decode_bytes(payload, part.get_content_charset())
                    if ctype == "text/html":
                        txt = re.sub(r"<[^>]+>", " ", txt)
                    texts.append(txt)
    else:
        payload = msg.get_payload(decode=True)
        if payload:
            txt = _safe_decode_bytes(payload, msg.get_content_charset())
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
            try:
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
                urls = re.findall(r"https?://[^\s<>)x27]+", body_text)
                vacancy_urls = [
                    u for u in urls
                    if ("hh.ru/vacancy/" in u or "superjob.ru/vacancy/" in u or "/ml/r/" in u)
                ]

                hh_matches = re.findall(r"(https?://hh\.ru/vacancy/\d+[^\s<>)x27]*)", body_text)
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
                            "raw_text": f"{subject}\n{body_text[:2500]}",
                            "published_at": datetime.now(timezone.utc).isoformat(),
                        }
                    )
            except Exception as msg_exc:
                print(f"[warn] Пропущено одно письмо при IMAP-разборе: {msg_exc}")
                continue
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
                        "summary": desc[:450] if desc else "Вакансия из RSS-ленты Workspace.ru.",
                        "raw_text": f"{title}\n{desc}",
                        "published_at": datetime.now(timezone.utc).isoformat(),
                    }
                )
    except Exception as exc:
        print(f"[warn] RSS Workspace не загружен: {exc}")
    return items


def fetch_telegram_public_preview_12h(channels: list[str], hours_window: int = 12) -> list[dict]:
    """Собирает свежие публикации из публичных веб-превью (t.me/s/<channel>) без ранней обрезки текста."""
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

            for blk in msg_blocks[-12:]:
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

                first_line = next((ln.strip() for ln in clean_txt.splitlines() if ln.strip()), clean_txt[:110])
                post_link_m = re.search(rf"https?://t\.me/{re.escape(ch)}/\d+", blk)
                post_url = post_link_m.group(0) if post_link_m else f"https://t.me/{ch}"

                items.append(
                    {
                        "title": first_line[:120],
                        "source": f"Telegram @{ch}",
                        "url": post_url,
                        "summary": clean_txt[:500],
                        "raw_text": clean_txt,
                        "published_at": dt_match.group(1) if dt_match else datetime.now(timezone.utc).isoformat(),
                    }
                )
        except Exception:
            continue

    return items


def is_non_vacancy(item: dict) -> tuple[bool, str]:
    """Отсекает статьи, рекламу, вебинары, резюме соискателей и шапки каналов до скоринга."""
    title_low = re.sub(r"\s+", " ", (item.get("title") or "").strip().lower())
    raw_low = (item.get("raw_text") or "").lower()

    if title_low in NON_VACANCY_EXACT_TITLES:
        return True, "Шапка/репост канала"

    for pat in NON_VACANCY_TITLE_PATTERNS:
        if re.search(pat, title_low, flags=re.I):
            return True, "Статья, реклама или анонс мероприятия"

    if re.search(r"\bищу работу\b|\bрезюме соискателя\b|\bмое портфолио\b", raw_low[:400], flags=re.I):
        return True, "Резюме соискателя, а не вакансия"

    return False, ""


def is_hard_stop_role(item: dict) -> tuple[bool, str]:
    """Полностью исключает продажи, коммерцию, торговцев (Head of Sales и т. п.) и бытовой шум."""
    title_low = (item.get("title") or "").lower()
    for pat in HARD_STOP_ROLE_PATTERNS:
        if re.search(pat, title_low, flags=re.I):
            return True, "Стоп-фактор роли: продажи/коммерция или непрофильная позиция"
    return False, ""


def _normalize_dedup_key(item: dict) -> str:
    title = (item.get("title") or "").lower()
    title = re.sub(r"https?://\S+", "", title)
    title = re.sub(r"\(hh\.ru #\d+\)", "", title)
    title = re.sub(r"[^a-zа-яё0-9\s]", " ", title)
    tokens = [w for w in title.split() if len(w) > 2][:7]
    return " ".join(tokens)


def deduplicate_items(items: list[dict], seen_urls: set[str]) -> tuple[list[dict], set[str], int]:
    """Удаляет дубликаты между запусками и склеивает кросспосты внутри одного окна."""
    unique: list[dict] = []
    updated_seen = set(seen_urls)
    by_norm_key: dict[str, dict] = {}
    merged_dups = 0

    for it in items:
        url = (it.get("url") or "").strip()
        url_low = url.lower()
        norm_key = _normalize_dedup_key(it)

        if url_low and url_low in updated_seen:
            continue

        if norm_key and norm_key in by_norm_key:
            primary = by_norm_key[norm_key]
            dup_list = primary.setdefault("duplicate_sources", [])
            src_label = it.get("source", "")
            if url and url != primary.get("url") and all(d.get("url") != url for d in dup_list):
                dup_list.append({"source": src_label, "url": url})
            if url_low:
                updated_seen.add(url_low)
            merged_dups += 1
            continue

        if url_low:
            updated_seen.add(url_low)
        if norm_key:
            by_norm_key[norm_key] = it
        unique.append(it)

    return unique, updated_seen, merged_dups


def score_item_100(item: dict) -> dict:
    """100-балльная модель оценки под резюме №1 и №2."""
    title_low = (item.get("title") or "").lower()
    text_blob = f"{item.get('title', '')} {item.get('summary', '')} {item.get('raw_text', '')}".lower()

    role_score = 4
    role_note = "роль слабо пересекается с редакцией и контентом"

    if any(re.search(p, title_low, flags=re.I) for p in ROLE_TIER_1_PATTERNS):
        role_score = 34
        role_note = "руководящая редакторская/контентная роль (Head of Content / главред / шеф-редактор / контент-завод)"
    elif any(re.search(p, title_low, flags=re.I) for p in ROLE_TIER_2_PATTERNS):
        role_score = 28
        role_note = "профильная редакторская/медийная или AI-редакционная роль"
    elif any(re.search(p, title_low, flags=re.I) for p in ROLE_TIER_3_PATTERNS):
        role_score = 22
        role_note = "смежная контентная/текстовая или медийная роль"
    elif any(re.search(p, title_low, flags=re.I) for p in NON_CONTENT_LOW_ROLE_PATTERNS):
        role_score = 4
        role_note = "непрофильная функция (таргет, дизайн, монтаж, перевод или ИТ/продукт)"
    elif any(re.search(p, text_blob[:500], flags=re.I) for p in ROLE_TIER_1_PATTERNS):
        role_score = 26
        role_note = "есть задачи управления контентом/редакцией"
    elif any(re.search(p, text_blob[:500], flags=re.I) for p in ROLE_TIER_2_PATTERNS):
        role_score = 20
        role_note = "есть редакторские или контентные задачи"

    is_marketing_heavy = any(re.search(p, text_blob, flags=re.I) for p in PURE_MARKETING_PENALTY_PATTERNS)
    if is_marketing_heavy and role_score > 14:
        role_score = max(14, role_score - 8)
        role_note += "; понижено из-за уклона в контент-маркетинг/воронки/SMM"

    if any(re.search(p, text_blob, flags=re.I) for p in [r"\bсми\b", r"бренд[- ]медиа", r"редакц", r"подкаст", r"youtube"]):
        role_score = min(40, role_score + 2)

    level_score = 7
    if any(re.search(p, text_blob, flags=re.I) for p in [r"head of", r"директор", r"главн\w* редактор", r"шеф[- ]редактор", r"руководитель", r"lead", r"тимлид", r"глава"]):
        level_score = 14
    elif any(re.search(p, text_blob, flags=re.I) for p in [r"senior", r"ведущий", r"продюсер", r"стратег"]):
        level_score = 10
    elif any(re.search(p, text_blob, flags=re.I) for p in [r"junior", r"младший", r"начинающ", r"опыт.*1[-–]3", r"без опыта"]):
        level_score = 3
    else:
        level_score = 6

    has_remote = any(re.search(p, text_blob, flags=re.I) for p in [r"удален", r"удалён", r"remote", r"дистанц", r"из любой точки"])
    has_spb = any(re.search(p, text_blob, flags=re.I) for p in [r"санкт-петербург", r"\bспб\b", r"петербург"])
    has_reloc = any(re.search(p, text_blob, flags=re.I) for p in [r"релокац", r"переезд", r"шанхай", r"цюрих", r"тель-авив", r"астана", r"алматы"])
    has_moscow_or_other_city = any(re.search(p, text_blob, flags=re.I) for p in [r"москв", r"казан", r"краснодар", r"екатеринбург", r"новосибирск", r"иннополис"])

    if has_remote or has_spb:
        location_score = 20
        loc_note = "удалённо или Санкт-Петербург"
    elif has_reloc:
        location_score = 2
        loc_note = "требуется переезд/другая страна (в резюме: не готов к переезду)"
    elif has_moscow_or_other_city:
        location_score = 6
        loc_note = "офис/гибрид в другом городе без явной удалёнки"
    else:
        location_score = 12
        loc_note = "локация и формат не указаны"

    skills_score = 4
    matched_skills = []
    skill_checks = [
        (r"\bseo\b|\bgeo\b", 3, "SEO/GEO"),
        (r"\bai\b|\bии\b|нейросет|chatgpt|llm", 3, "AI в редакции"),
        (r"дзен|\bvc\b|telegram|тг[- ]канал|tenchat", 3, "Дзен/VC/Telegram"),
        (r"видео|youtube|reels|shorts|tiktok|подкаст", 2, "видео/подкасты"),
        (r"метрик|google analytics|\bga\b|аналитик", 2, "аналитика"),
        (r"wordpress|tilda|\bcms\b", 2, "CMS"),
    ]
    for pat, pts, label in skill_checks:
        if re.search(pat, text_blob, flags=re.I):
            skills_score += pts
            matched_skills.append(label)

    if re.search(r"(стат\w*|копирайт\w*|текст\w*).{0,35}английск|на английском", text_blob, flags=re.I):
        skills_score = max(4, skills_score - 3)
        matched_skills.append("риск по английскому (у вас B2)")

    skills_score = min(15, skills_score)

    cond_score = 4
    cond_note = "оплата не указана (нейтральные 4/10)"

    usd_match = re.search(r"\$\s*(\d[\d\s]{2,5})", text_blob)
    rub_matches = [int(x.replace(" ", "")) for x in re.findall(r"(\d{2,3}[\s]?\d{3})\s*(?:₽|руб|р\.)", text_blob)]
    k_rub_matches = [int(x) * 1000 for x in re.findall(r"(\d{2,3})\s*к\b", text_blob)]
    all_rub = [v for v in (rub_matches + k_rub_matches) if 20000 <= v <= 2000000]

    if usd_match:
        usd_val = int(usd_match.group(1).replace(" ", ""))
        if usd_val >= 2000:
            cond_score = 9
            cond_note = f"от ${usd_val} (соответствует ориентиру 2 000 $)"
        else:
            cond_score = 6
            cond_note = f"${usd_val}"
    elif all_rub:
        max_rub = max(all_rub)
        if max_rub >= 250000:
            cond_score = 10
            cond_note = f"до {max_rub:,} ₽ (выше ориентира 2 000 $)".replace(",", " ")
        elif max_rub >= 170000:
            cond_score = 8
            cond_note = f"до {max_rub:,} ₽ (близко к 2 000 $)".replace(",", " ")
        elif max_rub >= 130000:
            cond_score = 6
            cond_note = f"до {max_rub:,} ₽ (нижняя граница ожиданий)".replace(",", " ")
        else:
            cond_score = 3
            cond_note = f"до {max_rub:,} ₽ (ниже ожиданий)".replace(",", " ")

    raw_total = role_score + level_score + location_score + skills_score + cond_score
    capped = False
    if role_score <= 6 and raw_total > 30:
        total_score = 30
        capped = True
    else:
        total_score = min(100, raw_total)

    is_digest_post = any(re.search(p, title_low, flags=re.I) for p in DIGEST_POST_PATTERNS)

    tier = "D"
    if total_score >= 70:
        tier = "A"
    elif total_score >= 55:
        tier = "B"
    elif total_score >= 40:
        tier = "C"

    breakdown = f"Роль {role_score}/40 · Уровень {level_score}/15 · Локация {location_score}/20 · Навыки {skills_score}/15 · Условия {cond_score}/10"
    if capped:
        breakdown += " · ограничено 30 (роль не по профилю)"

    skills_str = f" Навыки: {', '.join(matched_skills)}." if matched_skills else ""
    digest_note = " Пост-подборка: проверьте позиции внутри поста." if is_digest_post else ""
    explanation = f"{role_note.capitalize()}; {loc_note}; {cond_note}.{skills_str}{digest_note}"

    return {
        **item,
        "score": total_score,
        "tier": tier,
        "breakdown": breakdown,
        "explanation": explanation,
        "is_digest_post": is_digest_post,
    }


def collect_and_score_12h(
    env_path: str | Path = DEFAULT_CONFIG_PATH,
    state_path: str | Path = DEFAULT_STATE_PATH,
    include_medium_tg: bool = True,
    hours_window: int = 12,
) -> tuple[list[dict], list[dict], list[dict], dict]:
    """Собирает свежие вакансии, отсекает не-вакансии и продажи (Head of Sales и др.), оценивает по 100-балльной шкале."""
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

    unique_items, updated_seen, merged_dups = deduplicate_items(raw_items, seen_set)

    tier_a: list[dict] = []
    tier_b: list[dict] = []
    tier_c: list[dict] = []
    non_vacancies_count = 0
    hard_stopped_count = 0
    low_score_count = 0

    for raw_it in unique_items:
        non_vac, _ = is_non_vacancy(raw_it)
        if non_vac:
            non_vacancies_count += 1
            continue

        hard_stop, _ = is_hard_stop_role(raw_it)
        if hard_stop:
            hard_stopped_count += 1
            continue

        scored = score_item_100(raw_it)
        if scored["tier"] == "A":
            tier_a.append(scored)
        elif scored["tier"] == "B":
            tier_b.append(scored)
        elif scored["tier"] == "C":
            tier_c.append(scored)
        else:
            low_score_count += 1

    tier_a.sort(key=lambda x: x.get("score", 0), reverse=True)
    tier_b.sort(key=lambda x: x.get("score", 0), reverse=True)
    tier_c.sort(key=lambda x: x.get("score", 0), reverse=True)

    state["seen_urls"] = list(updated_seen)[-1500:]
    state_file.parent.mkdir(parents=True, exist_ok=True)
    state_file.write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8")

    stats = {
        "raw_collected": len(raw_items),
        "merged_duplicates": merged_dups,
        "non_vacancies_excluded": non_vacancies_count,
        "hard_stopped_sales_etc": hard_stopped_count,
        "tier_A_70_100": len(tier_a),
        "tier_B_55_69": len(tier_b),
        "tier_C_40_54": len(tier_c),
        "tier_D_under_40_hidden": low_score_count,
    }
    return tier_a, tier_b, tier_c, stats


def format_digest_html_and_text(
    tier_a: list[dict],
    tier_b: list[dict],
    tier_c: list[dict],
    stats: dict,
    window_label: str,
) -> tuple[str, str]:
    """Формирует текстовую и аккуратную HTML-версию письма для Gmail с карточками и бейджами."""
    text_lines = [
        f"Дайджест вакансий ({window_label})",
        "=" * 44,
        f"A (70–100): {len(tier_a)} | B (55–69): {len(tier_b)} | C (40–54): {len(tier_c)}",
        (
            f"Отсеяно: не-вакансий — {stats.get('non_vacancies_excluded', 0)}, "
            f"продажи/стоп-факторы — {stats.get('hard_stopped_sales_etc', 0)}, "
            f"не по профилю (<40) — {stats.get('tier_D_under_40_hidden', 0)}, "
            f"дублей склеено — {stats.get('merged_duplicates', 0)}"
        ),
        "",
    ]

    font_stack = "-apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, Arial, sans-serif"

    html_parts = [
        "<!DOCTYPE html>",
        "<html lang='ru'>",
        "<head><meta charset='UTF-8'><meta name='viewport' content='width=device-width, initial-scale=1.0'></head>",
        f"<body style=\"margin:0; padding:0; background-color:#f4f5f7; font-family:{font_stack}; color:#1f2328; -webkit-font-smoothing:antialiased;\">",
        "<table role='presentation' width='100%' cellpadding='0' cellspacing='0' border='0' style='background-color:#f4f5f7; padding:20px 12px;'>",
        "<tr><td align='center'>",
        "<table role='presentation' width='100%' cellpadding='0' cellspacing='0' border='0' style='max-width:680px; background-color:#ffffff; border-radius:12px; border:1px solid #e1e4e8; overflow:hidden;'>",
        "<tr><td style='background-color:#111827; padding:24px 28px; color:#ffffff;'>",
        "<div style='font-size:12px; text-transform:uppercase; letter-spacing:0.08em; color:#9ca3af; margin-bottom:6px;'>Автоматический отбор · 12 часов</div>",
        "<div style='font-size:22px; font-weight:700; line-height:1.3; margin-bottom:6px;'>Дайджест вакансий</div>",
        f"<div style='font-size:13px; color:#d1d5db;'>Выпуск от {html_lib.escape(window_label)}</div>",
        "</td></tr>",
        "<tr><td style='padding:20px 28px 8px 28px;'>",
        "<table role='presentation' width='100%' cellpadding='0' cellspacing='0' border='0' style='background-color:#f8fafc; border:1px solid #e2e8f0; border-radius:8px;'>",
        "<tr>",
        f"<td width='33%' style='padding:12px 14px; border-right:1px solid #e2e8f0; text-align:center;'>"
        f"<div style='font-size:20px; font-weight:700; color:#15803d;'>{len(tier_a)}</div>"
        f"<div style='font-size:12px; color:#475569; margin-top:2px;'>A · Идеально (70–100)</div></td>",
        f"<td width='33%' style='padding:12px 14px; border-right:1px solid #e2e8f0; text-align:center;'>"
        f"<div style='font-size:20px; font-weight:700; color:#1d4ed8;'>{len(tier_b)}</div>"
        f"<div style='font-size:12px; color:#475569; margin-top:2px;'>B · Хорошо (55–69)</div></td>",
        f"<td width='34%' style='padding:12px 14px; text-align:center;'>"
        f"<div style='font-size:20px; font-weight:700; color:#b45309;'>{len(tier_c)}</div>"
        f"<div style='font-size:12px; color:#475569; margin-top:2px;'>C · С оговорками (40–54)</div></td>",
        "</tr></table>",
        f"<div style='font-size:12px; color:#64748b; line-height:1.5; margin-top:10px;'>"
        f"Отсеяно фильтром: не-вакансий — <b>{stats.get('non_vacancies_excluded', 0)}</b>, "
        f"продажи и стоп-факторы — <b>{stats.get('hard_stopped_sales_etc', 0)}</b>, "
        f"не по профилю (&lt;40) — <b>{stats.get('tier_D_under_40_hidden', 0)}</b>, "
        f"дублей склеено — <b>{stats.get('merged_duplicates', 0)}</b>."
        f"</div>",
        "</td></tr>",
    ]

    counter = [0]

    def _add_section(title: str, subtitle: str, items: list[dict], accent_color: str, badge_bg: str, badge_fg: str) -> None:
        text_lines.append(title)
        text_lines.append("-" * 36)

        html_parts.append("<tr><td style='padding:20px 28px 6px 28px;'>")
        html_parts.append(
            f"<div style='border-left:4px solid {accent_color}; padding-left:12px; margin-bottom:14px;'>"
            f"<div style='font-size:17px; font-weight:700; color:#111827;'>{html_lib.escape(title)}</div>"
            f"<div style='font-size:12px; color:#6b7280; margin-top:2px;'>{html_lib.escape(subtitle)}</div>"
            f"</div>"
        )

        if not items:
            text_lines.append("Нет новых позиций в этом окне.\n")
            html_parts.append(
                "<div style='padding:12px 14px; background-color:#f9fafb; border:1px dashed #d1d5db; border-radius:8px; font-size:13px; color:#6b7280;'>"
                "Нет новых позиций в этом окне."
                "</div>"
            )
            html_parts.append("</td></tr>")
            return

        for item in items:
            counter[0] += 1
            num = counter[0]
            role = item.get("title", "Без названия")
            source = item.get("source", "")
            url = item.get("url", "")
            score = item.get("score", 0)
            breakdown = item.get("breakdown", "")
            explanation = item.get("explanation", "")
            dups = item.get("duplicate_sources") or []

            text_lines.append(f"{num}. {role} — {score}/100")
            text_lines.append(f"   {breakdown}")
            text_lines.append(f"   Источник: {source}")
            text_lines.append(f"   {explanation}")
            if url:
                text_lines.append(f"   Ссылка: {url}")
            if dups:
                dup_str = ", ".join(f"{d.get('source')} ({d.get('url')})" for d in dups)
                text_lines.append(f"   Дубль в других каналах: {dup_str}")
            text_lines.append("")

            safe_role = html_lib.escape(role)
            safe_source = html_lib.escape(source)
            safe_breakdown = html_lib.escape(breakdown)
            safe_explanation = html_lib.escape(explanation)
            safe_url = html_lib.escape(url, quote=True)

            title_block = (
                f"<a href='{safe_url}' style='color:#111827; text-decoration:none; border-bottom:1px solid #cbd5e1;'>{safe_role}</a>"
                if url else safe_role
            )

            dup_html = ""
            if dups:
                dup_links = ", ".join(
                    f"<a href='{html_lib.escape(d.get('url', ''), quote=True)}' style='color:#2563eb; text-decoration:none;'>{html_lib.escape(d.get('source', ''))}</a>"
                    for d in dups
                )
                dup_html = f"<div style='font-size:12px; color:#6b7280; margin-top:6px;'>Дубль в других каналах: {dup_links}</div>"

            cta_html = (
                f"<div style='margin-top:10px;'>"
                f"<a href='{safe_url}' style='display:inline-block; font-size:12px; font-weight:600; color:#2563eb; text-decoration:none;'>Открыть вакансию &rarr;</a>"
                f"</div>"
                if url else ""
            )

            html_parts.append(
                "<div style='border:1px solid #e5e7eb; border-radius:10px; padding:14px 16px; margin-bottom:12px; background-color:#ffffff;'>"
                "<table role='presentation' width='100%' cellpadding='0' cellspacing='0' border='0'>"
                "<tr>"
                f"<td valign='top' style='font-size:15px; font-weight:700; line-height:1.4; color:#111827; padding-right:10px;'>{num}. {title_block}</td>"
                f"<td valign='top' align='right' style='white-space:nowrap;'>"
                f"<span style='display:inline-block; background-color:{badge_bg}; color:{badge_fg}; font-size:12px; font-weight:700; padding:3px 9px; border-radius:999px;'>{score}/100</span>"
                f"</td>"
                "</tr></table>"
                f"<div style='font-size:12px; color:#4b5563; margin-top:6px;'>{safe_breakdown}</div>"
                f"<div style='font-size:12px; color:#6b7280; margin-top:3px;'>Источник: {safe_source}</div>"
                f"<div style='font-size:13.5px; line-height:1.5; color:#1f2937; margin-top:8px;'>{safe_explanation}</div>"
                f"{dup_html}"
                f"{cta_html}"
                "</div>"
            )

        html_parts.append("</td></tr>")

    _add_section(
        "A. Идеально и очень близко (70–100)",
        "Прямое совпадение по уровню, редакторской/контентной функции и условиям",
        tier_a,
        accent_color="#16a34a",
        badge_bg="#dcfce7",
        badge_fg="#166534",
    )
    _add_section(
        "B. Хорошо, стоит откликаться (55–69)",
        "Близкие по профилю и навыкам роли — имеет смысл посмотреть детали",
        tier_b,
        accent_color="#2563eb",
        badge_bg="#dbeafe",
        badge_fg="#1e40af",
    )
    _add_section(
        "C. С оговорками (40–54)",
        "Смежные позиции, ниже по уровню или с вопросами к формату/локации",
        tier_c,
        accent_color="#d97706",
        badge_bg="#fef3c7",
        badge_fg="#92400e",
    )

    html_parts.extend([
        "<tr><td style='padding:16px 28px 24px 28px; border-top:1px solid #f1f5f9; font-size:12px; color:#94a3b8; text-align:center;'>",
        "Дайджест сформирован автоматически по 100-балльной модели профиля · Позиции &lt;40 баллов и не-вакансии скрыты",
        "</td></tr>",
        "</table>",
        "</td></tr></table>",
        "</body></html>",
    ])

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
    tier_a: list[dict],
    tier_b: list[dict],
    tier_c: list[dict],
    stats: dict,
    state_path: str | Path = BASE_DIR / "data" / "delivery_state.json",
    env_path: str | Path = DEFAULT_CONFIG_PATH,
    notify_when_empty: bool = True,
) -> dict:
    """Отправляет дайджест A/B/C в Gmail и сводку в Telegram."""
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

    if not tier_a and not tier_b and not tier_c:
        if notify_when_empty and tg_token and tg_chat_id and state.get("last_empty_window") != window_id:
            send_telegram_notice(
                tg_token,
                tg_chat_id,
                f"Дайджест вакансий ({window_label}): за последние 12 ч новых позиций уровня A/B/C нет, письмо в Gmail не отправлялось.",
            )
            state["last_empty_window"] = window_id
            state_file.parent.mkdir(parents=True, exist_ok=True)
            state_file.write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8")
        return {"status": "empty", "window_id": window_id, "config_path": str(loaded_path)}

    subject = f"Дайджест вакансий (12 ч): A={len(tier_a)}, B={len(tier_b)}, C={len(tier_c)} — {now_utc.strftime('%d.%m')}"
    text_body, html_body = format_digest_html_and_text(tier_a, tier_b, tier_c, stats, window_label)

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
        top_source = tier_a[:3] or tier_b[:3] or tier_c[:3]
        top_titles = [f"• [{x.get('score')}/100] {x.get('title', 'Вакансия')}" for x in top_source]
        tg_msg = (
            f"Дайджест вакансий отправлен в Gmail ({gmail_user}).\n"
            f"A (70–100): {len(tier_a)} | B (55–69): {len(tier_b)} | C (40–54): {len(tier_c)}\n\n"
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
        "A": len(tier_a),
        "B": len(tier_b),
        "C": len(tier_c),
    }


if __name__ == "__main__":
    a_items, b_items, c_items, stats = collect_and_score_12h(hours_window=12, include_medium_tg=True)
    print("Статистика сбора и отбора:", stats)
    res = deliver_digest(a_items, b_items, c_items, stats)
    print("Результат доставки:", res)
