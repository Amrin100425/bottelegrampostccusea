# -*- coding: utf-8 -*-
"""
Telegram Job Posting Bot (Persistent Modern Contact Buttons + Optional Info/Photo)
======================================================================================
Bot សម្រាប់ជួយ Admin ទម្លាក់ព័ត៌មានការងារទៅកាន់ Telegram Channel
ដោយភ្ជាប់ Inline Buttons "Contact" (មាន Icon/ពណ៌ Emoji) ដោយស្វ័យប្រវត្តិ។

លក្ខណៈពិសេស:
    - Contact Buttons ត្រូវបានកំណត់ *តែម្តង* ហើយប្រើប្រាស់ជាប់រហូតគ្រប់ post
      (កែប្រែពេលក្រោយបានគ្រប់ពេល ដោយប្រើ /setcontact ម្តងទៀត)
    - ដាក់ច្រើនប៊ូតុងជាជួរដូចគ្នាបាន (រហូតដល់ 3 ក្នុងមួយជួរ) ដោយប្រើសញ្ញា |
    - អាចដាក់ Icon (Emoji) និង "ពណ៌" (តាមរយៈ style:color -> បំប្លែងទៅជារង្វង់ Emoji ពណ៌)
    - /setcontact ដំណើរការជាទម្រង់ interactive (សួរឱ្យវាយបញ្ជីប៊ូតុង និងអាច /cancel បាន)
      ការពារកុំឱ្យច្រឡំបញ្ជូនអត្ថបទប៊ូតុងទៅកាន់ Channel ពេលកំពុង edit មិនទាន់រួច។
    - គ្រប់ការបង្ហោះទាំងអស់ (មិនថាតាម /post, ឬ forward, ឬផ្ញើសារផ្ទាល់មក bot)
      សុទ្ធតែមាន Confirmation (✅ YES / ❌ NO) សិន មុននឹងបញ្ជូនទៅកាន់ Channel។
"""

import html
import io
import json
import logging
import os
import re
from datetime import datetime
from dotenv import load_dotenv
load_dotenv()
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    ApplicationBuilder,
    CallbackQueryHandler,
    CommandHandler,
    ConversationHandler,
    ContextTypes,
    MessageHandler,
    filters,
)
from tracker import (
    register_tracking_link,
    record_click,
    record_telegram_button_click,
    get_available_months,
    get_monthly_report_data,
    format_telegram_report,
    generate_csv_report,
    RedirectTrackerHandler,
    WebReportHandler,
    WebCsvExportHandler,
    WebClicksJsonHandler,
    load_click_data,
    save_click_data,
    merge_click_data,
)

# ------------------------------------------------------------------
# ការកំណត់រចនាសម្ព័ន្ធ (CONFIG)
# ------------------------------------------------------------------
BOT_TOKEN = os.getenv("BOT_TOKEN")
raw_channel = (os.getenv("CHANNEL_ID") or "-1001535612806").strip()
if raw_channel:
    try:
        CHANNEL_ID = int(raw_channel)
    except ValueError:
        CHANNEL_ID = raw_channel
else:
    CHANNEL_ID = -1001535612806

try:
    admin_env = os.getenv("ADMIN_IDS") or os.getenv("ADMIN_ID") or "[1147056937, 468517256, 1287745757, 8824663759]"
    ADMIN_IDS = json.loads(admin_env) if admin_env.startswith("[") else [int(x.strip()) for x in admin_env.split(",") if x.strip()]
except Exception:
    ADMIN_IDS = [1147056937, 468517256, 1287745757, 8824663759]
WEBHOOK_URL = (os.getenv("RENDER_EXTERNAL_URL") or os.getenv("WEBHOOK_URL") or "https://bottelegrampostccusea.onrender.com").rstrip("/")

# Contact ដែលថេរ (Fixed) - វានឹងបង្ហាញជានិច្ចនៅខាងក្រោម មិនបាត់បង់ទេ
# FIXED_CONTACT_ROWS = [
#     [{"label": "📞 Contact Us", "url": "https://t.me/USEACCAD"}],
# ]

DATA_DIR = os.getenv("DATA_DIR", "").strip()
_DEFAULT_CONTACT_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "contact.json")
if DATA_DIR and os.path.exists(DATA_DIR):
    CONTACT_STORE_FILE = os.path.join(DATA_DIR, "contact.json")
    if not os.path.exists(CONTACT_STORE_FILE) and os.path.exists(_DEFAULT_CONTACT_FILE):
        try:
            import shutil
            shutil.copy2(_DEFAULT_CONTACT_FILE, CONTACT_STORE_FILE)
            logger.info("Initialized persistent CONTACT_STORE_FILE at %s", CONTACT_STORE_FILE)
        except Exception as copy_e:
            logger.warning("Failed to initialize CONTACT_STORE_FILE in DATA_DIR: %s", copy_e)
else:
    CONTACT_STORE_FILE = _DEFAULT_CONTACT_FILE

# Telegram Native Solid Button Background Colors (Bot API 9.4+)
# Blue (primary), Red (danger), Green (success)
NATIVE_BUTTON_STYLES = {
    # Blue / ពណ៌ខៀវ
    "blue": "primary",
    "primary": "primary",
    "ខៀវ": "primary",

    # Red / ពណ៌ក្រហម
    "red": "danger",
    "danger": "danger",
    "ក្រហម": "danger",

    # Green / ពណ៌បៃតង
    "green": "success",
    "success": "success",
    "បៃតង": "success",
}

STYLE_EMOJI = {
    "yellow": "🟨",
    "gold": "🟨",
    "orange": "🟧",
    "purple": "🟪",
    "violet": "🟪",
    "brown": "🟫",
    "black": "⬛",
    "white": "⬜",
    "pink": "🩷",
    "rose": "🌸",
    "cyan": "🩵",
    "teal": "🩵",
    "gray": "🩶",
    "grey": "🩶",
    "លឿង": "🟨",
    "ទឹកក្រូច": "🟧",
    "ស្វាយ": "🟪",
    "ផ្កាឈូក": "🩷",
}

MAX_BUTTONS_PER_ROW = 3

TELEGRAM_CAPTION_LIMIT = 1024
TELEGRAM_MESSAGE_LIMIT = 4096

# ------------------------------------------------------------------
# Logging
# ------------------------------------------------------------------
logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO,
)
logger = logging.getLogger(__name__)

# ------------------------------------------------------------------
# States សម្រាប់ ConversationHandler
# ------------------------------------------------------------------
CONTENT, CONFIRM = range(2)
SETTING_CONTACT = 0


def is_admin(user_id: int) -> bool:
    return user_id in ADMIN_IDS


# ------------------------------------------------------------------
# Contact URL & Phone Helper
# ------------------------------------------------------------------
def format_phone_number(raw: str) -> str:
    """Format local Cambodian numbers (0xx) or international numbers with +country code."""
    raw = raw.strip()
    digits = "".join(ch for ch in raw if ch.isdigit())
    if not digits:
        return ""
    if digits.startswith("0"):
        return f"+855{digits[1:]}"
    elif digits.startswith("855"):
        return f"+{digits}"
    elif raw.startswith("+"):
        return f"+{digits}"
    return f"+{digits}"


def build_contact_url(raw: str) -> str:
    """បំប្លែង username ឬលេខទូរស័ព្ទ (Telegram/WhatsApp) ឬ Email ឬ Web URL ទៅជា Link ត្រឹមត្រូវសម្រាប់ប៊ូតុង"""
    raw = raw.strip()

    # 0. Email detection: mailto:, email:, mail:, or user@domain.com
    if raw.lower().startswith(("mailto:", "email:", "mail:")):
        email_part = raw.split(":", 1)[1].strip()
        return f"mailto:{email_part}"

    if "@" in raw and "." in raw and not raw.startswith("@") and "/" not in raw:
        return f"mailto:{raw}"

    # 1. WhatsApp prefix: wa:012345678 or whatsapp:012345678
    if raw.lower().startswith(("wa:", "whatsapp:")):
        num_part = raw.split(":", 1)[1].strip()
        phone = format_phone_number(num_part)
        clean = phone.lstrip("+")
        return f"https://wa.me/{clean}"

    # 2. Telegram prefix: tg:012345678 or telegram:012345678 or t.me:012345678
    if raw.lower().startswith(("tg:", "telegram:", "t.me:")):
        target = raw.split(":", 1)[1].strip()
        if target.startswith("@"):
            return f"https://t.me/{target[1:]}"
        phone = format_phone_number(target)
        return f"https://t.me/{phone}" if phone else f"https://t.me/{target}"

    # 3. Username with @
    if raw.startswith("@"):
        return f"https://t.me/{raw[1:]}"

    # 4. Standard HTTP/HTTPS link
    if raw.startswith(("https://", "http://")):
        return raw

    # 5. Tel: or Phone: prefix
    if raw.lower().startswith(("tel:", "phone:")):
        num_part = raw.split(":", 1)[1].strip()
        phone = format_phone_number(num_part)
        return f"https://t.me/{phone}"

    # 6. Raw phone number (digits >= 8, e.g. 012 345 678, 098765432, +85512345678)
    digits = "".join(ch for ch in raw if ch.isdigit())
    if digits and len(digits) >= 8:
        phone = format_phone_number(raw)
        return f"https://t.me/{phone}"

    # 7. Fallback to Telegram username
    return f"https://t.me/{raw}"


# ------------------------------------------------------------------
# Contact Storage (persistent) & Keyboard Builders
# ------------------------------------------------------------------
BOT_USERNAME = os.getenv("BOT_USERNAME", "USEACCBot")

# Default Telegram Premium Custom Animated Emoji IDs
DEFAULT_ADMIN_CONTACT_EMOJI = "5850292279503228917"
DEFAULT_ADMIN_APPLY_NOW_EMOJI = "5472239203590888751"
DEFAULT_ADMIN_CV_EMOJI = "5431420628978641216"

# Static button 1: Admin contact — never changes
STATIC_ADMIN_BUTTON_LABEL = "📲 Contact Admin"
STATIC_ADMIN_BUTTON_URL = "https://t.me/USEACCAD"

# Static button 3: Bot redirect — never changes
STATIC_BOT_BUTTON_LABEL = "Career Tips, CV & Cover Letter"
STATIC_BOT_BUTTON_URL = "https://t.me/USEACCASTbot"

DEFAULT_APPLY_CONTACTS = {
    "buttons": [],
    "employer": {
        "label": "Apply Now",
        "btn_style": "danger",
    },
    "email": {
        "label": "Apply via Email",
        "btn_style": "danger",
    },
    "admin": {
        "label": STATIC_ADMIN_BUTTON_LABEL,
        "url": STATIC_ADMIN_BUTTON_URL,
        "btn_style": "success",
    },
}

DEFAULT_FIXED_BUTTONS = []


