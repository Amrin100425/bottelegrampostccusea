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
    - អាចដាក់ Icon (Emoji) និង "ពណ៌" (តាមរយៈ style:color -> បំប្លែងទៅជារង្វង់ Emoji ពណ៌
      ព្រោះ Telegram Bot API មិនអនុញ្ញាតឱ្យប្តូរពណ៌ផ្ទៃខាងក្រោយប៊ូតុងពិតប្រាកដទេ)
    - ពេលបង្ហោះការងារថ្មី: ព័ត៌មានការងារ និង/ឬ រូបភាព ត្រូវផ្ញើក្នុង *សារតែមួយ*
      (ផ្ញើរូបភាពជាមួយ Caption, ឬផ្ញើតែអត្ថបទ, ឬផ្ញើតែរូបភាព)
    - ព័ត៌មានការងារវែងៗ (ច្រើនជាង Telegram Caption Limit) ត្រូវបានគាំទ្រដោយស្វ័យប្រវត្តិ៖
      ប្រសិនបើមានរូបភាព ហើយអត្ថបទវែងជាង 1024 តួ (Caption limit របស់ Telegram) ->
      រូបភាពនឹងផ្ញើដោយគ្មាន Caption រួចអត្ថបទពេញលេញនឹងផ្ញើជាសារបន្ទាប់ភ្លាមៗ
      (ភ្ជាប់ Contact Buttons ទៅសារអត្ថបទនោះជំនួសវិញ)។
    - Forward: Admin អាច forward សារ (អត្ថបទ, រូបភាព, វីដេអូ, ឯកសារ, ។ល។)
      ពី group/channel/user ណាក៏បានមកដល់ Bot ដោយផ្ទាល់ (គ្មាន /post ក៏បាន)
      Bot នឹង re-post ខ្លឹមសារនោះទៅ Channel ដោយភ្ជាប់ Contact Buttons ដោយស្វ័យប្រវត្តិ។

របៀបប្រើប្រាស់ /setcontact (សម្រាប់ Admin ក្នុង Private Chat ជាមួយ Bot):

    /setcontact
    Button text 1 - http://www.example.com/
    Button text 2 - http://www.example2.com/

    អាចដាក់ពណ៌ (បំប្លែងទៅជារង្វង់ Emoji ពណ៌):
    /setcontact
    Button text 1 - http://www.example.com/ - style:green
    Button text 2 - http://www.example2.com/ - style:blue
    Button text 3 - http://www.example3.com/ - style:red

    ដាក់ច្រើនប៊ូតុងក្នុងជួរតែមួយ (រហូតដល់ 3) ដោយប្រើ |:
    /setcontact
    Button text 1 - http://www.example.com/ | Button text 2 - http://www.example2.com/
    Button text 3 - http://www.example3.com/ - style:red

    ពណ៌ដែលគាំទ្រ: green, blue, red, yellow, orange, purple, black, white

    /post        -> ចាប់ផ្តើមបង្ហោះការងារថ្មី (ផ្ញើព័ត៌មាន/រូបភាព ក្នុងសារតែមួយ)
    /cancel      -> បោះបង់ការបញ្ចូលព័ត៌មាន
    /showcontact -> មើល Contact បច្ចុប្បន្នដែលកំពុងប្រើ

    Forward: forward សារណាមួយមកដល់ Bot ដោយផ្ទាល់ — Bot នឹង post ទៅ Channel ភ្លាម

តម្រូវការ:
    pip install python-telegram-bot==21.*
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
# ការកំណត់រចនាសម្ព័ន្ធ (CONFIG) - ត្រូវកែតម្លៃទាំងនេះ
# ------------------------------------------------------------------
BOT_TOKEN  = os.getenv("BOT_TOKEN")        # ទទួលបានពី @BotFather (កុំចែករំលែក token ជាសាធារណៈ!)
CHANNEL_ID = os.getenv("CHANNEL_ID")           # ឧ. "@jobs_kh" ឬ "-1001234567890"
ADMIN_IDS  = [1147056937, 468517256, 1287745757]                        # Telegram user id របស់ Admin (អាចដាក់ច្រើននាក់)
WEBHOOK_URL = os.getenv("WEBHOOK_URL", "https://bottelegrampostccusea.onrender.com")

