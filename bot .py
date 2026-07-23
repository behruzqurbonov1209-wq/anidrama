import logging
import os
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    Application, CommandHandler, CallbackQueryHandler,
    MessageHandler, filters, ContextTypes, ConversationHandler
)
from database import db

logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

BOT_TOKEN = os.getenv("BOT_TOKEN", "8897498710:AAEnb8SdQPv-09-F14riBjAqhjfVZ70wURw")
ADMIN_IDS = [int(x) for x in os.getenv("ADMIN_IDS", "7356097969").split(",")]

# ── Conversation states ────────────────────────────────────────────────
(
    # Kontent qo'shish
    ADD_CAT, ADD_CODE, ADD_TITLE, ADD_DESC,
    ADD_EP_NUM, ADD_EP_FILE,
    # Qism qo'shish (mavjud serialga)
    ADDEP_CAT, ADDEP_CODE, ADDEP_FILE,
    # O'chirish
    DEL_CAT, DEL_CODE,
    # Broadcast
    BROADCAST
) = range(12)

CATEGORY_NAMES = {
    "anime": "🎌 Anime",
    "drama": "🎭 Drama",
    "kino":  "🎬 Kino"
}

def is_admin(user_id: int) -> bool:
    return user_id in ADMIN_IDS

# ══════════════════════════════════════════════════════════
#  FOYDALANUVCHI
# ══════════════════════════════════════════════════════════

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    db.add_user(user.id, user.username or "", user.full_name or "")

    keyboard = [
        [
            InlineKeyboardButton("🎌 Anime",  callback_data="cat_anime"),
            InlineKeyboardButton("🎭 Drama",  callback_data="cat_drama"),
        ],
        [InlineKeyboardButton("🎬 Kino", callback_data="cat_kino")],
    ]
    if is_admin(user.id):
        keyboard.append([InlineKeyboardButton("⚙️ Admin Panel", callback_data="admin_panel")])

    text = (
        f"Salom, {user.first_name}! 👋\n\n"
        "Kategoriya tanlang:\n\n"
        "🎌 <b>Anime</b> — Anime seriyalar\n"
        "🎭 <b>Drama</b> — Drama seriyalar\n"
        "🎬 <b>Kino</b> — Tarjima kinolar"
    )
    if update.message:
        await update.message.reply_text(text, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode="HTML")
    else:
        await update.callback_query.edit_message_text(text, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode="HTML")


