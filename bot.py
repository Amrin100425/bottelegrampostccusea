"""
Hiring Post Approval Bot
=========================

Flow:
1. An employer sends a job posting message to the bot (private chat).
2. The bot forwards it to the ADMIN with "Approve" / "Reject" buttons.
3. If the admin approves, the bot posts the job to the public CAREER_CHANNEL
   and notifies the employer it was published.
4. If the admin rejects, the employer is notified their post was declined
   (optionally with a reason).

Requirements:
    pip install python-telegram-bot==21.4 --break-system-packages

Setup:
    1. Create a bot via @BotFather on Telegram, get the BOT_TOKEN.
    2. Get your admin numeric user id (message @userinfobot to find it).
    3. Create/choose your career channel, add the bot as an ADMIN of that
       channel (needs "Post Messages" permission), and get the channel's
       @username or its numeric chat id (e.g. -1001234567890).
    4. Fill in config.py (see config.py.example) or set environment variables.
    5. Run: python bot.py
"""

import logging
from dataclasses import dataclass, field
from typing import Dict, Optional

from telegram import (
    Update,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    Message,
)
from telegram.constants import ParseMode
from telegram.ext import (
    Application,
    ApplicationBuilder,
    CommandHandler,
    MessageHandler,
    CallbackQueryHandler,
    ContextTypes,
    filters,
)

import config

# --------------------------------------------------------------------------
# Logging
# --------------------------------------------------------------------------
logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO,
)
logger = logging.getLogger(__name__)


# --------------------------------------------------------------------------
# In-memory store for pending submissions.
# Key = submission id (int, auto-incrementing).
# For production use, swap this for a small database (SQLite, etc.) so
# pending posts survive a bot restart.
# --------------------------------------------------------------------------
@dataclass
class Submission:
    submission_id: int
    employer_chat_id: int
    employer_name: str
    original_message_id: int
    # Copy of the content so we can re-post it into the channel even if the
    # employer deletes their original message.
    text: Optional[str] = None
    caption: Optional[str] = None
    photo_file_id: Optional[str] = None
    document_file_id: Optional[str] = None
    document_file_name: Optional[str] = None
    status: str = "pending"  # pending | approved | rejected


class Store:
    def __init__(self) -> None:
        self._data: Dict[int, Submission] = {}
        self._next_id = 1

    def add(self, sub: "Submission") -> int:
        sub.submission_id = self._next_id
        self._data[self._next_id] = sub
        self._next_id += 1
        return sub.submission_id

    def get(self, submission_id: int) -> Optional[Submission]:
        return self._data.get(submission_id)


store = Store()


# --------------------------------------------------------------------------
# Helpers
# --------------------------------------------------------------------------
def admin_keyboard(submission_id: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        [
            [
                InlineKeyboardButton("✅ Approve", callback_data=f"approve:{submission_id}"),
                InlineKeyboardButton("❌ Reject", callback_data=f"reject:{submission_id}"),
            ]
        ]
    )


def is_admin(user_id: int) -> bool:
    return user_id == config.ADMIN_CHAT_ID


# --------------------------------------------------------------------------
# Command handlers
# --------------------------------------------------------------------------
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await update.message.reply_text(
        "👋 Hi! I collect job postings from employers.\n\n"
        "Send me your job description as a message (text, or a photo/document "
        "with a caption describing the role). I'll pass it to our admin team "
        "for approval, and once approved it'll go live in our career channel.\n\n"
        "Please include: job title, company, location, requirements, and how "
        "to apply."
    )


async def help_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await start(update, context)


