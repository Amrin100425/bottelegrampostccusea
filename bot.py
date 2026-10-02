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

import json
import logging
import os
import re
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

# ------------------------------------------------------------------
# ការកំណត់រចនាសម្ព័ន្ធ (CONFIG)
# ------------------------------------------------------------------
BOT_TOKEN = os.getenv("BOT_TOKEN")
raw_channel = os.getenv("CHANNEL_ID")
if raw_channel:
    try:
        CHANNEL_ID = int(raw_channel)
    except ValueError:
        CHANNEL_ID = raw_channel
else:
    CHANNEL_ID = None

try:
    admin_env = os.getenv("ADMIN_IDS", "[1147056937, 468517256, 1287745757, 8824663759]")
    ADMIN_IDS = json.loads(admin_env) if admin_env.startswith("[") else [int(x.strip()) for x in admin_env.split(",") if x.strip()]
except Exception:
    ADMIN_IDS = [1147056937, 468517256, 1287745757, 8824663759]
WEBHOOK_URL = (os.getenv("RENDER_EXTERNAL_URL") or os.getenv("WEBHOOK_URL") or "https://bottelegrampostccusea.onrender.com").rstrip("/")

# Contact ដែលថេរ (Fixed) - វានឹងបង្ហាញជានិច្ចនៅខាងក្រោម មិនបាត់បង់ទេ
# FIXED_CONTACT_ROWS = [
#     [{"label": "📞 Contact Us", "url": "https://t.me/USEACCAD"}],
# ]

CONTACT_STORE_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "contact.json")

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
    """បំប្លែង username ឬលេខទូរស័ព្ទ (Telegram/WhatsApp) ឬ Web URL ទៅជា Link ត្រឹមត្រូវសម្រាប់ប៊ូតុង"""
    raw = raw.strip()

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
# Contact Storage (persistent)
# ------------------------------------------------------------------
def load_contact_rows() -> list:
    if os.path.exists(CONTACT_STORE_FILE):
        try:
            with open(CONTACT_STORE_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)
                rows = data.get("rows")
                if rows:
                    return rows
        except Exception as e:
            logger.warning("មិនអាចអាន contact.json បាន: %s", e)
    return []


def save_contact_rows(rows: list) -> None:
    with open(CONTACT_STORE_FILE, "w", encoding="utf-8") as f:
        json.dump({"rows": rows}, f, ensure_ascii=False, indent=2)


def build_keyboard_markup(rows: list) -> InlineKeyboardMarkup:
    kb_rows = []
    for row in rows:
        row_btns = []
        for b in row:
            kwargs = {}
            if b.get("btn_style"):
                kwargs["api_kwargs"] = {"style": b["btn_style"]}
            row_btns.append(InlineKeyboardButton(b["label"], url=b["url"], **kwargs))
        kb_rows.append(row_btns)
    return InlineKeyboardMarkup(kb_rows)


def get_contact_keyboard():
    dynamic_rows = load_contact_rows()
    combined_rows = (dynamic_rows or [])
    if not combined_rows:
        return None
    return build_keyboard_markup(combined_rows)


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