async def show_category(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    category = query.data.replace("cat_", "")
    context.user_data["category"] = category

    items = db.get_all_items(category)
    cat_name = CATEGORY_NAMES.get(category, category)

    if not items:
        text = f"{cat_name}\n\n📭 Hozircha hech narsa yo'q."
    else:
        lines = [f"{cat_name} ro'yxati:\n"]
        for item in items:
            ep_count = item.get("episode_count", 0)
            ep_info = f"({ep_count} qism)" if ep_count else "(qism yo'q)"
            lines.append(f"🔹 <code>{item['code']}</code> — {item['title']} {ep_info}")
        lines.append(f"\n📩 Kodni yozing, masalan: <code>{items[0]['code']}</code>")
        text = "\n".join(lines)

    keyboard = [[InlineKeyboardButton("🔙 Orqaga", callback_data="back_main")]]
    await query.edit_message_text(text, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode="HTML")


async def back_main(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    await start(update, context)


async def handle_code(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Foydalanuvchi kod yozganda — qismlar tugmalarini ko'rsatadi"""
    user = update.effective_user
    db.add_user(user.id, user.username or "", user.full_name or "")
    code = update.message.text.strip().upper()

    # Kategoriyadan qidirish
    category = context.user_data.get("category")
    found = None
    found_cat = None

    if category:
        found = db.get_item(category, code)
        found_cat = category

    if not found:
        for cat in ["anime", "drama", "kino"]:
            item = db.get_item(cat, code)
            if item:
                found = item
                found_cat = cat
                break

    if not found:
        await update.message.reply_text(
            f"❌ <b>{code}</b> kodi topilmadi.\n\n"
            "To'g'ri kod kiriting yoki /start bosing.",
            parse_mode="HTML"
        )
        return

    episodes = db.get_episodes(found_cat, code)
    cat_name = CATEGORY_NAMES.get(found_cat, found_cat)

    if not episodes:
        await update.message.reply_text(
            f"{cat_name} | <b>{found['title']}</b>\n\n"
            "📭 Hali qismlar qo'shilmagan.",
            parse_mode="HTML"
        )
        return

    # Qismlar tugmalari — 3 tadan qator
    ep_buttons = []
    row = []
    for ep in episodes:
        ep_title = ep.get("title") or f"{ep['episode_num']}-qism"
        row.append(InlineKeyboardButton(
            ep_title,
            callback_data=f"ep_{found_cat}_{code}_{ep['episode_num']}"
        ))
        if len(row) == 3:
            ep_buttons.append(row)
            row = []
    if row:
        ep_buttons.append(row)

    ep_buttons.append([InlineKeyboardButton("🔙 Orqaga", callback_data=f"cat_{found_cat}")])

    text = (
        f"{cat_name}\n\n"
        f"🎬 <b>{found['title']}</b>\n"
    )
    if found.get("description"):
        text += f"📝 {found['description']}\n"
    text += f"\n📺 {len(episodes)} ta qism mavjud. Birini tanlang:"

    await update.message.reply_text(
        text,
        reply_markup=InlineKeyboardMarkup(ep_buttons),
        parse_mode="HTML"
    )


async def send_episode(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Tugma bosilganda qismni yuboradi"""
    query = update.callback_query
    await query.answer()

    # callback: ep_anime_A001_3
    parts = query.data.split("_", 3)
    # parts = ["ep", category, code, episode_num]
    _, category, code, ep_num_str = parts
    episode_num = int(ep_num_str)

    episode = db.get_episode(category, code, episode_num)
    item = db.get_item(category, code)

    if not episode or not item:
        await query.answer("❌ Qism topilmadi!", show_alert=True)
        return

    cat_name = CATEGORY_NAMES.get(category, category)
    ep_label = episode.get("title") or f"{episode_num}-qism"
    caption = (
        f"{cat_name} | <b>{item['title']}</b>\n"
        f"📺 <b>{ep_label}</b>"
    )

    file_id   = episode["file_id"]
    file_type = episode["file_type"]

    try:
        if file_type == "video":
            await query.message.reply_video(video=file_id, caption=caption, parse_mode="HTML")
        elif file_type == "document":
            await query.message.reply_document(document=file_id, caption=caption, parse_mode="HTML")
        elif file_type == "photo":
            await query.message.reply_photo(photo=file_id, caption=caption, parse_mode="HTML")
        else:
            await query.message.reply_text(caption, parse_mode="HTML")
    except Exception as e:
        logger.error(f"Episode send error: {e}")
        await query.answer("⚠️ Faylni yuborishda xatolik!", show_alert=True)


# ══════════════════════════════════════════════════════════
#  ADMIN PANEL
# ══════════════════════════════════════════════════════════

async def admin_panel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    if not is_admin(query.from_user.id):
        await query.answer("❌ Ruxsat yo'q!", show_alert=True)
        return

    stats = db.get_stats()
    text = (
        "⚙️ <b>Admin Panel</b>\n\n"
        f"👥 Foydalanuvchilar: <b>{stats['users']}</b>\n"
        f"🎌 Anime: <b>{stats['anime']}</b> ta serial\n"
        f"🎭 Drama: <b>{stats['drama']}</b> ta serial\n"
        f"🎬 Kino: <b>{stats['kino']}</b> ta\n"
        f"📺 Jami qismlar: <b>{stats.get('episodes', 0)}</b> ta\n"
    )
    keyboard = [
        [
            InlineKeyboardButton("➕ Serial qo'sh",  callback_data="admin_add"),
            InlineKeyboardButton("📺 Qism qo'sh",   callback_data="admin_addep"),
        ],
        [
            InlineKeyboardButton("🗑 O'chirish",     callback_data="admin_delete"),
            InlineKeyboardButton("📊 Statistika",    callback_data="admin_stats"),
        ],
        [InlineKeyboardButton("📢 Broadcast",        callback_data="admin_broadcast")],
        [InlineKeyboardButton("🔙 Orqaga",           callback_data="back_main")],
    ]
    await query.edit_message_text(text, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode="HTML")


async def admin_stats(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    if not is_admin(query.from_user.id):
        return

    stats = db.get_stats()
    users = db.get_recent_users(10)
    text = (
        "📊 <b>Statistika</b>\n\n"
        f"👥 Foydalanuvchilar: <b>{stats['users']}</b>\n\n"
        f"📦 Kontent:\n"
        f"  🎌 Anime: {stats['anime']} serial\n"
        f"  🎭 Drama: {stats['drama']} serial\n"
        f"  🎬 Kino: {stats['kino']} ta\n"
        f"  📺 Jami qismlar: {stats.get('episodes', 0)} ta\n\n"
        "👤 So'nggi foydalanuvchilar:\n"
    )
    for u in users:
        name = u['full_name'] or u['username'] or f"ID:{u['user_id']}"
        text += f"  • {name}\n"

    keyboard = [[InlineKeyboardButton("🔙 Admin Panel", callback_data="admin_panel")]]
    await query.edit_message_text(text, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode="HTML")


# ── SERIAL QO'SHISH ────────────────────────────────────────────────────

async def admin_add_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    if not is_admin(query.from_user.id):
        return

    keyboard = [
        [
            InlineKeyboardButton("🎌 Anime", callback_data="add_anime"),
            InlineKeyboardButton("🎭 Drama", callback_data="add_drama"),
            InlineKeyboardButton("🎬 Kino",  callback_data="add_kino"),
        ],
        [InlineKeyboardButton("❌ Bekor", callback_data="admin_panel")]
    ]
    await query.edit_message_text(
        "➕ <b>Yangi serial — kategoriya tanlang:</b>",
        reply_markup=InlineKeyboardMarkup(keyboard),
        parse_mode="HTML"
    )
    return ADD_CAT


async def add_select_cat(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    context.user_data["add_cat"] = query.data.replace("add_", "")
    await query.edit_message_text(
        "📌 <b>Kod kiriting</b> (masalan: A001, D12):\n<i>Kod unikal bo'lsin</i>",
        parse_mode="HTML"
    )
    return ADD_CODE


async def add_get_code(update: Update, context: ContextTypes.DEFAULT_TYPE):
    code = update.message.text.strip().upper()
    cat  = context.user_data["add_cat"]
    if db.get_item(cat, code):
        await update.message.reply_text(f"⚠️ <code>{code}</code> kodi mavjud. Boshqa kod kiriting:", parse_mode="HTML")
        return ADD_CODE
    context.user_data["add_code"] = code
    await update.message.reply_text("📝 <b>Sarlavha kiriting:</b>", parse_mode="HTML")
    return ADD_TITLE


async def add_get_title(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data["add_title"] = update.message.text.strip()
    await update.message.reply_text(
        "📄 <b>Tavsif kiriting</b> (ixtiyoriy — o'tkazish: /skip):",
        parse_mode="HTML"
    )
    return ADD_DESC


async def add_get_desc(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text.strip()
    context.user_data["add_desc"] = "" if text == "/skip" else text

    cat  = context.user_data["add_cat"]
    code = context.user_data["add_code"]
    db.add_item(cat, code, context.user_data["add_title"], context.user_data["add_desc"])

    cat_name = CATEGORY_NAMES.get(cat, cat)
    await update.message.reply_text(
        f"✅ <b>Serial qo'shildi!</b>\n\n"
        f"📁 {cat_name}\n"
        f"🔑 Kod: <code>{code}</code>\n"
        f"🎬 Sarlavha: {context.user_data['add_title']}\n\n"
        f"Endi <b>qismlarni qo'shishingiz</b> mumkin.\n"
        f"Admin panel → 📺 Qism qo'sh",
        parse_mode="HTML"
    )
    for k in ["add_cat","add_code","add_title","add_desc"]:
        context.user_data.pop(k, None)
    return ConversationHandler.END


# ── QISM QO'SHISH ──────────────────────────────────────────────────────

async def admin_addep_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    if not is_admin(query.from_user.id):
        return

    keyboard = [
        [
            InlineKeyboardButton("🎌 Anime", callback_data="addep_anime"),
            InlineKeyboardButton("🎭 Drama", callback_data="addep_drama"),
            InlineKeyboardButton("🎬 Kino",  callback_data="addep_kino"),
        ],
        [InlineKeyboardButton("❌ Bekor", callback_data="admin_panel")]
    ]
    await query.edit_message_text(
        "📺 <b>Qism qo'shish — kategoriya tanlang:</b>",
        reply_markup=InlineKeyboardMarkup(keyboard),
        parse_mode="HTML"
    )
    return ADDEP_CAT


async def addep_select_cat(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    cat = query.data.replace("addep_", "")
    context.user_data["ep_cat"] = cat

    items = db.get_all_items(cat)
    cat_name = CATEGORY_NAMES.get(cat, cat)

    if not items:
        await query.edit_message_text(f"{cat_name} bo'sh. Avval serial qo'shing.")
        return ConversationHandler.END

    lines = [f"📺 {cat_name} — qism qo'shish\n\nSeriallar:\n"]
    for item in items:
        ep_count = item.get("episode_count", 0)
        lines.append(f"  🔹 <code>{item['code']}</code> — {item['title']} ({ep_count} qism)")
    lines.append("\n✏️ <b>Serial kodini yozing:</b>")
    await query.edit_message_text("\n".join(lines), parse_mode="HTML")
    return ADDEP_CODE


async def addep_get_code(update: Update, context: ContextTypes.DEFAULT_TYPE):
    code = update.message.text.strip().upper()
    cat  = context.user_data["ep_cat"]
    item = db.get_item(cat, code)

    if not item:
        await update.message.reply_text(
            f"❌ <code>{code}</code> topilmadi. Qaytadan yozing:",
            parse_mode="HTML"
        )
        return ADDEP_CODE

    context.user_data["ep_code"] = code
    next_num = db.get_next_episode_num(cat, code)

    await update.message.reply_text(
        f"✅ <b>{item['title']}</b>\n\n"
        f"📺 Keyingi qism raqami: <b>{next_num}</b>\n\n"
        f"Endi <b>{next_num}-qism faylini yuboring</b> (video yoki hujjat):",
        parse_mode="HTML"
    )
    return ADDEP_FILE


async def addep_get_file(update: Update, context: ContextTypes.DEFAULT_TYPE):
    cat  = context.user_data["ep_cat"]
    code = context.user_data["ep_code"]
    next_num = db.get_next_episode_num(cat, code)

    file_id   = None
    file_type = None

    if update.message.video:
        file_id   = update.message.video.file_id
        file_type = "video"
    elif update.message.document:
        file_id   = update.message.document.file_id
        file_type = "document"
    elif update.message.photo:
        file_id   = update.message.photo[-1].file_id
        file_type = "photo"
    else:
        await update.message.reply_text("❌ Video, hujjat yoki rasm yuboring.")
        return ADDEP_FILE

    db.add_episode(cat, code, next_num, file_id, file_type)
    item = db.get_item(cat, code)
    cat_name = CATEGORY_NAMES.get(cat, cat)

    # Davom ettirishni so'raymiz
    keyboard = [
        [
            InlineKeyboardButton(f"➕ {next_num+1}-qism qo'sh", callback_data=f"cont_ep_{cat}_{code}"),
            InlineKeyboardButton("✅ Tugat", callback_data="admin_panel"),
        ]
    ]
    await update.message.reply_text(
        f"✅ <b>{next_num}-qism qo'shildi!</b>\n\n"
        f"📁 {cat_name} | {item['title']}\n"
        f"📺 Jami: {next_num} ta qism",
        reply_markup=InlineKeyboardMarkup(keyboard),
        parse_mode="HTML"
    )
    context.user_data.pop("ep_cat", None)
    context.user_data.pop("ep_code", None)
    return ConversationHandler.END


async def continue_episode(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """'Keyingi qism qo'sh' tugmasi"""
    query = update.callback_query
    await query.answer()
    # cont_ep_anime_A001
    parts = query.data.split("_", 3)
    cat  = parts[2]
    code = parts[3]
    context.user_data["ep_cat"]  = cat
    context.user_data["ep_code"] = code
    next_num = db.get_next_episode_num(cat, code)
    item = db.get_item(cat, code)

    await query.edit_message_text(
        f"📺 <b>{item['title']}</b>\n\n"
        f"{next_num}-qism faylini yuboring:",
        parse_mode="HTML"
    )
    return ADDEP_FILE


# ── O'CHIRISH ──────────────────────────────────────────────────────────

async def admin_delete_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    if not is_admin(query.from_user.id):
        return

    keyboard = [
        [
            InlineKeyboardButton("🎌 Anime", callback_data="del_anime"),
            InlineKeyboardButton("🎭 Drama", callback_data="del_drama"),
            InlineKeyboardButton("🎬 Kino",  callback_data="del_kino"),
        ],
        [InlineKeyboardButton("❌ Bekor", callback_data="admin_panel")]
    ]
    await query.edit_message_text(
        "🗑 <b>O'chirish — kategoriya tanlang:</b>",
        reply_markup=InlineKeyboardMarkup(keyboard),
        parse_mode="HTML"
    )
    return DEL_CAT


async def delete_select_cat(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    cat = query.data.replace("del_", "")
    context.user_data["del_cat"] = cat

    items = db.get_all_items(cat)
    cat_name = CATEGORY_NAMES.get(cat, cat)

    if not items:
        await query.edit_message_text(f"{cat_name} bo'sh.")
        return ConversationHandler.END

    lines = [f"🗑 {cat_name}\n\nKodlar:\n"]
    for item in items:
        ep_count = item.get("episode_count", 0)
        lines.append(f"  🔹 <code>{item['code']}</code> — {item['title']} ({ep_count} qism)")
    lines.append("\n✏️ <b>O'chirmoqchi bo'lgan kodni yozing:</b>")
    await query.edit_message_text("\n".join(lines), parse_mode="HTML")
    return DEL_CODE


async def delete_confirm(update: Update, context: ContextTypes.DEFAULT_TYPE):
    code = update.message.text.strip().upper()
    cat  = context.user_data["del_cat"]
    item = db.get_item(cat, code)

    if not item:
        await update.message.reply_text(f"❌ <code>{code}</code> topilmadi.", parse_mode="HTML")
        return DEL_CODE

    db.delete_item(cat, code)
    cat_name = CATEGORY_NAMES.get(cat, cat)
    await update.message.reply_text(
        f"✅ <b>O'chirildi!</b>\n\n"
        f"📁 {cat_name} / <code>{code}</code> — {item['title']}\n"
        f"(Barcha qismlari ham o'chirildi)",
        parse_mode="HTML"
    )
    return ConversationHandler.END


# ── BROADCAST ─────────────────────────────────────────────────────────

async def admin_broadcast_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    if not is_admin(query.from_user.id):
        return

    stats = db.get_stats()
    await query.edit_message_text(
        f"📢 <b>Broadcast</b>\n\n"
        f"👥 {stats['users']} ta foydalanuvchiga yuboriladi\n\n"
        "Xabar yozing yoki fayl yuboring.\n"
        "<i>Bekor: /cancel</i>",
        parse_mode="HTML"
    )
    return BROADCAST


async def do_broadcast(update: Update, context: ContextTypes.DEFAULT_TYPE):
    users  = db.get_all_users()
    sent   = 0
    failed = 0
    status = await update.message.reply_text(f"📤 Yuborilmoqda... 0/{len(users)}")

    for i, user in enumerate(users):
        try:
            uid = user["user_id"]
            if update.message.text:
                await context.bot.send_message(uid, update.message.text, parse_mode="HTML")
            elif update.message.video:
                await context.bot.send_video(uid, update.message.video.file_id,
                                             caption=update.message.caption or "", parse_mode="HTML")
            elif update.message.photo:
                await context.bot.send_photo(uid, update.message.photo[-1].file_id,
                                             caption=update.message.caption or "", parse_mode="HTML")
            elif update.message.document:
                await context.bot.send_document(uid, update.message.document.file_id,
                                                caption=update.message.caption or "", parse_mode="HTML")
            sent += 1
        except Exception:
            failed += 1
        if (i + 1) % 10 == 0:
            try:
                await status.edit_text(f"📤 Yuborilmoqda... {i+1}/{len(users)}")
            except Exception:
                pass

    await status.edit_text(
        f"✅ <b>Broadcast tugadi!</b>\n\n✔️ Yuborildi: {sent}\n❌ Xatolik: {failed}",
        parse_mode="HTML"
    )
    return ConversationHandler.END


async def conv_cancel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("❌ Bekor qilindi.")
    return ConversationHandler.END


# ══════════════════════════════════════════════════════════
#  MAIN
# ══════════════════════════════════════════════════════════

def main():
    app = Application.builder().token(BOT_TOKEN).build()

    # Serial qo'shish
    add_conv = ConversationHandler(
        entry_points=[CallbackQueryHandler(admin_add_start, pattern="^admin_add$")],
        states={
            ADD_CAT:  [CallbackQueryHandler(add_select_cat, pattern="^add_")],
            ADD_CODE: [MessageHandler(filters.TEXT & ~filters.COMMAND, add_get_code)],
            ADD_TITLE:[MessageHandler(filters.TEXT & ~filters.COMMAND, add_get_title)],
            ADD_DESC: [MessageHandler(filters.TEXT, add_get_desc)],
        },
        fallbacks=[
            CommandHandler("cancel", conv_cancel),
            CallbackQueryHandler(admin_panel, pattern="^admin_panel$"),
        ],
        per_user=True,
    )

    # Qism qo'shish
    addep_conv = ConversationHandler(
        entry_points=[
            CallbackQueryHandler(admin_addep_start, pattern="^admin_addep$"),
            CallbackQueryHandler(continue_episode,  pattern="^cont_ep_"),
        ],
        states={
            ADDEP_CAT:  [CallbackQueryHandler(addep_select_cat, pattern="^addep_")],
            ADDEP_CODE: [MessageHandler(filters.TEXT & ~filters.COMMAND, addep_get_code)],
            ADDEP_FILE: [MessageHandler(filters.VIDEO | filters.Document.ALL | filters.PHOTO, addep_get_file)],
        },
        fallbacks=[
            CommandHandler("cancel", conv_cancel),
            CallbackQueryHandler(admin_panel, pattern="^admin_panel$"),
        ],
        per_user=True,
    )

    # O'chirish
    del_conv = ConversationHandler(
        entry_points=[CallbackQueryHandler(admin_delete_start, pattern="^admin_delete$")],
        states={
            DEL_CAT:  [CallbackQueryHandler(delete_select_cat, pattern="^del_")],
            DEL_CODE: [MessageHandler(filters.TEXT & ~filters.COMMAND, delete_confirm)],
        },
        fallbacks=[
            CommandHandler("cancel", conv_cancel),
            CallbackQueryHandler(admin_panel, pattern="^admin_panel$"),
        ],
        per_user=True,
    )

    # Broadcast
    broadcast_conv = ConversationHandler(
        entry_points=[CallbackQueryHandler(admin_broadcast_start, pattern="^admin_broadcast$")],
        states={
            BROADCAST: [MessageHandler(
                filters.TEXT | filters.VIDEO | filters.PHOTO | filters.Document.ALL,
                do_broadcast
            )],
        },
        fallbacks=[CommandHandler("cancel", conv_cancel)],
        per_user=True,
    )

    app.add_handler(CommandHandler("start", start))
    app.add_handler(add_conv)
    app.add_handler(addep_conv)
    app.add_handler(del_conv)
    app.add_handler(broadcast_conv)
    app.add_handler(CallbackQueryHandler(show_category,  pattern="^cat_"))
    app.add_handler(CallbackQueryHandler(back_main,      pattern="^back_main$"))
    app.add_handler(CallbackQueryHandler(admin_panel,    pattern="^admin_panel$"))
    app.add_handler(CallbackQueryHandler(admin_stats,    pattern="^admin_stats$"))
    app.add_handler(CallbackQueryHandler(send_episode,   pattern="^ep_"))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_code))

    logger.info("Bot ishga tushdi...")
    app.run_polling(allowed_updates=Update.ALL_TYPES)


if __name__ == "__main__":
    main()
