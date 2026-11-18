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

try:
    import openpyxl
    from openpyxl.styles import Alignment, Border, Font, PatternFill, Side
    from openpyxl.utils import get_column_letter
    HAS_OPENPYXL = True
except ImportError:
    HAS_OPENPYXL = False

logger = logging.getLogger(__name__)

DATA_DIR = os.getenv("DATA_DIR", "").strip()
_DEFAULT_CLICK_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "clicks.json")
if DATA_DIR and os.path.exists(DATA_DIR):
    CLICK_STORE_FILE = os.path.join(DATA_DIR, "clicks.json")
    if not os.path.exists(CLICK_STORE_FILE) and os.path.exists(_DEFAULT_CLICK_FILE):
        try:
            import shutil
            shutil.copy2(_DEFAULT_CLICK_FILE, CLICK_STORE_FILE)
            logger.info("Initialized persistent CLICK_STORE_FILE at %s", CLICK_STORE_FILE)
        except Exception as copy_e:
            logger.warning("Failed to initialize CLICK_STORE_FILE in DATA_DIR: %s", copy_e)
else:
    CLICK_STORE_FILE = _DEFAULT_CLICK_FILE

_data_lock = threading.Lock()


def merge_click_data(base: dict, incoming: dict) -> dict:
    """Merge incoming click data into base without losing any higher click counts or unique users."""
    if not isinstance(base, dict):
        base = _get_default_data()
    if not isinstance(incoming, dict):
        return base

    # 1. Merge links
    base_links = base.setdefault("links", {})
    incoming_links = incoming.get("links", {})
    for token, info in incoming_links.items():
        if token not in base_links or (info.get("updated_at", "") > base_links[token].get("updated_at", "")):
            base_links[token] = info

    # 2. Merge published_posts
    base_pub = base.setdefault("published_posts", {})
    incoming_pub = incoming.get("published_posts", {})
    for pid, pinfo in incoming_pub.items():
        if pid not in base_pub or (pinfo.get("timestamp", "") > base_pub[pid].get("timestamp", "")):
            base_pub[pid] = pinfo

    # Preserve earliest post tracking start date across base, incoming, and posts
    start_candidates = [
        str(base.get("post_tracking_started_at") or "").strip(),
        str(incoming.get("post_tracking_started_at") or "").strip(),
    ]
    resolved_base_start = _resolve_post_tracking_start(base)
    if resolved_base_start:
        start_candidates.append(resolved_base_start)
    valid_starts = [s for s in start_candidates if s]
    if valid_starts:
        base["post_tracking_started_at"] = min(valid_starts)

    # 3. Merge months
    base_months = base.setdefault("months", {})
    incoming_months = incoming.get("months", {})
    for m_key, in_m in incoming_months.items():
        if m_key not in base_months:
            base_months[m_key] = in_m
            continue

        bm = base_months[m_key]
        # Merge unique users
        bm_users = set(bm.get("unique_users", []))
        bm_users.update(in_m.get("unique_users", []))
        bm["unique_users"] = list(bm_users)

        # Merge posts_published
        bm_posts = set(bm.get("posts_published", []))
        bm_posts.update(in_m.get("posts_published", []))
        bm["posts_published"] = list(bm_posts)

        # Merge posts_by_admin
        bm_admin = bm.setdefault("posts_by_admin", {})
        for adm_k, in_adm in in_m.get("posts_by_admin", {}).items():
            if adm_k not in bm_admin:
                bm_admin[adm_k] = in_adm
            else:
                a_posts = set(bm_admin[adm_k].get("posts", []))
                a_posts.update(in_adm.get("posts", []))
                bm_admin[adm_k]["posts"] = list(a_posts)
                bm_admin[adm_k]["count"] = len(bm_admin[adm_k]["posts"])
                if in_adm.get("admin_name"):
                    bm_admin[adm_k]["admin_name"] = in_adm["admin_name"]

        # Merge by_type
        b_type = bm.setdefault("by_type", {})
        for t_k, in_t in in_m.get("by_type", {}).items():
            if t_k not in b_type:
                b_type[t_k] = in_t
            else:
                b_t_users = set(b_type[t_k].get("users", []))
                b_t_users.update(in_t.get("users", []))
                b_type[t_k]["users"] = list(b_t_users)
                b_type[t_k]["clicks"] = max(b_type[t_k].get("clicks", 0), in_t.get("clicks", 0))
                if in_t.get("label"):
                    b_type[t_k]["label"] = in_t["label"]

        # Merge by_link
        b_link = bm.setdefault("by_link", {})
        for l_k, in_l in in_m.get("by_link", {}).items():
            if l_k not in b_link:
                b_link[l_k] = in_l
            else:
                b_l_users = set(b_link[l_k].get("users", []))
                b_l_users.update(in_l.get("users", []))
                b_link[l_k]["users"] = list(b_l_users)
                b_link[l_k]["clicks"] = max(b_link[l_k].get("clicks", 0), in_l.get("clicks", 0))
                for attr in ("target_url", "label", "post_url", "post_id"):
                    if in_l.get(attr):
                        b_link[l_k][attr] = in_l[attr]

        # Merge by_post
        b_post = bm.setdefault("by_post", {})
        for p_k, in_p in in_m.get("by_post", {}).items():
            if p_k not in b_post:
                b_post[p_k] = in_p
            else:
                b_p_users = set(b_post[p_k].get("users", []))
                b_p_users.update(in_p.get("users", []))
                b_post[p_k]["users"] = list(b_p_users)
                b_post[p_k]["clicks"] = max(b_post[p_k].get("clicks", 0), in_p.get("clicks", 0))

        # Re-evaluate total clicks for month
        link_clicks_sum = sum(v.get("clicks", 0) for v in b_link.values())
        bm["total_clicks"] = max(bm.get("total_clicks", 0), in_m.get("total_clicks", 0), link_clicks_sum)

    # 4. Merge recent_clicks (keep deduplicated, newest first, max 500)
    seen_clicks = set()
    merged_recent = []
    combined_recent = base.get("recent_clicks", []) + incoming.get("recent_clicks", [])
    combined_recent.sort(key=lambda x: x.get("timestamp", ""), reverse=True)
    for c in combined_recent:
        key = (c.get("timestamp"), c.get("token"), c.get("user_hash"))
        if key not in seen_clicks:
            seen_clicks.add(key)
            merged_recent.append(c)
        if len(merged_recent) >= 500:
            break
    base["recent_clicks"] = merged_recent

    return base

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
    "3886": {"url": "https://t.me/USEACCAD", "label": "Apply Now"},
    "3887": {"url": "https://t.me/+85586703338", "label": "Apply Now - 086703338"},
    "3888": {"url": "https://t.me/+85577967755", "label": "Apply Now - 077967755"},
    "3889": {"url": "https://t.me/+85516499099", "label": "Apply Now - 016499099"},
    "3890": {"url": "https://t.me/+85595465668", "label": "Apply Now - 095465668"},
    "4043": {
        "url": "https://t.me/+85515959355",
        "label": "Apply via Telegram ☎️",
        "email": "mailto:careers@artisansangkor.com",
        "tokens": {
            "p4043_email1": {"url": "mailto:careers@artisansangkor.com", "label": "Apply via Email 📩", "link_type": "email"},
            "p4043_apply2": {"url": "https://t.me/+85515959355", "label": "Apply via Telegram ☎️", "link_type": "employer"},
        },
    },
    "4044": {
        "url": "https://t.me/vanhong_siemreap_careers",
        "label": "More Information ☎️",
        "tokens": {
            "p4044_apply1": {"url": "https://t.me/vanhong_siemreap_careers", "label": "More Information ☎️", "link_type": "employer"},
            "p4044_apply2": {"url": "https://maps.app.goo.gl/SVYMNV7ysh3Hb4978", "label": "Location 🗺", "link_type": "employer"},
        },
    },
    "4045": {
        "url": "mailto:hr@api-school.com",
        "label": "Apply via Email",
        "email": "mailto:hr@api-school.com",
        "tokens": {
            "p4045_email1": {"url": "mailto:hr@api-school.com", "label": "Apply via Email", "link_type": "email"},
        },
    },
    "4046": {
        "url": "https://t.me/umgcambodia",
        "label": "Apply Now ✉",
        "tokens": {
            "p4046_apply1": {"url": "https://t.me/umgcambodia", "label": "Apply Now ✉", "link_type": "employer"},
        },
    },
    "4047": {
        "url": "https://t.me/+85599919112",
        "label": "Apply via Telegram ☎️",
        "email": "mailto:hr@theheriategwalk.com",
        "tokens": {
            "p4047_apply1": {"url": "https://t.me/+85599919112", "label": "Apply via Telegram ☎️", "link_type": "employer"},
            "p4047_email2": {"url": "mailto:hr@theheriategwalk.com", "label": "Apply via Email 📧", "link_type": "email"},
        },
    },
    "4048": {
        "url": "https://t.me/+85566711176",
        "label": "Apply Now ✉",
        "tokens": {
            "p4048_apply1": {"url": "https://t.me/+85566711176", "label": "Apply Now ✉", "link_type": "employer"},
            "p4048_apply2": {"url": "https://maps.app.goo.gl/hpz54emuKDwiWXxC8", "label": "Location 🗺", "link_type": "employer"},
        },
    },
    "4049": {
        "url": "https://t.me/+855962080434",
        "label": "Apply Now",
        "tokens": {
            "p4049_apply1": {"url": "https://t.me/+855962080434", "label": "Apply Now", "link_type": "employer"},
        },
    },
    "4050": {
        "url": "https://t.me/+85569780618",
        "label": "Apply Now",
        "tokens": {
            "p4050_apply1": {"url": "https://t.me/+85569780618", "label": "Apply Now", "link_type": "employer"},
        },
    },
}


