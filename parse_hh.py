import email
from email.header import decode_header
from email.utils import parsedate_to_datetime
import hashlib
import html as html_lib
import imaplib
import json
import os
import re
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from html.parser import HTMLParser
from typing import Dict, List, Optional, Set, Tuple
from urllib.parse import parse_qsl, urlencode, urlparse, urlunparse

# ==============================================================================
# КОНФИГУРАЦИЯ И ПАТТЕРНЫ ФИЛЬТРАЦИИ МУСОРНЫХ ССЫЛОК
# ==============================================================================

USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/124.0.0.0 Safari/537.36"
)

WEB_HEADERS = {
    "User-Agent": USER_AGENT,
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "ru-RU,ru;q=0.9,en-US;q=0.8,en;q=0.7",
}

HH_API_HEADERS = {
    "User-Agent": "JobsDigestPipeline/1.0 (contact@like-a.ru)",
    "Accept": "application/json",
}

IGNORED_DOMAINS = (
    "vk.com",
    "t.me",
    "telegram.me",
    "youtube.com",
    "youtu.be",
    "ok.ru",
    "dzen.ru",
    "zen.yandex.ru",
    "instagram.com",
    "facebook.com",
    "twitter.com",
    "x.com",
    "linkedin.com",
    "play.google.com",
    "apps.apple.com",
    "appgallery.huawei.com",
    "rustore.ru",
    "yandex.ru",
    "google.com",
    "mail.ru",
    "fonts.googleapis.com",
    "w3.org",
)

IGNORED_URL_SUBSTRINGS = (
    "unsubscribe",
    "optout",
    "opt-out",
    "preferences",
    "settings",
    "notification",
    "subscriptions",
    "manage-alerts",
    "applicant/resumes",
    "applicant/negotiations",
    "applicant/settings",
    "login",
    "auth",
    "register",
    "signup",
    "privacy",
    "terms",
    "agreement",
    "help",
    "support",
    "feedback",
    "pixel",
    "open.gif",
    "track/open",
    "mailto:",
    "tel:",
    "javascript:",
)

IGNORED_ANCHOR_KEYWORDS = (
    "отписаться",
    "отписка",
    "настройки рассылки",
    "управление подпиской",
    "личные данные",
    "политика конфиденциальности",
    "пользовательское соглашение",
    "службу поддержки",
    "помощь",
    "войти",
    "личный кабинет",
    "мои резюме",
    "все вакансии",
    "смотреть все",
    "показать все",
    "перейти на сайт",
    "app store",
    "google play",
    "rustore",
)

TRACKING_QUERY_PARAMS = {
    "utm_source",
    "utm_medium",
    "utm_campaign",
    "utm_term",
    "utm_content",
    "utm_referrer",
    "yclid",
    "gclid",
    "fbclid",
    "from",
    "hhtmFrom",
    "hhtmFromLabel",
    "roistat",
    "erid",
}

NOISE_SECTION_MARKERS = (
    "похожие вакансии",
    "другие вакансии",
    "вам могут понравиться",
    "рекомендуем также",
    "смотрите также",
    "вакансии компании",
    "о компании в цифрах",
    "поделиться вакансией",
    "жалоба на вакансию",
    "пожаловаться на вакансию",
)


# ==============================================================================
# HTML-ПАРСЕРЫ НА СТАНДАРТНОЙ БИБЛИОТЕКЕ (БЕЗ ВНЕШНИХ ЗАВИСИМОСТЕЙ)
# ==============================================================================