SETCONTACT_HELP = (
    "📌 *របៀបប្រើ /setcontact*\n\n"
    "មួយបន្ទាត់ = មួយជួរប៊ូតុង\n"
    "ប្រើ `|` ដើម្បីដាក់ច្រើនប៊ូតុងក្នុងជួរតែមួយ (រហូតដល់ 3)\n\n"

    "*— 📞 ការប្រើប្រាស់លេខទូរស័ព្ទ (Phone Number) —*\n"
    "អាចដាក់លេខទូរស័ព្ទជំនួស `@username` បានដោយផ្ទាល់:\n"
    "• *Telegram Chat តាមលេខទូរស័ព្ទ*: `012345678` ឬ `098 765 432` ឬ `+85512345678`\n"
    "• *WhatsApp Chat*: `wa:012345678`\n"
    "ឧទាហរណ៍:\n"
    "`ទាក់ទងមកយើង - 012345678 - icon:📞 - color:green`  →  (ចុចទៅ Telegram Chat តាមលេខទូរស័ព្ទ)\n"
    "`WhatsApp - wa:012345678 - icon:💬 - color:green`  →  (ចុចទៅ WhatsApp Chat)\n\n"

    "*— 🎨 1. ពណ៌ផ្ទៃខាងក្រោយប៊ូតុងពេញ (Solid Background Colors) —*\n"
    "• ពណ៌ខៀវ (Blue): `color:blue` ឬ `style:primary` ឬ `ពណ៌:ខៀវ`\n"
    "• ពណ៌ក្រហម (Red): `color:red` ឬ `style:danger` ឬ `ពណ៌:ក្រហម`\n"
    "• ពណ៌បៃតង (Green): `color:green` ឬ `style:success` ឬ `ពណ៌:បៃតង`\n\n"
    "ឧទាហរណ៍:\n"
    "`View my balance - https://example.com - color:green`\n"
    "`Unlock exclusive offers - https://example.com - icon:🎁 - color:blue`\n"
    "`Cancel - 012345678 - icon:🪅 - color:red | Renew - 098765432 - icon:🍿 - color:green`\n\n"

    "*— 🌈 2. ពណ៌បន្ថែម (Pink, Yellow, Purple, Orange...) —*\n"
    "• ពណ៌ផ្កាឈូក (Pink): `color:pink` 🩷 ឬ `color:rose` 🌸 ឬ `ពណ៌:ផ្កាឈូក`\n"
    "• ពណ៌លឿង (Yellow): `color:yellow` 🟨 ឬ `color:gold` 🟨 ឬ `ពណ៌:លឿង`\n"
    "• ពណ៌ស្វាយ (Purple): `color:purple` 🟪\n"
    "• ពណ៌ទឹកក្រូច (Orange): `color:orange` 🟧\n"
    "• ពណ៌ផ្ទៃមេឃ (Cyan): `color:cyan` 🩵\n\n"

    "*— 3. ដាក់ Icon / Emoji —*\n"
    "`ទំនាក់ទំនង - @username - icon:📞 - color:blue`"
)


async def set_contact_start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    user = update.effective_user
    if not is_admin(user.id):
        await update.message.reply_text("❌ អ្នកមិនមានសិទ្ធិប្រើ command នេះទេ។")
        return ConversationHandler.END

    raw_text = update.message.text.partition(" ")[2].strip()
    if not raw_text and "\n" in update.message.text:
        raw_text = update.message.text.split("\n", 1)[1].strip()

    if raw_text:
        rows, errors = parse_contact_text(raw_text)
        if not rows:
            await update.message.reply_text(
                "⚠️ មិនអាចអានប៊ូតុងណាមួយបានទេ។\n\n" + SETCONTACT_HELP, parse_mode="Markdown"
            )
            return ConversationHandler.END

        save_contact_rows(rows)
        keyboard = get_contact_keyboard()
        total = sum(len(r) for r in (rows))

        msg = f"✅ បានកំណត់ Contact Buttons ថ្មីរួចរាល់ ({total} ប៊ូតុង រួមទាំង Contact Us ថេរ)!\nវានឹងប្រើប្រាស់ជាប់រហូតគ្រប់ post បន្ទាប់ៗទៀត។"
        if errors:
            msg += "\n\n⚠️ បន្ទាត់ខ្លះមានបញ្ហា (បានរំលង):\n" + "\n".join(errors)
        msg += "\n\nឧទាហរណ៍ប៊ូតុង៖"
        await update.message.reply_text(msg, reply_markup=keyboard)
        return ConversationHandler.END

    await update.message.reply_text(
        SETCONTACT_HELP + "\n\n━━━━━━━━━━━━━━━━━━━━\n"
        "📝 *សូមផ្ញើអត្ថបទប៊ូតុង Contact របស់អ្នកឥឡូវនេះ (ឬសរសេរ /cancel ដើម្បីបោះបង់)៖*",
        parse_mode="Markdown",
    )
    return SETTING_CONTACT