def load_contact_data() -> dict:
    if os.path.exists(CONTACT_STORE_FILE):
        try:
            with open(CONTACT_STORE_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)
                if isinstance(data, dict):
                    if "apply_contacts" in data or "fixed_buttons" in data:
                        apply_contacts = data.get("apply_contacts")
                        if not isinstance(apply_contacts, dict):
                            apply_contacts = {}
                        if "buttons" not in apply_contacts:
                            btns = []
                            if apply_contacts.get("employer", {}).get("url"):
                                btns.append(apply_contacts["employer"])
                            if apply_contacts.get("email", {}).get("url"):
                                btns.append(apply_contacts["email"])
                            apply_contacts["buttons"] = btns
                        return {
                            "apply_contacts": apply_contacts,
                            "fixed_buttons": data.get("fixed_buttons", DEFAULT_FIXED_BUTTONS),
                        }
                    elif "rows" in data:
                        rows = data.get("rows", [])
                        flat = [b for r in rows for b in r]
                        emp = flat[1] if len(flat) > 1 else {}
                        adm = flat[0] if flat else DEFAULT_APPLY_CONTACTS["admin"]
                        return {
                            "apply_contacts": {
                                "buttons": [emp] if emp.get("url") else [],
                                "employer": emp,
                                "admin": adm,
                            },
                            "fixed_buttons": DEFAULT_FIXED_BUTTONS,
                        }
        except Exception as e:
            logger.warning("មិនអាចអាន contact.json បាន: %s", e)
    return {
        "apply_contacts": {
            "buttons": [],
            "employer": {},
            "email": {},
            "admin": DEFAULT_APPLY_CONTACTS.get("admin", {}),
        },
        "fixed_buttons": DEFAULT_FIXED_BUTTONS,
    }


def save_contact_data(apply_contacts: dict, fixed_buttons: list = None) -> None:
    if fixed_buttons is None:
        current = load_contact_data()
        fixed_buttons = current.get("fixed_buttons", [])
    with open(CONTACT_STORE_FILE, "w", encoding="utf-8") as f:
        json.dump(
            {
                "apply_contacts": apply_contacts,
                "fixed_buttons": fixed_buttons,
            },
            f,
            ensure_ascii=False,
            indent=2,
        )


def load_contact_rows() -> list:
    """Compatibility helper returning flat rows for the keyboard."""
    data = load_contact_data()
    fixed_buttons = data.get("fixed_buttons", DEFAULT_FIXED_BUTTONS)
    rows = [[{"label": "📥 Apply for This Job", "url": f"https://t.me/{BOT_USERNAME}?start=apply", "btn_style": "primary"}]]
    rows.extend(fixed_buttons)
    return rows


def save_contact_rows(rows: list) -> None:
    """Compatibility helper for saving list of rows."""
    current = load_contact_data()
    save_contact_data(current.get("apply_contacts", DEFAULT_APPLY_CONTACTS), fixed_buttons=rows)


def build_keyboard_markup(rows: list) -> InlineKeyboardMarkup:
    kb_rows = []
    for row in rows:
        row_btns = []
        for b in row:
            kwargs = {}
            if b.get("btn_style"):
                kwargs["api_kwargs"] = {"style": b["btn_style"]}
            else:
                kwargs["api_kwargs"] = {"style": "primary"}
            row_btns.append(InlineKeyboardButton(b["label"], url=b["url"], **kwargs))
        kb_rows.append(row_btns)
    return InlineKeyboardMarkup(kb_rows)


def build_admin_contact_url(
    base_url: str = STATIC_ADMIN_BUTTON_URL,
    post_url: str = None,
    post_text: str = None,
) -> str:
    """
    Construct URL to redirect to Admin Career Center (https://t.me/USEACCAD)
    with pre-filled text containing greeting and post URL.
    """
    target_base = base_url or STATIC_ADMIN_BUTTON_URL
    if post_url:
        msg_text = f"ជម្រាបសួរបង ខ្ញុំចាប់អារម្មណ៍នឹងការងារនេះ: 🔗 {post_url}"
    elif post_text:
        msg_text = "ជម្រាបសួរបង ខ្ញុំចាប់អារម្មណ៍នឹងការងារនេះ"
    else:
        return target_base

    import urllib.parse
    encoded_text = urllib.parse.quote(msg_text)
    sep = "&" if "?" in target_base else "?"
    return f"{target_base}{sep}text={encoded_text}"


def get_contact_keyboard(
    post_url: str = None,
    post_text: str = None,
    post_id: str = None,
    enable_tracking: bool = True,
    enable_custom_emoji: bool = True,
) -> InlineKeyboardMarkup:
    data = load_contact_data()
    apply_contacts = data.get("apply_contacts") or {}

    # Extract all dynamic buttons (supports 1, 2, 3, or more buttons!)
    raw_buttons = apply_contacts.get("buttons")
    if raw_buttons is None:
        raw_buttons = []
        if apply_contacts.get("employer", {}).get("url"):
            raw_buttons.append(apply_contacts["employer"])
        if apply_contacts.get("email", {}).get("url"):
            raw_buttons.append(apply_contacts["email"])

    # If post_url is provided but post_id is not, extract post_id from post_url
    if post_url and not post_id:
        try:
            candidate_id = post_url.rstrip("/").split("/")[-1]
            if candidate_id.isdigit():
                post_id = candidate_id
        except Exception:
            post_id = None

    admin_contact_url = build_admin_contact_url(
        base_url=STATIC_ADMIN_BUTTON_URL,
        post_url=post_url,
        post_text=post_text,
    )

    should_track = enable_tracking and bool(post_url or post_id) and bool(WEBHOOK_URL)

    if should_track:
        final_admin_url = register_tracking_link(
            base_url=WEBHOOK_URL,
            target_url=admin_contact_url,
            label=STATIC_ADMIN_BUTTON_LABEL,
            link_type="admin",
            post_id=post_id,
            post_url=post_url,
        )
        final_bot_url = register_tracking_link(
            base_url=WEBHOOK_URL,
            target_url=STATIC_BOT_BUTTON_URL,
            label=STATIC_BOT_BUTTON_LABEL,
            link_type="bot",
            post_id=post_id,
            post_url=post_url,
        )
    else:
        final_admin_url = admin_contact_url
        final_bot_url = STATIC_BOT_BUTTON_URL

    # Process all dynamic buttons (ALL styled in RED / danger)
    dynamic_btns = []
    for idx, b in enumerate(raw_buttons, start=1):
        b_url = (b.get("url") or "").strip()
        b_label = (b.get("label") or "").strip() or "Apply Now"
        b_style = b.get("btn_style") or "danger"
        if not b_url:
            continue

        is_email = b_url.startswith("mailto:")
        link_type = f"email{idx}" if is_email else f"apply{idx}"

        # Telegram Bot API strictly prohibits mailto: in InlineKeyboardButton.url.
        # It must ALWAYS be routed through web redirect URL:
        if is_email or not b_url.startswith(("http://", "https://", "tg://")):
            final_b_url = register_tracking_link(
                base_url=WEBHOOK_URL,
                target_url=b_url,
                label=b_label,
                link_type=link_type,
                post_id=post_id or "preview",
                post_url=post_url or "",
            )
        elif should_track:
            final_b_url = register_tracking_link(
                base_url=WEBHOOK_URL,
                target_url=b_url,
                label=b_label,
                link_type=link_type,
                post_id=post_id,
                post_url=post_url,
            )
        else:
            final_b_url = b_url

        dynamic_btns.append(
            InlineKeyboardButton(
                b_label,
                url=final_b_url,
                api_kwargs={"style": b_style},
            )
        )

    kb_rows = []
    admin_data = apply_contacts.get("admin") or {}
    admin_btn = InlineKeyboardButton(
        STATIC_ADMIN_BUTTON_LABEL,
        url=final_admin_url,
        api_kwargs={"style": admin_data.get("btn_style") or "success"},
    )

    if len(dynamic_btns) == 0:
        # 0 dynamic buttons -> Row 1 has only Contact Admin
        kb_rows.append([admin_btn])
    elif len(dynamic_btns) == 1:
        # 1 dynamic button -> Row 1 has Contact Admin + Button 1
        kb_rows.append([admin_btn, dynamic_btns[0]])
    elif len(dynamic_btns) == 2:
        # 2 dynamic buttons -> Row 1 has Contact Admin + Button 1; Row 2 has Button 2
        kb_rows.append([admin_btn, dynamic_btns[0]])
        kb_rows.append([dynamic_btns[1]])
    else:
        # 3 or more dynamic buttons -> Row 1: Contact Admin + Button 1; remaining buttons 2 per row
        kb_rows.append([admin_btn, dynamic_btns[0]])
        rem = dynamic_btns[1:]
        for i in range(0, len(rem), 2):
            kb_rows.append(rem[i : i + 2])

    # Bottom Row: Static bot redirect button directly to career tips bot (BLUE)
    kb_rows.append([
        InlineKeyboardButton(
            STATIC_BOT_BUTTON_LABEL,
            url=final_bot_url,
            api_kwargs={"style": "primary"},
        )
    ])

    return InlineKeyboardMarkup(kb_rows)




def parse_button_entry(entry: str):
    """Parse 'Button text - url' with optional solid colors ('- color:blue', '- color:red', '- color:green') or emojis."""
    entry = entry.strip()
    if not entry:
        return None

    style_name = None
    emoji_icon = None

    # ស្វែងរក - style:color ឬ - color:color ឬ - colour:color ឬ - ពណ៌:color
    m_style = re.search(r"-\s*(?:style|color|colour|ពណ៌)\s*[:=\s]\s*([\w\u1780-\u17FF\-]+)", entry, flags=re.IGNORECASE)
    if m_style:
        style_candidate = m_style.group(1).lower()
        if style_candidate in NATIVE_BUTTON_STYLES or style_candidate in STYLE_EMOJI:
            style_name = style_candidate
            entry = entry[:m_style.start()] + entry[m_style.end():]

    # ស្វែងរក - emoji:<icon> ឬ - icon:<icon>
    m_emoji = re.search(r"-\s*(?:emoji|icon)\s*[:=\s]\s*(\S+)", entry, flags=re.IGNORECASE)
    if m_emoji:
        emoji_icon = m_emoji.group(1).strip()
        entry = entry[:m_emoji.start()] + entry[m_emoji.end():]

    entry = re.sub(r"\s*-\s*-\s*", " - ", entry).strip()

    # បំបែក Label និង URL ដោយប្រើ " - " ចុងក្រោយ
    label, sep, target = entry.rpartition(" - ")
    if not sep:
        label, sep, target = entry.rpartition("-")
    if not sep:
        return None

    label = label.strip()
    target = target.strip()
    if not label or not target:
        return None

    if emoji_icon:
        label = f"{emoji_icon} {label}"

    btn_dict = {"label": label, "url": build_contact_url(target)}

    if style_name:
        if style_name in NATIVE_BUTTON_STYLES:
            # Telegram Native Solid Background Color (Blue, Red, Green)
            btn_dict["btn_style"] = NATIVE_BUTTON_STYLES[style_name]
        elif style_name in STYLE_EMOJI:
            # Emoji styling fallback for other colors (yellow, orange, purple, etc.)
            color_box = STYLE_EMOJI[style_name]
            btn_dict["label"] = f"{color_box} {label} {color_box}"

    return btn_dict


def parse_contact_text(raw_text: str):
    """បំប្លែងអត្ថបទច្រើនបន្ទាត់ ទៅជា Rows នៃប៊ូតុង។ Return (rows, errors)"""
    rows = []
    errors = []
    lines = [ln for ln in raw_text.splitlines() if ln.strip()]

    for line_no, line in enumerate(lines, start=1):
        parts = line.split("|")
        row = []
        for part in parts[:MAX_BUTTONS_PER_ROW]:
            btn = parse_button_entry(part)
            if btn:
                row.append(btn)
            else:
                errors.append(f"បន្ទាត់ទី {line_no}: '{part.strip()}' — ទម្រង់មិនត្រឹមត្រូវ")
        if len(parts) > MAX_BUTTONS_PER_ROW:
            errors.append(f"បន្ទាត់ទី {line_no}: លើសពី {MAX_BUTTONS_PER_ROW} ប៊ូតុងក្នុងមួយជួរ — យកតែ {MAX_BUTTONS_PER_ROW} ដំបូង")
        if row:
            rows.append(row)

    return rows, errors