# Contact លំនាំដើម (Rows នីមួយៗគឺជាមួយជួរ, រៀងក្នុងជួរអាចមានច្រើនប៊ូតុង)
DEFAULT_CONTACT_ROWS = [
    [{"label": "📞 ទាក់ទង", "url": "https://t.me/your_username"}],
]

# ឯកសារសម្រាប់រក្សាទុក Contact ជាអចិន្ត្រៃយ៍ (មិនបាត់ទោះបើ restart bot)
CONTACT_STORE_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "contact.json")

# ពណ៌ដែលគាំទ្រ -> បំប្លែងទៅជារង្វង់ Emoji ពណ៌ (Telegram Bot API មិនអនុញ្ញាតប្តូរពណ៌ប៊ូតុងពិតទេ)
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

# --- Telegram Bot API hard limits (used to support longer job descriptions) ---
TELEGRAM_CAPTION_LIMIT = 1024   # limit for photo/video caption text
TELEGRAM_MESSAGE_LIMIT = 4096   # limit for a plain text message

# ------------------------------------------------------------------
# Logging
# ------------------------------------------------------------------
logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO,
)
logger = logging.getLogger(__name__)

# ------------------------------------------------------------------
# States សម្រាប់ ConversationHandler (/post)
# ------------------------------------------------------------------
CONTENT, CONFIRM = range(2)


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
# Contact Storage (persistent) - ប្រើ JSON file ដើម្បីរក្សាទុក Rows នៃប៊ូតុង
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
    return DEFAULT_CONTACT_ROWS


def save_contact_rows(rows: list) -> None:
    with open(CONTACT_STORE_FILE, "w", encoding="utf-8") as f:
        json.dump({"rows": rows}, f, ensure_ascii=False, indent=2)


def build_keyboard_markup(rows: list) -> InlineKeyboardMarkup:
    kb_rows = [
        [InlineKeyboardButton(b["label"], url=b["url"]) for b in row]
        for row in rows
    ]
    return InlineKeyboardMarkup(kb_rows)


def get_contact_keyboard() -> InlineKeyboardMarkup:
    return build_keyboard_markup(load_contact_rows())


# ------------------------------------------------------------------
# Parser សម្រាប់ទម្រង់ /setcontact (multiline, | សម្រាប់ជួរដូចគ្នា, - style:color Optional)
# ------------------------------------------------------------------
def parse_button_entry(entry: str):
    """Parse 'Button text - url' or with optional '- style:green' / '- emoji:🔥' suffixes."""
    entry = entry.strip()
    if not entry:
        return None

    style_prefix = ""
    emoji_prefix = ""

    # ស្វែងរក - style:color (ពណ៌ Emoji ពណ៌ដូច 🟢)
    m_style = re.search(r"-\s*style\s*:\s*(\w+)\s*$", entry, flags=re.IGNORECASE)
    if m_style:
        style_name = m_style.group(1).lower()
        if style_name in STYLE_EMOJI:
            style_prefix = STYLE_EMOJI[style_name] + " "
        entry = entry[: m_style.start()].strip()

    # ស្វែងរក - emoji:<any emoji or text> (Emoji ដែលអ្នកប្ដូរបាន)
    m_emoji = re.search(r"-\s*emoji\s*:\s*(\S+)\s*$", entry, flags=re.IGNORECASE)
    if m_emoji:
        emoji_prefix = m_emoji.group(1).strip() + " "
        entry = entry[: m_emoji.start()].strip()

    # បំបែក Label និង URL ដោយប្រើ " - " ចុងក្រោយ (URL តែងតែជាផ្នែកចុងក្រោយ)
    label, sep, target = entry.rpartition(" - ")
    if not sep:
        label, sep, target = entry.rpartition("-")
    if not sep:
        return None

    label = label.strip()
    target = target.strip()
    if not label or not target:
        return None

    # emoji: overrides style: if both given
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