# --------------------------------------------------------------------------
# Employer submission handler
# --------------------------------------------------------------------------
async def handle_employer_message(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    message: Message = update.message
    user = update.effective_user

    # Ignore messages sent by the admin in their own DM to the bot (avoids
    # accidentally treating admin chatter as a job submission). Admin actions
    # happen via the inline buttons, not by sending new messages here.
    if is_admin(user.id):
        await message.reply_text(
            "You're set up as the admin — you'll receive submissions here "
            "with Approve/Reject buttons instead of submitting through this chat."
        )
        return

    sub = Submission(
        submission_id=0,  # assigned by store.add
        employer_chat_id=message.chat_id,
        employer_name=user.full_name or user.username or "Unknown",
        original_message_id=message.message_id,
        text=message.text,
        caption=message.caption,
    )

    if message.photo:
        sub.photo_file_id = message.photo[-1].file_id
    if message.document:
        sub.document_file_id = message.document.file_id
        sub.document_file_name = message.document.file_name

    if not any([sub.text, sub.caption, sub.photo_file_id, sub.document_file_id]):
        await message.reply_text(
            "I couldn't find any content to submit. Please send text, or a "
            "photo/document with a caption describing the job."
        )
        return

    submission_id = store.add(sub)

    # Confirm to employer
    await message.reply_text(
        "✅ Thanks! Your job posting has been sent to our team for review. "
        "You'll be notified here once it's approved and published."
    )

    # Notify admin
    admin_header = (
        f"📩 <b>New job posting submission</b> (#{submission_id})\n"
        f"From: {sub.employer_name} (id: {sub.employer_chat_id})\n\n"
        f"Review below and Approve or Reject:"
    )
    await context.bot.send_message(
        chat_id=config.ADMIN_CHAT_ID,
        text=admin_header,
        parse_mode=ParseMode.HTML,
    )

    # Forward/re-send the actual content to the admin so they can review it,
    # followed by the approve/reject buttons attached to a short footer.
    if sub.photo_file_id:
        await context.bot.send_photo(
            chat_id=config.ADMIN_CHAT_ID,
            photo=sub.photo_file_id,
            caption=sub.caption or "",
        )
    elif sub.document_file_id:
        await context.bot.send_document(
            chat_id=config.ADMIN_CHAT_ID,
            document=sub.document_file_id,
            caption=sub.caption or "",
        )
    elif sub.text:
        await context.bot.send_message(chat_id=config.ADMIN_CHAT_ID, text=sub.text)

    await context.bot.send_message(
        chat_id=config.ADMIN_CHAT_ID,
        text=f"Decision for submission #{submission_id}:",
        reply_markup=admin_keyboard(submission_id),
    )


# --------------------------------------------------------------------------
# Admin decision handler (inline button callback)
# --------------------------------------------------------------------------
async def handle_decision(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    user = update.effective_user

    if not is_admin(user.id):
        await query.answer("Only the admin can approve or reject posts.", show_alert=True)
        return

    action, sub_id_str = query.data.split(":", 1)
    submission_id = int(sub_id_str)
    sub = store.get(submission_id)

    if sub is None:
        await query.answer("Submission not found (maybe already handled).", show_alert=True)
        return

    if sub.status != "pending":
        await query.answer(f"This submission was already {sub.status}.", show_alert=True)
        return

    if action == "approve":
        await publish_to_channel(context, sub)
        sub.status = "approved"
        await query.answer("Approved and published ✅")
        await query.edit_message_text(
            f"✅ Submission #{submission_id} approved and posted to the career channel."
        )
        await context.bot.send_message(
            chat_id=sub.employer_chat_id,
            text="🎉 Good news — your job posting has been approved and is now live "
                 "in our career channel!",
        )

    elif action == "reject":
        sub.status = "rejected"
        await query.answer("Rejected ❌")
        await query.edit_message_text(f"❌ Submission #{submission_id} rejected.")
        await context.bot.send_message(
            chat_id=sub.employer_chat_id,
            text="Thanks for the submission. Unfortunately your job posting "
                 "wasn't approved this time. Feel free to revise and resend it, "
                 "or contact us for feedback.",
        )


async def publish_to_channel(context: ContextTypes.DEFAULT_TYPE, sub: Submission) -> None:
    footer = "\n\n— posted via employer submission"
    if sub.photo_file_id:
        await context.bot.send_photo(
            chat_id=config.CAREER_CHANNEL,
            photo=sub.photo_file_id,
            caption=(sub.caption or "") + footer,
        )
    elif sub.document_file_id:
        await context.bot.send_document(
            chat_id=config.CAREER_CHANNEL,
            document=sub.document_file_id,
            caption=(sub.caption or "") + footer,
        )
    elif sub.text:
        await context.bot.send_message(
            chat_id=config.CAREER_CHANNEL,
            text=sub.text + footer,
        )


# --------------------------------------------------------------------------
# Entry point
# --------------------------------------------------------------------------
def main() -> None:
    app: Application = ApplicationBuilder().token(config.BOT_TOKEN).build()

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("help", help_cmd))
    app.add_handler(CallbackQueryHandler(handle_decision, pattern=r"^(approve|reject):\d+$"))
    # Any non-command message (text, photo, document) in private chat is
    # treated as a job submission.
    app.add_handler(
        MessageHandler(
            (filters.TEXT | filters.PHOTO | filters.Document.ALL) & ~filters.COMMAND,
            handle_employer_message,
        )
    )

    logger.info("Bot starting...")
    app.run_polling(allowed_updates=Update.ALL_TYPES)


if __name__ == "__main__":
    main()