def parse_apply_contacts_input(raw_text: str):
    """
    Parse input for dynamic Apply Now & Email contact buttons.
    Supports any number of buttons (1, 2, 3, 4, etc.).
    """
    lines = [ln.strip() for ln in raw_text.splitlines() if ln.strip()]
    if not lines:
        return None

    raw_lower = raw_text.strip().lower()

    # Clear options
    if raw_lower in (
        "clear",
        "none",
        "off",
        "0",
        "del",
        "delete",
        "remove",
        "គ្មាន",
        "លុប",
        "បិទ",
        "clear all",
        "clear contact",
        "clear contacts",
        "clearcontact",
        "/clearcontact",
        "/clear",
        "លុប contact",
        "លុបទាំងអស់",
    ):
        return {
            "buttons": [],
            "employer": {},
            "email": {},
            "admin": DEFAULT_APPLY_CONTACTS.get("admin", {}),
        }
    elif raw_lower in ("clear email", "clear mail", "clearemail", "លុប email", "លុបអ៊ីមែល"):
        current = load_contact_data()
        apply_c = current.get("apply_contacts") or {}
        new_btns = [b for b in apply_c.get("buttons", []) if not (b.get("url") or "").startswith("mailto:")]
        return {
            "buttons": new_btns,
            "employer": apply_c.get("employer", {}),
            "email": {},
            "admin": apply_c.get("admin", DEFAULT_APPLY_CONTACTS.get("admin", {})),
        }
    elif raw_lower in ("clear employer", "clear telegram", "clear phone", "clear tg", "លុប telegram"):
        current = load_contact_data()
        apply_c = current.get("apply_contacts") or {}
        new_btns = [b for b in apply_c.get("buttons", []) if (b.get("url") or "").startswith("mailto:")]
        return {
            "buttons": new_btns,
            "employer": {},
            "email": apply_c.get("email", {}),
            "admin": apply_c.get("admin", DEFAULT_APPLY_CONTACTS.get("admin", {})),
        }

    buttons = []
    first_employer = {}
    first_email = {}

    for line in lines:
        label = ""
        target = line
        if " - " in line:
            label, _, target = line.rpartition(" - ")
        elif "-" in line and not any(ch.isdigit() for ch in line.split("-")[0]):
            label, _, target = line.rpartition("-")

        clean_target = target.strip()
        url = build_contact_url(clean_target) if clean_target else ""
        if not url:
            continue

        clean_label = label.strip()
        if not clean_label:
            if url.startswith("mailto:"):
                clean_label = "✉️ Apply via Email"
            else:
                clean_label = "Apply Now"

        btn_dict = {
            "label": clean_label,
            "url": url,
            "btn_style": "danger",
        }
        buttons.append(btn_dict)

        if url.startswith("mailto:") and not first_email:
            first_email = btn_dict
        elif not url.startswith("mailto:") and not first_employer:
            first_employer = btn_dict

    if not buttons:
        return None

    return {
        "buttons": buttons,
        "employer": first_employer,
        "email": first_email,
        "admin": DEFAULT_APPLY_CONTACTS.get("admin", {}),
    }


SETCONTACT_HELP = (
    "📌 *របៀបកំណត់ប៊ូតុង Apply Now & Email*\n\n"
    "ប៊ូតុង Apply Now និងប៊ូតុង Email (ពណ៌ក្រហម) នឹងបង្ហាញតែនៅពេលអ្នកបានកំណត់ប៉ុណ្ណោះ។ "
    "ប្រសិនបើមិនទាន់កំណត់ ឬលុបចេញ ប៊ូតុងទាំងនោះនឹងបាត់ (មិនបង្ហាញក្នុង Post ទេ)។\n\n"
    "*👉 របៀបកំណត់ Contact:*\n"
    "• កំណត់ Apply Now (Telegram/ទូរស័ព្ទ): ផ្ញើលេខទូរស័ព្ទ ឬ @username\n"
    "  ឧទាហរណ៍: `0975406969` ឬ `Apply Now - 0975406969`\n\n"
    "• កំណត់ Email: ផ្ញើអាសយដ្ឋាន Email\n"
    "  ឧទាហរណ៍: `hr@company.com` ឬ `Apply via Email - hr@company.com`\n\n"
    "• កំណត់ទាំងពីរក្នុងពេលតែមួយ (ផ្ញើ ២ បន្ទាត់):\n"
    "  `Apply Now - 0975406969`\n"
    "  `Apply via Email - hr@company.com`\n\n"
    "🗑️ *របៀបលុបប៊ូតុងចេញ:*\n"
    "• លុបទាំងអស់: `/setcontact clear` ឬ `/clearcontact`\n"
    "• លុបតែ Email: `/clearemail` ឬ `/clearcontact email`\n"
    "• លុបតែ Telegram: `/clearcontact telegram`\n\n"
    "📌 *ប៊ូតុងថេរ (បង្ហាញជានិច្ច):*\n"
    f"• {STATIC_ADMIN_BUTTON_LABEL} (ពណ៌បៃតង — ភ្ជាប់ព័ត៌មាន Admin ដោយស្វ័យប្រវត្តិ)\n"
    f"• {STATIC_BOT_BUTTON_LABEL} (ពណ៌ខៀវ)"
)



def is_contact_setting_text(text: str) -> bool:
    """
    Returns True if the text looks like a contact setting command/input
    rather than a channel job post.
    """
    if not text:
        return False
    lines = [ln.strip() for ln in text.strip().splitlines() if ln.strip()]
    if not lines or len(lines) > 10:
        return False

    first_line = lines[0].lower()
    if first_line.startswith(("/setcontact", "/setemail", "/clearcontact", "/clearemail")):
        return True

    matched = 0
    for line in lines:
        lower = line.lower()
        if lower in (
            "clear",
            "clear all",
            "clear contact",
            "clear contacts",
            "clearcontact",
            "clearemail",
            "clear email",
            "clear employer",
            "/clear",
            "/clearcontact",
            "/clearemail",
            "លុប",
            "គ្មាន",
            "លុប contact",
            "លុបទាំងអស់",
            "off",
            "none",
            "0",
        ):
            matched += 1
            continue

        if any(
            lower.startswith(p)
            for p in (
                "apply now",
                "apply",
                "email",
                "mail",
                "apply via email",
                "telegram",
                "phone",
                "tel",
                "wa:",
                "tg:",
                "contact",
            )
        ) and ("-" in line or ":" in line):
            matched += 1
            continue

        digits = "".join(c for c in line if c.isdigit())
        if len(digits) >= 8 and len(line) <= 20 and not any(c in line for c in ("$", "%", "USD", "usd", "៛")):
            matched += 1
            continue

        if "@" in line and "." in line and " " not in line and not line.startswith("@"):
            matched += 1
            continue

        if line.startswith("@") and len(line) <= 35 and " " not in line:
            matched += 1
            continue
        if (line.startswith("https://t.me/") or line.startswith("t.me/")) and " " not in line:
            matched += 1
            continue

    return matched == len(lines)


async def apply_contacts_and_reply(update: Update, raw_text: str) -> bool:
    contacts = parse_apply_contacts_input(raw_text)
    if contacts is None:
        return False

    save_contact_data(contacts)
    keyboard = get_contact_keyboard()

    buttons = contacts.get("buttons") or []
    lines = ["✅ បានកំណត់ Contact រួចរាល់!"]
    if buttons:
        for idx, b in enumerate(buttons, start=1):
            lbl = b.get("label", "Apply Now")
            u = b.get("url", "")
            lines.append(f"• ប៊ូតុងទី {idx}: {lbl} → {u}")
    else:
        lines = [
            "✅ បានលុប Contact សម្រាប់ប៊ូតុង Dynamic រួចរាល់!",
            "👉 ប៊ូតុងទាំងនេះនឹងមិនបង្ហាញក្នុង Post ទេ (លុះត្រាតែកំណត់ Contact ម្តងទៀត)។",
        ]
    lines.append("\nឧទាហរណ៍ប៊ូតុង (នឹងបង្ហាញក្នុង Post)៖")
    try:
        await update.message.reply_text("\n".join(lines), reply_markup=keyboard)
    except Exception as err:
        logger.error("apply_contacts_and_reply error with keyboard: %s", err)
        await update.message.reply_text("\n".join(lines))
    return True

async def set_contact_start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    user = update.effective_user
    if not is_admin(user.id):
        await update.message.reply_text("❌ អ្នកមិនមានសិទ្ធិប្រើ command នេះទេ។")
        return ConversationHandler.END

    raw_text = update.message.text.partition(" ")[2].strip()
    if not raw_text and "\n" in update.message.text:
        raw_text = update.message.text.split("\n", 1)[1].strip()

    if raw_text:
        ok = await apply_contacts_and_reply(update, raw_text)
        if not ok:
            await update.message.reply_text(
                "⚠️ មិនអាចអាន Contact បានទេ។\n\n" + SETCONTACT_HELP, parse_mode="Markdown"
            )
        return ConversationHandler.END

    try:
        await update.message.reply_text(
            SETCONTACT_HELP + "\n\n━━━━━━━━━━━━━━━━━━━━\n"
            "📝 *សូមផ្ញើ Contact របស់អ្នកឥឡូវនេះ (ឬផ្ញើ `clear` ដើម្បីលុប / `/cancel` ដើម្បីបោះបង់)៖*",
            parse_mode="Markdown",
        )
    except Exception as err:
        logger.error("set_contact_start markdown error: %s", err)
        await update.message.reply_text(
            SETCONTACT_HELP.replace("*", "").replace("`", "") + "\n\n━━━━━━━━━━━━━━━━━━━━\n"
            "📝 សូមផ្ញើ Contact របស់អ្នកឥឡូវនេះ (ឬផ្ញើ clear ដើម្បីលុប / /cancel ដើម្បីបោះបង់)៖"
        )
    return SETTING_CONTACT


