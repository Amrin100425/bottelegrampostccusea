# -*- coding: utf-8 -*-
"""
Link Click Tracking & Monthly Analytics Reporter
======================================================================================
Module សម្រាប់តាមដាន និងកត់ត្រាចំនួនចុច (Clicks) លើប៊ូតុងនីមួយៗ (Each Button)
នៃ Channel Posts ព្រមទាំងបង្កើតរបាយការណ៍ប្រចាំខែ (Monthly Report) ជាអត្ថបទ Telegram,
Web Dashboard, និងទាញយកជាឯកសារ Excel/CSV។
"""

import csv
import hashlib
import io
import json
import logging
import os
import threading
from datetime import datetime
from typing import Dict, List, Optional, Tuple

import tornado.web

logger = logging.getLogger(__name__)

CLICK_STORE_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "clicks.json")
_data_lock = threading.Lock()

# Mapping for past posts (3866-3882) where each post has its own employer contact
PAST_POST_CONTACTS = {
    "3866": {"url": "https://t.me/USEACCAD", "label": "Apply Now"},
    "3867": {
        "url": "https://t.me/USEACCAD?text=%E1%9E%87%E1%9E%98%E1%9F%92%E1%9E%9A%E1%9E%B6%E1%9E%94%E1%9E%9F%E1%9E%BD%E1%9E%9A%E1%9E%94%E1%9E%84%20%E1%9E%81%E1%9F%92%E1%9E%89%E1%9E%BB%E1%9F%86%E1%9E%85%E1%9E%B6%E1%9E%94%E1%9F%8B%E1%9E%A2%E1%9E%B6%E1%9E%9A%E1%9E%98%E1%9F%92%E1%9E%98%E1%9E%8E%E1%9F%8D%E1%9E%93%E1%9E%B9%E1%9E%84%E1%9E%80%E1%9E%B6%E1%9E%9A%E1%9E%84%E1%9E%B6%E1%9E%9A%E1%9E%93%E1%9F%81%E1%9F%87%3A%20%F0%9F%94%97%20https%3A//t.me/useacareercenter/3867",
        "label": "More information",
    },
    "3868": {"url": "https://t.me/USEACCAD", "label": "Apply Now"},
    "3869": {"url": "https://t.me/USEACCAD", "label": "Apply Now"},
    "3871": {"url": "https://t.me/belikekhmersiemreap", "label": "Apply Now - Be Like Khmer"},
    "3872": {"url": "https://t.me/+85515344663", "label": "Apply Now - 015344663"},
    "3873": {"url": "https://t.me/RAIS_SCHOOL", "label": "Apply Now - @RAIS_SCHOOL"},
    "3874": {"url": "https://t.me/+85570588000", "label": "Apply Now - 070588000"},
    "3875": {"url": "https://t.me/cjftec", "label": "Apply Now - CJFTEC"},
    "3876": {"url": "https://t.me/+85581787985", "label": "Apply Now - 081787985"},
    "3877": {"url": "https://t.me/cjftec", "label": "Apply Now - CJFTEC"},
    "3878": {"url": "https://t.me/+85516757174", "label": "Apply Now - 016757174"},
    "3879": {"url": "https://t.me/USEACCAD", "label": "Apply Now"},
    "3880": {"url": "https://t.me/+85578555671", "label": "Apply Now - 078555671"},
    "3881": {"url": "https://t.me/+85595473808", "label": "Apple Now - 095473808"},
    "3882": {"url": "https://t.me/+855962080434", "label": "Apply Now - 0962080434"},
    "3883": {"url": "https://t.me/recruitment_SSR", "label": "Apply Now - Sokha Hotels"},
    "3884": {"url": "https://t.me/+855975406969", "label": "Apply Now - 0975406969"},
    "3885": {"url": "https://t.me/+85581808237", "label": "Apply Now - 081808237"},
}


def _get_default_data() -> dict:
    return {
        "links": {},
        "months": {},
        "recent_clicks": [],
    }