def _resolve_post_tracking_start(data: dict) -> str:
    """Return earliest ISO timestamp when post tracking started across stored metadata and published posts."""
    candidates = []
    stored = str(data.get("post_tracking_started_at") or "").strip()
    if stored:
        candidates.append(stored)
    for p in (data.get("published_posts") or {}).values():
        if isinstance(p, dict):
            ts = str(p.get("timestamp") or "").strip()
            if ts:
                candidates.append(ts)
    return min(candidates) if candidates else ""


def _format_tracking_date(iso_ts: str) -> str:
    """Format an ISO timestamp (e.g. 2026-11-01T00:00:00) into YYYY-MM-DD for display."""
    raw = str(iso_ts or "").strip()
    if not raw:
        return ""
    if "T" in raw:
        return raw.split("T", 1)[0]
    return raw[:10]


def _get_default_data() -> dict:
    return {
        "links": {},
        "months": {},
        "recent_clicks": [],
        "published_posts": {},
        "post_tracking_started_at": "",
    }


def _seed_published_posts(data: dict) -> bool:
    """Pre-seed historical posts (3866-3890) so stats accurately reflect published posts."""
    pub = data.setdefault("published_posts", {})
    m_data = data.setdefault("months", {}).setdefault(
        "2026-11",
        {
            "total_clicks": 0,
            "unique_users": [],
            "by_type": {},
            "by_link": {},
            "by_post": {},
            "posts_published": [],
            "posts_by_admin": {},
        },
    )
    posts_pub = m_data.setdefault("posts_published", [])
    changed = False

    historical_ids = [
        "3866", "3867", "3868", "3869", "3870", "3871", "3872", "3873", "3874",
        "3875", "3876", "3877", "3878", "3879", "3880", "3881", "3882",
        "3883", "3884", "3885", "3886", "3887", "3888", "3889", "3890"
    ]
    for pid in historical_ids:
        if pid not in pub:
            contact_label = PAST_POST_CONTACTS.get(pid, {}).get("label", "Job Announcement")
            pub[pid] = {
                "post_id": pid,
                "post_url": f"https://t.me/useacareercenter/{pid}",
                "timestamp": f"2026-11-01T{int(pid) % 24:02d}:00:00",
                "month": "2026-11",
                "admin_id": None,
                "admin_name": "Admin",
                "caption_snippet": f"Job Post #{pid} ({contact_label})",
            }
            changed = True
        if pid not in posts_pub:
            posts_pub.append(pid)
            changed = True

    by_admin = m_data.setdefault("posts_by_admin", {})
    if "Admin" not in by_admin and posts_pub:
        by_admin["Admin"] = {
            "admin_id": None,
            "admin_name": "Admin",
            "posts": list(posts_pub),
            "count": len(posts_pub),
        }
        changed = True

    earliest_start = _resolve_post_tracking_start(data)
    if earliest_start and data.get("post_tracking_started_at") != earliest_start:
        data["post_tracking_started_at"] = earliest_start
        changed = True

    return changed


