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
BOT_TOKEN  = os.getenv("BOT_TOKEN")
CHANNEL_ID = os.getenv("CHANNEL_ID")
try:
    ADMIN_IDS = json.loads(os.getenv("ADMIN_IDS", "[1147056937, 468517256, 1287745757, 8824663759]"))
except Exception:
    ADMIN_IDS = [1147056937, 468517256, 1287745757, 8824663759]
WEBHOOK_URL = os.getenv("WEBHOOK_URL", "https://bottelegrampostccusea.onrender.com")

CONTACT_STORE_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "contact.json")

STYLE_EMOJI = {
    "green": "🟢",
    "blue": "🔵",
    "red": "🔴",
    "yellow": "🟡",
    "orange": "🟠",
    "purple": "🟣",
    "black": "⚫️",
    "white": "⚪️",
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
# Contact URL helper
# ------------------------------------------------------------------
def build_contact_url(raw: str) -> str:
    """បំប្លែង username ឬលេខទូរស័ព្ទ ឬ URL ទៅជា Link ត្រឹមត្រូវសម្រាប់ប៊ូតុង"""
    raw = raw.strip()
    if raw.startswith("@"):
        return f"https://t.me/{raw[1:]}"
    if raw.startswith("https://") or raw.startswith("http://"):
        return raw
    digits = "".join(ch for ch in raw if ch.isdigit())
    return f"https://wa.me/{digits}"


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
    kb_rows = [
        [InlineKeyboardButton(b["label"], url=b["url"]) for b in row]
        for row in rows
    ]
    return InlineKeyboardMarkup(kb_rows)


def get_contact_keyboard():
    dynamic_rows = load_contact_rows()
    if not dynamic_rows:
        return None
    return build_keyboard_markup(dynamic_rows)


def parse_button_entry(entry: str):
    """Parse 'Button text - url' or with optional '- style:green' / '- emoji:🔥' suffixes."""
    entry = entry.strip()
    if not entry:
        return None

    style_prefix = ""
    emoji_prefix = ""

    # ស្វែងរក - style:color
    m_style = re.search(r"-\s*style\s*:\s*(\w+)\s*$", entry, flags=re.IGNORECASE)
    if m_style:
        style_name = m_style.group(1).lower()
        if style_name in STYLE_EMOJI:
            style_prefix = STYLE_EMOJI[style_name] + " "
        entry = entry[: m_style.start()].strip()

    # ស្វែងរក - emoji:<any emoji or text>
    m_emoji = re.search(r"-\s*emoji\s*:\s*(\S+)\s*$", entry, flags=re.IGNORECASE)
    if m_emoji:
        emoji_prefix = m_emoji.group(1).strip() + " "
        entry = entry[: m_emoji.start()].strip()

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

    prefix = emoji_prefix if emoji_prefix else style_prefix
    label = f"{prefix}{label}"

    return {"label": label, "url": build_contact_url(target)}


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

    "*— ប៊ូតុងធម្មតា —*\n"
    "`ទំនាក់ទំនង - @username`\n"
    "`គេហទំព័រ - https://example.com`\n\n"

    "*— ដាក់ពណ៌ (style:) —*\n"
    "Telegram មិនអនុញ្ញាតប្ដូរពណ៌ប៊ូតុងពិតប្រាកដទេ\n"
    "ដូច្នេះពណ៌ត្រូវបានបង្ហាញជា Emoji ពណ៌ នៅខាងមុខ Label\n"
    "`ទំនាក់ទំនង - @username - style:green`  →  🟢 ទំនាក់ទំនង\n"
    "`Apply - https://example.com - style:blue`  →  🔵 Apply\n"
    "ពណ៌ដែលគាំទ្រ: `green` 🟢 `blue` 🔵 `red` 🔴 `yellow` 🟡 `orange` 🟠 `purple` 🟣 `black` ⚫️ `white` ⚪️\n\n"

    "*— ដាក់ Emoji ផ្ទាល់ (emoji:) —*\n"
    "ប្រើ Emoji ណាក៏បានតាមចង់\n"
    "`ទំនាក់ទំនង - @username - emoji:📞`  →  📞 ទំនាក់ទំនង\n"
    "`Apply Now - https://example.com - emoji:🚀`  →  🚀 Apply Now\n\n"

    "*— ច្រើនប៊ូតុង (|) —*\n"
    "`ទំនាក់ទំនង - @username - emoji:📞 | Apply - https://example.com - style:green`\n\n"

    "URL អាចជា `@username`, លេខទូរស័ព្ទ, ឬ URL ពេញ។"
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
        keyboard = build_keyboard_markup(rows)
        total = sum(len(r) for r in rows)

        msg = f"✅ បានកំណត់ Contact Buttons ថ្មីរួចរាល់ ({total} ប៊ូតុង)!\nវានឹងប្រើប្រាស់ជាប់រហូតគ្រប់ post បន្ទាប់ៗទៀត។"
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
    keyboard = build_keyboard_markup(rows)
    total = sum(len(r) for r in rows)

    msg = f"✅ បានកំណត់ Contact Buttons ថ្មីរួចរាល់ ({total} ប៊ូតុង)!\nវានឹងប្រើប្រាស់ជាប់រហូតគ្រប់ post បន្ទាប់ៗទៀត។"
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
    if not dynamic_rows:
        await update.message.reply_text("ℹ️ មិនទាន់មាន Contact Buttons ទេបច្ចុប្បន្ន។ សូមប្រើ /setcontact ដើម្បីកំណត់។")
        return
    
    lines = []
    for row in dynamic_rows:
        lines.append(" | ".join(f"{b['label']} → {b['url']}" for b in row))
        
    await update.message.reply_text(
        "ℹ️ Contact Buttons បច្ចុប្បន្ន៖\n\n" + "\n".join(lines),
        reply_markup=build_keyboard_markup(dynamic_rows),
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
            InlineKeyboardButton("✅ YES — បញ្ជូនទៅ Channel", callback_data="confirm_yes"),
            InlineKeyboardButton("❌ NO — បោះបង់", callback_data="confirm_no"),
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

    if query.data != "confirm_yes":
        await query.edit_message_text("❌ បានបោះបង់។ សរសេរ /post ដើម្បីចាប់ផ្តើមម្តងទៀត។")
        context.user_data.clear()
        return ConversationHandler.END

    await query.edit_message_text("⏳ កំពុងបញ្ជូនទៅកាន់ Channel...")

    try:
        await _publish_data_to_channel(context.bot, context.user_data)
        await query.edit_message_text("🎉 បានបញ្ជូនព័ត៌មានការងារទៅ Channel ដោយជោគជ័យ!")
    except Exception as e:
        logger.error("Failed to send to channel: %s", e)
        await query.edit_message_text(
            f"⚠️ បរាជ័យក្នុងការបញ្ជូនទៅ Channel។ សូមប្រាកដថា Bot ជា Admin នៅក្នុង Channel។\n\nError: {e}"
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
            InlineKeyboardButton("✅ YES — បញ្ជូនទៅ Channel", callback_data="standalone_confirm_yes"),
            InlineKeyboardButton("❌ NO — បោះបង់", callback_data="standalone_confirm_no"),
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

    if query.data == "standalone_confirm_no":
        await query.edit_message_text("❌ បានបោះបង់ការបង្ហោះ។")
        context.user_data.clear()
        return

    if not context.user_data.get("source_message_id") and not context.user_data.get("info"):
        await query.edit_message_text("⚠️ ព័ត៌មានសារនេះហួសសុពលភាពហើយ។ សូមផ្ញើសារម្តងទៀត។")
        return

    await query.edit_message_text("⏳ កំពុងបញ្ជូនទៅកាន់ Channel...")

    try:
        await _publish_data_to_channel(context.bot, context.user_data)
        await query.edit_message_text("🎉 បានបញ្ជូនព័ត៌មានទៅ Channel ដោយជោគជ័យ!")
    except Exception as e:
        logger.error("Failed to send standalone to channel: %s", e)
        await query.edit_message_text(
            f"⚠️ បរាជ័យក្នុងការបញ្ជូនទៅ Channel។\n\nError: {e}"
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
            CONFIRM: [CallbackQueryHandler(confirm_post, pattern="^confirm_(yes|no)$")],
        },
        fallbacks=[
            CommandHandler("cancel", cancel),
            CommandHandler("post", post_start),
        ],
        allow_reentry=True,
        conversation_timeout=600,
    )

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("showcontact", show_contact))
    app.add_handler(contact_conv_handler)
    app.add_handler(post_conv_handler)
    app.add_handler(
        CallbackQueryHandler(
            standalone_confirm_callback, pattern="^standalone_confirm_(yes|no)$"
        )
    )
    app.add_handler(
        MessageHandler(
            (filters.ALL & ~filters.COMMAND) & filters.ChatType.PRIVATE,
            handle_standalone_message,
        )
    )

    logger.info("Bot is running with webhook...")

    app.run_webhook(
        listen="0.0.0.0",
        port=int(os.getenv("PORT", 8443)),
        url_path=BOT_TOKEN,
        webhook_url=f"{WEBHOOK_URL}/{BOT_TOKEN}",
    )


if __name__ == "__main__":
    main()