def load_click_data() -> dict:
    """Load persistent click data from JSON store."""
    if not os.path.exists(CLICK_STORE_FILE):
        return _get_default_data()

    try:
        with open(CLICK_STORE_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
            if not isinstance(data, dict):
                return _get_default_data()
            data.setdefault("links", {})
            data.setdefault("months", {})
            data.setdefault("recent_clicks", [])
            return data
    except Exception as exc:
        logger.warning("Error loading %s: %s. Re-initializing default.", CLICK_STORE_FILE, exc)
        return _get_default_data()


def save_click_data(data: dict) -> None:
    """Atomically save click data to avoid corruption."""
    with _data_lock:
        temp_file = f"{CLICK_STORE_FILE}.tmp"
        try:
            with open(temp_file, "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
            if os.path.exists(CLICK_STORE_FILE):
                os.replace(temp_file, CLICK_STORE_FILE)
            else:
                os.rename(temp_file, CLICK_STORE_FILE)
        except Exception as exc:
            logger.error("Failed to save click data to %s: %s", CLICK_STORE_FILE, exc)
            if os.path.exists(temp_file):
                try:
                    os.remove(temp_file)
                except OSError:
                    pass


def hash_user(client_ip: str, user_agent: str) -> str:
    """
    Generate an anonymized, consistent user identifier from IP and User-Agent
    to calculate unique users per button per month without storing personally identifiable info.
    """
    raw = f"useacc_salt_{client_ip.strip()}_{user_agent.strip()}"
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:12]


def register_tracking_link(
    base_url: str,
    target_url: str,
    label: str,
    link_type: str,
    post_id: Optional[str] = None,
    post_url: Optional[str] = None,
) -> str:
    """
    Register a button link and return a tracking URL (e.g. https://.../r/p3866_admin).
    Uses deterministic tokens based on post_id and link_type.
    """
    if not target_url:
        return ""

    post_id_str = str(post_id).strip() if post_id else ""
    if post_id_str:
        token = f"p{post_id_str}_{link_type}"
    else:
        # Deterministic hash of target_url for generic links
        short_hash = hashlib.md5(target_url.encode("utf-8")).hexdigest()[:8]
        token = f"g_{short_hash}_{link_type}"

    data = load_click_data()
    data["links"][token] = {
        "token": token,
        "target_url": target_url,
        "label": label,
        "link_type": link_type,
        "post_id": post_id_str,
        "post_url": post_url or "",
        "updated_at": datetime.now().isoformat(),
    }
    save_click_data(data)

    clean_base = (base_url or "").rstrip("/")
    return f"{clean_base}/r/{token}"


def record_click(token: str, client_ip: str = "", user_agent: str = "") -> str:
    """
    Record a click event on a button, increment monthly stats and unique users for each button,
    and return the destination target_url.
    """
    data = load_click_data()
    link_info = data["links"].get(token)

    post_id = ""
    link_type = "general"
    label = "Button"
    post_url = ""
    target_url = "https://t.me/USEACCAD"

    if link_info:
        target_url = link_info.get("target_url") or target_url
        label = link_info.get("label") or label
        link_type = link_info.get("link_type") or link_type
        post_id = str(link_info.get("post_id") or "")
        post_url = link_info.get("post_url") or ""
    elif token.startswith("p") and "_" in token:
        # Fallback parse from token if link_info not saved
        try:
            parts = token[1:].split("_", 1)
            post_id = parts[0]
            link_type = parts[1]
            if link_type in ("bot", "tips"):
                label = "Career Tips, CV & Cover Letter"
                target_url = "https://t.me/USEACCASTbot"
            elif link_type == "admin":
                label = "📞 Contact Admin"
                target_url = "https://t.me/USEACCAD"
                if post_id:
                    import urllib.parse
                    admin_msg = f"ជម្រាបសួរបង ខ្ញុំចាប់អារម្មណ៍នឹងការងារនេះ: 🔗 https://t.me/useacareercenter/{post_id}"
                    target_url = f"https://t.me/USEACCAD?text={urllib.parse.quote(admin_msg)}"
            elif link_type in ("employer", "apply"):
                if post_id in PAST_POST_CONTACTS:
                    info = PAST_POST_CONTACTS[post_id]
                    label = info.get("label", "Apply Now")
                    target_url = info.get("url", "https://t.me/USEACCAD")
                else:
                    label = "Apply Now"
                    target_url = "https://t.me/USEACCAD"
                    try:
                        cfile = os.path.join(os.path.dirname(os.path.abspath(__file__)), "contact.json")
                        if os.path.exists(cfile):
                            with open(cfile, "r", encoding="utf-8") as f:
                                cdata = json.load(f)
                                emp = cdata.get("apply_contacts", {}).get("employer", {})
                                if emp.get("url"):
                                    target_url = emp.get("url")
                                if emp.get("label"):
                                    label = emp.get("label")
                    except Exception:
                        pass
                    if target_url == "https://t.me/USEACCAD" and post_id:
                        import urllib.parse
                        admin_msg = f"ជម្រាបសួរបង ខ្ញុំចាប់អារម្មណ៍នឹងការងារនេះ: 🔗 https://t.me/useacareercenter/{post_id}"
                        target_url = f"https://t.me/USEACCAD?text={urllib.parse.quote(admin_msg)}"
            elif link_type == "email":
                label = "✉️ Apply via Email"
                target_url = "https://t.me/USEACCAD"
                try:
                    cfile = os.path.join(os.path.dirname(os.path.abspath(__file__)), "contact.json")
                    if os.path.exists(cfile):
                        with open(cfile, "r", encoding="utf-8") as f:
                            cdata = json.load(f)
                            em_data = cdata.get("apply_contacts", {}).get("email", {})
                            if em_data.get("url"):
                                target_url = em_data.get("url")
                            if em_data.get("label"):
                                label = em_data.get("label")
                except Exception:
                    pass
                if target_url == "https://t.me/USEACCAD" and post_id:
                    import urllib.parse
                    admin_msg = f"ជម្រាបសួរបង ខ្ញុំចាប់អារម្មណ៍នឹងការងារនេះ: 🔗 https://t.me/useacareercenter/{post_id}"
                    target_url = f"https://t.me/USEACCAD?text={urllib.parse.quote(admin_msg)}"

            post_url = f"https://t.me/useacareercenter/{post_id}"
        except Exception:
            pass

    now = datetime.now()
    month_key = now.strftime("%Y-%m")
    now_iso = now.isoformat()
    user_id = hash_user(client_ip, user_agent)

    # 1. Update month aggregated stats
    months = data.setdefault("months", {})
    m_data = months.setdefault(
        month_key,
        {
            "total_clicks": 0,
            "unique_users": [],
            "by_type": {},
            "by_link": {},
            "by_post": {},
        },
    )

    m_data["total_clicks"] = m_data.get("total_clicks", 0) + 1
    u_list = m_data.setdefault("unique_users", [])
    if user_id not in u_list:
        u_list.append(user_id)

    # By button type (e.g. admin, employer, bot)
    by_type = m_data.setdefault("by_type", {})
    t_entry = by_type.setdefault(link_type, {"label": label, "clicks": 0, "users": []})
    t_entry["clicks"] = t_entry.get("clicks", 0) + 1
    t_entry["label"] = label
    t_users = t_entry.setdefault("users", [])
    if user_id not in t_users:
        t_users.append(user_id)

    # By individual link token
    by_link = m_data.setdefault("by_link", {})
    l_entry = by_link.setdefault(
        token,
        {
            "token": token,
            "label": label,
            "link_type": link_type,
            "post_id": post_id,
            "post_url": post_url,
            "target_url": target_url,
            "clicks": 0,
            "users": [],
        },
    )
    l_entry["clicks"] = l_entry.get("clicks", 0) + 1
    l_users = l_entry.setdefault("users", [])
    if user_id not in l_users:
        l_users.append(user_id)

    # By post ID
    if post_id:
        by_post = m_data.setdefault("by_post", {})
        p_entry = by_post.setdefault(
            post_id,
            {
                "post_id": post_id,
                "post_url": post_url or f"https://t.me/useacareercenter/{post_id}",
                "clicks": 0,
                "users": [],
            },
        )
        p_entry["clicks"] = p_entry.get("clicks", 0) + 1
        p_users = p_entry.setdefault("users", [])
        if user_id not in p_users:
            p_users.append(user_id)

    # 2. Append to recent clicks log (keep last 5000)
    recent = data.setdefault("recent_clicks", [])
    recent.append(
        {
            "timestamp": now_iso,
            "month": month_key,
            "token": token,
            "label": label,
            "link_type": link_type,
            "post_id": post_id,
            "post_url": post_url,
            "target_url": target_url,
            "user_hash": user_id,
        }
    )
    if len(recent) > 5000:
        data["recent_clicks"] = recent[-5000:]

    save_click_data(data)
    logger.info("Recorded click: token=%s, button=%s, post=%s, month=%s", token, label, post_id, month_key)
    return target_url


def record_telegram_button_click(
    link_type: str,
    user_id: int,
    user_display: str = "",
    label: str = "",
    post_id: str = "",
    post_url: str = "",
    target_url: str = "",
) -> None:
    """
    Record a button click event triggered directly from Telegram deep links (Option 1).
    100% inside Telegram without web browser or Render redirection.
    """
    data = load_click_data()
    now = datetime.now()
    month_key = now.strftime("%Y-%m")
    now_iso = now.isoformat()
    uid_str = str(user_id)

    default_labels = {
        "admin": "📞 Contact Admin",
        "employer": "💼 Apply Now",
        "bot": "🤖 Career Tips Bot",
    }
    btn_label = label or default_labels.get(link_type, link_type)

    # 1. Update month aggregated stats
    months = data.setdefault("months", {})
    m_data = months.setdefault(
        month_key,
        {
            "total_clicks": 0,
            "unique_users": [],
            "by_type": {},
            "by_link": {},
            "by_post": {},
        },
    )

    m_data["total_clicks"] = m_data.get("total_clicks", 0) + 1
    u_list = m_data.setdefault("unique_users", [])
    if uid_str not in u_list:
        u_list.append(uid_str)

    # By button type (admin, employer, bot)
    by_type = m_data.setdefault("by_type", {})
    t_entry = by_type.setdefault(link_type, {"label": btn_label, "clicks": 0, "users": []})
    t_entry["clicks"] = t_entry.get("clicks", 0) + 1
    t_entry["label"] = btn_label
    t_users = t_entry.setdefault("users", [])
    if uid_str not in t_users:
        t_users.append(uid_str)

    # By post ID
    if post_id:
        by_post = m_data.setdefault("by_post", {})
        p_entry = by_post.setdefault(
            str(post_id),
            {
                "post_id": str(post_id),
                "post_url": post_url or f"https://t.me/useacareercenter/{post_id}",
                "clicks": 0,
                "users": [],
            },
        )
        p_entry["clicks"] = p_entry.get("clicks", 0) + 1
        p_users = p_entry.setdefault("users", [])
        if uid_str not in p_users:
            p_users.append(uid_str)

    # 2. Append to recent clicks log
    recent = data.setdefault("recent_clicks", [])
    recent.append(
        {
            "timestamp": now_iso,
            "month": month_key,
            "token": f"tg_{link_type}_{post_id}",
            "label": btn_label,
            "link_type": link_type,
            "post_id": str(post_id),
            "post_url": post_url or (f"https://t.me/useacareercenter/{post_id}" if post_id else ""),
            "target_url": target_url,
            "user_hash": uid_str,
            "user_display": user_display,
        }
    )
    if len(recent) > 5000:
        data["recent_clicks"] = recent[-5000:]

    save_click_data(data)
    logger.info("Recorded Telegram button click: type=%s, user=%s (%s), post=%s, month=%s", link_type, uid_str, user_display, post_id, month_key)


def get_available_months() -> List[str]:
    """Return sorted list of month strings (YYYY-MM), newest first."""
    data = load_click_data()
    months = set(data.get("months", {}).keys())
    current_month = datetime.now().strftime("%Y-%m")
    months.add(current_month)
    return sorted(list(months), reverse=True)


def get_monthly_report_data(month: Optional[str] = None) -> dict:
    """
    Retrieve aggregated statistics for each button for a specific month or all time ('all').
    """
    data = load_click_data()
    current_month = datetime.now().strftime("%Y-%m")
    target_month = month or current_month

    if target_month == "all":
        # Aggregate across all months
        total_clicks = 0
        all_users = set()
        by_type_merged = {}
        by_post_merged = {}

        for m_key, m_val in data.get("months", {}).items():
            total_clicks += m_val.get("total_clicks", 0)
            all_users.update(m_val.get("unique_users", []))

            # merge by_type (each button)
            for t_key, t_info in m_val.get("by_type", {}).items():
                dest = by_type_merged.setdefault(
                    t_key, {"label": t_info.get("label", t_key), "clicks": 0, "users": set()}
                )
                dest["clicks"] += t_info.get("clicks", 0)
                dest["users"].update(t_info.get("users", []))

            # merge by_post
            for p_key, p_info in m_val.get("by_post", {}).items():
                dest = by_post_merged.setdefault(
                    p_key,
                    {"post_id": p_key, "post_url": p_info.get("post_url", ""), "clicks": 0, "users": set()},
                )
                dest["clicks"] += p_info.get("clicks", 0)
                dest["users"].update(p_info.get("users", []))

        by_type_formatted = {
            k: {"label": v["label"], "clicks": v["clicks"], "unique_users": len(v["users"])}
            for k, v in by_type_merged.items()
        }
        by_post_formatted = {
            k: {
                "post_id": v["post_id"],
                "post_url": v["post_url"],
                "clicks": v["clicks"],
                "unique_users": len(v["users"]),
            }
            for k, v in by_post_merged.items()
        }

        return {
            "month": "all",
            "month_display": "គ្រប់ខែទាំងអស់ (All-Time)",
            "total_clicks": total_clicks,
            "unique_users_count": len(all_users),
            "by_type": by_type_formatted,
            "by_post": by_post_formatted,
        }

    # Specific month
    m_data = data.get("months", {}).get(target_month) or {
        "total_clicks": 0,
        "unique_users": [],
        "by_type": {},
        "by_link": {},
        "by_post": {},
    }

    by_type_formatted = {}
    for k, v in m_data.get("by_type", {}).items():
        by_type_formatted[k] = {
            "label": v.get("label", k),
            "clicks": v.get("clicks", 0),
            "unique_users": len(v.get("users", [])),
        }

    by_post_formatted = {}
    for k, v in m_data.get("by_post", {}).items():
        by_post_formatted[k] = {
            "post_id": v.get("post_id", k),
            "post_url": v.get("post_url", ""),
            "clicks": v.get("clicks", 0),
            "unique_users": len(v.get("users", [])),
        }

    return {
        "month": target_month,
        "month_display": f"ខែ {target_month}",
        "total_clicks": m_data.get("total_clicks", 0),
        "unique_users_count": len(m_data.get("unique_users", [])),
        "by_type": by_type_formatted,
        "by_post": by_post_formatted,
    }


def format_telegram_report(report_data: dict, webhook_url: str = "") -> str:
    """
    Format report into a clean HTML Telegram message clearly showing
    how many users clicked EACH BUTTON for the month.
    """
    month_display = report_data.get("month_display") or report_data.get("month")
    total_clicks = report_data.get("total_clicks", 0)
    unique_users = report_data.get("unique_users_count", 0)

    lines = [
        f"📊 <b>របាយការណ៍ចំនួនអ្នកចុចលើប៊ូតុងនីមួយៗ</b>",
        f"📅 <b>ប្រចាំ:</b> <code>{month_display}</code>",
        "━━━━━━━━━━━━━━━━━━━━",
        "🔘 <b>ស្ថិតិតាមប៊ូតុងនីមួយៗ (Stats for Each Button):</b>\n",
    ]

    by_type = report_data.get("by_type") or {}

    button_configs = [
        ("admin", "1️⃣ 📞 Contact Admin"),
        ("employer", "2️⃣ 💼 Apply Now (Employer)"),
        ("bot", "3️⃣ 🤖 Career Tips, CV & Cover Letter"),
    ]

    # Display primary buttons even if 0 clicks so admin sees full button layout
    for b_type, default_name in button_configs:
        b_info = by_type.get(b_type)
        if b_info:
            label = b_info.get("label") or default_name
            clicks = b_info.get("clicks", 0)
            users = b_info.get("unique_users", 0)
        else:
            label = default_name
            clicks = 0
            users = 0

        lines.append(f"<b>{label}:</b>")
        lines.append(f"   • ចំនួនអ្នកចុច (Unique Users): <b>{users}</b> នាក់")
        lines.append(f"   • ចំនួនចុចសរុប (Total Clicks): <b>{clicks}</b> ដង\n")

    # Extra custom buttons if any
    for b_type, b_info in by_type.items():
        if b_type not in ["admin", "employer", "bot"]:
            label = b_info.get("label", b_type)
            clicks = b_info.get("clicks", 0)
            users = b_info.get("unique_users", 0)
            lines.append(f"<b>🔘 {label}:</b>")
            lines.append(f"   • ចំនួនអ្នកចុច (Unique Users): <b>{users}</b> នាក់")
            lines.append(f"   • ចំនួនចុចសរុប (Total Clicks): <b>{clicks}</b> ដង\n")

    lines.append("━━━━━━━━━━━━━━━━━━━━")
    lines.append(f"👥 <b>អ្នកចុចសរុបទាំងអស់ (Total Unique Users):</b> <b>{unique_users}</b> នាក់")
    lines.append(f"👆 <b>ចំនួនចុចសរុបគ្រប់ប៊ូតុង (Total Button Clicks):</b> <b>{total_clicks}</b> ដង")

    by_post = report_data.get("by_post") or {}
    if by_post:
        lines.append("\n📌 <b>Post ដែលមានអ្នកចុចច្រើនជាងគេ (Top Posts):</b>")
        sorted_posts = sorted(by_post.values(), key=lambda x: x.get("clicks", 0), reverse=True)
        for p in sorted_posts[:5]:
            pid = p.get("post_id")
            p_url = p.get("post_url") or f"https://t.me/useacareercenter/{pid}"
            c = p.get("clicks", 0)
            u = p.get("unique_users", 0)
            lines.append(f"• <b>Post #{pid}:</b> {u} នាក់ ({c} clicks) — <a href=\"{p_url}\">មើល Post</a>")

    clean_webhook = (webhook_url or "").rstrip("/")
    if clean_webhook:
        lines.append(f"\n🌐 <b>Web Dashboard:</b> <a href=\"{clean_webhook}/report\">បើកមើលតារាងពេញលេញលើ Web</a>")

    return "\n".join(lines)


def generate_csv_report(month: Optional[str] = None) -> bytes:
    """
    Generate CSV file bytes with UTF-8 BOM encoding for Microsoft Excel compatibility.
    """
    data = load_click_data()
    recent = data.get("recent_clicks", [])

    output = io.StringIO()
    writer = csv.writer(output, quoting=csv.QUOTE_MINIMAL)

    # Header
    writer.writerow([
        "Timestamp (UTC/Local)",
        "Month (YYYY-MM)",
        "Button Name",
        "Button Type",
        "Post ID",
        "Post URL",
        "Destination Target URL",
        "Visitor Telegram ID",
        "Visitor Name / Username",
    ])

    rows_written = 0
    target_month = month if month and month != "all" else None

    for c in recent:
        if target_month and c.get("month") != target_month:
            continue
        writer.writerow([
            c.get("timestamp", ""),
            c.get("month", ""),
            c.get("label", ""),
            c.get("link_type", ""),
            c.get("post_id", ""),
            c.get("post_url", ""),
            c.get("target_url", ""),
            c.get("user_hash", ""),
            c.get("user_display", ""),
        ])
        rows_written += 1

    # If no individual logs found (e.g. older months), export aggregated summary rows
    if rows_written == 0:
        writer.writerow([])
        writer.writerow(["--- Monthly Button Summary Breakdown ---"])
        writer.writerow(["Month", "Button Name / Post", "Clicks", "Unique Users"])
        rep = get_monthly_report_data(month)
        for t_key, t_info in rep.get("by_type", {}).items():
            writer.writerow([
                rep.get("month", ""),
                f"Button: {t_info.get('label')}",
                t_info.get("clicks", 0),
                t_info.get("unique_users", 0),
            ])
        for p_key, p_info in rep.get("by_post", {}).items():
            writer.writerow([
                rep.get("month", ""),
                f"Post #{p_key}",
                p_info.get("clicks", 0),
                p_info.get("unique_users", 0),
            ])

    # UTF-8 BOM (\xef\xbb\xbf) ensures Khmer script opens correctly in Excel
    return "\ufeff".encode("utf-8") + output.getvalue().encode("utf-8")


# ------------------------------------------------------------------
# Tornado Web Handlers
# ------------------------------------------------------------------
class RedirectTrackerHandler(tornado.web.RequestHandler):
    """
    Handle GET /r/{token}: Log button click with IP/User-Agent and redirect with HTTP 302.
    """

    def get(self, token: str):
        token = token.strip()
        client_ip = self.request.headers.get("X-Forwarded-For", self.request.remote_ip or "")
        if "," in client_ip:
            client_ip = client_ip.split(",")[0].strip()
        user_agent = self.request.headers.get("User-Agent", "")

        target_url = record_click(token=token, client_ip=client_ip, user_agent=user_agent)
        self.redirect(target_url, status=302)

    def head(self, token: str):
        self.set_status(200)


class WebReportHandler(tornado.web.RequestHandler):
    """
    Handle GET /report: Beautiful interactive web dashboard showing stats for each button.
    """

    def get(self):
        month = self.get_argument("month", None)
        avail_months = get_available_months()
        if not month:
            month = avail_months[0] if avail_months else datetime.now().strftime("%Y-%m")

        rep = get_monthly_report_data(month)
        total_clicks = rep.get("total_clicks", 0)
        unique_users = rep.get("unique_users_count", 0)
        by_type = rep.get("by_type", {})
        by_post = rep.get("by_post", {})

        options_html = []
        for m in avail_months:
            selected = "selected" if m == month else ""
            options_html.append(f'<option value="{m}" {selected}>{m}</option>')
        options_html.append(
            f'<option value="all" {"selected" if month == "all" else ""}>All-Time (គ្រប់ខែ)</option>'
        )

        type_rows = []
        for k, v in by_type.items():
            pct = round((v["clicks"] / total_clicks * 100), 1) if total_clicks > 0 else 0
            type_rows.append(f"""
            <tr>
                <td><strong>{v['label']}</strong></td>
                <td><span class="badge">{k}</span></td>
                <td><strong style="color:var(--primary); font-size:1.1rem;">{v['unique_users']}</strong> នាក់</td>
                <td><strong>{v['clicks']}</strong> ដង</td>
                <td style="width: 25%;">
                    <div class="progress-bar-bg">
                        <div class="progress-bar-fill" style="width: {pct}%;"></div>
                    </div>
                    <small>{pct}%</small>
                </td>
            </tr>
            """)

        post_rows = []
        sorted_posts = sorted(by_post.values(), key=lambda x: x.get("clicks", 0), reverse=True)
        for p in sorted_posts[:25]:
            post_rows.append(f"""
            <tr>
                <td><strong>#{p['post_id']}</strong></td>
                <td><a href="{p['post_url']}" target="_blank" class="link">{p['post_url']}</a></td>
                <td><strong>{p['unique_users']}</strong> នាក់</td>
                <td><strong>{p['clicks']}</strong> ដង</td>
            </tr>
            """)

        html = f"""<!DOCTYPE html>
<html lang="km">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>USEA Career Center - Button Clicks Analytics</title>
    <style>
        :root {{
            --bg: #0f172a;
            --card-bg: #1e293b;
            --border: #334155;
            --primary: #38bdf8;
            --text: #f8fafc;
            --text-muted: #94a3b8;
            --success: #22c55e;
        }}
        body {{
            font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, 'Hanuman', 'Kantumruy Pro', sans-serif;
            background: var(--bg);
            color: var(--text);
            margin: 0;
            padding: 24px;
        }}
        .container {{
            max-width: 900px;
            margin: 0 auto;
        }}
        .header {{
            display: flex;
            justify-content: space-between;
            align-items: center;
            flex-wrap: wrap;
            gap: 16px;
            margin-bottom: 24px;
        }}
        h1 {{
            margin: 0;
            font-size: 1.6rem;
            color: var(--primary);
        }}
        .controls {{
            display: flex;
            gap: 10px;
            align-items: center;
        }}
        select, .btn {{
            background: var(--card-bg);
            border: 1px solid var(--border);
            color: var(--text);
            padding: 8px 14px;
            border-radius: 8px;
            font-size: 0.95rem;
            cursor: pointer;
            text-decoration: none;
        }}
        .btn-primary {{
            background: #0284c7;
            color: #fff;
            border: none;
            font-weight: 500;
        }}
        .btn-primary:hover {{
            background: #0369a1;
        }}
        .grid {{
            display: grid;
            grid-template-columns: repeat(auto-fit, minmax(200px, 1fr));
            gap: 16px;
            margin-bottom: 24px;
        }}
        .stat-card {{
            background: var(--card-bg);
            border: 1px solid var(--border);
            border-radius: 12px;
            padding: 20px;
            text-align: center;
        }}
        .stat-val {{
            font-size: 2rem;
            font-weight: 700;
            color: var(--primary);
            margin-top: 8px;
        }}
        .stat-label {{
            color: var(--text-muted);
            font-size: 0.85rem;
            text-transform: uppercase;
            letter-spacing: 0.05em;
        }}
        .card {{
            background: var(--card-bg);
            border: 1px solid var(--border);
            border-radius: 12px;
            padding: 20px;
            margin-bottom: 24px;
        }}
        .card h2 {{
            margin-top: 0;
            font-size: 1.2rem;
            margin-bottom: 16px;
            border-bottom: 1px solid var(--border);
            padding-bottom: 8px;
        }}
        table {{
            width: 100%;
            border-collapse: collapse;
            text-align: left;
        }}
        th, td {{
            padding: 12px 14px;
            border-bottom: 1px solid var(--border);
            font-size: 0.95rem;
        }}
        th {{
            color: var(--text-muted);
            font-weight: 600;
        }}
        .badge {{
            background: #334155;
            padding: 3px 8px;
            border-radius: 6px;
            font-size: 0.8rem;
        }}
        .link {{
            color: var(--primary);
            text-decoration: none;
            word-break: break-all;
        }}
        .progress-bar-bg {{
            background: #334155;
            height: 8px;
            border-radius: 4px;
            overflow: hidden;
            margin-bottom: 4px;
        }}
        .progress-bar-fill {{
            background: var(--primary);
            height: 100%;
        }}
    </style>
</head>
<body>
    <div class="container">
        <div class="header">
            <div>
                <h1>📊 USEA Career Center Analytics</h1>
                <div style="color: var(--text-muted); font-size: 0.9rem;">ស្ថិតិចុចលើប៊ូតុងនីមួយៗប្រចាំខែ ({rep.get('month_display')})</div>
            </div>
            <div class="controls">
                <select onchange="window.location.href='/report?month=' + this.value">
                    {''.join(options_html)}
                </select>
                <a href="/report/csv?month={month}" class="btn btn-primary">📥 Download CSV</a>
            </div>
        </div>

        <div class="grid">
            <div class="stat-card">
                <div class="stat-label">👥 អ្នកចុចសរុប (Unique Users)</div>
                <div class="stat-val">{unique_users}</div>
            </div>
            <div class="stat-card">
                <div class="stat-label">👆 ចំនួនចុចសរុប (Total Button Clicks)</div>
                <div class="stat-val">{total_clicks}</div>
            </div>
            <div class="stat-card">
                <div class="stat-label">📌 ចំនួន Post ដែលត្រូវបានចុច</div>
                <div class="stat-val">{len(by_post)}</div>
            </div>
        </div>

        <div class="card">
            <h2>🔘 ចំនួនអ្នកចុច និងចំនួនចុចលើប៊ូតុងនីមួយៗ (Stats for Each Button)</h2>
            <table>
                <thead>
                    <tr>
                        <th>ឈ្មោះប៊ូតុង (Button Name)</th>
                        <th>ប្រភេទ (Type)</th>
                        <th>ចំនួនអ្នកចុច (Unique Users)</th>
                        <th>ចំនួនចុចសរុប (Total Clicks)</th>
                        <th>សមាមាត្រ (%)</th>
                    </tr>
                </thead>
                <tbody>
                    {''.join(type_rows) if type_rows else '<tr><td colspan="5" style="text-align:center; color:var(--text-muted);">មិនទាន់មានទិន្នន័យ (No data)</td></tr>'}
                </tbody>
            </table>
        </div>

        <div class="card">
            <h2>📢 ចំនួនចុចតាម Channel Posts (Top Posts)</h2>
            <table>
                <thead>
                    <tr>
                        <th>Post ID</th>
                        <th>Post URL</th>
                        <th>ចំនួនអ្នកចុច (Users)</th>
                        <th>ចំនួនចុច (Clicks)</th>
                    </tr>
                </thead>
                <tbody>
                    {''.join(post_rows) if post_rows else '<tr><td colspan="4" style="text-align:center; color:var(--text-muted);">មិនទាន់មានទិន្នន័យ (No data)</td></tr>'}
                </tbody>
            </table>
        </div>
    </div>
</body>
</html>"""
        self.set_header("Content-Type", "text/html; charset=utf-8")
        self.write(html)


class WebCsvExportHandler(tornado.web.RequestHandler):
    """
    Handle GET /report/csv?month=YYYY-MM: Direct CSV file download.
    """

    def get(self):
        month = self.get_argument("month", None)
        avail_months = get_available_months()
        if not month:
            month = avail_months[0] if avail_months else datetime.now().strftime("%Y-%m")

        csv_bytes = generate_csv_report(month=month)
        filename = f"usea_button_clicks_report_{month}.csv"
        self.set_header("Content-Type", "text/csv; charset=utf-8")
        self.set_header("Content-Disposition", f'attachment; filename="{filename}"')
        self.write(csv_bytes)