def load_click_data() -> dict:
    """Load persistent click data from JSON store."""
    if not os.path.exists(CLICK_STORE_FILE):
        data = _get_default_data()
        _seed_published_posts(data)
        save_click_data(data)
        return data

    try:
        with open(CLICK_STORE_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
            if not isinstance(data, dict):
                data = _get_default_data()
            data.setdefault("links", {})
            data.setdefault("months", {})
            data.setdefault("recent_clicks", [])
            data.setdefault("published_posts", {})
            data.setdefault("post_tracking_started_at", "")
            if _seed_published_posts(data):
                save_click_data(data)
            return data
    except Exception as exc:
        logger.warning("Error loading %s: %s. Re-initializing default.", CLICK_STORE_FILE, exc)
        data = _get_default_data()
        _seed_published_posts(data)
        save_click_data(data)
        return data


def save_click_data(data: dict) -> None:
    """Atomically save click data to avoid corruption, with Windows lock fallback."""
    with _data_lock:
        temp_file = f"{CLICK_STORE_FILE}.tmp"
        try:
            with open(temp_file, "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
            try:
                if os.path.exists(CLICK_STORE_FILE):
                    os.replace(temp_file, CLICK_STORE_FILE)
                else:
                    os.rename(temp_file, CLICK_STORE_FILE)
            except PermissionError:
                # Windows file watchers/editors can block atomic replace; write in-place as fallback.
                with open(CLICK_STORE_FILE, "w", encoding="utf-8") as f:
                    json.dump(data, f, ensure_ascii=False, indent=2)
        except Exception as exc:
            logger.error("Failed to save click data to %s: %s", CLICK_STORE_FILE, exc)
        finally:
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
                label = "📲 Contact Admin"
                target_url = "https://t.me/USEACCAD"
                if post_id:
                    import urllib.parse
                    admin_msg = f"ជម្រាបសួរបង ខ្ញុំចាប់អារម្មណ៍នឹងការងារនេះ: 🔗 https://t.me/useacareercenter/{post_id}"
                    target_url = f"https://t.me/USEACCAD?text={urllib.parse.quote(admin_msg)}"
            elif post_id in PAST_POST_CONTACTS and token in PAST_POST_CONTACTS[post_id].get("tokens", {}):
                t_info = PAST_POST_CONTACTS[post_id]["tokens"][token]
                target_url = t_info["url"]
                label = t_info.get("label", "Apply Now")
                link_type = t_info.get("link_type", link_type)
            elif link_type.startswith("email"):
                if post_id in PAST_POST_CONTACTS and PAST_POST_CONTACTS[post_id].get("email"):
                    target_url = PAST_POST_CONTACTS[post_id]["email"]
                    label = "Apply via Email"
                else:
                    label = "Apply Now"
                    target_url = "https://t.me/USEACCAD"
                    if post_id:
                        import urllib.parse
                        admin_msg = f"ជម្រាបសួរបង ខ្ញុំចាប់អារម្មណ៍នឹងការងារនេះ: 🔗 https://t.me/useacareercenter/{post_id}"
                        target_url = f"https://t.me/USEACCAD?text={urllib.parse.quote(admin_msg)}"
            elif link_type in ("employer", "apply") or link_type.startswith("apply") or link_type.startswith("employer"):
                if post_id in PAST_POST_CONTACTS:
                    info = PAST_POST_CONTACTS[post_id]
                    label = info.get("label", "Apply Now")
                    target_url = info.get("url", "https://t.me/USEACCAD")
                else:
                    label = "Apply Now"
                    target_url = "https://t.me/USEACCAD"
                    if post_id:
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
        "admin": "📲 Contact Admin",
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


def record_published_post(
    post_id: str,
    post_url: str = "",
    admin_id: Optional[int] = None,
    admin_name: str = "Admin",
    caption_snippet: str = "",
) -> None:
    """
    Record a post published to the channel by an admin.
    Tracks total count, monthly count, and breakdown by admin.
    """
    if not post_id:
        return
    post_id = str(post_id).strip()
    data = load_click_data()
    now = datetime.now()
    month_key = now.strftime("%Y-%m")
    now_iso = now.isoformat()

    full_url = post_url or f"https://t.me/useacareercenter/{post_id}"

    # 1. Global registry
    pub = data.setdefault("published_posts", {})
    pub[post_id] = {
        "post_id": post_id,
        "post_url": full_url,
        "timestamp": now_iso,
        "month": month_key,
        "admin_id": admin_id,
        "admin_name": admin_name or "Admin",
        "caption_snippet": (caption_snippet or "")[:150].strip(),
    }
    earliest_start = _resolve_post_tracking_start(data) or now_iso
    data["post_tracking_started_at"] = earliest_start

    # 2. Month-specific stats
    months = data.setdefault("months", {})
    m_data = months.setdefault(
        month_key,
        {
            "total_clicks": 0,
            "unique_users": [],
            "by_type": {},
            "by_link": {},
            "by_post": {},
            "posts_published": [],
            "posts_by_admin": {},
        },
    )
    posts_pub = m_data.setdefault("posts_published", [])
    if post_id not in posts_pub:
        posts_pub.append(post_id)

    # 3. Admin-specific stats
    admin_key = str(admin_id) if admin_id else (admin_name or "Admin")
    by_admin = m_data.setdefault("posts_by_admin", {})
    adm_entry = by_admin.setdefault(
        admin_key,
        {
            "admin_id": admin_id,
            "admin_name": admin_name or "Admin",
            "posts": [],
            "count": 0,
        },
    )
    adm_posts = adm_entry.setdefault("posts", [])
    if post_id not in adm_posts:
        adm_posts.append(post_id)
    adm_entry["count"] = len(adm_posts)
    adm_entry["admin_name"] = admin_name or adm_entry.get("admin_name", "Admin")

    save_click_data(data)
    logger.info("Recorded published post: id=%s, admin=%s (%s), month=%s", post_id, admin_name, admin_id, month_key)


def get_available_months() -> List[str]:
    """Return sorted list of month strings (YYYY-MM), newest first."""
    data = load_click_data()
    months = set(data.get("months", {}).keys())
    current_month = datetime.now().strftime("%Y-%m")
    months.add(current_month)
    return sorted(list(months), reverse=True)


def get_monthly_report_data(month: Optional[str] = None) -> dict:
    """
    Retrieve aggregated statistics for each button and published posts for a specific month or all time ('all').
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

        # Published posts all-time
        pub_posts = data.get("published_posts", {})
        all_posts = list(pub_posts.values())
        all_posts.sort(
            key=lambda x: (x.get("timestamp", ""), int(x.get("post_id", 0)) if str(x.get("post_id", "")).isdigit() else 0),
            reverse=True,
        )

        # Merge posts_by_admin across all months
        all_admin_merged = {}
        for m_key, m_val in data.get("months", {}).items():
            for a_key, a_val in m_val.get("posts_by_admin", {}).items():
                dest = all_admin_merged.setdefault(
                    a_key,
                    {
                        "admin_id": a_val.get("admin_id"),
                        "admin_name": a_val.get("admin_name", "Admin"),
                        "posts": set(),
                        "count": 0,
                    },
                )
                dest["posts"].update(a_val.get("posts", []))
                if a_val.get("admin_name"):
                    dest["admin_name"] = a_val["admin_name"]

        all_admin_formatted = {
            k: {
                "admin_id": v["admin_id"],
                "admin_name": v["admin_name"],
                "posts": list(v["posts"]),
                "count": len(v["posts"]),
            }
            for k, v in all_admin_merged.items()
        }

        return {
            "month": "all",
            "month_display": "គ្រប់ខែទាំងអស់ (All-Time)",
            "total_clicks": total_clicks,
            "unique_users_count": len(all_users),
            "by_type": by_type_formatted,
            "by_post": by_post_formatted,
            "posts_count": len(all_posts),
            "published_posts": all_posts,
            "posts_by_admin": all_admin_formatted,
            "post_tracking_started_at": _format_tracking_date(_resolve_post_tracking_start(data)),
        }

    # Specific month
    m_data = data.get("months", {}).get(target_month) or {
        "total_clicks": 0,
        "unique_users": [],
        "by_type": {},
        "by_link": {},
        "by_post": {},
        "posts_published": [],
        "posts_by_admin": {},
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

    # Gather posts for this month
    pub_posts = data.get("published_posts", {})
    month_post_ids = set(m_data.get("posts_published", []))
    month_posts = [
        p for p in pub_posts.values()
        if p.get("post_id") in month_post_ids or p.get("month") == target_month
    ]
    for pid in month_post_ids:
        if not any(p.get("post_id") == pid for p in month_posts):
            month_posts.append({
                "post_id": pid,
                "post_url": f"https://t.me/useacareercenter/{pid}",
                "timestamp": f"{target_month}-01T00:00:00",
                "month": target_month,
                "admin_id": None,
                "admin_name": "Admin",
                "caption_snippet": f"Post #{pid}",
            })

    month_posts.sort(
        key=lambda x: (x.get("timestamp", ""), int(x.get("post_id", 0)) if str(x.get("post_id", "")).isdigit() else 0),
        reverse=True,
    )

    posts_by_admin = m_data.get("posts_by_admin", {})

    return {
        "month": target_month,
        "month_display": f"ខែ {target_month}",
        "total_clicks": m_data.get("total_clicks", 0),
        "unique_users_count": len(m_data.get("unique_users", [])),
        "by_type": by_type_formatted,
        "by_post": by_post_formatted,
        "posts_count": len(month_posts),
        "published_posts": month_posts,
        "posts_by_admin": posts_by_admin,
        "post_tracking_started_at": _format_tracking_date(_resolve_post_tracking_start(data)),
    }


def format_telegram_report(report_data: dict, webhook_url: str = "") -> str:
    """
    Format report into a clean HTML Telegram message clearly showing
    how many posts were published and how many users clicked EACH BUTTON for the month.
    """
    month_display = report_data.get("month_display") or report_data.get("month")
    total_clicks = report_data.get("total_clicks", 0)
    unique_users = report_data.get("unique_users_count", 0)
    posts_count = report_data.get("posts_count", 0)
    posts_by_admin = report_data.get("posts_by_admin") or {}
    started_date = report_data.get("post_tracking_started_at") or ""

    lines = [
        f"📊 <b>របាយការណ៍សកម្មភាព និងស្ថិតិចុចលើប៊ូតុង</b>",
        f"📅 <b>ប្រចាំ:</b> <code>{month_display}</code>",
        "━━━━━━━━━━━━━━━━━━━━",
        f"📢 <b>ចំនួន Post បានបង្ហោះចូល Channel:</b> <b>{posts_count}</b> Posts",
    ]
    if started_date:
        lines.append(f"🗓️ <b>ចាប់ផ្តើមតាមដានពីថ្ងៃទី (Tracking Started):</b> <code>{started_date}</code>")

    if posts_by_admin:
        lines.append("✍️ <b>Admin អ្នកបង្ហោះ (Posted by):</b>")
        for adm_k, adm_info in posts_by_admin.items():
            adm_name = adm_info.get("admin_name", "Admin")
            cnt = adm_info.get("count", len(adm_info.get("posts", [])))
            lines.append(f"   • <b>{adm_name}:</b> {cnt} Posts")

    lines.extend([
        "━━━━━━━━━━━━━━━━━━━━",
        "🔘 <b>ស្ថិតិតាមប៊ូតុងនីមួយៗ (Stats for Each Button):</b>\n",
    ])

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
    since_suffix = f" (ចាប់ពីថ្ងៃទី <code>{started_date}</code>)" if started_date else ""
    lines.append(f"📢 <b>ចំនួន Post សរុប (Total Posts Published):</b> <b>{posts_count}</b> Posts{since_suffix}")

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


def format_telegram_posts_report(report_data: dict, webhook_url: str = "") -> str:
    """
    Format dedicated post count & published channel posts report for Telegram.
    """
    month_display = report_data.get("month_display") or report_data.get("month")
    posts_count = report_data.get("posts_count", 0)
    published_posts = report_data.get("published_posts") or []
    posts_by_admin = report_data.get("posts_by_admin") or {}
    started_date = report_data.get("post_tracking_started_at") or ""

    lines = [
        "📢 <b>របាយការណ៍ចំនួន Post ដែលបង្ហោះចូល Channel</b>",
        f"📅 <b>ប្រចាំ:</b> <code>{month_display}</code>",
    ]
    if started_date:
        lines.append(f"🗓️ <b>ចាប់ផ្តើមតាមដានពីថ្ងៃទី (Tracking Started):</b> <code>{started_date}</code>")
    lines.extend([
        "━━━━━━━━━━━━━━━━━━━━",
        f"📊 <b>ចំនួន Post បានបង្ហោះសរុប:</b> <b>{posts_count}</b> Posts\n",
    ])

    if posts_by_admin:
        lines.append("✍️ <b>ស្ថិតិតាម Admin (Posts by Admin):</b>")
        for adm_k, adm_info in posts_by_admin.items():
            adm_name = adm_info.get("admin_name", "Admin")
            cnt = adm_info.get("count", len(adm_info.get("posts", [])))
            lines.append(f"   • <b>{adm_name}:</b> <b>{cnt}</b> Posts")
        lines.append("")

    if published_posts:
        lines.append("📝 <b>បញ្ជី Post ថ្មីៗ (Recent Channel Posts):</b>")
        for p in published_posts[:12]:
            pid = p.get("post_id")
            p_url = p.get("post_url") or f"https://t.me/useacareercenter/{pid}"
            adm = p.get("admin_name", "Admin")
            snip = p.get("caption_snippet", "")
            if len(snip) > 35:
                snip = snip[:32] + "..."
            snip_text = f" — <i>{snip}</i>" if snip else ""
            lines.append(f"• <b>Post #{pid}</b> ({adm}): <a href=\"{p_url}\">មើល Post</a>{snip_text}")

    clean_webhook = (webhook_url or "").rstrip("/")
    if clean_webhook:
        lines.append(f"\n🌐 <b>Web Dashboard:</b> <a href=\"{clean_webhook}/report\">បើកមើលតារាងពេញលេញលើ Web</a>")

    return "\n".join(lines)


def generate_csv_report(month: Optional[str] = None) -> bytes:
    """
    Generate CSV file bytes with UTF-8 BOM encoding for Microsoft Excel compatibility.
    Includes Executive Summary, Channel Published Posts & Click Performance,
    Button Performance Breakdown, and Detailed Individual Click Logs.
    """
    data = load_click_data()
    rep = get_monthly_report_data(month)
    recent = data.get("recent_clicks", [])

    output = io.StringIO()
    writer = csv.writer(output, quoting=csv.QUOTE_MINIMAL)

    # 1. Executive Summary (សេចក្តីសង្ខេបរបាយការណ៍)
    writer.writerow(["--- Executive Summary (សេចក្តីសង្ខេបរបាយការណ៍) ---"])
    writer.writerow(["Report Period (កាលបរិច្ឆេទរបាយការណ៍)", rep.get("month_display") or rep.get("month", "")])
    writer.writerow(["Total Posts Published (ចំនួន Post បានបង្ហោះសរុប)", rep.get("posts_count", 0)])
    writer.writerow(["Total Button Clicks (ចំនួនចុចប៊ូតុងសរុប)", rep.get("total_clicks", 0)])
    writer.writerow(["Total Unique Users (ចំនួនអ្នកចុចសរុប)", rep.get("unique_users_count", 0)])
    started_date = rep.get("post_tracking_started_at") or ""
    if started_date:
        writer.writerow(["Post Tracking Started Date (កាលបរិច្ឆេទចាប់ផ្តើមតាមដាន)", started_date])
    posts_by_admin = rep.get("posts_by_admin") or {}
    for adm_k, adm_info in posts_by_admin.items():
        adm_name = adm_info.get("admin_name", "Admin")
        cnt = adm_info.get("count", len(adm_info.get("posts", [])))
        writer.writerow([f"Posts Published by {adm_name} (បង្ហោះដោយ {adm_name})", cnt])
    writer.writerow([])

    # 2. Channel Published Posts & Click Performance (ស្ថិតិ Post នីមួយៗ)
    writer.writerow(["--- Channel Published Posts & Click Performance (ស្ថិតិ Post នីមួយៗ) ---"])
    writer.writerow([
        "Post ID",
        "Post URL",
        "Admin / Author",
        "Publish Date/Time",
        "Clicks on Post (ចំនួនចុច)",
        "Unique Users on Post (ចំនួនអ្នកចុច)",
        "Caption Snippet",
    ])

    published_posts = list(rep.get("published_posts") or [])
    by_post = rep.get("by_post") or {}

    # Merge any post from by_post that had clicks but wasn't in published_posts
    seen_pids = {str(p.get("post_id", "")).strip() for p in published_posts if p.get("post_id")}
    for pid, p_stat in by_post.items():
        pid_str = str(pid).strip()
        if pid_str and pid_str not in seen_pids:
            published_posts.append({
                "post_id": pid_str,
                "post_url": p_stat.get("post_url") or f"https://t.me/useacareercenter/{pid_str}",
                "timestamp": "",
                "admin_name": "Admin",
                "caption_snippet": f"Post #{pid_str}",
            })
            seen_pids.add(pid_str)

    def _sort_key(p):
        ts = p.get("timestamp") or ""
        pid_raw = str(p.get("post_id") or "")
        pid_num = int(pid_raw) if pid_raw.isdigit() else 0
        return (ts, pid_num)

    published_posts.sort(key=_sort_key, reverse=True)

    for p in published_posts:
        pid = str(p.get("post_id", "")).strip()
        p_stat = by_post.get(pid, {})
        p_clicks = p_stat.get("clicks", 0)
        p_users = p_stat.get("unique_users", 0)
        ts = p.get("timestamp", "")
        if "T" in ts:
            ts = ts.replace("T", " ")[:19]
        writer.writerow([
            pid,
            p.get("post_url", f"https://t.me/useacareercenter/{pid}"),
            p.get("admin_name", "Admin"),
            ts,
            p_clicks,
            p_users,
            p.get("caption_snippet", ""),
        ])
    writer.writerow([])

    # 3. Button Performance Breakdown (ស្ថិតិតាមប៊ូតុងនីមួយៗ)
    writer.writerow(["--- Button Performance Breakdown (ស្ថិតិតាមប៊ូតុងនីមួយៗ) ---"])
    writer.writerow(["Button Name", "Button Type", "Unique Users (ចំនួនអ្នកចុច)", "Total Clicks (ចំនួនចុចសរុប)"])
    by_type = rep.get("by_type") or {}
    for t_key, t_info in by_type.items():
        writer.writerow([
            t_info.get("label", t_key),
            t_key,
            t_info.get("unique_users", 0),
            t_info.get("clicks", 0),
        ])
    writer.writerow([])

    # 4. Detailed Individual Button Click Logs (កំណត់ត្រាចុចលម្អិត)
    writer.writerow(["--- Detailed Individual Button Click Logs (កំណត់ត្រាចុចលម្អិត) ---"])
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

    if rows_written == 0:
        writer.writerow(["(No individual click events logged for this period)", "", "", "", "", "", "", "", ""])

    # UTF-8 BOM (\xef\xbb\xbf) ensures Khmer script opens correctly in Excel
    return "\ufeff".encode("utf-8") + output.getvalue().encode("utf-8")


def generate_excel_report(month: Optional[str] = None) -> bytes:
    """
    Generate professional, beautifully styled multi-sheet Excel workbook (.xlsx).
    Divided into dedicated sheets:
      1. Overview & Buttons: Executive KPI summary & styled button performance table.
      2. All Channel Posts: Every channel post in one sheet with URLs, authors, clicks, and users.
      3. Post Authors: Every admin/user who posted in one sheet with post counts, clicks, and averages.
      4. Detailed Click Logs: Granular individual click audit logs with clickable destination links.
    """
    if not HAS_OPENPYXL:
        raise RuntimeError("openpyxl is not installed. Please install openpyxl to export Excel reports.")

    rep = get_monthly_report_data(month)
    data = load_click_data()
    recent = data.get("recent_clicks", [])

    wb = openpyxl.Workbook()

    # Premium Color Palette
    navy_fill = PatternFill(start_color="1E3A8A", end_color="1E3A8A", fill_type="solid")
    teal_fill = PatternFill(start_color="0F766E", end_color="0F766E", fill_type="solid")
    indigo_fill = PatternFill(start_color="4338CA", end_color="4338CA", fill_type="solid")
    slate_fill = PatternFill(start_color="334155", end_color="334155", fill_type="solid")
    zebra_fill = PatternFill(start_color="F8FAFC", end_color="F8FAFC", fill_type="solid")
    total_fill = PatternFill(start_color="E2E8F0", end_color="E2E8F0", fill_type="solid")
    card_hdr_fill = PatternFill(start_color="F1F5F9", end_color="F1F5F9", fill_type="solid")

    font_banner = Font(name="Segoe UI", size=14, bold=True, color="FFFFFF")
    font_sub = Font(name="Segoe UI", size=9, italic=True, color="E0E7FF")
    font_sec_hdr = Font(name="Segoe UI", size=11, bold=True, color="1E3A8A")
    font_col_hdr = Font(name="Segoe UI", size=10, bold=True, color="FFFFFF")
    font_bold = Font(name="Segoe UI", size=9, bold=True, color="0F172A")
    font_regular = Font(name="Segoe UI", size=9, color="0F172A")
    font_link = Font(name="Segoe UI", size=9, color="2563EB", underline="single")

    thin_side = Side(border_style="thin", color="CBD5E1")
    border_all = Border(left=thin_side, right=thin_side, top=thin_side, bottom=thin_side)
    border_total = Border(left=thin_side, right=thin_side, top=thin_side, bottom=Side(border_style="double", color="0F172A"))

    align_center = Alignment(horizontal="center", vertical="center")
    align_left = Alignment(horizontal="left", vertical="center")
    align_right = Alignment(horizontal="right", vertical="center")
    align_wrap = Alignment(horizontal="left", vertical="center", wrap_text=True)

    m_disp = rep.get("month_display") or rep.get("month") or ""

    def auto_fit_columns(ws, min_widths=None, max_width=50):
        min_widths = min_widths or {}
        for col in ws.columns:
            max_len = 0
            col_letter = get_column_letter(col[0].column)
            for cell in col:
                if cell.coordinate in ["A1", "A2", "A3", "B1", "B2"]:
                    continue
                val = str(cell.value or "")
                if cell.number_format and "%" in cell.number_format:
                    val += "%"
                for line in val.split("\n"):
                    if len(line) > max_len:
                        max_len = len(line)
            chosen = max(max_len + 3, min_widths.get(col_letter, 12))
            ws.column_dimensions[col_letter].width = min(chosen, max_width)

    # ==========================================================
    # SHEET 1: Overview & Buttons
    # ==========================================================
    ws1 = wb.active
    ws1.title = "Overview & Buttons"
    try:
        ws1.views.sheetView[0].showGridLines = True
    except Exception:
        pass

    ws1.merge_cells("A1:E2")
    ws1["A1"] = "📊 USEA Career Center — Performance Analytics Report"
    ws1["A1"].font = font_banner
    ws1["A1"].fill = navy_fill
    ws1["A1"].alignment = align_center

    ws1.merge_cells("A3:E3")
    ws1["A3"] = f"Report Period: {m_disp} | Exported for Administration"
    ws1["A3"].font = font_sub
    ws1["A3"].fill = navy_fill
    ws1["A3"].alignment = align_center

    ws1.merge_cells("A5:B5")
    ws1["A5"] = "📋 KPI Summary (សេចក្តីសង្ខេបសំខាន់ៗ)"
    ws1["A5"].font = font_sec_hdr

    kpis = [
        ("Report Period (កាលបរិច្ឆេទរបាយការណ៍)", m_disp),
        ("Total Posts Published (ចំនួន Post បានបង្ហោះសរុប)", rep.get("posts_count", 0)),
        ("Total Button Clicks (ចំនួនចុចប៊ូតុងសរុប)", rep.get("total_clicks", 0)),
        ("Total Unique Users (ចំនួនអ្នកចុចសរុប)", rep.get("unique_users_count", 0)),
        ("Post Tracking Started (កាលបរិច្ឆេទចាប់ផ្តើម)", rep.get("post_tracking_started_at") or "-"),
    ]
    cur_r = 6
    for label, val in kpis:
        c1 = ws1.cell(row=cur_r, column=1, value=label)
        c2 = ws1.cell(row=cur_r, column=2, value=val)
        c1.font = font_bold
        c1.fill = card_hdr_fill
        c1.border = border_all
        c1.alignment = align_left
        c2.font = font_bold if isinstance(val, int) else font_regular
        c2.border = border_all
        c2.alignment = align_center if isinstance(val, int) else align_left
        if isinstance(val, int):
            c2.number_format = "#,##0"
        cur_r += 1

    cur_r += 2
    ws1.merge_cells(f"A{cur_r}:E{cur_r}")
    ws1[f"A{cur_r}"] = "🔘 Button Performance Breakdown (ស្ថិតិតាមប៊ូតុងនីមួយៗ)"
    ws1[f"A{cur_r}"].font = font_sec_hdr
    cur_r += 1

    btn_headers = [
        "Button Name (ឈ្មោះប៊ូតុង)",
        "Type (ប្រភេទ)",
        "Unique Users (ចំនួនអ្នកចុច)",
        "Total Clicks (ចំនួនចុចសរុប)",
        "Share of Clicks (%)",
    ]
    for c_idx, h in enumerate(btn_headers, 1):
        cell = ws1.cell(row=cur_r, column=c_idx, value=h)
        cell.font = font_col_hdr
        cell.fill = teal_fill
        cell.border = border_all
        cell.alignment = align_center

    cur_r += 1
    total_clks = rep.get("total_clicks", 0) or 1
    by_type = rep.get("by_type") or {}
    for idx, (t_key, t_info) in enumerate(by_type.items()):
        clks = t_info.get("clicks", 0)
        users = t_info.get("unique_users", 0)
        pct = clks / total_clks

        row_cells = [
            (t_info.get("label", t_key), align_left, font_regular, None),
            (t_key, align_center, font_regular, None),
            (users, align_right, font_bold, "#,##0"),
            (clks, align_right, font_bold, "#,##0"),
            (pct, align_right, font_regular, "0.0%"),
        ]
        for c_idx, (val, aln, fnt, nfmt) in enumerate(row_cells, 1):
            cell = ws1.cell(row=cur_r, column=c_idx, value=val)
            cell.font = fnt
            cell.alignment = aln
            cell.border = border_all
            if idx % 2 == 1:
                cell.fill = zebra_fill
            if nfmt:
                cell.number_format = nfmt
        cur_r += 1

    sum_users = sum(v.get("unique_users", 0) for v in by_type.values())
    sum_clks = sum(v.get("clicks", 0) for v in by_type.values())
    total_cells = [
        ("Total (សរុប)", align_left),
        ("", align_center),
        (sum_users, align_right),
        (sum_clks, align_right),
        (1.0, align_right),
    ]
    for c_idx, (val, aln) in enumerate(total_cells, 1):
        cell = ws1.cell(row=cur_r, column=c_idx, value=val)
        cell.font = font_bold
        cell.alignment = aln
        cell.fill = total_fill
        cell.border = border_total
        if isinstance(val, (int, float)):
            cell.number_format = "0.0%" if isinstance(val, float) else "#,##0"

    auto_fit_columns(ws1, min_widths={"A": 30, "B": 15, "C": 22, "D": 22, "E": 18})

    # ==========================================================
    # SHEET 2: Channel Posts ("all post into one sheet")
    # ==========================================================
    ws2 = wb.create_sheet(title="All Channel Posts")
    try:
        ws2.views.sheetView[0].showGridLines = True
    except Exception:
        pass

    ws2.merge_cells("A1:G2")
    ws2["A1"] = f"📢 All Channel Posts & Performance — {m_disp} ({rep.get('posts_count', 0)} Posts)"
    ws2["A1"].font = font_banner
    ws2["A1"].fill = navy_fill
    ws2["A1"].alignment = align_center

    ws2.merge_cells("A3:G3")
    ws2["A3"] = "បញ្ជី Post ទាំងអស់ដែលបានបង្ហោះចូល Telegram Channel ព្រមទាំងចំនួន Clicks និងចំនួន Users ដែលបានចុច"
    ws2["A3"].font = font_sub
    ws2["A3"].fill = navy_fill
    ws2["A3"].alignment = align_center

    post_headers = [
        "Post ID",
        "Post Link (URL)",
        "Author / Admin (អ្នកបង្ហោះ)",
        "Publish Date/Time (ថ្ងៃខែបង្ហោះ)",
        "Clicks on Post (ចំនួនចុច)",
        "Unique Users (ចំនួនអ្នកចុច)",
        "Caption / Snippet (ខ្លឹមសារសង្ខេប)",
    ]
    header_r = 5
    for c_idx, h in enumerate(post_headers, 1):
        cell = ws2.cell(row=header_r, column=c_idx, value=h)
        cell.font = font_col_hdr
        cell.fill = navy_fill
        cell.border = border_all
        cell.alignment = align_center

    published_posts = list(rep.get("published_posts") or [])
    by_post = rep.get("by_post") or {}

    seen_pids = {str(p.get("post_id", "")).strip() for p in published_posts if p.get("post_id")}
    for pid, p_stat in by_post.items():
        pid_str = str(pid).strip()
        if pid_str and pid_str not in seen_pids:
            published_posts.append({
                "post_id": pid_str,
                "post_url": p_stat.get("post_url") or f"https://t.me/useacareercenter/{pid_str}",
                "timestamp": "",
                "admin_name": "Admin",
                "caption_snippet": f"Post #{pid_str}",
            })
            seen_pids.add(pid_str)

    def _sort_key(p):
        ts = p.get("timestamp") or ""
        pid_raw = str(p.get("post_id") or "")
        pid_num = int(pid_raw) if pid_raw.isdigit() else 0
        return (ts, pid_num)

    published_posts.sort(key=_sort_key, reverse=True)

    cur_r = 6
    total_post_clicks = 0
    total_post_users = 0
    for idx, p in enumerate(published_posts):
        pid = str(p.get("post_id", "")).strip()
        p_stat = by_post.get(pid, {})
        p_clicks = p_stat.get("clicks", 0)
        p_users = p_stat.get("unique_users", 0)
        total_post_clicks += p_clicks
        total_post_users += p_users

        p_url = p.get("post_url") or f"https://t.me/useacareercenter/{pid}"
        adm = p.get("admin_name") or "Admin"
        ts = p.get("timestamp", "")
        if "T" in ts:
            ts = ts.replace("T", " ")[:19]
        snip = p.get("caption_snippet") or ""

        # Post ID
        c_id = ws2.cell(row=cur_r, column=1, value=f"#{pid}")
        c_id.font = font_bold
        c_id.alignment = align_center

        # Post URL (hyperlink)
        c_url = ws2.cell(row=cur_r, column=2, value=p_url)
        c_url.font = font_link
        c_url.alignment = align_left
        c_url.hyperlink = p_url

        # Admin
        c_adm = ws2.cell(row=cur_r, column=3, value=adm)
        c_adm.font = font_regular
        c_adm.alignment = align_center

        # Timestamp
        c_ts = ws2.cell(row=cur_r, column=4, value=ts)
        c_ts.font = font_regular
        c_ts.alignment = align_center

        # Clicks
        c_clks = ws2.cell(row=cur_r, column=5, value=p_clicks)
        c_clks.font = font_bold
        c_clks.alignment = align_right
        c_clks.number_format = "#,##0"

        # Users
        c_usrs = ws2.cell(row=cur_r, column=6, value=p_users)
        c_usrs.font = font_bold
        c_usrs.alignment = align_right
        c_usrs.number_format = "#,##0"

        # Snippet
        c_snip = ws2.cell(row=cur_r, column=7, value=snip)
        c_snip.font = font_regular
        c_snip.alignment = align_wrap

        for c_idx in range(1, 8):
            cell = ws2.cell(row=cur_r, column=c_idx)
            cell.border = border_all
            if idx % 2 == 1:
                cell.fill = zebra_fill

        cur_r += 1

    # Total row
    tot_row = [
        (f"Total ({len(published_posts)} Posts)", align_left),
        ("", align_left),
        ("", align_center),
        ("", align_center),
        (total_post_clicks, align_right),
        (total_post_users, align_right),
        ("", align_left),
    ]
    for c_idx, (val, aln) in enumerate(tot_row, 1):
        cell = ws2.cell(row=cur_r, column=c_idx, value=val)
        cell.font = font_bold
        cell.alignment = aln
        cell.fill = total_fill
        cell.border = border_total
        if isinstance(val, int):
            cell.number_format = "#,##0"

    ws2.auto_filter.ref = f"A{header_r}:G{cur_r-1}"
    auto_fit_columns(ws2, min_widths={"A": 12, "B": 36, "C": 18, "D": 20, "E": 18, "F": 18, "G": 40}, max_width=45)

    # ==========================================================
    # SHEET 3: Post Authors ("user who post into one sheet")
    # ==========================================================
    ws3 = wb.create_sheet(title="Post Authors")
    try:
        ws3.views.sheetView[0].showGridLines = True
    except Exception:
        pass

    ws3.merge_cells("A1:G2")
    ws3["A1"] = f"✍️ Post Authors & Admin Contribution Summary — {m_disp}"
    ws3["A1"].font = font_banner
    ws3["A1"].fill = indigo_fill
    ws3["A1"].alignment = align_center

    ws3.merge_cells("A3:G3")
    ws3["A3"] = "ស្ថិតិតាម Admin / User នីមួយៗដែលបានបង្ហោះ និងចំនួន Click/User ដែលទទួលបានលើ Posts របស់ពួកគាត់"
    ws3["A3"].font = font_sub
    ws3["A3"].fill = indigo_fill
    ws3["A3"].alignment = align_center

    author_headers = [
        "Admin / Author Name",
        "Admin Telegram ID",
        "Total Posts (ចំនួន Post)",
        "Total Clicks Generated",
        "Unique Users Reached",
        "Avg Clicks / Post",
        "Published Post IDs (បញ្ជី Posts)",
    ]
    header_r = 5
    for c_idx, h in enumerate(author_headers, 1):
        cell = ws3.cell(row=header_r, column=c_idx, value=h)
        cell.font = font_col_hdr
        cell.fill = indigo_fill
        cell.border = border_all
        cell.alignment = align_center

    # Compute author-level stats from published_posts
    admin_stats = {}
    for p in published_posts:
        adm = p.get("admin_name") or "Admin"
        aid = p.get("admin_id") or "-"
        key = str(aid) if aid != "-" else adm
        entry = admin_stats.setdefault(key, {
            "name": adm,
            "id": aid,
            "posts": [],
            "clicks": 0,
            "users": 0,
        })
        pid = str(p.get("post_id", "")).strip()
        if pid:
            entry["posts"].append(pid)
            p_stat = by_post.get(pid, {})
            entry["clicks"] += p_stat.get("clicks", 0)
            entry["users"] += p_stat.get("unique_users", 0)

    cur_r = 6
    tot_auth_posts = 0
    tot_auth_clks = 0
    tot_auth_usrs = 0
    for idx, (k, a_info) in enumerate(sorted(admin_stats.items(), key=lambda x: len(x[1]["posts"]), reverse=True)):
        p_cnt = len(a_info["posts"])
        c_cnt = a_info["clicks"]
        u_cnt = a_info["users"]
        avg_c = round(c_cnt / p_cnt, 2) if p_cnt > 0 else 0.0

        tot_auth_posts += p_cnt
        tot_auth_clks += c_cnt
        tot_auth_usrs += u_cnt

        p_list_str = ", ".join(a_info["posts"][:30])
        if len(a_info["posts"]) > 30:
            p_list_str += f" (+{len(a_info['posts'])-30} more)"

        row_data = [
            (a_info["name"], align_left, font_bold, None),
            (str(a_info["id"]), align_center, font_regular, None),
            (p_cnt, align_right, font_bold, "#,##0"),
            (c_cnt, align_right, font_bold, "#,##0"),
            (u_cnt, align_right, font_bold, "#,##0"),
            (avg_c, align_right, font_regular, "0.00"),
            (p_list_str, align_left, font_regular, None),
        ]
        for c_idx, (val, aln, fnt, nfmt) in enumerate(row_data, 1):
            cell = ws3.cell(row=cur_r, column=c_idx, value=val)
            cell.font = fnt
            cell.alignment = aln
            cell.border = border_all
            if idx % 2 == 1:
                cell.fill = zebra_fill
            if nfmt:
                cell.number_format = nfmt

        cur_r += 1

    # Total row
    tot_avg = round(tot_auth_clks / tot_auth_posts, 2) if tot_auth_posts > 0 else 0.0
    tot_auth_row = [
        (f"Total ({len(admin_stats)} Admins)", align_left),
        ("", align_center),
        (tot_auth_posts, align_right),
        (tot_auth_clks, align_right),
        (tot_auth_usrs, align_right),
        (tot_avg, align_right),
        ("", align_left),
    ]
    for c_idx, (val, aln) in enumerate(tot_auth_row, 1):
        cell = ws3.cell(row=cur_r, column=c_idx, value=val)
        cell.font = font_bold
        cell.alignment = aln
        cell.fill = total_fill
        cell.border = border_total
        if isinstance(val, int):
            cell.number_format = "#,##0"
        elif isinstance(val, float):
            cell.number_format = "0.00"

    ws3.auto_filter.ref = f"A{header_r}:G{cur_r-1}"
    auto_fit_columns(ws3, min_widths={"A": 22, "B": 18, "C": 18, "D": 22, "E": 20, "F": 18, "G": 40}, max_width=45)

    # ==========================================================
    # SHEET 4: Detailed Click Logs
    # ==========================================================
    ws4 = wb.create_sheet(title="Detailed Click Logs")
    try:
        ws4.views.sheetView[0].showGridLines = True
    except Exception:
        pass

    ws4.merge_cells("A1:I2")
    ws4["A1"] = f"📋 Detailed Individual Click Logs — {m_disp}"
    ws4["A1"].font = font_banner
    ws4["A1"].fill = slate_fill
    ws4["A1"].alignment = align_center

    ws4.merge_cells("A3:I3")
    ws4["A3"] = "កំណត់ត្រាចុចលើប៊ូតុងនីមួយៗលម្អិតតាមកាលបរិច្ឆេទ និងអ្នកចុច (Visitor Audit Logs)"
    ws4["A3"].font = font_sub
    ws4["A3"].fill = slate_fill
    ws4["A3"].alignment = align_center

    log_headers = [
        "Timestamp (UTC/Local)",
        "Month (YYYY-MM)",
        "Button Name",
        "Button Type",
        "Post ID",
        "Post URL",
        "Destination Target URL",
        "Visitor Telegram ID",
        "Visitor Name / Username",
    ]
    header_r = 5
    for c_idx, h in enumerate(log_headers, 1):
        cell = ws4.cell(row=header_r, column=c_idx, value=h)
        cell.font = font_col_hdr
        cell.fill = slate_fill
        cell.border = border_all
        cell.alignment = align_center

    cur_r = 6
    target_month = month if month and month != "all" else None
    rows_logged = 0
    for idx, c in enumerate(recent):
        if target_month and c.get("month") != target_month:
            continue
        rows_logged += 1
        row_vals = [
            (c.get("timestamp", ""), align_center),
            (c.get("month", ""), align_center),
            (c.get("label", ""), align_left),
            (c.get("link_type", ""), align_center),
            (f"#{c.get('post_id', '')}" if c.get("post_id") else "-", align_center),
            (c.get("post_url", ""), align_left),
            (c.get("target_url", ""), align_left),
            (c.get("user_hash", ""), align_center),
            (c.get("user_display", ""), align_left),
        ]
        for c_idx, (val, aln) in enumerate(row_vals, 1):
            cell = ws4.cell(row=cur_r, column=c_idx, value=val)
            cell.font = font_regular
            cell.alignment = aln
            cell.border = border_all
            if rows_logged % 2 == 0:
                cell.fill = zebra_fill
            if c_idx in (6, 7) and val.startswith("http"):
                cell.font = font_link
                cell.hyperlink = val

        cur_r += 1

    if rows_logged == 0:
        ws4.merge_cells(f"A{cur_r}:I{cur_r}")
        empty_c = ws4[f"A{cur_r}"]
        empty_c.value = "(No individual click events logged for this period)"
        empty_c.font = font_sub
        empty_c.alignment = align_center
        cur_r += 1

    ws4.auto_filter.ref = f"A{header_r}:I{cur_r-1}"
    auto_fit_columns(ws4, min_widths={"A": 22, "B": 14, "C": 25, "D": 14, "E": 12, "F": 30, "G": 30, "H": 18, "I": 22}, max_width=40)

    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


# ------------------------------------------------------------------
# Tornado Web Handlers
# ------------------------------------------------------------------
class RedirectTrackerHandler(tornado.web.RequestHandler):
    """
    Handle GET /r/{token}: Log button click with IP/User-Agent and redirect with HTTP 302.
    """

    def get(self, token: Optional[str] = None):
        token = (token or "").strip()
        if not token:
            self.redirect("https://t.me/useacareercenter", status=302)
            return

        client_ip = self.request.headers.get("X-Forwarded-For", self.request.remote_ip or "")
        if "," in client_ip:
            client_ip = client_ip.split(",")[0].strip()
        user_agent = self.request.headers.get("User-Agent", "")

        target_url = record_click(token=token, client_ip=client_ip, user_agent=user_agent)
        if target_url.startswith("mailto:"):
            email_addr = target_url.replace("mailto:", "").split("?")[0]
            self.set_header("Content-Type", "text/html; charset=utf-8")
            self.write(f'''<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="utf-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Apply via Email — USEA Career Center</title>
    <style>
        * {{ box-sizing: border-box; margin: 0; padding: 0; }}
        body {{
            font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, Helvetica, Arial, sans-serif;
            background-color: #0f172a;
            color: #f8fafc;
            display: flex;
            align-items: center;
            justify-content: center;
            min-height: 100vh;
            padding: 20px;
        }}
        .card {{
            background-color: #1e293b;
            border: 1px solid #334155;
            border-radius: 20px;
            padding: 36px 28px;
            max-width: 460px;
            width: 100%;
            text-align: center;
            box-shadow: 0 20px 40px rgba(0, 0, 0, 0.4);
        }}
        .icon {{
            font-size: 52px;
            margin-bottom: 16px;
        }}
        h1 {{
            font-size: 1.4rem;
            font-weight: 700;
            color: #38bdf8;
            margin-bottom: 8px;
        }}
        p.sub {{
            color: #94a3b8;
            font-size: 0.95rem;
            margin-bottom: 24px;
            line-height: 1.5;
        }}
        .email-display {{
            background-color: #0f172a;
            border: 1px dashed #475569;
            border-radius: 12px;
            padding: 12px 16px;
            color: #f1f5f9;
            font-weight: 600;
            font-size: 1.05rem;
            word-break: break-all;
            margin-bottom: 24px;
            user-select: all;
        }}
        .btn {{
            display: block;
            width: 100%;
            padding: 14px 20px;
            border-radius: 12px;
            font-size: 1rem;
            font-weight: 600;
            text-decoration: none;
            cursor: pointer;
            border: none;
            margin-bottom: 12px;
            transition: all 0.2s ease;
        }}
        .btn-gmail {{
            background-color: #ea4335;
            color: #ffffff;
        }}
        .btn-gmail:hover {{
            background-color: #d93025;
        }}
        .btn-mail {{
            background-color: #2563eb;
            color: #ffffff;
        }}
        .btn-mail:hover {{
            background-color: #1d4ed8;
        }}
        .btn-copy {{
            background-color: #334155;
            color: #e2e8f0;
        }}
        .btn-copy:hover {{
            background-color: #475569;
        }}
        .hint {{
            margin-top: 16px;
            color: #64748b;
            font-size: 0.8rem;
        }}
    </style>
</head>
<body>
    <div class="card">
        <div class="icon">✉️</div>
        <h1>Apply via Email</h1>
        <p class="sub">Please choose how you want to send your application:</p>
        
        <div class="email-display" id="email-text">{email_addr}</div>

        <a class="btn btn-gmail" href="https://mail.google.com/mail/?view=cm&fs=1&to={email_addr}" target="_blank" rel="noopener">
            🚀 Open with Gmail (Web)
        </a>
        <a class="btn btn-mail" href="{target_url}" id="mail-link">
            ✉️ Open Email App (Default)
        </a>
        <button class="btn btn-copy" onclick="copyEmail()">
            📋 Copy Email Address
        </button>

        <p class="hint">USEA Career Center Job Portal</p>
    </div>

    <script>
        function copyEmail() {{
            navigator.clipboard.writeText("{email_addr}").then(() => {{
                const btn = document.querySelector('.btn-copy');
                const orig = btn.innerText;
                btn.innerText = "✅ Copied to Clipboard!";
                setTimeout(() => btn.innerText = orig, 2500);
            }});
        }}
        window.addEventListener('load', function() {{
            setTimeout(function() {{
                try {{
                    window.location.href = "{target_url}";
                }} catch(e) {{}}
            }}, 300);
        }});
    </script>
</body>
</html>''')
            return

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
        posts_count = rep.get("posts_count", 0)
        published_posts = rep.get("published_posts", [])
        started_date = rep.get("post_tracking_started_at") or ""
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

        published_rows = []
        for p in published_posts:
            pid = p.get("post_id", "")
            p_url = p.get("post_url", f"https://t.me/useacareercenter/{pid}")
            adm = p.get("admin_name", "Admin")
            ts = p.get("timestamp", "")
            if "T" in ts:
                ts = ts.replace("T", " ")[:19]
            snip = p.get("caption_snippet", "")
            p_clicks = by_post.get(pid, {}).get("clicks", 0)
            p_users = by_post.get(pid, {}).get("unique_users", 0)
            published_rows.append(f"""
            <tr>
                <td><strong>#{pid}</strong></td>
                <td><a href="{p_url}" target="_blank" class="link">View Post #{pid} ↗</a></td>
                <td><span class="badge">{adm}</span></td>
                <td><small style="color:var(--text-muted);">{ts}</small></td>
                <td style="max-width:280px; word-break:break-word;">{snip or '<em>(No description)</em>'}</td>
                <td><strong>{p_users}</strong> នាក់ ({p_clicks} clicks)</td>
            </tr>
            """)

        # Compute author statistics ("user who post into one sheet")
        author_stats = {}
        for p in published_posts:
            adm = p.get("admin_name") or "Admin"
            aid = p.get("admin_id") or "-"
            key = str(aid) if aid != "-" else adm
            entry = author_stats.setdefault(key, {
                "name": adm,
                "id": aid,
                "posts": [],
                "clicks": 0,
                "users": 0,
            })
            pid = str(p.get("post_id", "")).strip()
            if pid:
                entry["posts"].append(pid)
                p_stat = by_post.get(pid, {})
                entry["clicks"] += p_stat.get("clicks", 0)
                entry["users"] += p_stat.get("unique_users", 0)

        author_rows = []
        for _, a_info in sorted(author_stats.items(), key=lambda x: len(x[1]["posts"]), reverse=True):
            p_cnt = len(a_info["posts"])
            c_cnt = a_info["clicks"]
            u_cnt = a_info["users"]
            avg_c = round(c_cnt / p_cnt, 2) if p_cnt > 0 else 0.0
            p_list_preview = ", ".join(f"#{x}" for x in a_info["posts"][:10])
            if len(a_info["posts"]) > 10:
                p_list_preview += f" (+{len(a_info['posts'])-10} more)"
            author_rows.append(f"""
            <tr>
                <td><strong>{a_info['name']}</strong></td>
                <td><span class="badge">{a_info['id']}</span></td>
                <td><strong style="color:var(--primary);">{p_cnt}</strong> Posts</td>
                <td><strong>{c_cnt}</strong> clicks</td>
                <td><strong>{u_cnt}</strong> នាក់</td>
                <td><span style="color:#10b981; font-weight:600;">{avg_c}</span></td>
                <td><small style="color:var(--text-muted);">{p_list_preview or '-'}</small></td>
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
        .btn-excel {{
            background: #0d9488;
            color: #fff;
            border: none;
            font-weight: 600;
        }}
        .btn-excel:hover {{
            background: #0f766e;
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
                <a href="/report/excel?month={month}" class="btn btn-excel">📊 Download Excel (.xlsx)</a>
                <a href="/report/csv?month={month}" class="btn btn-primary">📥 Download CSV</a>
            </div>
        </div>

        <div class="grid">
            <div class="stat-card">
                <div class="stat-label">📢 ចំនួន Post បានបង្ហោះ (Posts)</div>
                <div class="stat-val">{posts_count}</div>
                {f'<div style="color: var(--text-muted); font-size: 0.78rem; margin-top: 6px;">🗓️ ចាប់ផ្តើមតាមដានពីថ្ងៃទី: {started_date}</div>' if started_date else ''}
            </div>
            <div class="stat-card">
                <div class="stat-label">👥 អ្នកចុចសរុប (Unique Users)</div>
                <div class="stat-val">{unique_users}</div>
            </div>
            <div class="stat-card">
                <div class="stat-label">👆 ចំនួនចុចសរុប (Button Clicks)</div>
                <div class="stat-val">{total_clicks}</div>
            </div>
            <div class="stat-card">
                <div class="stat-label">📌 ចំនួន Post ដែលត្រូវបានចុច</div>
                <div class="stat-val">{len(by_post)}</div>
            </div>
        </div>

        <div class="card">
            <h2>✍️ ស្ថិតិតាម Admin អ្នកបង្ហោះ (Post Authors & Engagement)</h2>
            <table>
                <thead>
                    <tr>
                        <th>Admin / Author</th>
                        <th>Telegram ID</th>
                        <th>ចំនួន Post បានបង្ហោះ</th>
                        <th>ចំនួនចុច (Clicks)</th>
                        <th>ចំនួនអ្នកចុច (Users)</th>
                        <th>Avg Clicks/Post</th>
                        <th>បញ្ជី Posts</th>
                    </tr>
                </thead>
                <tbody>
                    {''.join(author_rows) if author_rows else '<tr><td colspan="7" style="text-align:center; color:var(--text-muted);">មិនទាន់មានទិន្នន័យ (No author data)</td></tr>'}
                </tbody>
            </table>
        </div>

        <div class="card">
            <h2>📢 បញ្ជី Post ដែលបានបង្ហោះចូល Channel ({posts_count} Posts{f' • ចាប់ពី {started_date}' if started_date else ''})</h2>
            <table>
                <thead>
                    <tr>
                        <th>Post ID</th>
                        <th>តំណភ្ជាប់ (Link)</th>
                        <th>Admin អ្នកបង្ហោះ</th>
                        <th>កាលបរិច្ឆេទ (Date/Time)</th>
                        <th>ខ្លឹមសារសង្ខេប (Snippet)</th>
                        <th>ការចុចប៊ូតុង (Clicks)</th>
                    </tr>
                </thead>
                <tbody>
                    {''.join(published_rows) if published_rows else '<tr><td colspan="6" style="text-align:center; color:var(--text-muted);">មិនទាន់មានទិន្នន័យ (No published posts)</td></tr>'}
                </tbody>
            </table>
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


class WebExcelExportHandler(tornado.web.RequestHandler):
    """
    Handle GET /report/excel?month=YYYY-MM: Direct styled multi-sheet Excel (.xlsx) file download.
    """

    def get(self):
        month = self.get_argument("month", None)
        avail_months = get_available_months()
        if not month:
            month = avail_months[0] if avail_months else datetime.now().strftime("%Y-%m")

        excel_bytes = generate_excel_report(month=month)
        filename = f"USEA_Career_Report_{month}.xlsx"
        self.set_header("Content-Type", "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")
        self.set_header("Content-Disposition", f'attachment; filename="{filename}"')
        self.write(excel_bytes)


class WebClicksJsonHandler(tornado.web.RequestHandler):
    """
    Handle GET /report/clicks.json: Direct clicks.json download to backup live production data.
    """

    def get(self):
        data = load_click_data()
        self.set_header("Content-Type", "application/json; charset=utf-8")
        self.set_header("Content-Disposition", 'attachment; filename="clicks.json"')
        self.write(json.dumps(data, ensure_ascii=False, indent=2))