async def set_contact_process(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    raw_text = update.message.text.strip()
    ok = await apply_contacts_and_reply(update, raw_text)
    if not ok:
        await update.message.reply_text(
            "⚠️ មិនអាចអាន Contact បានទេ។ សូមពិនិត្យទម្រង់រួចផ្ញើម្តងទៀត ឬសរសេរ /cancel ដើម្បីបោះបង់៖\n\n"
            + SETCONTACT_HELP,
            parse_mode="Markdown",
        )
        return SETTING_CONTACT
    return ConversationHandler.END


async def cancel_contact(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    context.user_data.clear()
    await update.message.reply_text("❌ បានបោះបង់ការកំណត់ Contact Buttons។")
    return ConversationHandler.END


async def cancel_all_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    context.user_data.clear()
    await update.message.reply_text("❌ បានបោះបង់ដំណើរការ (Cancelled)។")
    return ConversationHandler.END


async def clear_contact_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user = update.effective_user
    if not is_admin(user.id):
        await update.message.reply_text("❌ អ្នកមិនមានសិទ្ធិប្រើ command នេះទេ។")
        return

    arg = (context.args[0].lower() if context.args else "").strip()

    data = load_contact_data()
    apply_contacts = data.get("apply_contacts") or {}

    if arg in ("email", "mail"):
        apply_contacts["email"] = {}
        apply_contacts["buttons"] = [
            b for b in apply_contacts.get("buttons", [])
            if not (b.get("url") or "").startswith("mailto:")
        ]
        msg_action = "បានលុប Contact សម្រាប់ប៊ូតុង Email រួចរាល់!"
        msg_sub = "👉 ប៊ូតុង Email នឹងមិនបង្ហាញក្នុង Post ទៀតទេ (លុះត្រាតែកំណត់ម្តងទៀត)។"
    elif arg in ("employer", "telegram", "phone", "tg"):
        apply_contacts["employer"] = {}
        apply_contacts["buttons"] = [
            b for b in apply_contacts.get("buttons", [])
            if (b.get("url") or "").startswith("mailto:")
        ]
        msg_action = "បានលុប Contact សម្រាប់ប៊ូតុង Apply Now រួចរាល់!"
        msg_sub = "👉 ប៊ូតុង Apply Now នឹងមិនបង្ហាញក្នុង Post ទៀតទេ (លុះត្រាតែកំណត់ម្តងទៀត)។"
    else:
        apply_contacts["buttons"] = []
        apply_contacts["employer"] = {}
        apply_contacts["email"] = {}
        msg_action = "បានលុប Contact ទាំងអស់ (Dynamic Buttons) រួចរាល់!"
        msg_sub = "👉 ប៊ូតុង Dynamic ទាំងអស់នឹងមិនបង្ហាញក្នុង Post ទៀតទេ (លុះត្រាតែកំណត់ម្តងទៀត)។"

    save_contact_data(apply_contacts, fixed_buttons=data.get("fixed_buttons", DEFAULT_FIXED_BUTTONS))

    keyboard = get_contact_keyboard()
    try:
        await update.message.reply_text(
            f"✅ {msg_action}\n{msg_sub}\n\nទម្រង់ប៊ូតុងបច្ចុប្បន្ន៖",
            reply_markup=keyboard,
        )
    except Exception as err:
        logger.error("clear_contact_command reply error: %s", err)
        await update.message.reply_text(f"✅ {msg_action}\n{msg_sub}")


async def clear_email_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user = update.effective_user
    if not is_admin(user.id):
        await update.message.reply_text("❌ អ្នកមិនមានសិទ្ធិប្រើ command នេះទេ។")
        return

    data = load_contact_data()
    apply_contacts = data.get("apply_contacts") or {}
    apply_contacts["email"] = {}
    apply_contacts["buttons"] = [
        b for b in apply_contacts.get("buttons", [])
        if not (b.get("url") or "").startswith("mailto:")
    ]
    save_contact_data(apply_contacts, fixed_buttons=data.get("fixed_buttons", DEFAULT_FIXED_BUTTONS))

    keyboard = get_contact_keyboard()
    try:
        await update.message.reply_text(
            "✅ បានលុប Contact សម្រាប់ប៊ូតុង Email រួចរាល់!\n"
            "👉 ប៊ូតុង Email នឹងមិនបង្ហាញក្នុង Post ទៀតទេ (លុះត្រាតែកំណត់ម្តងទៀតតាមរយៈ /setemail ឬ /setcontact)។\n\n"
            "ទម្រង់ប៊ូតុងបច្ចុប្បន្ន៖",
            reply_markup=keyboard,
        )
    except Exception as err:
        logger.error("clear_email_command error: %s", err)
        await update.message.reply_text("✅ បានលុប Contact សម្រាប់ប៊ូតុង Email រួចរាល់!")


async def set_email_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user = update.effective_user
    if not is_admin(user.id):
        await update.message.reply_text("❌ អ្នកមិនមានសិទ្ធិប្រើ command នេះទេ។")
        return

    raw_text = update.message.text.partition(" ")[2].strip()
    if not raw_text:
        await update.message.reply_text(
            "📝 *សូមផ្ញើ Email ជាមួយ command នេះ៖*\n\n"
            "ឧទាហរណ៍៖\n"
            "`/setemail hr@company.com`\n"
            "`/setemail Apply via Email - hr@company.com`\n\n"
            "ដើម្បីលុបប៊ូតុង Email ចេញ៖ `/clearemail`",
            parse_mode="Markdown",
        )
        return

    label = ""
    target = raw_text
    if " - " in raw_text:
        label, _, target = raw_text.rpartition(" - ")
    elif "-" in raw_text and not any(ch.isdigit() for ch in raw_text.split("-")[0]):
        label, _, target = raw_text.rpartition("-")

    clean_target = target.strip()
    url = build_contact_url(clean_target)
    if not url.startswith("mailto:"):
        url = f"mailto:{clean_target}"

    clean_label = label.strip() or "✉️ Apply via Email"

    data = load_contact_data()
    apply_contacts = data.get("apply_contacts") or {}
    email_btn = {
        "label": clean_label,
        "url": url,
        "btn_style": "danger",
    }
    apply_contacts["email"] = email_btn
    btns = apply_contacts.get("buttons") or []
    btns = [b for b in btns if not (b.get("url") or "").startswith("mailto:")]
    btns.append(email_btn)
    apply_contacts["buttons"] = btns
    save_contact_data(apply_contacts, fixed_buttons=data.get("fixed_buttons", DEFAULT_FIXED_BUTTONS))

    keyboard = get_contact_keyboard()
    await update.message.reply_text(
        f"✅ បានកំណត់ប៊ូតុង Email រួចរាល់!\n"
        f"• Label: {clean_label}\n"
        f"• Link: {url}\n\n"
        "ឧទាហរណ៍ប៊ូតុង (នឹងបង្ហាញក្នុង Post)៖",
        reply_markup=keyboard,
    )


async def show_contact(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user = update.effective_user
    if not is_admin(user.id):
        await update.message.reply_text("❌ អ្នកមិនមានសិទ្ធិប្រើ command នេះទេ។")
        return

    data = load_contact_data()
    apply_contacts = data.get("apply_contacts") or {}

    buttons = apply_contacts.get("buttons") or []
    if not buttons:
        if apply_contacts.get("employer", {}).get("url"):
            buttons.append(apply_contacts["employer"])
        if apply_contacts.get("email", {}).get("url"):
            buttons.append(apply_contacts["email"])

    lines = [
        "ℹ️ <b>ទម្រង់ប៊ូតុងបច្ចុប្បន្ន (Current Button Layout)</b>\n",
        "🔒 <b>ប៊ូតុងថេរ (Static):</b>",
        f"• {html.escape(STATIC_ADMIN_BUTTON_LABEL)} → {html.escape(STATIC_ADMIN_BUTTON_URL)} (ពណ៌បៃតង)",
        f"• {html.escape(STATIC_BOT_BUTTON_LABEL)} → {html.escape(STATIC_BOT_BUTTON_URL)} (ពណ៌ខៀវ)\n",
        "🔄 <b>ប៊ូតុង Dynamic (ពណ៌ក្រហម — បង្ហាញតែពេលកំណត់):</b>",
    ]

    if buttons:
        for idx, b in enumerate(buttons, start=1):
            lbl = b.get("label", "Apply Now")
            u = b.get("url", "")
            lines.append(f"• ប៊ូតុងទី {idx}: ✅ {html.escape(lbl)} → {html.escape(u)}")
    else:
        lines.append("• ❌ មិនទាន់កំណត់ (គ្មានប៊ូតុង Dynamic ក្នុង Post ទេ)")

    lines.append("\n💡 ផ្ញើ Contact (លេខទូរស័ព្ទ ឬ Email) ដើម្បីកំណត់ | ផ្ញើ clear ឬ /clearcontact ដើម្បីលុប")

    keyboard = get_contact_keyboard()
    try:
        await update.message.reply_text(
            "\n".join(lines),
            reply_markup=keyboard,
            parse_mode="HTML",
        )
    except Exception as err:
        logger.error("show_contact HTML error: %s, falling back to plain text", err)
        plain = "\n".join(lines).replace("<b>", "").replace("</b>", "")
        try:
            await update.message.reply_text(plain, reply_markup=keyboard)
        except Exception:
            await update.message.reply_text(plain)


# ------------------------------------------------------------------
# Helper Functions for Post Formatting & Dispatch
# ------------------------------------------------------------------
async def handle_contact_admin(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    await query.answer("✅ Your interest has been sent to the Admin! They will contact you soon.", show_alert=True)
    
    admin_id = 8824663759
    user = update.effective_user
    
    try:
        # Copy the original message from the channel to the admin
        await context.bot.copy_message(
            chat_id=admin_id,
            from_chat_id=query.message.chat_id,
            message_id=query.message.message_id
        )
        
        # Send user info to the admin
        username_str = f"@{user.username}" if user.username else "No username"
        text = (
            f"👤 **New Applicant!**\n"
            f"Name: {user.full_name}\n"
            f"Username: {username_str}\n"
            f"Profile: [Click here](tg://user?id={user.id})"
        )
        await context.bot.send_message(
            chat_id=admin_id,
            text=text,
            parse_mode="Markdown"
        )
    except Exception as e:
        logger.error(f"Failed to forward to admin: {e}")


def telegram_length(text: str) -> int:
    """Telegram UTF-16 code units length calculator."""
    if not text:
        return 0
    return len(text.encode("utf-16-le")) // 2


def _needs_split_caption(raw_length: int) -> bool:
    """True if text + photo combo exceeds Telegram's caption limit."""
    return raw_length > TELEGRAM_CAPTION_LIMIT


async def post_start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    user = update.effective_user
    if not is_admin(user.id):
        await update.message.reply_text("❌ អ្នកមិនមានសិទ្ធិប្រើ command នេះទេ។")
        return ConversationHandler.END

    context.user_data.clear()
    await update.message.reply_text(
        "📝 សូមផ្ញើ *ព័ត៌មានអំពីការងារ និង/ឬ រូបភាព* ក្នុងសារតែមួយ (ឬ forward មកក៏បាន)៖\n\n"
        "🔸 ផ្ញើរូបភាព ជាមួយ Caption (ព័ត៌មានការងារ) — ល្អបំផុត\n"
        "🔸 ឬផ្ញើតែអត្ថបទ (គ្មានរូបភាព)\n"
        "🔸 ឬផ្ញើតែរូបភាព (គ្មាន Caption)\n\n"
        "ព័ត៌មានវែងៗគាំទ្របានដល់ប្រហែល 4000 តួ — បើវែងជាង Caption limit "
        "(1024 តួ) នៅពេលមានរូបភាព, Bot នឹងផ្ញើរូបភាព រួចផ្ញើអត្ថបទពេញលេញជាសារបន្ទាប់ដោយស្វ័យប្រវត្តិ។\n\n"
        "ចំណាំ: ប្រសិនបើអ្នកបានបង្កើត Hyperlink (Create Link) លើពាក្យណាមួយ "
        "វានឹងនៅតែ Click បានដដែលនៅពេលបង្ហោះ។\n\n"
        "សរសេរ /cancel ដើម្បីបោះបង់។",
        parse_mode="Markdown",
    )
    return CONTENT


async def _save_and_preview_post(update: Update, context: ContextTypes.DEFAULT_TYPE, msg) -> None:
    """Preview message for admin and store metadata for confirmation."""
    caption_html = (msg.caption_html or "").strip() or None
    text_html = (msg.text_html or "").strip() if msg.text else None
    info = caption_html or text_html

    context.user_data["source_chat_id"] = msg.chat_id
    context.user_data["source_message_id"] = msg.message_id
    context.user_data["photo_id"] = msg.photo[-1].file_id if msg.photo else None
    context.user_data["video_id"] = msg.video.file_id if msg.video else None
    context.user_data["document_id"] = msg.document.file_id if msg.document else None
    context.user_data["audio_id"] = msg.audio.file_id if msg.audio else None
    context.user_data["voice_id"] = msg.voice.file_id if msg.voice else None
    context.user_data["animation_id"] = msg.animation.file_id if msg.animation else None
    context.user_data["sticker_id"] = msg.sticker.file_id if msg.sticker else None
    context.user_data["info"] = info
    raw_length = telegram_length(msg.caption or msg.text or "")
    context.user_data["raw_length"] = raw_length

    keyboard = get_contact_keyboard(post_text=info)

    # Send preview: Prioritize copy_message to perfectly preserve Telegram Premium custom/animated emojis!
    preview_copied = False
    if not (msg.photo and _needs_split_caption(raw_length)):
        try:
            await context.bot.copy_message(
                chat_id=msg.chat_id,
                from_chat_id=msg.chat_id,
                message_id=msg.message_id,
                reply_markup=keyboard,
            )
            preview_copied = True
        except Exception as copy_err:
            logger.warning("Preview copy_message failed (%s), falling back to standard send.", copy_err)
            preview_copied = False

    if not preview_copied:
        if msg.photo:
            if _needs_split_caption(raw_length):
                await update.message.reply_photo(photo=msg.photo[-1].file_id)
                await update.message.reply_text(
                    caption_html or "", parse_mode="HTML", reply_markup=keyboard
                )
            else:
                await update.message.reply_photo(
                    photo=msg.photo[-1].file_id,
                    caption=caption_html,
                    parse_mode="HTML" if caption_html else None,
                    reply_markup=keyboard,
                )
        elif msg.text:
            await update.message.reply_text(
                text_html, parse_mode="HTML", reply_markup=keyboard
            )
        elif msg.video:
            await update.message.reply_video(
                video=msg.video.file_id,
                caption=caption_html,
                parse_mode="HTML" if caption_html else None,
                reply_markup=keyboard,
            )
        elif msg.document:
            await update.message.reply_document(
                document=msg.document.file_id,
                caption=caption_html,
                parse_mode="HTML" if caption_html else None,
                reply_markup=keyboard,
            )
        elif msg.sticker:
            await update.message.reply_sticker(sticker=msg.sticker.file_id)
            await update.message.reply_text("​", reply_markup=keyboard)


async def get_content(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    msg = update.message
    if msg.text:
        text_len = telegram_length(msg.text)
        if text_len > TELEGRAM_MESSAGE_LIMIT:
            await update.message.reply_text(
                f"⚠️ អត្ថបទវែងពេក ({text_len} តួ)។ Telegram អនុញ្ញាតតែរហូតដល់ "
                f"{TELEGRAM_MESSAGE_LIMIT} តួសម្រាប់សារអត្ថបទតែម្នាក់ឯង។ សូមកាត់បន្ថយ ឬ ផ្ញើជាមួយរូបភាព។"
            )
            return CONTENT

    await _save_and_preview_post(update, context, msg)

    confirm_keyboard = InlineKeyboardMarkup([
        [
            InlineKeyboardButton("✅ YES — បញ្ជូនទៅ Channel", callback_data="confirm_yes", api_kwargs={"style": "success"}),
            InlineKeyboardButton("❌ NO — បោះបង់", callback_data="confirm_no", api_kwargs={"style": "danger"}),
        ]
    ])
    await update.message.reply_text(
        "✅ **មើលទម្រង់សារមុនបង្ហោះ (Preview)**\n❓ តើអ្នកពិតជាចង់បង្ហោះសារនេះទៅកាន់ Channel ដែរឬទេ?",
        reply_markup=confirm_keyboard,
        parse_mode="Markdown",
    )
    return CONFIRM


def clear_dynamic_contacts_after_post() -> None:
    """Auto-clear dynamic apply contacts from storage after post is published."""
    try:
        data = load_contact_data()
        apply_contacts = data.get("apply_contacts") or {}
        apply_contacts["buttons"] = []
        apply_contacts["employer"] = {}
        apply_contacts["email"] = {}
        save_contact_data(apply_contacts, fixed_buttons=data.get("fixed_buttons", DEFAULT_FIXED_BUTTONS))
        logger.info("Automatically cleared dynamic apply contacts after post published to channel.")
    except Exception as e:
        logger.warning("Failed to auto-clear dynamic contacts after post: %s", e)


async def _publish_data_to_channel(bot, data: dict) -> None:
    """Core function to dispatch prepared post data to the channel."""
    info = data.get("info") or ""
    keyboard = get_contact_keyboard(post_text=info)
    source_chat_id = data.get("source_chat_id")
    source_message_id = data.get("source_message_id")
    raw_length = data.get("raw_length", 0)
    
    sent_msg_id = None

    # 1. If photo with split caption (longer than 1024 chars)
    if data.get("photo_id") and _needs_split_caption(raw_length):
        await bot.send_photo(chat_id=CHANNEL_ID, photo=data["photo_id"])
        msg = await bot.send_message(
            chat_id=CHANNEL_ID,
            text=info,
            parse_mode="HTML",
            reply_markup=keyboard,
        )
        sent_msg_id = msg.message_id

    # 2. Try copy_message first (preserves native formatting, forwards, documents, etc.)
    elif source_chat_id and source_message_id:
        try:
            msg_id_obj = await bot.copy_message(
                chat_id=CHANNEL_ID,
                from_chat_id=source_chat_id,
                message_id=source_message_id,
                reply_markup=keyboard,
            )
            sent_msg_id = msg_id_obj.message_id
        except Exception as copy_err:
            logger.warning("copy_message to channel failed (%s), trying fallback.", copy_err)
            sent_msg_id = None

    # 3. Direct send fallbacks
    if not sent_msg_id:
        msg = None
        if data.get("photo_id"):
            msg = await bot.send_photo(
                chat_id=CHANNEL_ID,
                photo=data["photo_id"],
                caption=info if info else None,
                parse_mode="HTML" if info else None,
                reply_markup=keyboard,
            )
        elif data.get("video_id"):
            msg = await bot.send_video(
                chat_id=CHANNEL_ID,
                video=data["video_id"],
                caption=info if info else None,
                parse_mode="HTML" if info else None,
                reply_markup=keyboard,
            )
        elif data.get("document_id"):
            msg = await bot.send_document(
                chat_id=CHANNEL_ID,
                document=data["document_id"],
                caption=info if info else None,
                parse_mode="HTML" if info else None,
                reply_markup=keyboard,
            )
        elif data.get("audio_id"):
            msg = await bot.send_audio(
                chat_id=CHANNEL_ID,
                audio=data["audio_id"],
                caption=info if info else None,
                parse_mode="HTML" if info else None,
                reply_markup=keyboard,
            )
        elif data.get("voice_id"):
            msg = await bot.send_voice(
                chat_id=CHANNEL_ID,
                voice=data["voice_id"],
                reply_markup=keyboard,
            )
        elif data.get("animation_id"):
            msg = await bot.send_animation(
                chat_id=CHANNEL_ID,
                animation=data["animation_id"],
                caption=info if info else None,
                parse_mode="HTML" if info else None,
                reply_markup=keyboard,
            )
        elif data.get("sticker_id"):
            await bot.send_sticker(chat_id=CHANNEL_ID, sticker=data["sticker_id"])
            msg = await bot.send_message(chat_id=CHANNEL_ID, text="​", reply_markup=keyboard)
        elif info:
            msg = await bot.send_message(
                chat_id=CHANNEL_ID,
                text=info,
                parse_mode="HTML",
                reply_markup=keyboard,
            )
        
        if msg:
            sent_msg_id = msg.message_id
            
    # Now that we have the sent_msg_id, we can append it to the contact button URLs
    if sent_msg_id:
        post_url = ""
        channel_str = str(CHANNEL_ID)
        if channel_str == "-1001535612806" or "useacareercenter" in channel_str:
            post_url = f"https://t.me/useacareercenter/{sent_msg_id}"
        elif channel_str.startswith("-100"):
            post_url = f"https://t.me/c/{channel_str[4:]}/{sent_msg_id}"
        elif channel_str.startswith("@"):
            post_url = f"https://t.me/{channel_str[1:]}/{sent_msg_id}"
        else:
            post_url = f"https://t.me/useacareercenter/{sent_msg_id}"

        new_keyboard = get_contact_keyboard(
            post_url=post_url,
            post_text=info,
            post_id=str(sent_msg_id),
            enable_tracking=True,
        )
        if new_keyboard:
            try:
                await bot.edit_message_reply_markup(
                    chat_id=CHANNEL_ID,
                    message_id=sent_msg_id,
                    reply_markup=new_keyboard
                )
            except Exception as e:
                logger.warning("Failed to edit reply markup to add post URL: %s", e)

    # Immediately after post is published, clear dynamic apply contacts from storage
    # so they are not reused for future posts, waiting for admin to set new contacts.
    clear_dynamic_contacts_after_post()


async def confirm_post(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    await query.answer()
    logger.info("confirm_post triggered with data: %s", query.data)

    if not query.data.endswith("_yes"):
        await query.edit_message_text("❌ បានបោះបង់ការបង្ហោះ។")
        context.user_data.clear()
        return ConversationHandler.END

    await query.edit_message_text("⏳ កំពុងបញ្ជូនទៅកាន់ Channel/Group...")

    try:
        await _publish_data_to_channel(context.bot, context.user_data)
        await query.edit_message_text(
            "🎉 បានបញ្ជូនព័ត៌មានទៅកាន់ Channel ដោយជោគជ័យ!\n\n"
            "💡 Contact សម្រាប់ Post នេះត្រូវបានសម្អាតរួចរាល់ (Bot នឹងរង់ចាំការកំណត់ Contact ថ្មីសម្រាប់ Post បន្ទាប់)។"
        )
        logger.info("Successfully published post to Channel/Group ID %s", CHANNEL_ID)
    except Exception as e:
        logger.error("Failed to send to channel/group: %s", e, exc_info=True)
        await query.edit_message_text(
            f"⚠️ បរាជ័យក្នុងការបញ្ជូនទៅ Channel/Group (ID: {CHANNEL_ID})។\n\n"
            f"Error: {e}\n\n"
            f"👉 សូមពិនិត្យមើល:\n"
            f"1. Bot ត្រូវបាន Add ចូល Channel/Group រួចរាល់\n"
            f"2. Bot មានសិទ្ធិជា Administrator (Post/Send Messages)\n"
            f"3. CHANNEL_ID ក្នុង .env ត្រឹមត្រូវ"
        )

    context.user_data.clear()
    return ConversationHandler.END


async def cancel(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    context.user_data.clear()
    await update.message.reply_text("❌ បានបោះបង់ដំណើរការ។")
    return ConversationHandler.END


# ------------------------------------------------------------------
# Standalone Messages / Direct Forwards (Always Confirm Before Send)
# ------------------------------------------------------------------
async def handle_standalone_message(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """When admin sends or forwards any message directly without /post command."""
    user = update.effective_user
    if not is_admin(user.id):
        return

    msg = update.message

    # Check if this plain text message is intended to cancel
    if msg.text and not msg.photo and msg.text.strip().lower() in ("cancel", "/cancel", "cancel contact", "/cancelcontact", "បោះបង់"):
        context.user_data.clear()
        await update.message.reply_text("❌ បានបោះបង់ដំណើរការ (Cancelled)។")
        return

    # Check if this plain text message is intended to set or clear contact buttons
    if msg.text and not msg.photo and is_contact_setting_text(msg.text):
        ok = await apply_contacts_and_reply(update, msg.text)
        if ok:
            return

    await _save_and_preview_post(update, context, msg)

    confirm_keyboard = InlineKeyboardMarkup([
        [
            InlineKeyboardButton("✅ YES — បញ្ជូនទៅ Channel", callback_data="standalone_confirm_yes", api_kwargs={"style": "success"}),
            InlineKeyboardButton("❌ NO — បោះបង់", callback_data="standalone_confirm_no", api_kwargs={"style": "danger"}),
        ]
    ])
    await update.message.reply_text(
        "✅ **មើលទម្រង់សារមុនបង្ហោះ (Preview)**\n❓ តើអ្នកពិតជាចង់បង្ហោះសារនេះទៅកាន់ Channel ដែរឬទេ?",
        reply_markup=confirm_keyboard,
        parse_mode="Markdown",
    )


async def standalone_confirm_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    await query.answer()
    logger.info("standalone_confirm_callback triggered with data: %s", query.data)

    if not query.data.endswith("_yes"):
        await query.edit_message_text("❌ បានបោះបង់ការបង្ហោះ។")
        context.user_data.clear()
        return

    if not context.user_data.get("source_message_id") and not context.user_data.get("info"):
        await query.edit_message_text("⚠️ ព័ត៌មានសារនេះហួសសុពលភាពហើយ។ សូមផ្ញើសារថ្មីម្តងទៀត។")
        return

    await query.edit_message_text("⏳ កំពុងបញ្ជូនទៅកាន់ Channel/Group...")

    try:
        await _publish_data_to_channel(context.bot, context.user_data)
        await query.edit_message_text(
            "🎉 បានបញ្ជូនព័ត៌មានទៅកាន់ Channel ដោយជោគជ័យ!\n\n"
            "💡 Contact សម្រាប់ Post នេះត្រូវបានសម្អាតរួចរាល់ (Bot នឹងរង់ចាំការកំណត់ Contact ថ្មីសម្រាប់ Post បន្ទាប់)។"
        )
        logger.info("Successfully published post to Channel/Group ID %s", CHANNEL_ID)
    except Exception as e:
        logger.error("Failed to send standalone to channel/group: %s", e, exc_info=True)
        await query.edit_message_text(
            f"⚠️ បរាជ័យក្នុងការបញ្ជូនទៅ Channel/Group (ID: {CHANNEL_ID})។\n\n"
            f"Error: {e}\n\n"
            f"👉 សូមពិនិត្យមើល:\n"
            f"1. Bot ត្រូវបាន Add ចូល Channel/Group រួចរាល់\n"
            f"2. Bot មានសិទ្ធិជា Administrator (Post/Send Messages)\n"
            f"3. CHANNEL_ID ក្នុង .env ត្រឹមត្រូវ"
        )

    context.user_data.clear()


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user = update.effective_user
    args = context.args or []
    arg = args[0] if args else ""

    # 1. Handle native Telegram deep-link button clicks from channel posts (Option 1)
    if arg:
        post_id = ""
        action = arg
        if "_" in arg:
            parts = arg.split("_", 1)
            action = parts[0]
            post_id = parts[1]

        post_link = f"https://t.me/useacareercenter/{post_id}" if post_id else ""
        username_str = f"@{user.username}" if user.username else "គ្មាន (No username)"
        user_disp = f"{user.full_name} ({username_str})"

        # A. Clicked "📞 Contact Admin"
        if action == "admin":
            admin_msg = (
                f"ជម្រាបសួរបង ខ្ញុំចាប់អារម្មណ៍នឹងការងារនេះ: 🔗 {post_link}"
                if post_link
                else "ជម្រាបសួរបង ខ្ញុំចាប់អារម្មណ៍នឹងការងារនេះ"
            )
            import urllib.parse
            encoded_text = urllib.parse.quote(admin_msg)
            sep = "&" if "?" in STATIC_ADMIN_BUTTON_URL else "?"
            admin_direct_url = f"{STATIC_ADMIN_BUTTON_URL}{sep}text={encoded_text}"

            record_telegram_button_click(
                link_type="admin",
                user_id=user.id,
                user_display=user_disp,
                label=STATIC_ADMIN_BUTTON_LABEL,
                post_id=post_id,
                post_url=post_link,
                target_url=admin_direct_url,
            )

            kb = [
                [
                    InlineKeyboardButton(
                        "💬 ផ្ញើសារទៅកាន់ Admin @USEACCAD",
                        url=admin_direct_url,
                        api_kwargs={"style": "success"},
                    )
                ]
            ]
            if post_link:
                kb.append([
                    InlineKeyboardButton(
                        "📢 មើលការងារក្នុង Channel",
                        url=post_link,
                        api_kwargs={"style": "primary"},
                    )
                ])

            resp_text = (
                f"👋 <b>សួស្តី {user.first_name}!</b>\n\n"
                f"សូមចុចប៊ូតុងខាងក្រោមដើម្បីផ្ញើសារទាក់ទងទៅកាន់ Admin USEA Career Center ផ្ទាល់៖\n"
                f"(Click button below to message Admin):"
            )
            if post_link:
                resp_text += f"\n\n🔗 <b>ការងារដែលចាប់អារម្មណ៍:</b> {post_link}"

            await update.message.reply_text(
                resp_text,
                reply_markup=InlineKeyboardMarkup(kb),
                parse_mode="HTML",
                disable_web_page_preview=True,
            )
            return

        # B. Clicked "Apply Now" (Employer contact)
        elif action in ("apply", "employer"):
            data = load_contact_data()
            apply_contacts = data.get("apply_contacts", DEFAULT_APPLY_CONTACTS)
            employer = apply_contacts.get("employer", {})
            emp_url = (employer.get("url") or "").strip()
            emp_label = (employer.get("label") or "").strip() or "🏢 ទំនាក់ទំនងកន្លែងជ្រើសរើសបុគ្គលិក (Place Looking for Staff)"

            record_telegram_button_click(
                link_type="employer",
                user_id=user.id,
                user_display=user_disp,
                label=emp_label,
                post_id=post_id,
                post_url=post_link,
                target_url=emp_url,
            )

            kb = []
            if emp_url:
                kb.append([
                    InlineKeyboardButton(
                        f"👉 {emp_label}",
                        url=emp_url,
                        api_kwargs={"style": "danger"},
                    )
                ])

            admin_msg = (
                f"ជម្រាបសួរបង ខ្ញុំចាប់អារម្មណ៍នឹងការងារនេះ: 🔗 {post_link}"
                if post_link
                else "ជម្រាបសួរបង ខ្ញុំចាប់អារម្មណ៍នឹងការងារនេះ"
            )
            import urllib.parse
            encoded_text = urllib.parse.quote(admin_msg)
            sep = "&" if "?" in STATIC_ADMIN_BUTTON_URL else "?"
            admin_direct_url = f"{STATIC_ADMIN_BUTTON_URL}{sep}text={encoded_text}"
            kb.append([
                InlineKeyboardButton(
                    "👤 ទំនាក់ទំនង Admin USEA Career Center",
                    url=admin_direct_url,
                    api_kwargs={"style": "success"},
                )
            ])
            if post_link:
                kb.append([
                    InlineKeyboardButton(
                        "📢 មើលការងារក្នុង Channel",
                        url=post_link,
                        api_kwargs={"style": "primary"},
                    )
                ])

            resp_text = (
                f"💼 <b>ដាក់ពាក្យស្នើសុំការងារ / Job Application</b>\n\n"
                f"សូមជ្រើសរើសទំនាក់ទំនងខាងក្រោមដើម្បីដាក់ពាក្យ៖\n"
                f"(Please choose a contact below to apply):"
            )
            if post_link:
                resp_text += f"\n\n🔗 <b>ការងារ:</b> {post_link}"

            await update.message.reply_text(
                resp_text,
                reply_markup=InlineKeyboardMarkup(kb),
                parse_mode="HTML",
                disable_web_page_preview=True,
            )

            # Notify admins about the applicant
            applicant_alert = (
                f"👤 <b>បេក្ខជនថ្មីចាប់អារម្មណ៍ការងារ (New Applicant!)</b>\n\n"
                f"• ឈ្មោះ: {user.full_name}\n"
                f"• Username: {username_str}\n"
                f"• Profile: <a href='tg://user?id={user.id}'>ចុចមើល Profile</a>"
            )
            if post_link:
                applicant_alert += f"\n• ការងារ: {post_link}"

            for aid in ADMIN_IDS:
                try:
                    await context.bot.send_message(chat_id=aid, text=applicant_alert, parse_mode="HTML")
                except Exception:
                    pass
            return

        # C. Clicked "Career Tips, CV & Cover Letter"
        elif action in ("tips", "bot"):
            record_telegram_button_click(
                link_type="bot",
                user_id=user.id,
                user_display=user_disp,
                label=STATIC_BOT_BUTTON_LABEL,
                post_id=post_id,
                post_url=post_link,
                target_url=STATIC_BOT_BUTTON_URL,
            )
            kb = [
                [
                    InlineKeyboardButton(
                        "🚀 ចូលទៅកាន់ Bot @USEACCASTbot",
                        url=STATIC_BOT_BUTTON_URL,
                        api_kwargs={"style": "primary"},
                    )
                ]
            ]
            resp_text = (
                f"👋 <b>សួស្តី {user.first_name}!</b>\n\n"
                f"🤖 <b>Career Tips, CV & Cover Letter Bot</b>\n\n"
                f"សូមចុចប៊ូតុងខាងក្រោមដើម្បីចូលទៅកាន់ Bot គន្លឹះការងារ រៀនសរសេរ CV និង Cover Letter ឥតគិតថ្លៃ៖\n"
                f"(Click button below to access career tips, CV & Cover letter):"
            )
            await update.message.reply_text(
                resp_text,
                reply_markup=InlineKeyboardMarkup(kb),
                parse_mode="HTML",
            )
            return

    # 2. Non-admin visitor
    if not is_admin(user.id):
        await update.message.reply_text(
            f"👋 សួស្តី {user.first_name}! ខ្ញុំជា USEA Career Center Bot។\n\n"
            "📢 សូមតាមដានឱកាសការងារ និងព័ត៌មានអាជីពនៅទីនេះ៖\n"
            "👉 https://t.me/useacareercenter"
        )
        return

    # 3. Admin user
    await update.message.reply_text(
        "👋 សួស្តី Admin! ខ្ញុំជា Bot សម្រាប់ទម្លាក់ព័ត៌មានការងារ។\n\n"
        "Admin អាចប្រើ:\n"
        "• /post — បង្ហោះការងារថ្មី (ផ្ញើព័ត៌មាន/រូបភាព ក្នុងសារតែមួយ)\n"
        "• /setcontact — កំណត់ Contact សម្រាប់ប៊ូតុង Apply Now (បើមិនកំណត់ ឬលុប ប៊ូតុងនឹងបាត់)\n"
        "• /clearcontact — លុប Contact (ធ្វើឱ្យប៊ូតុង Apply Now បាត់)\n"
        "• /showcontact — មើលទម្រង់ប៊ូតុងបច្ចុប្បន្ន\n"
        "• /report — មើលរបាយការណ៍ចំនួនអ្នកចុចលើប៊ូតុងនីមួយៗប្រចាំខែ (Button Clicks Report)\n"
        "• ឬ forward សារណាមួយមក bot ដោយផ្ទាល់ (bot នឹងសួរ confirm មុន post)"
    )


# ------------------------------------------------------------------
# Report & Analytics Helpers & Commands
# ------------------------------------------------------------------
def build_report_month_keyboard(current_selected_month: str = None) -> InlineKeyboardMarkup:
    """Build inline keyboard allowing admin to pick any month or all-time."""
    months = get_available_months()
    keyboard_rows = []

    # 2 buttons per row
    row = []
    now_month = datetime.now().strftime("%Y-%m")
    for m in months[:8]:
        label = f"📅 {m}"
        if m == now_month:
            label += " (ខែនេះ)"
        if m == current_selected_month:
            label = f"✅ {label}"
        row.append(InlineKeyboardButton(label, callback_data=f"rep_month:{m}"))
        if len(row) == 2:
            keyboard_rows.append(row)
            row = []
    if row:
        keyboard_rows.append(row)

    all_label = "📈 គ្រប់ខែទាំងអស់ (All-Time)"
    if current_selected_month == "all":
        all_label = f"✅ {all_label}"
    keyboard_rows.append([InlineKeyboardButton(all_label, callback_data="rep_month:all")])

    target = current_selected_month or now_month
    keyboard_rows.append([
        InlineKeyboardButton(f"📥 ទាញយក CSV ({target})", callback_data=f"rep_csv:{target}")
    ])

    return InlineKeyboardMarkup(keyboard_rows)


def build_report_view_keyboard(month: str) -> InlineKeyboardMarkup:
    """Build action buttons when viewing a specific month report."""
    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton("📥 ទាញយកជា CSV", callback_data=f"rep_csv:{month}"),
            InlineKeyboardButton("🔄 Refresh", callback_data=f"rep_month:{month}"),
        ],
        [
            InlineKeyboardButton("🔙 ជ្រើសរើសខែផ្សេង (Choose Another Month)", callback_data="rep_home"),
        ],
    ])


async def send_csv_report_file(update: Update, context: ContextTypes.DEFAULT_TYPE, month: str) -> None:
    """Generate and send CSV report directly to admin chat."""
    csv_bytes = generate_csv_report(month=month)
    filename = f"button_clicks_{month}.csv"
    chat_id = update.effective_chat.id

    caption = (
        f"📥 <b>របាយការណ៍ស្ថិតិចុចលើប៊ូតុងនីមួយៗ (Button Click Report)</b>\n"
        f"📅 ប្រចាំ: <code>{month}</code>\n"
        f"💡 ឯកសារនេះអាចបើកមើលក្នុង Microsoft Excel បានយ៉ាងស្រួល។"
    )
    await context.bot.send_document(
        chat_id=chat_id,
        document=io.BytesIO(csv_bytes),
        filename=filename,
        caption=caption,
        parse_mode="HTML",
    )


async def report_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user = update.effective_user
    if not is_admin(user.id):
        await update.message.reply_text("⚠️ បញ្ជានេះសម្រាប់តែ Admin ប៉ុណ្ណោះ (Admins only)។")
        return

    args = context.args or []
    now_month = datetime.now().strftime("%Y-%m")

    # If admin types /report csv or /report csv 2026-10
    if args and args[0].lower() == "csv":
        target_month = args[1] if len(args) > 1 else now_month
        await send_csv_report_file(update, context, target_month)
        return

    if not args:
        # Show interactive month selector with current month's report
        rep_data = get_monthly_report_data(now_month)
        text = format_telegram_report(rep_data, webhook_url=WEBHOOK_URL)
        keyboard = build_report_month_keyboard(current_selected_month=now_month)
    else:
        # User specified a month, e.g. /report 2026-10 or /report all
        target_month = args[0]
        rep_data = get_monthly_report_data(target_month)
        text = format_telegram_report(rep_data, webhook_url=WEBHOOK_URL)
        keyboard = build_report_view_keyboard(target_month)

    await update.message.reply_text(
        text,
        reply_markup=keyboard,
        parse_mode="HTML",
        disable_web_page_preview=True,
    )


async def report_callback_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    user = update.effective_user

    if not is_admin(user.id):
        await query.answer("⚠️ សុំទោស អ្នកមិនមែនជា Admin ទេ (Admins only)!", show_alert=True)
        return

    data = query.data or ""
    await query.answer()

    if data == "rep_home":
        now_month = datetime.now().strftime("%Y-%m")
        rep_data = get_monthly_report_data(now_month)
        text = format_telegram_report(rep_data, webhook_url=WEBHOOK_URL)
        kb = build_report_month_keyboard(current_selected_month=now_month)
        try:
            await query.edit_message_text(
                text,
                reply_markup=kb,
                parse_mode="HTML",
                disable_web_page_preview=True,
            )
        except Exception:
            pass
    elif data.startswith("rep_month:"):
        month = data.split(":", 1)[1]
        rep_data = get_monthly_report_data(month)
        text = format_telegram_report(rep_data, webhook_url=WEBHOOK_URL)
        kb = build_report_view_keyboard(month)
        try:
            await query.edit_message_text(
                text,
                reply_markup=kb,
                parse_mode="HTML",
                disable_web_page_preview=True,
            )
        except Exception:
            pass
    elif data.startswith("rep_csv:"):
        month = data.split(":", 1)[1]
        await send_csv_report_file(update, context, month)


async def get_emoji_id_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Helper command for admins to extract custom_emoji_id from any Telegram Premium animated emoji."""
    user = update.effective_user
    if not is_admin(user.id):
        await update.message.reply_text("⚠️ បញ្ជានេះសម្រាប់តែ Admin ប៉ុណ្ណោះ (Admins only)។")
        return

    msg = update.message
    target_msg = msg.reply_to_message or msg
    entities = target_msg.entities or target_msg.caption_entities or []

    found_ids = []
    for ent in entities:
        if ent.type == "custom_emoji" and ent.custom_emoji_id:
            found_ids.append(ent.custom_emoji_id)

    if found_ids:
        ids_text = "\n".join([f"• <code>{eid}</code>" for eid in found_ids])
        await update.message.reply_text(
            f"🎉 <b>រកឃើញ Custom Animated Emoji ID:</b>\n\n{ids_text}\n\n"
            f"💡 <b>របៀបប្រើប្រាស់ក្នុង <code>.env</code>:</b>\n"
            f"• Contact Admin: <code>ADMIN_CONTACT={found_ids[0]}</code>\n"
            f"• Apply Now: <code>ADMIN_APPLY_NOW={found_ids[0]}</code>\n"
            f"• CV & Tips: <code>ADMIN_CV={found_ids[0]}</code>",
            parse_mode="HTML",
        )
    else:
        await update.message.reply_text(
            "ℹ️ <b>របៀបស្វែងរក Animated Emoji ID:</b>\n\n"
            "1. ផ្ញើ Animated Emoji ពី Telegram Premium របស់អ្នកមកកាន់ Bot នេះ (ឬ Reply លើសារនោះជាមួយ <code>/getemoji</code>)\n"
            "2. Bot នឹងបង្ហាញលេខ ID សម្រាប់អ្នកយកទៅដាក់ក្នុង <code>.env</code> (ADMIN_CONTACT=...) ភ្លាមៗ!",
            parse_mode="HTML",
        )


async def backup_clicks_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Send live clicks.json directly to admin chat as a backup file."""
    user = update.effective_user
    if not is_admin(user.id):
        await update.message.reply_text("⚠️ បញ្ជានេះសម្រាប់តែ Admin ប៉ុណ្ណោះ (Admins only)។")
        return

    data = load_click_data()
    data_bytes = json.dumps(data, ensure_ascii=False, indent=2).encode("utf-8")
    now_str = datetime.now().strftime("%Y-%m-%d_%H%M%S")
    filename = f"clicks_backup_{now_str}.json"

    total_links = len(data.get("links", {}))
    curr_m = datetime.now().strftime("%Y-%m")
    m_clicks = data.get("months", {}).get(curr_m, {}).get("total_clicks", 0)

    caption = (
        f"📦 <b>Backup ទិន្នន័យ Clicks Tracker ({now_str})</b>\n\n"
        f"🔗 Links សរុប: <b>{total_links}</b>\n"
        f"📊 Clicks ខែនេះ ({curr_m}): <b>{m_clicks}</b>\n\n"
        f"💡 <b>របៀបការពារទិន្នន័យពេល redeploy:</b>\n"
        f"1. មុនពេល update code ទៅ GitHub ចុច save file នេះទុក\n"
        f"2. ឬប្រសិនបើ redeploy នៅ Render ហើយឃើញ click បាត់ សូមគ្រាន់តែផ្ញើ file នេះត្រឡប់មក bot វិញ "
        f"ជាមួយ caption <code>/restore</code> នោះ Bot នឹង merge ស្តារទិន្នន័យទាំងអស់មកវិញភ្លាមៗ 100%!"
    )
    await context.bot.send_document(
        chat_id=update.effective_chat.id,
        document=io.BytesIO(data_bytes),
        filename=filename,
        caption=caption,
        parse_mode="HTML",
    )


async def restore_clicks_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Restore and merge clicks.json from an uploaded file."""
    user = update.effective_user
    if not is_admin(user.id):
        await update.message.reply_text("⚠️ បញ្ជានេះសម្រាប់តែ Admin ប៉ុណ្ណោះ (Admins only)។")
        return

    msg = update.message
    doc = msg.document
    if not doc and msg.reply_to_message and msg.reply_to_message.document:
        doc = msg.reply_to_message.document

    if not doc or not (doc.file_name or "").lower().endswith(".json"):
        await msg.reply_text(
            "⚠️ <b>របៀប Restore ទិន្នន័យ Clicks:</b>\n\n"
            "សូមផ្ញើ file <code>clicks.json</code> មកកាន់ Bot នេះ "
            "ហើយដាក់ Caption <code>/restore</code> ឬ Reply លើ file នោះជាមួយ command <code>/restore</code>។",
            parse_mode="HTML",
        )
        return

    try:
        file_obj = await context.bot.get_file(doc.file_id)
        content_bytes = await file_obj.download_as_bytearray()
        incoming = json.loads(content_bytes.decode("utf-8"))

        if not isinstance(incoming, dict) or ("links" not in incoming and "months" not in incoming):
            await msg.reply_text("❌ File នេះមិនមែនជាទម្រង់ clicks.json ត្រឹមត្រូវទេ។")
            return

        current = load_click_data()
        merged = merge_click_data(current, incoming)
        save_click_data(merged)

        total_links = len(merged.get("links", {}))
        curr_m = datetime.now().strftime("%Y-%m")
        m_clicks = merged.get("months", {}).get(curr_m, {}).get("total_clicks", 0)

        await msg.reply_text(
            f"🎉 <b>បាន Restore & Merge ទិន្នន័យ Clicks ដោយជោគជ័យ!</b>\n\n"
            f"🔗 Links សរុបក្នុងប្រព័ន្ធ: <b>{total_links}</b>\n"
            f"📊 Clicks ខែនេះ ({curr_m}): <b>{m_clicks}</b>\n"
            f"💾 រាល់ click counts ទាំងអស់ត្រូវបានបញ្ចូលរួមគ្នា ដោយមិនបាត់បង់ទិន្នន័យចាស់ឡើយ!",
            parse_mode="HTML",
        )
    except Exception as err:
        logger.error("Restore clicks failed: %s", err, exc_info=True)
        await msg.reply_text(f"❌ បរាជ័យក្នុងការ Restore: {err}")


async def auto_backup_clicks_job(context: ContextTypes.DEFAULT_TYPE) -> None:
    """Daily silent auto-backup of clicks.json to primary admin."""
    try:
        primary_admin_id = 8824663759
        data = load_click_data()
        now_str = datetime.now().strftime("%Y-%m-%d")
        data_bytes = json.dumps(data, ensure_ascii=False, indent=2).encode("utf-8")
        await context.bot.send_document(
            chat_id=primary_admin_id,
            document=io.BytesIO(data_bytes),
            filename=f"clicks_auto_backup_{now_str}.json",
            caption=f"🤖 <b>Auto-Backup Tracker Data ({now_str})</b>\n💡 សារ Backup ប្រចាំថ្ងៃសម្រាប់ទុក Restore ពេល redeploy។",
            parse_mode="HTML",
            disable_notification=True,
        )
    except Exception as e:
        logger.debug("Auto backup job notice: %s", e)


def setup_webhook_health_routes() -> None:
    """
    Patch python-telegram-bot's internal Tornado webhook server to provide
    HTTP GET/HEAD routes for root '/' (Render URL & health check), '/health',
    and '/ping', preventing 404 errors when visiting the URL on Render.
    """
    try:
        import telegram.ext._utils.webhookhandler as ptb_webhook
        import tornado.web

        class HealthCheckHandler(tornado.web.RequestHandler):
            def get(self):
                accept_header = self.request.headers.get("Accept", "")
                if "application/json" in accept_header:
                    self.set_header("Content-Type", "application/json; charset=utf-8")
                    self.write(json.dumps({"status": "ok", "service": "USEA Career Center Bot"}))
                    return

                self.set_header("Content-Type", "text/html; charset=utf-8")
                self.write(
                    """<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>USEA Career Center Bot - Status</title>
    <style>
        body {
            font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, Helvetica, Arial, sans-serif;
            background: #0f172a;
            color: #f8fafc;
            display: flex;
            align-items: center;
            justify-content: center;
            min-height: 100vh;
            margin: 0;
            padding: 20px;
            box-sizing: border-box;
        }
        .card {
            background: #1e293b;
            border: 1px solid #334155;
            border-radius: 16px;
            padding: 32px;
            max-width: 480px;
            width: 100%;
            text-align: center;
            box-shadow: 0 10px 25px -5px rgba(0, 0, 0, 0.3);
        }
        .status-badge {
            display: inline-flex;
            align-items: center;
            gap: 8px;
            background: #064e3b;
            color: #34d399;
            padding: 6px 16px;
            border-radius: 9999px;
            font-size: 14px;
            font-weight: 600;
            margin-bottom: 20px;
        }
        .status-dot {
            width: 8px;
            height: 8px;
            background: #10b981;
            border-radius: 50%;
            box-shadow: 0 0 8px #10b981;
        }
        h1 {
            font-size: 24px;
            margin: 0 0 12px;
            color: #ffffff;
        }
        p {
            color: #94a3b8;
            line-height: 1.6;
            margin: 0 0 24px;
        }
        .btn {
            display: inline-block;
            background: #2563eb;
            color: #ffffff;
            text-decoration: none;
            padding: 10px 24px;
            border-radius: 8px;
            font-weight: 500;
            transition: background 0.2s;
        }
        .btn:hover {
            background: #1d4ed8;
        }
    </style>
</head>
<body>
    <div class="card">
        <div class="status-badge">
            <span class="status-dot"></span>
            Online &amp; Healthy
        </div>
        <h1>USEA Career Center Bot</h1>
        <p>The Telegram Job Posting Bot is live and running smoothly on Render.</p>
        <a href="https://t.me/useacareercenter" class="btn" target="_blank">Visit Telegram Channel</a>
    </div>
</body>
</html>"""
                )

            def head(self):
                self.set_status(200)

        class JsonHealthHandler(tornado.web.RequestHandler):
            def get(self):
                self.set_header("Content-Type", "application/json; charset=utf-8")
                self.write(json.dumps({"status": "ok", "service": "USEA Career Center Bot"}))

            def head(self):
                self.set_status(200)

        class FaviconHandler(tornado.web.RequestHandler):
            def get(self):
                self.set_status(204)

        _original_init = ptb_webhook.WebhookAppClass.__init__

        def _patched_webhook_init(self, webhook_path: str, bot, update_queue, secret_token=None):
            _original_init(self, webhook_path, bot, update_queue, secret_token)
            self.add_handlers(
                r".*",
                [
                    (r"/?$", HealthCheckHandler),
                    (r"/health(?:z)?/?", JsonHealthHandler),
                    (r"/ping/?", HealthCheckHandler),
                    (r"/favicon\.ico", FaviconHandler),
                    (r"/r/(?P<token>[^/]+)/?", RedirectTrackerHandler),
                    (r"/report/?", WebReportHandler),
                    (r"/report/csv/?", WebCsvExportHandler),
                    (r"/report/clicks\.json/?", WebClicksJsonHandler),
                ],
            )

        ptb_webhook.WebhookAppClass.__init__ = _patched_webhook_init

        # Support GET/HEAD on the webhook endpoint so visiting the webhook path directly
        # in a browser returns 200 OK instead of 405 Method Not Allowed
        def _telegram_get(self):
            self.set_header("Content-Type", "text/plain; charset=utf-8")
            self.write("USEA Career Center Bot webhook is active.")

        ptb_webhook.TelegramHandler.SUPPORTED_METHODS = ("POST", "GET", "HEAD")
        ptb_webhook.TelegramHandler.get = _telegram_get
        ptb_webhook.TelegramHandler.head = lambda self: self.set_status(200)

        logger.info("Configured web routes: /, /health, /ping, /r/, /report, /report/csv")
    except Exception as exc:
        logger.warning("Could not setup webhook health routes: %s", exc)


def start_local_tracking_server_if_needed(port: int = 10000) -> None:
    """Start lightweight local Tornado server in polling mode so /r/ and /report work locally."""
    is_render = bool(os.getenv("RENDER") or os.getenv("RENDER_EXTERNAL_URL") or os.getenv("USE_WEBHOOK"))
    if is_render:
        return

    import threading
    import tornado.ioloop
    import tornado.web

    local_app = tornado.web.Application([
        (r"/r/(?P<token>[^/]+)/?", RedirectTrackerHandler),
        (r"/report/?", WebReportHandler),
        (r"/report/csv/?", WebCsvExportHandler),
        (r"/report/clicks\.json/?", WebClicksJsonHandler),
    ])

    def _run():
        try:
            loop = tornado.ioloop.IOLoop()
            loop.make_current()
            local_app.listen(port)
            logger.info("Local tracking server running on http://127.0.0.1:%s", port)
            loop.start()
        except Exception as e:
            logger.warning("Could not start local tracking server on port %s: %s", port, e)

    t = threading.Thread(target=_run, daemon=True)
    t.start()


def main() -> None:
    app = ApplicationBuilder().token(BOT_TOKEN).build()

    if app.job_queue:
        app.job_queue.run_repeating(auto_backup_clicks_job, interval=86400, first=3600)

    # Conversation handler សម្រាប់ /setcontact (ការពារកុំឱ្យច្រឡំផ្ញើជា post ពេលកំពុង edit)
    contact_conv_handler = ConversationHandler(
        entry_points=[CommandHandler("setcontact", set_contact_start)],
        states={
            SETTING_CONTACT: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, set_contact_process)
            ],
        },
        fallbacks=[
            CommandHandler("cancel", cancel_contact),
            CommandHandler("setcontact", set_contact_start),
            CommandHandler("clearcontact", clear_contact_command),
        ],
        allow_reentry=True,
        conversation_timeout=600,
        per_message=False,
    )

    # Conversation handler សម្រាប់ /post
    post_conv_handler = ConversationHandler(
        entry_points=[CommandHandler("post", post_start)],
        states={
            CONTENT: [
                MessageHandler(
                    filters.ALL & ~filters.COMMAND,
                    get_content,
                ),
            ],
            CONFIRM: [CallbackQueryHandler(confirm_post, pattern="^(confirm|standalone_confirm)_(yes|no)$")],
        },
        fallbacks=[
            CommandHandler("cancel", cancel),
            CommandHandler("post", post_start),
        ],
        allow_reentry=True,
        conversation_timeout=600,
        per_message=False,
    )

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("cancel", cancel_all_command))
    app.add_handler(CommandHandler("showcontact", show_contact))
    app.add_handler(CommandHandler("clearcontact", clear_contact_command))
    app.add_handler(CommandHandler("getemoji", get_emoji_id_command))
    app.add_handler(CommandHandler("emoji", get_emoji_id_command))
    app.add_handler(CommandHandler("setemail", set_email_command))
    app.add_handler(CommandHandler("clearemail", clear_email_command))
    app.add_handler(CommandHandler("report", report_command))
    app.add_handler(CommandHandler("reports", report_command))
    app.add_handler(CommandHandler("stats", report_command))
    app.add_handler(CommandHandler(["backup", "backupclicks", "exportclicks"], backup_clicks_command))
    app.add_handler(CommandHandler(["restore", "restoreclicks", "importclicks"], restore_clicks_command))
    app.add_handler(
        MessageHandler(
            filters.Document.FileExtension("json") & filters.ChatType.PRIVATE,
            restore_clicks_command,
        )
    )
    app.add_handler(
        CallbackQueryHandler(
            report_callback_handler, pattern="^rep_(home|month|csv):?.*$"
        )
    )
    app.add_handler(contact_conv_handler)
    app.add_handler(post_conv_handler)
    app.add_handler(CallbackQueryHandler(handle_contact_admin, pattern="^contact_admin_8824663759$"))
    app.add_handler(
        CallbackQueryHandler(
            standalone_confirm_callback, pattern="^(confirm|standalone_confirm)_(yes|no)$"
        )
    )
    app.add_handler(
        MessageHandler(
            (filters.ALL & ~filters.COMMAND) & filters.ChatType.PRIVATE,
            handle_standalone_message,
        )
    )
    # Fallback to answer any expired/unhandled button clicks immediately so it never spins/glows indefinitely
    async def fallback_expired_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        query = update.callback_query
        if query:
            await query.answer("⚠️ ប៊ូតុងនេះហួសសុពលភាពហើយ (bot ត្រូវបាន restart)។ សូមផ្ញើសារម្តងទៀត។", show_alert=True)
            try:
                await query.edit_message_text("⚠️ ព័ត៌មានសារនេះហួសសុពលភាពហើយ។ សូមផ្ញើសារថ្មីម្តងទៀត។")
            except Exception:
                pass

    app.add_handler(CallbackQueryHandler(fallback_expired_callback))

    is_render = bool(os.getenv("RENDER") or os.getenv("RENDER_EXTERNAL_URL") or os.getenv("USE_WEBHOOK"))

    if is_render and WEBHOOK_URL:
        setup_webhook_health_routes()
        logger.info("Bot is running with Webhook on Render (%s)...", WEBHOOK_URL)
        app.run_webhook(
            listen="0.0.0.0",
            port=int(os.getenv("PORT", 10000)),
            url_path=BOT_TOKEN,
            webhook_url=f"{WEBHOOK_URL}/{BOT_TOKEN}",
            allowed_updates=Update.ALL_TYPES,
            drop_pending_updates=True,
        )
    else:
        start_local_tracking_server_if_needed(port=int(os.getenv("PORT", 10000)))
        logger.info("Bot is running with Polling (Local Development Mode)...")
        app.run_polling(drop_pending_updates=True, allowed_updates=Update.ALL_TYPES)


if __name__ == "__main__":
    main()