async def set_contact(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user = update.effective_user
    if not is_admin(user.id):
        await update.message.reply_text("❌ អ្នកមិនមានសិទ្ធិប្រើ command នេះទេ។")
        return

    raw_text = update.message.text.partition(" ")[2].strip()
    # គាំទ្រទាំង "/setcontact\nButton..." (multiline immediately after command)
    if not raw_text and "\n" in update.message.text:
        raw_text = update.message.text.split("\n", 1)[1].strip()

    if not raw_text:
        await update.message.reply_text(SETCONTACT_HELP, parse_mode="Markdown")
        return

    rows, errors = parse_contact_text(raw_text)

    if not rows:
        await update.message.reply_text(
            "⚠️ មិនអាចអានប៊ូតុងណាមួយបានទេ។\n\n" + SETCONTACT_HELP, parse_mode="Markdown"
        )
        return

    save_contact_rows(rows)
    keyboard = build_keyboard_markup(rows)
    total = sum(len(r) for r in rows)

    msg = f"✅ បានកំណត់ Contact Buttons ថ្មីរួចរាល់ ({total} ប៊ូតុង)!\nវានឹងប្រើប្រាស់ជាប់រហូតគ្រប់ post បន្ទាប់ៗទៀត។"
    if errors:
        msg += "\n\n⚠️ បន្ទាត់ខ្លះមានបញ្ហា (បានរំលង):\n" + "\n".join(errors)
    msg += "\n\nឧទាហរណ៍ប៊ូតុង៖"

    await update.message.reply_text(msg, reply_markup=keyboard)


async def show_contact(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    rows = load_contact_rows()
    lines = []
    for row in rows:
        lines.append(" | ".join(f"{b['label']} → {b['url']}" for b in row))
    await update.message.reply_text(
        "ℹ️ Contact Buttons បច្ចុប្បន្ន៖\n\n" + "\n".join(lines),
        reply_markup=build_keyboard_markup(rows),
    )


# ------------------------------------------------------------------
# /post - បង្ហោះការងារថ្មី (ព័ត៌មាន + រូបភាព ក្នុងសារតែមួយ)
#   - ផ្ញើរូបភាពមួយជាមួយ Caption -> ព័ត៌មាន = Caption, រូបភាព = រូបនោះ
#   - ផ្ញើតែអត្ថបទ -> ព័ត៌មានតែមួយមុខ គ្មានរូបភាព
#   - ផ្ញើតែរូបភាព គ្មាន Caption -> រូបភាពតែមួយមុខ គ្មានព័ត៌មាន
#
#   ចំណាំ: Telegram កំណត់ Caption limit = 1024 តួ និង Message limit = 4096 តួ។
#   ប្រសិនបើអត្ថបទវែងជាងកំណត់ អ្នកជំនួយខាងក្រោមនឹងបំបែកវាដោយស្វ័យប្រវត្តិ
#   ដើម្បីកុំឱ្យត្រូវកាត់ (truncate) ដោយ Telegram។
# ------------------------------------------------------------------
async def post_start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    user = update.effective_user
    if not is_admin(user.id):
        await update.message.reply_text("❌ អ្នកមិនមានសិទ្ធិប្រើ command នេះទេ។")
        return ConversationHandler.END

    context.user_data.clear()
    await update.message.reply_text(
        "📝 សូមផ្ញើ *ព័ត៌មានអំពីការងារ និង/ឬ រូបភាព* ក្នុងសារតែមួយ៖\n\n"
        "🔸 ផ្ញើរូបភាព ជាមួយ Caption (ព័ត៌មានការងារ) — ល្អបំផុត\n"
        "🔸 ឬផ្ញើតែអត្ថបទ (គ្មានរូបភាព)\n"
        "🔸 ឬផ្ញើតែរូបភាព (គ្មាន Caption)\n\n"
        "ព័ត៌មានវែងៗគាំទ្របានដល់ប្រហែល 4000 តួ — បើវែងជាង Caption limit "
        "(1024 តួ) នៅពេលមានរូបភាព, Bot នឹងផ្ញើរូបភាព រួចផ្ញើអត្ថបទពេញលេញជាសារបន្ទាប់ដោយស្វ័យប្រវត្តិ។\n\n"
        "សរសេរ /cancel ដើម្បីបោះបង់។",
        parse_mode="Markdown",
    )
    return CONTENT


async def get_content(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    msg = update.message

    # --- Handle forwarded messages inside the /post flow ---
    if msg.forward_date or msg.forward_origin:
        # Delegate to the forward handler; it posts directly and ends the conversation
        await _do_forward_post(update, context)
        context.user_data.clear()
        return ConversationHandler.END

    if msg.photo:
        context.user_data["photo_id"] = msg.photo[-1].file_id
        context.user_data["info"] = (msg.caption or "").strip() or None
    elif msg.text:
        text = msg.text.strip()
        text_len = telegram_length(text)
        if text_len > TELEGRAM_MESSAGE_LIMIT:
            await update.message.reply_text(
                f"⚠️ អត្ថបទវែងពេក ({text_len} តួ)។ Telegram អនុញ្ញាតតែរហូតដល់ "
                f"{TELEGRAM_MESSAGE_LIMIT} តួសម្រាប់សារអត្ថបទតែម្នាក់ឯង។ សូមកាត់បន្ថយ ឬ ផ្ញើជាមួយរូបភាព។"
            )
            return CONTENT
        context.user_data["photo_id"] = None
        context.user_data["info"] = text
    else:
        await update.message.reply_text(
            "⚠️ សូមផ្ញើ *អត្ថបទ* ឬ *រូបភាព* (អាចមាន Caption)។", parse_mode="Markdown"
        )
        return CONTENT

    await show_preview(update, context)
    return CONFIRM


def telegram_length(text: str) -> int:
    """
    Telegram counts text length in UTF-16 code units, not Python characters.
    Characters outside the Basic Multilingual Plane (many emoji, for example)
    take up 2 UTF-16 units, so we measure it the same way Telegram does to
    avoid off-by-a-few truncation at the caption/message limits.
    """
    return len(text.encode("utf-16-le")) // 2


def _needs_split_caption(post_text: str) -> bool:
    """True if text + photo combo would exceed Telegram's caption limit."""
    return bool(post_text) and telegram_length(post_text) > TELEGRAM_CAPTION_LIMIT


async def show_preview(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    data = context.user_data
    post_text = data.get("info") or ""
    keyboard = get_contact_keyboard()

    if data.get("photo_id"):
        if _needs_split_caption(post_text):
            # Caption would be too long -> send photo alone, then full text as its own message
            await update.message.reply_photo(photo=data["photo_id"])
            await update.message.reply_text(
                post_text, parse_mode="Markdown", reply_markup=keyboard
            )
        else:
            await update.message.reply_photo(
                photo=data["photo_id"],
                caption=post_text if post_text else None,
                parse_mode="Markdown" if post_text else None,
                reply_markup=keyboard,
            )
    else:
        await update.message.reply_text(
            post_text, parse_mode="Markdown", reply_markup=keyboard
        )

    confirm_keyboard = InlineKeyboardMarkup([
        [
            InlineKeyboardButton("✅ YES — បញ្ជូន", callback_data="confirm_yes"),
            InlineKeyboardButton("❌ NO — បោះបង់", callback_data="confirm_no"),
        ]
    ])
    await update.message.reply_text(
        "✅ ត្រឹមត្រូវហើយឬ? សូមចុចប៊ូតុងខាងក្រោមដើម្បីបញ្ជាក់។",
        reply_markup=confirm_keyboard,
    )


async def confirm_post(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    await query.answer()  # acknowledge the button tap immediately

    if query.data != "confirm_yes":
        await query.edit_message_text("❌ បានបោះបង់។ សរសេរ /post ដើម្បីចាប់ផ្តើមម្តងទៀត។")
        context.user_data.clear()
        return ConversationHandler.END

    data = context.user_data
    post_text = data.get("info") or ""
    keyboard = get_contact_keyboard()

    await query.edit_message_text("⏳ កំពុងបញ្ជូន...")

    try:
        if data.get("photo_id"):
            if _needs_split_caption(post_text):
                # Photo without caption, then the full description as a separate message
                # (with the contact buttons attached to the text message).
                await context.bot.send_photo(chat_id=CHANNEL_ID, photo=data["photo_id"])
                await context.bot.send_message(
                    chat_id=CHANNEL_ID,
                    text=post_text,
                    parse_mode="Markdown",
                    reply_markup=keyboard,
                )
            else:
                await context.bot.send_photo(
                    chat_id=CHANNEL_ID,
                    photo=data["photo_id"],
                    caption=post_text if post_text else None,
                    parse_mode="Markdown" if post_text else None,
                    reply_markup=keyboard,
                )
        else:
            await context.bot.send_message(
                chat_id=CHANNEL_ID,
                text=post_text,
                parse_mode="Markdown",
                reply_markup=keyboard,
            )
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
# Forward handler — Admin forwards any message directly to Bot
# The bot re-posts it to the channel with contact buttons appended.
# Works for: text, photo, video, document, audio, voice, sticker, animation.
# ------------------------------------------------------------------
async def _do_forward_post(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Core logic: take the forwarded message and publish it to the channel."""
    msg = update.message
    keyboard = get_contact_keyboard()

    try:
        if msg.photo:
            caption = (msg.caption or "").strip() or None
            if caption and telegram_length(caption) > TELEGRAM_CAPTION_LIMIT:
                # Caption too long — send photo first, then text with buttons
                await context.bot.send_photo(chat_id=CHANNEL_ID, photo=msg.photo[-1].file_id)
                await context.bot.send_message(
                    chat_id=CHANNEL_ID,
                    text=caption,
                    reply_markup=keyboard,
                )
            else:
                await context.bot.send_photo(
                    chat_id=CHANNEL_ID,
                    photo=msg.photo[-1].file_id,
                    caption=caption,
                    parse_mode="HTML" if caption else None,
                    reply_markup=keyboard,
                )

        elif msg.video:
            caption = (msg.caption or "").strip() or None
            await context.bot.send_video(
                chat_id=CHANNEL_ID,
                video=msg.video.file_id,
                caption=caption,
                parse_mode="HTML" if caption else None,
                reply_markup=keyboard,
            )

        elif msg.document:
            caption = (msg.caption or "").strip() or None
            await context.bot.send_document(
                chat_id=CHANNEL_ID,
                document=msg.document.file_id,
                caption=caption,
                parse_mode="HTML" if caption else None,
                reply_markup=keyboard,
            )

        elif msg.audio:
            caption = (msg.caption or "").strip() or None
            await context.bot.send_audio(
                chat_id=CHANNEL_ID,
                audio=msg.audio.file_id,
                caption=caption,
                parse_mode="HTML" if caption else None,
                reply_markup=keyboard,
            )

        elif msg.voice:
            await context.bot.send_voice(
                chat_id=CHANNEL_ID,
                voice=msg.voice.file_id,
                reply_markup=keyboard,
            )

        elif msg.animation:
            caption = (msg.caption or "").strip() or None
            await context.bot.send_animation(
                chat_id=CHANNEL_ID,
                animation=msg.animation.file_id,
                caption=caption,
                parse_mode="HTML" if caption else None,
                reply_markup=keyboard,
            )

        elif msg.sticker:
            # Stickers cannot have captions or inline keyboards via send_sticker,
            # so send the sticker then a follow-up text with the buttons.
            await context.bot.send_sticker(chat_id=CHANNEL_ID, sticker=msg.sticker.file_id)
            await context.bot.send_message(
                chat_id=CHANNEL_ID,
                text="\u200b",  # zero-width space as placeholder text
                reply_markup=keyboard,
            )

        elif msg.text:
            text = msg.text.strip()
            if telegram_length(text) > TELEGRAM_MESSAGE_LIMIT:
                await update.message.reply_text(
                    f"⚠️ អត្ថបទក្នុងសារ forward វែងពេក ({telegram_length(text)} តួ)។"
                )
                return
            await context.bot.send_message(
                chat_id=CHANNEL_ID,
                text=text,
                reply_markup=keyboard,
            )

        else:
            await update.message.reply_text(
                "⚠️ ប្រភេទសារនេះមិនអាច forward បានទេ (ប្រភេទមិនគាំទ្រ)។"
            )
            return

        await update.message.reply_text("🎉 បាន post ព័ត៌មានដែល forward ទៅ Channel ដោយជោគជ័យ!")

    except Exception as e:
        logger.error("Forward post failed: %s", e)
        await update.message.reply_text(
            f"⚠️ បរាជ័យក្នុងការ post ទៅ Channel។\n\nError: {e}"
        )


async def handle_forward(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Standalone handler: Admin forwards any message to Bot outside the /post flow."""
    user = update.effective_user
    if not is_admin(user.id):
        # Silently ignore non-admin forwards
        return
    await _do_forward_post(update, context)


# ------------------------------------------------------------------
# /start command
# ------------------------------------------------------------------
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await update.message.reply_text(
        "👋 សួស្តី! ខ្ញុំជា Bot សម្រាប់ទម្លាក់ព័ត៌មានការងារ។\n\n"
        "Admin អាចប្រើ:\n"
        "• /កំណត់Contact — កំណត់/មើលរបៀបកំណត់ Contact Buttons ថេរ (Icon+ពណ៌+Layout)\n"
        "• /បង្ហោះការងារ — បង្ហោះការងារថ្មី (ផ្ញើព័ត៌មាន/រូបភាព ក្នុងសារតែមួយ)\n"
        "• /showcontact — មើល Contact បច្ចុប្បន្ន"
    )


# ------------------------------------------------------------------
# Main
# ------------------------------------------------------------------
def main() -> None:
    app = ApplicationBuilder().token(BOT_TOKEN).build()

    # Filter that matches any forwarded message (forward_origin is set on all forwards)
    FORWARDED = filters.FORWARDED

    conv_handler = ConversationHandler(
        entry_points=[CommandHandler("post", post_start)],
        states={
            CONTENT: [
                # Accept forwarded messages, photos, and plain text in the /post flow
                MessageHandler(
                    FORWARDED | filters.PHOTO | (filters.TEXT & ~filters.COMMAND),
                    get_content,
                ),
            ],
            CONFIRM: [CallbackQueryHandler(confirm_post, pattern="^confirm_(yes|no)$")],
        },
        fallbacks=[
            CommandHandler("cancel", cancel),
            CommandHandler("post", post_start),  # <-- lets /post restart even if "stuck"
        ],
        allow_reentry=True,        # <-- lets /post re-trigger entry_points anytime
        conversation_timeout=600,  # <-- auto-cancels an abandoned conversation after 10 min
    )

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("setcontact", set_contact))
    app.add_handler(CommandHandler("showcontact", show_contact))
    app.add_handler(conv_handler)
    # Standalone forward handler — must be registered AFTER conv_handler so that
    # forwards inside an active /post conversation are handled by conv_handler first.
    app.add_handler(MessageHandler(filters.FORWARDED, handle_forward))

    logger.info("Bot is running with webhook...")

    app.run_webhook(
        listen="0.0.0.0",
        port=int(os.getenv("PORT", 8443)),
        url_path=BOT_TOKEN,
        webhook_url=f"{WEBHOOK_URL}/{BOT_TOKEN}",
    )

if __name__ == "__main__":
    main()