async def set_contact_process(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    raw_text = update.message.text.strip()
    rows, errors = parse_contact_text(raw_text)

    if not rows:
        await update.message.reply_text(
            "⚠️ មិនអាចអានប៊ូតុងបានទេ។ សូមពិនិត្យទម្រង់រួចផ្ញើម្តងទៀត ឬសរសេរ /cancel ដើម្បីបោះបង់៖\n\n"
            + SETCONTACT_HELP,
            parse_mode="Markdown",
        )
        return SETTING_CONTACT

    save_contact_rows(rows)
    keyboard = get_contact_keyboard()
    total = sum(len(r) for r in (rows))

    msg = f"✅ បានកំណត់ Contact Buttons ថ្មីរួចរាល់ ({total} ប៊ូតុង រួមទាំង Contact Us ថេរ)!\nវានឹងប្រើប្រាស់ជាប់រហូតគ្រប់ post បន្ទាប់ៗទៀត។"
    if errors:
        msg += "\n\n⚠️ បន្ទាត់ខ្លះមានបញ្ហា (បានរំលង):\n" + "\n".join(errors)
    msg += "\n\nឧទាហរណ៍ប៊ូតុង៖"
    await update.message.reply_text(msg, reply_markup=keyboard)
    return ConversationHandler.END


async def cancel_contact(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    await update.message.reply_text("❌ បានបោះបង់ការកំណត់ Contact Buttons។")
    return ConversationHandler.END


async def show_contact(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user = update.effective_user
    if not is_admin(user.id):
        await update.message.reply_text("❌ អ្នកមិនមានសិទ្ធិប្រើ command នេះទេ។")
        return

    dynamic_rows = load_contact_rows()
    combined_rows = (dynamic_rows or [])
    if not combined_rows:
        await update.message.reply_text("ℹ️ មិនទាន់មាន Contact Buttons ទេបច្ចុប្បន្ន។ សូមប្រើ /setcontact ដើម្បីកំណត់។")
        return
    
    lines = []
    for row in combined_rows:
        lines.append(" | ".join(f"{b['label']} → {b['url']}" for b in row))
        
    await update.message.reply_text(
        "ℹ️ Contact Buttons បច្ចុប្បន្ន (រួមបញ្ចូលទាំង Contact Us ថេរ & ប៊ូតុងបន្ថែម)៖\n\n" + "\n".join(lines),
        reply_markup=build_keyboard_markup(combined_rows),
    )


# ------------------------------------------------------------------
# Helper Functions for Post Formatting & Dispatch
# ------------------------------------------------------------------
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
    keyboard = get_contact_keyboard()
    context.user_data["source_chat_id"] = msg.chat_id
    context.user_data["source_message_id"] = msg.message_id
    context.user_data["photo_id"] = msg.photo[-1].file_id if msg.photo else None
    context.user_data["video_id"] = msg.video.file_id if msg.video else None
    context.user_data["document_id"] = msg.document.file_id if msg.document else None
    context.user_data["audio_id"] = msg.audio.file_id if msg.audio else None
    context.user_data["voice_id"] = msg.voice.file_id if msg.voice else None
    context.user_data["animation_id"] = msg.animation.file_id if msg.animation else None
    context.user_data["sticker_id"] = msg.sticker.file_id if msg.sticker else None
    
    caption_html = (msg.caption_html or "").strip() or None
    text_html = (msg.text_html or "").strip() if msg.text else None
    context.user_data["info"] = caption_html or text_html
    raw_length = telegram_length(msg.caption or msg.text or "")
    context.user_data["raw_length"] = raw_length

    # Send preview
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
    else:
        try:
            await context.bot.copy_message(
                chat_id=msg.chat_id,
                from_chat_id=msg.chat_id,
                message_id=msg.message_id,
                reply_markup=keyboard,
            )
        except Exception:
            if msg.video:
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


async def _publish_data_to_channel(bot, data: dict) -> None:
    """Core function to dispatch prepared post data to the channel."""
    keyboard = get_contact_keyboard()
    source_chat_id = data.get("source_chat_id")
    source_message_id = data.get("source_message_id")
    raw_length = data.get("raw_length", 0)
    info = data.get("info") or ""

    # 1. If photo with split caption (longer than 1024 chars)
    if data.get("photo_id") and _needs_split_caption(raw_length):
        await bot.send_photo(chat_id=CHANNEL_ID, photo=data["photo_id"])
        await bot.send_message(
            chat_id=CHANNEL_ID,
            text=info,
            parse_mode="HTML",
            reply_markup=keyboard,
        )
        return

    # 2. Try copy_message first (preserves native formatting, forwards, documents, etc.)
    if source_chat_id and source_message_id:
        try:
            await bot.copy_message(
                chat_id=CHANNEL_ID,
                from_chat_id=source_chat_id,
                message_id=source_message_id,
                reply_markup=keyboard,
            )
            return
        except Exception as copy_err:
            logger.warning("copy_message to channel failed (%s), trying fallback.", copy_err)

    # 3. Direct send fallbacks
    if data.get("photo_id"):
        await bot.send_photo(
            chat_id=CHANNEL_ID,
            photo=data["photo_id"],
            caption=info if info else None,
            parse_mode="HTML" if info else None,
            reply_markup=keyboard,
        )
    elif data.get("video_id"):
        await bot.send_video(
            chat_id=CHANNEL_ID,
            video=data["video_id"],
            caption=info if info else None,
            parse_mode="HTML" if info else None,
            reply_markup=keyboard,
        )
    elif data.get("document_id"):
        await bot.send_document(
            chat_id=CHANNEL_ID,
            document=data["document_id"],
            caption=info if info else None,
            parse_mode="HTML" if info else None,
            reply_markup=keyboard,
        )
    elif data.get("audio_id"):
        await bot.send_audio(
            chat_id=CHANNEL_ID,
            audio=data["audio_id"],
            caption=info if info else None,
            parse_mode="HTML" if info else None,
            reply_markup=keyboard,
        )
    elif data.get("voice_id"):
        await bot.send_voice(
            chat_id=CHANNEL_ID,
            voice=data["voice_id"],
            reply_markup=keyboard,
        )
    elif data.get("animation_id"):
        await bot.send_animation(
            chat_id=CHANNEL_ID,
            animation=data["animation_id"],
            caption=info if info else None,
            parse_mode="HTML" if info else None,
            reply_markup=keyboard,
        )
    elif data.get("sticker_id"):
        await bot.send_sticker(chat_id=CHANNEL_ID, sticker=data["sticker_id"])
        await bot.send_message(chat_id=CHANNEL_ID, text="​", reply_markup=keyboard)
    elif info:
        await bot.send_message(
            chat_id=CHANNEL_ID,
            text=info,
            parse_mode="HTML",
            reply_markup=keyboard,
        )


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
        await query.edit_message_text("🎉 បានបញ្ជូនព័ត៌មានទៅកាន់ Channel/Group ដោយជោគជ័យ!")
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
        await query.edit_message_text("🎉 បានបញ្ជូនព័ត៌មានទៅកាន់ Channel/Group ដោយជោគជ័យ!")
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
    if not is_admin(user.id):
        await update.message.reply_text("❌ អ្នកមិនមានសិទ្ធិប្រើ Bot នេះទេ។")
        return

    await update.message.reply_text(
        "👋 សួស្តី! ខ្ញុំជា Bot សម្រាប់ទម្លាក់ព័ត៌មានការងារ។\n\n"
        "Admin អាចប្រើ:\n"
        "• /setcontact — កំណត់/កែប្រែ Contact Buttons ថេរ (Icon+ពណ៌+Layout)\n"
        "• /post — បង្ហោះការងារថ្មី (ផ្ញើព័ត៌មាន/រូបភាព ក្នុងសារតែមួយ)\n"
        "• /showcontact — មើល Contact បច្ចុប្បន្ន\n"
        "• ឬ forward សារណាមួយមក bot ដោយផ្ទាល់ (bot នឹងសួរ confirm មុន post)"
    )


def main() -> None:
    app = ApplicationBuilder().token(BOT_TOKEN).build()

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
    app.add_handler(CommandHandler("showcontact", show_contact))
    app.add_handler(contact_conv_handler)
    app.add_handler(post_conv_handler)
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
        logger.info("Bot is running with Polling (Local Development Mode)...")
        app.run_polling(drop_pending_updates=True, allowed_updates=Update.ALL_TYPES)


if __name__ == "__main__":
    main()