class _AnchorExtractor(HTMLParser):
    """Извлекает пары (href, anchor_text) из HTML-письма."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.links: List[Tuple[str, str]] = []
        self._in_a = False
        self._current_href = ""
        self._text_chunks: List[str] = []
        self._img_alts: List[str] = []

    def handle_starttag(self, tag: str, attrs: List[Tuple[str, Optional[str]]]) -> None:
        tag_l = tag.lower()
        attr_map = {k.lower(): (v or "") for k, v in attrs}
        if tag_l == "a" and attr_map.get("href"):
            self._in_a = True
            self._current_href = attr_map["href"].strip()
            self._text_chunks = []
            self._img_alts = []
        elif self._in_a and tag_l == "img" and attr_map.get("alt"):
            self._img_alts.append(attr_map["alt"].strip())

    def handle_data(self, data: str) -> None:
        if self._in_a and data:
            self._text_chunks.append(data)

    def handle_endtag(self, tag: str) -> None:
        if tag.lower() == "a" and self._in_a:
            anchor = " ".join("".join(self._text_chunks).split()).strip()
            if not anchor and self._img_alts:
                anchor = " ".join(self._img_alts).strip()
            if self._current_href:
                self.links.append((self._current_href, anchor))
            self._in_a = False
            self._current_href = ""
            self._text_chunks = []
            self._img_alts = []


class _CleanPageParser(HTMLParser):
    """Извлекает заголовок (<h1> / og:title / <title>) и чистый текст страницы."""

    SKIP_TAGS = {"script", "style", "noscript", "svg", "iframe", "nav", "header", "footer", "aside", "form"}
    BLOCK_TAGS = {"p", "div", "br", "li", "h1", "h2", "h3", "h4", "h5", "h6", "tr", "section", "article"}
    NOISE_ATTR_RE = re.compile(
        r"(cookie|banner|popup|modal|subscribe|similar|related|recommend|sidebar|breadcrumb|share|social|auth|login)",
        re.IGNORECASE,
    )

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self._skip_depth = 0
        self._in_h1 = False
        self._in_title = False
        self.h1_parts: List[str] = []
        self.title_parts: List[str] = []
        self.og_title = ""
        self.text_parts: List[str] = []

    def handle_starttag(self, tag: str, attrs: List[Tuple[str, Optional[str]]]) -> None:
        tag_l = tag.lower()
        attr_map = {k.lower(): (v or "") for k, v in attrs}

        if tag_l == "meta":
            prop = attr_map.get("property", "").lower()
            name = attr_map.get("name", "").lower()
            if (prop == "og:title" or name == "og:title") and attr_map.get("content") and not self.og_title:
                self.og_title = attr_map["content"].strip()
            return

        if tag_l == "h1":
            self._in_h1 = True
        elif tag_l == "title":
            self._in_title = True

        if self._skip_depth > 0:
            self._skip_depth += 1
            return

        if tag_l in self.SKIP_TAGS:
            self._skip_depth = 1
            return

        if tag_l not in ("html", "body", "main", "article", "h1"):
            check_str = " ".join(
                [attr_map.get("id", ""), attr_map.get("class", ""), attr_map.get("data-qa", "")]
            ).strip()
            if check_str and self.NOISE_ATTR_RE.search(check_str):
                self._skip_depth = 1
                return

        if tag_l in self.BLOCK_TAGS:
            self.text_parts.append("\n")

    def handle_data(self, data: str) -> None:
        if not data:
            return
        if self._in_h1:
            self.h1_parts.append(data)
        if self._in_title:
            self.title_parts.append(data)
        if self._skip_depth == 0 and not self._in_title:
            self.text_parts.append(data)

    def handle_endtag(self, tag: str) -> None:
        tag_l = tag.lower()
        if tag_l == "h1":
            self._in_h1 = False
        elif tag_l == "title":
            self._in_title = False

        if self._skip_depth > 0:
            self._skip_depth -= 1
            return

        if tag_l in self.BLOCK_TAGS:
            self.text_parts.append("\n")


# ==============================================================================
# УТИЛИТЫ ОЧИСТКИ И НОРМАЛИЗАЦИИ
# ==============================================================================

def decode_mime_header(raw_value: Optional[str]) -> str:
    if not raw_value:
        return ""
    parts = decode_header(raw_value)
    decoded: List[str] = []
    for content, charset in parts:
        if isinstance(content, bytes):
            decoded.append(content.decode(charset or "utf-8", errors="replace"))
        else:
            decoded.append(str(content))
    return "".join(decoded).strip()


def build_email_tracking_id(msg: email.message.Message, raw_bytes: bytes) -> str:
    """Формирует стабильный ключ письма (Message-ID либо хэш заголовков/тела), чтобы не парсить повторно."""
    msg_id = (msg.get("Message-ID") or msg.get("Message-Id") or "").strip()
    if msg_id:
        return msg_id.lower()
    digest_src = "|".join(
        [
            (msg.get("Date") or "").strip(),
            (msg.get("From") or "").strip(),
            (msg.get("Subject") or "").strip(),
            str(len(raw_bytes)),
        ]
    )
    return "hash:" + hashlib.sha256(digest_src.encode("utf-8", errors="replace")).hexdigest()[:24]


def clean_url(url: str) -> str:
    """Убирает UTM-метки, якоря и лишние пробелы из URL."""
    url = html_lib.unescape(url or "").strip()
    if not url:
        return ""
    parsed = urlparse(url)
    if parsed.scheme not in ("http", "https") or not parsed.netloc:
        return ""
    filtered_query = [
        (k, v)
        for k, v in parse_qsl(parsed.query, keep_blank_values=True)
        if k not in TRACKING_QUERY_PARAMS and not k.startswith("utm_")
    ]
    cleaned = parsed._replace(
        query=urlencode(filtered_query, doseq=True),
        fragment="",
    )
    return urlunparse(cleaned)


def normalize_whitespace(text: str) -> str:
    text = html_lib.unescape(text or "")
    text = text.replace("\xa0", " ").replace("\u202f", " ").replace("\u200b", "")
    lines = [re.sub(r"[ \t]+", " ", line).strip() for line in text.splitlines()]
    result: List[str] = []
    empty_streak = 0
    for line in lines:
        if not line:
            empty_streak += 1
            if empty_streak <= 1:
                result.append("")
        else:
            empty_streak = 0
            result.append(line)
    return "\n".join(result).strip()


def strip_html_tags(raw_html: str) -> str:
    parser = _CleanPageParser()
    parser.feed(raw_html or "")
    return normalize_whitespace("".join(parser.text_parts))


def is_candidate_vacancy_url(url: str, anchor_text: str = "") -> bool:
    """Отсекает служебные ссылки, соцсети, отписки и главные страницы сайтов."""
    if not url:
        return False
    parsed = urlparse(url)
    host = parsed.netloc.lower()
    if host.startswith("www."):
        host = host[4:]

    for domain in IGNORED_DOMAINS:
        if host == domain or host.endswith("." + domain):
            return False

    lower_full = url.lower()
    for bad in IGNORED_URL_SUBSTRINGS:
        if bad in lower_full:
            return False

    if re.search(r"\.(png|jpg|jpeg|gif|svg|webp|ico|css|js|pdf|zip)(\?|$)", lower_full):
        return False

    if parsed.path in ("", "/") and not parsed.query:
        return False

    lower_anchor = (anchor_text or "").strip().lower()
    if lower_anchor:
        for kw in IGNORED_ANCHOR_KEYWORDS:
            if kw in lower_anchor:
                return False

    return True


def _http_get(url: str, headers: Dict[str, str], timeout: int = 18) -> Tuple[str, str, str]:
    """Выполняет HTTP GET с поддержкой редиректов. Возвращает (final_url, content_type, text)."""
    req = urllib.request.Request(url, headers=headers)
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        final_url = resp.geturl() or url
        content_type = resp.headers.get("Content-Type", "")
        raw_bytes = resp.read()
        charset = "utf-8"
        m = re.search(r"charset=([a-zA-Z0-9_-]+)", content_type, re.IGNORECASE)
        if m:
            charset = m.group(1)
        text = raw_bytes.decode(charset, errors="replace")
        return final_url, content_type, text


# ==============================================================================
# ИЗВЛЕЧЕНИЕ ССЫЛОК ИЗ ПИСЬМА
# ==============================================================================

def extract_links_from_email(msg: email.message.Message) -> List[Tuple[str, str]]:
    """
    Возвращает все релевантные пары (url, anchor_text) из письма (без лимита на количество),
    исключая отписки, соцсети, трекинг-пиксели и главные страницы.
    """
    html_parts: List[str] = []
    text_parts: List[str] = []

    if msg.is_multipart():
        for part in msg.walk():
            content_type = part.get_content_type()
            disp = str(part.get("Content-Disposition") or "")
            if "attachment" in disp.lower():
                continue
            payload = part.get_payload(decode=True)
            if not payload:
                continue
            charset = part.get_content_charset() or "utf-8"
            decoded = payload.decode(charset, errors="replace")
            if content_type == "text/html":
                html_parts.append(decoded)
            elif content_type == "text/plain":
                text_parts.append(decoded)
    else:
        payload = msg.get_payload(decode=True)
        if payload:
            charset = msg.get_content_charset() or "utf-8"
            decoded = payload.decode(charset, errors="replace")
            if msg.get_content_type() == "text/html":
                html_parts.append(decoded)
            else:
                text_parts.append(decoded)

    found: List[Tuple[str, str]] = []
    seen_keys: Set[str] = set()

    for raw_html in html_parts:
        extractor = _AnchorExtractor()
        extractor.feed(raw_html)
        for raw_href, anchor in extractor.links:
            if not is_candidate_vacancy_url(raw_href, anchor):
                continue
            dedup_key = clean_url(raw_href) or raw_href
            if dedup_key in seen_keys:
                continue
            seen_keys.add(dedup_key)
            found.append((raw_href, anchor))

    if not found:
        for raw_text in text_parts:
            for match in re.finditer(r"https?://[^\s<>\"\')\]]+", raw_text):
                raw_href = match.group(0).rstrip(".,;:!?")
                if not is_candidate_vacancy_url(raw_href, ""):
                    continue
                dedup_key = clean_url(raw_href) or raw_href
                if dedup_key in seen_keys:
                    continue
                seen_keys.add(dedup_key)
                found.append((raw_href, ""))

    return found


# ==============================================================================
# ПАРСИНГ СТРАНИЦЫ ВАКАНСИИ (HH.RU API/HTML + УНИВЕРСАЛЬНЫЙ ЭКСТРАКТОР)
# ==============================================================================

def extract_hh_vacancy_id(url: str) -> Optional[str]:
    parsed = urlparse(url)
    host = parsed.netloc.lower()
    if "hh.ru" not in host and "hh.kz" not in host:
        return None
    m = re.search(r"/vacancy/(\d+)", parsed.path)
    return m.group(1) if m else None


def format_hh_salary(salary_obj: Optional[dict]) -> str:
    if not salary_obj:
        return ""
    s_from = salary_obj.get("from")
    s_to = salary_obj.get("to")
    curr = salary_obj.get("currency") or ""
    gross = "до вычета налогов" if salary_obj.get("gross") else "на руки"
    if s_from and s_to:
        return f"от {s_from:,} до {s_to:,} {curr} ({gross})".replace(",", " ")
    if s_from:
        return f"от {s_from:,} {curr} ({gross})".replace(",", " ")
    if s_to:
        return f"до {s_to:,} {curr} ({gross})".replace(",", " ")
    return ""


def parse_hh_vacancy(vacancy_id: str) -> Optional[Dict[str, str]]:
    """Получает чистые данные вакансии с hh.ru через публичный API (с фолбэком на HTML)."""
    api_url = f"https://api.hh.ru/vacancies/{vacancy_id}"
    try:
        _, _, raw_json = _http_get(api_url, headers=HH_API_HEADERS, timeout=15)
        data = json.loads(raw_json)
        title = (data.get("name") or "").strip()
        employer = ((data.get("employer") or {}).get("name") or "").strip()
        area = ((data.get("area") or {}).get("name") or "").strip()
        schedule = ((data.get("schedule") or {}).get("name") or "").strip()
        experience = ((data.get("experience") or {}).get("name") or "").strip()
        employment = ((data.get("employment") or {}).get("name") or "").strip()
        salary = format_hh_salary(data.get("salary"))

        raw_desc = data.get("description") or ""
        desc_text = strip_html_tags(raw_desc)
        skills = [
            s.get("name", "").strip()
            for s in (data.get("key_skills") or [])
            if s.get("name")
        ]

        meta_lines = []
        if employer:
            meta_lines.append(f"Компания: {employer}")
        if salary:
            meta_lines.append(f"Зарплата: {salary}")
        if area:
            meta_lines.append(f"Город: {area}")
        if schedule or employment:
            meta_lines.append(f"Формат и занятость: {', '.join(filter(None, [schedule, employment]))}")
        if experience:
            meta_lines.append(f"Опыт: {experience}")
        if skills:
            meta_lines.append(f"Ключевые навыки: {', '.join(skills)}")

        full_body = "\n".join(meta_lines)
        if desc_text:
            full_body = f"{full_body}\n\n{desc_text}".strip()

        if full_body:
            return {
                "title": title,
                "company": employer,
                "salary": salary,
                "location": area,
                "schedule": schedule,
                "body": full_body,
            }
    except Exception:
        pass

    web_url = f"https://hh.ru/vacancy/{vacancy_id}"
    return parse_generic_vacancy_page(web_url)


def cut_noise_tail(text: str) -> str:
    """Обрезает хвост страницы после блоков 'Похожие вакансии', 'Другие вакансии' и т.п."""
    lines = text.splitlines()
    cut_idx = len(lines)
    for idx, line in enumerate(lines):
        low = line.strip().lower()
        if any(marker == low or low.startswith(marker + ":") for marker in NOISE_SECTION_MARKERS):
            if idx >= 8:
                cut_idx = idx
                break
    return "\n".join(lines[:cut_idx]).strip()


def parse_generic_vacancy_page(url: str, prefetched_html: Optional[str] = None) -> Optional[Dict[str, str]]:
    """
    Универсальный парсер для любых джоб-бордов и сайтов (Zarplata.ru, Habr Career,
    SuperJob, Getmatch, корпоративные страницы вакансий): удаляет меню, футер,
    сайдбары и оставляет только заголовок и содержание вакансии.
    """
    try:
        html_text = prefetched_html
        if html_text is None:
            _, content_type, html_text = _http_get(url, headers=WEB_HEADERS, timeout=18)
            ct_low = content_type.lower()
            if "text/html" not in ct_low and "application/xhtml" not in ct_low:
                return None

        parser = _CleanPageParser()
        parser.feed(html_text)

        title = (
            normalize_whitespace("".join(parser.h1_parts))
            or normalize_whitespace(parser.og_title)
            or normalize_whitespace("".join(parser.title_parts))
        )
        cleaned_text = cut_noise_tail(normalize_whitespace("".join(parser.text_parts)))

        if len(cleaned_text) > 12000:
            cleaned_text = cleaned_text[:12000].rsplit("\n", 1)[0].strip()

        if len(cleaned_text) < 120:
            return None

        return {
            "title": title,
            "company": "",
            "salary": "",
            "location": "",
            "schedule": "",
            "body": cleaned_text,
        }
    except Exception:
        return None


def fetch_and_clean_vacancy(
    raw_url: str,
    anchor_text: str,
    cache: Dict[str, Optional[dict]],
) -> Optional[Dict[str, str]]:
    """
    Переходит по ссылке из письма, разворачивает редиректы, определяет ресурс
    (hh.ru или внешний сайт), выкачивает и очищает текст вакансии.
    """
    try:
        final_url_raw, content_type, page_html = _http_get(raw_url, headers=WEB_HEADERS, timeout=18)
        final_url = clean_url(final_url_raw) or clean_url(raw_url) or raw_url
    except Exception:
        final_url = clean_url(raw_url) or raw_url
        content_type = ""
        page_html = None

    if not is_candidate_vacancy_url(final_url, anchor_text):
        return None

    hh_id = extract_hh_vacancy_id(final_url)
    canonical_url = f"https://hh.ru/vacancy/{hh_id}" if hh_id else final_url

    if canonical_url in cache:
        return cache[canonical_url]

    if hh_id:
        parsed = parse_hh_vacancy(hh_id)
    else:
        ct_low = content_type.lower()
        if page_html and ("text/html" in ct_low or "application/xhtml" in ct_low):
            parsed = parse_generic_vacancy_page(canonical_url, prefetched_html=page_html)
        else:
            parsed = parse_generic_vacancy_page(canonical_url)

    if not parsed:
        cache[canonical_url] = None
        return None

    final_title = parsed.get("title") or anchor_text or "Вакансия без заголовка"
    result = {
        "url": canonical_url,
        "title": final_title,
        "company": parsed.get("company", ""),
        "salary": parsed.get("salary", ""),
        "location": parsed.get("location", ""),
        "schedule": parsed.get("schedule", ""),
        "body": parsed.get("body", ""),
    }
    cache[canonical_url] = result
    return result


# ==============================================================================
# ЧТЕНИЕ ВСЕХ НЕРАСПАРСЕННЫХ ПИСЕМ ИЗ GMAIL ПО ЯРЛЫКУ Jobs_Digest
# ==============================================================================

def select_digest_mailbox(imap: imaplib.IMAP4_SSL, preferred_label: str = "Jobs_Digest") -> bool:
    """Выбирает ярлык Jobs_Digest / jobs_digest в Gmail IMAP независимо от регистра."""
    candidates: List[str] = []
    for lbl in (preferred_label, "Jobs_Digest", "jobs_digest"):
        if lbl and lbl not in candidates:
            candidates.append(lbl)
            candidates.append(f'"{lbl}"')

    for folder in candidates:
        status, _ = imap.select(folder, readonly=True)
        if status == "OK":
            return True
    return False


def fetch_labeled_emails_vacancies_12h(
    imap_user: str,
    imap_password: str,
    label_name: str = "Jobs_Digest",
    imap_host: str = "imap.gmail.com",
    window_hours: int = 12,
    seen_urls: Optional[Set[str]] = None,
    seen_email_ids: Optional[Set[str]] = None,
    processed_email_ids_out: Optional[Set[str]] = None,
) -> List[Dict[str, str]]:
    """
    Берёт из Gmail ВСЕ письма с ярлыком Jobs_Digest (label:jobs_digest), которые ещё
    не были распарсены в прошлых запусках (без жёсткого ограничения в 12 часов по дате
    письма), переходит по всем релевантным ссылкам, очищает текст вакансий и возвращает
    новые карточки. Параметр `window_hours` сохранён для обратной совместимости.
    """
    if not imap_user or not imap_password:
        return []

    clean_pass = imap_password.replace(" ", "")
    seen_u: Set[str] = {u.strip().lower() for u in (seen_urls or set()) if u and u.strip()}
    seen_emails: Set[str] = {e.strip().lower() for e in (seen_email_ids or set()) if e and e.strip()}
    now_utc = datetime.now(timezone.utc)

    results: List[Dict[str, str]] = []
    url_cache: Dict[str, Optional[dict]] = {}

    imap = imaplib.IMAP4_SSL(imap_host, 993, timeout=25)
    try:
        imap.login(imap_user, clean_pass)

        if select_digest_mailbox(imap, preferred_label=label_name):
            status, data = imap.search(None, "ALL")
        else:
            all_mail_opened = False
            for all_folder in ('"[Gmail]/All Mail"', '"[Gmail]/Вся почта"', '"[Gmail]/Почта"'):
                st_all, _ = imap.select(all_folder, readonly=True)
                if st_all == "OK":
                    all_mail_opened = True
                    break
            if not all_mail_opened:
                return []
            status, data = imap.search(None, "X-GM-RAW", '"label:jobs_digest"')

        if status != "OK" or not data or not data[0]:
            return []

        msg_ids = data[0].split()
        for msg_id in msg_ids:
            try:
                fetch_status, msg_data = imap.fetch(msg_id, "(RFC822)")
                if fetch_status != "OK" or not msg_data:
                    continue

                raw_bytes: Optional[bytes] = None
                for item in msg_data:
                    if isinstance(item, tuple) and len(item) >= 2 and isinstance(item[1], bytes):
                        raw_bytes = item[1]
                        break
                if not raw_bytes:
                    continue

                msg = email.message_from_bytes(raw_bytes)
                email_key = build_email_tracking_id(msg, raw_bytes).lower()

                # Пропускаем письма, которые уже были распарсены ранее
                if email_key in seen_emails:
                    continue

                subject = decode_mime_header(msg.get("Subject"))
                sender = decode_mime_header(msg.get("From"))

                # Отмечаем письмо как обработанное даже если в нём нет новых вакансий
                seen_emails.add(email_key)
                if processed_email_ids_out is not None:
                    if isinstance(processed_email_ids_out, set):
                        processed_email_ids_out.add(email_key)
                    elif isinstance(processed_email_ids_out, list):
                        if email_key not in processed_email_ids_out:
                            processed_email_ids_out.append(email_key)

                if "резюме просмотрели" in subject.lower():
                    continue

                msg_dt_utc = now_utc
                raw_date = msg.get("Date")
                if raw_date:
                    try:
                        parsed_dt = parsedate_to_datetime(raw_date)
                        if parsed_dt.tzinfo is None:
                            msg_dt_utc = parsed_dt.replace(tzinfo=timezone.utc)
                        else:
                            msg_dt_utc = parsed_dt.astimezone(timezone.utc)
                    except Exception:
                        pass

                candidate_links = extract_links_from_email(msg)
                for raw_url, anchor_text in candidate_links:
                    cleaned_pre = (clean_url(raw_url) or raw_url).strip().lower()
                    if cleaned_pre in seen_u:
                        continue

                    vacancy = fetch_and_clean_vacancy(
                        raw_url=raw_url,
                        anchor_text=anchor_text,
                        cache=url_cache,
                    )
                    if not vacancy:
                        continue

                    canon_url = (vacancy["url"] or "").strip()
                    canon_low = canon_url.lower()
                    if not canon_url or canon_low in seen_u:
                        continue
                    seen_u.add(canon_low)

                    body_text = vacancy["body"]
                    summary_snippet = re.sub(r"\s+", " ", body_text)[:280].strip()
                    sender_short = sender[:38] if sender else "Gmail"

                    results.append(
                        {
                            "title": vacancy["title"],
                            "source": f"Gmail [{label_name}] ({sender_short})",
                            "url": canon_url,
                            "summary": summary_snippet or f"Из письма «{subject}»",
                            "raw_text": f"{vacancy['title']}\n{body_text}",
                            "published_at": msg_dt_utc.isoformat(),
                            "company": vacancy.get("company", ""),
                            "salary": vacancy.get("salary", ""),
                            "location": vacancy.get("location", ""),
                        }
                    )
            except Exception as msg_exc:
                print(f"[warn] Пропущено письмо в {label_name}: {msg_exc}")
                continue
    finally:
        try:
            imap.logout()
        except Exception:
            pass

    return results


if __name__ == "__main__":
    user = os.getenv("GMAIL_USER", "").strip()
    pwd = os.getenv("GMAIL_APP_PASSWORD", "").strip()
    lbl = os.getenv("GMAIL_LABEL", "Jobs_Digest").strip()
    items = fetch_labeled_emails_vacancies_12h(user, pwd, label_name=lbl)
    print(f"Найдено и распарсено новых вакансий из label:{lbl}: {len(items)}")
    for idx, item in enumerate(items, 1):
        print(f"{idx}. {item['title']} — {item['url']} (символов: {len(item['raw_text'])})")
