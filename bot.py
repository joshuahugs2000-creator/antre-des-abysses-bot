"""
╔══════════════════════════════════════════╗
║     BOT TELEGRAM - L'ANTRE DES ABYSSES  ║
║         Développé en Python 3.13         ║
╚══════════════════════════════════════════╝

Installation :
  pip install python-telegram-bot==21.6 aiohttp

Render :
  - Variable d'environnement : BOT_TOKEN = <ton token>
  - Start Command : python bot.py
  - Health Check Path : /

Commandes :
  /ban       → Bannir (répondre au message ou /ban @username)
  /unban     → Débannir (/unban @username)
  /mute      → Rendre muet
  /unmute    → Retirer le mute
  /call      → Taguer TOUS les membres du groupe
  /calladmin → Taguer uniquement les admins
  /silence   → Toggle silence total (seuls les admins parlent)
  /admin     → Nommer admin avec titre (/admin Titre en répondant au message)
"""

import asyncio
import logging
import os

from aiohttp import web
from telegram import Update, ChatPermissions
from telegram.ext import (
    Application,
    CommandHandler,
    ChatMemberHandler,
    MessageHandler,
    ContextTypes,
    filters,
)
from telegram.constants import ChatMemberStatus

# ══════════════════════════════════════════════════════════════════════════════
#  CONFIGURATION — token via variable d'environnement (Render dashboard)
# ══════════════════════════════════════════════════════════════════════════════

TOKEN              = os.environ.get("BOT_TOKEN", "8697861606:AAH3jOr93Qm1I7s_QkVPXtiBparA3sbgygA")
WELCOME_IMAGE_URL  = "https://i.pinimg.com/736x/44/ee/96/44ee963359073bffd25d751614ba67dc.jpg"
FAREWELL_IMAGE_URL = "https://i.pinimg.com/736x/d9/63/b1/d963b1061e1569d67d06d9c59a7b37f0.jpg"
PORT               = int(os.environ.get("PORT", 8080))

# ══════════════════════════════════════════════════════════════════════════════
#  TEXTES
# ══════════════════════════════════════════════════════════════════════════════

WELCOME_TEXT = """
🌑 *L'ANTRE DES ABYSSES t'accueille\.\.\.*

Âme errante, tu as franchi le seuil de l'obscurité\.
Bienvenue, {mention}, dans ce royaume où les ombres ont une voix et le silence un poids\.

Ici, les règles sont simples :
🩸 Respecte chaque âme qui erre dans ces ténèbres
🩸 La parole est un privilège, pas un droit
🩸 Les gardiens veillent — invisibles, mais omniprésents

*Que l'abysses te guide\.\.\. ou te consume\.*

🌊 _— Les Gardiens des Abysses_
"""

FAREWELL_TEXT = """
🌑 *Une âme quitte l'Antre\.\.\.*

{mention} a choisi de fuir les ténèbres\.
Ou peut\-être que les abysses l'ont rejeté\.\.\.

*Le vide que tu laisses sera vite comblé par l'obscurité\.*

_Que ton chemin soit aussi sombre que celui que tu quittes\._

🌊 _— Les Gardiens des Abysses_
"""

# ══════════════════════════════════════════════════════════════════════════════
#  PERMISSIONS
# ══════════════════════════════════════════════════════════════════════════════

FULL_PERMISSIONS = ChatPermissions(
    can_send_messages=True, can_send_audios=True, can_send_documents=True,
    can_send_photos=True, can_send_videos=True, can_send_video_notes=True,
    can_send_voice_notes=True, can_send_polls=True, can_send_other_messages=True,
    can_add_web_page_previews=True, can_invite_users=True,
)

MUTED_PERMISSIONS = ChatPermissions(
    can_send_messages=False, can_send_audios=False, can_send_documents=False,
    can_send_photos=False, can_send_videos=False, can_send_video_notes=False,
    can_send_voice_notes=False, can_send_polls=False, can_send_other_messages=False,
)

# ══════════════════════════════════════════════════════════════════════════════
#  LOGGING
# ══════════════════════════════════════════════════════════════════════════════

logging.basicConfig(format="%(asctime)s | %(levelname)s | %(message)s", level=logging.INFO)
logger = logging.getLogger(__name__)

# ══════════════════════════════════════════════════════════════════════════════
#  UTILITAIRES
# ══════════════════════════════════════════════════════════════════════════════

def escape_md(text: str) -> str:
    """Échappe les caractères spéciaux pour MarkdownV2."""
    special = r"\_*[]()~`>#+-=|{}.!"
    return "".join(f"\\{c}" if c in special else c for c in str(text))

async def is_admin(update: Update, context: ContextTypes.DEFAULT_TYPE, user_id: int) -> bool:
    try:
        member = await context.bot.get_chat_member(update.effective_chat.id, user_id)
        return member.status in [ChatMemberStatus.ADMINISTRATOR, ChatMemberStatus.OWNER]
    except Exception:
        return False

async def get_target(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Retourne (user_id, nom) depuis une réponse ou un argument."""
    if update.message.reply_to_message:
        u = update.message.reply_to_message.from_user
        return u.id, u.username or u.first_name
    if context.args:
        arg = context.args[0].lstrip("@")
        if arg.isdigit():
            return int(arg), arg
        # Username sans ID → impossible à résoudre sans interaction préalable
        return None, arg
    return None, None

# ══════════════════════════════════════════════════════════════════════════════
#  CACHE DES MEMBRES (isolé par chat_id pour /call)
# ══════════════════════════════════════════════════════════════════════════════

def get_members_for_chat(context: ContextTypes.DEFAULT_TYPE, chat_id: int) -> dict:
    if "members" not in context.bot_data:
        context.bot_data["members"] = {}
    return context.bot_data["members"].setdefault(str(chat_id), {})

async def cache_member(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Met en cache chaque membre qui parle, par groupe."""
    if update.effective_user and not update.effective_user.is_bot and update.effective_chat:
        u = update.effective_user
        members = get_members_for_chat(context, update.effective_chat.id)
        members[str(u.id)] = u.username or u.first_name

# ══════════════════════════════════════════════════════════════════════════════
#  ÉVÉNEMENTS MEMBRES (bienvenue / au revoir)
# ══════════════════════════════════════════════════════════════════════════════

async def on_member_update(update: Update, context: ContextTypes.DEFAULT_TYPE):
    r = update.chat_member
    old_status = r.old_chat_member.status
    new_status = r.new_chat_member.status

    # Arrivée d'un nouveau membre
    if new_status in ["member", "restricted"] and old_status not in ["member", "administrator", "creator", "restricted"]:
        user = r.new_chat_member.user
        mention = f"[{escape_md(user.first_name)}](tg://user?id={user.id})"
        text = WELCOME_TEXT.format(mention=mention)
        try:
            await context.bot.send_photo(chat_id=r.chat.id, photo=WELCOME_IMAGE_URL, caption=text, parse_mode="MarkdownV2")
        except Exception:
            await context.bot.send_message(chat_id=r.chat.id, text=text, parse_mode="MarkdownV2")

    # Départ d'un membre
    elif new_status in ["left", "kicked"] and old_status in ["member", "restricted", "administrator"]:
        user = r.old_chat_member.user
        mention = f"[{escape_md(user.first_name)}](tg://user?id={user.id})"
        text = FAREWELL_TEXT.format(mention=mention)
        try:
            await context.bot.send_photo(chat_id=r.chat.id, photo=FAREWELL_IMAGE_URL, caption=text, parse_mode="MarkdownV2")
        except Exception:
            await context.bot.send_message(chat_id=r.chat.id, text=text, parse_mode="MarkdownV2")

# ══════════════════════════════════════════════════════════════════════════════
#  COMMANDES DE MODÉRATION
# ══════════════════════════════════════════════════════════════════════════════

async def cmd_ban(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await is_admin(update, context, update.effective_user.id):
        return await update.message.reply_text("⛔ Seuls les Gardiens peuvent bannir.")
    user_id, name = await get_target(update, context)
    if not user_id:
        return await update.message.reply_text(
            "❌ Répondez à un message ou : /ban @username\n"
            "⚠️ Note : /ban @username ne fonctionne que si l'utilisateur a déjà parlé dans le groupe."
        )
    # Vérifier que la cible n'est pas admin
    if await is_admin(update, context, user_id):
        return await update.message.reply_text("⛔ Impossible de bannir un Gardien.")
    try:
        await context.bot.ban_chat_member(update.effective_chat.id, user_id)
        await update.message.reply_text(f"🔨 *{escape_md(str(name))}* a été banni des Abysses.", parse_mode="MarkdownV2")
    except Exception as e:
        await update.message.reply_text(f"❌ Erreur : {e}")

async def cmd_unban(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await is_admin(update, context, update.effective_user.id):
        return await update.message.reply_text("⛔ Seuls les Gardiens peuvent débannir.")
    user_id, name = await get_target(update, context)
    if not user_id:
        return await update.message.reply_text("❌ Usage : /unban @username (avec l'ID numérique de préférence)")
    try:
        await context.bot.unban_chat_member(update.effective_chat.id, user_id, only_if_banned=True)
        await update.message.reply_text(f"✅ *{escape_md(str(name))}* peut de nouveau fouler les Abysses.", parse_mode="MarkdownV2")
    except Exception as e:
        await update.message.reply_text(f"❌ Erreur : {e}")

async def cmd_mute(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await is_admin(update, context, update.effective_user.id):
        return await update.message.reply_text("⛔ Seuls les Gardiens peuvent réduire au silence.")
    user_id, name = await get_target(update, context)
    if not user_id:
        return await update.message.reply_text("❌ Répondez à un message ou : /mute @username")
    if await is_admin(update, context, user_id):
        return await update.message.reply_text("⛔ Impossible de muter un Gardien.")
    try:
        await context.bot.restrict_chat_member(update.effective_chat.id, user_id, MUTED_PERMISSIONS)
        await update.message.reply_text(f"🔇 *{escape_md(str(name))}* a été réduit au silence.", parse_mode="MarkdownV2")
    except Exception as e:
        await update.message.reply_text(f"❌ Erreur : {e}")

async def cmd_unmute(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await is_admin(update, context, update.effective_user.id):
        return await update.message.reply_text("⛔ Seuls les Gardiens peuvent libérer la parole.")
    user_id, name = await get_target(update, context)
    if not user_id:
        return await update.message.reply_text("❌ Répondez à un message ou : /unmute @username")
    try:
        await context.bot.restrict_chat_member(update.effective_chat.id, user_id, FULL_PERMISSIONS)
        await update.message.reply_text(f"🔊 *{escape_md(str(name))}* peut de nouveau parler dans les Abysses.", parse_mode="MarkdownV2")
    except Exception as e:
        await update.message.reply_text(f"❌ Erreur : {e}")

async def cmd_call(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """/call — Tague tous les membres en cache pour ce groupe."""
    if not await is_admin(update, context, update.effective_user.id):
        return await update.message.reply_text("⛔ Seuls les Gardiens peuvent convoquer les âmes.")

    members = get_members_for_chat(context, update.effective_chat.id)
    msg = escape_md(" ".join(context.args)) if context.args else "Rassemblement dans les Abysses \\!"

    if not members:
        return await update.message.reply_text(
            "⚠️ Aucun membre en cache pour l'instant.\n"
            "Les âmes doivent d'abord parler pour être convoquées."
        )

    mentions = [f"[{escape_md(name)}](tg://user?id={uid})" for uid, name in members.items()]
    chunks = [mentions[i:i+20] for i in range(0, len(mentions), 20)]

    header = f"📢 *CONVOCATION DE TOUTES LES ÂMES*\n\n_{msg}_\n\n"
    for i, chunk in enumerate(chunks):
        text = (header if i == 0 else "") + " ".join(chunk)
        if i == len(chunks) - 1:
            text += "\n\n🌊 _— Les Gardiens des Abysses_"
        await update.message.reply_text(text, parse_mode="MarkdownV2")
        await asyncio.sleep(1)  # Anti rate-limit Telegram

async def cmd_calladmin(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """/calladmin — Tague uniquement les admins du groupe."""
    if not await is_admin(update, context, update.effective_user.id):
        return await update.message.reply_text("⛔ Seuls les Gardiens peuvent convoquer les Gardiens.")
    admins = await context.bot.get_chat_administrators(update.effective_chat.id)
    mentions = [
        f"[{escape_md(a.user.first_name)}](tg://user?id={a.user.id})"
        for a in admins if not a.user.is_bot
    ]
    msg = escape_md(" ".join(context.args)) if context.args else "Conclave des Gardiens \\!"
    text = f"👁️ *CONVOCATION DES GARDIENS*\n\n_{msg}_\n\n{' '.join(mentions)}\n\n🌊 _— Les Abysses_"
    await update.message.reply_text(text, parse_mode="MarkdownV2")

async def cmd_silence(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await is_admin(update, context, update.effective_user.id):
        return await update.message.reply_text("⛔ Seuls les Gardiens peuvent imposer le silence.")
    chat = await context.bot.get_chat(update.effective_chat.id)
    if chat.permissions and not chat.permissions.can_send_messages:
        await context.bot.set_chat_permissions(update.effective_chat.id, FULL_PERMISSIONS)
        await update.message.reply_text("🔊 *Le silence est levé\\.* Les âmes peuvent de nouveau parler\\.", parse_mode="MarkdownV2")
    else:
        await context.bot.set_chat_permissions(update.effective_chat.id, MUTED_PERMISSIONS)
        await update.message.reply_text(
            "🤫 *SILENCE TOTAL\\.*\n\nSeuls les Gardiens des Abysses peuvent parler\\.\n_L'obscurité règne\\._",
            parse_mode="MarkdownV2"
        )

async def cmd_admin(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await is_admin(update, context, update.effective_user.id):
        return await update.message.reply_text("⛔ Seuls les Gardiens peuvent nommer de nouveaux Gardiens.")
    if not update.message.reply_to_message:
        return await update.message.reply_text("❌ Répondez au message de l'utilisateur + /admin Titre")
    user = update.message.reply_to_message.from_user
    title = " ".join(context.args) if context.args else "Gardien des Abysses"

    # Avertissement si titre tronqué
    warning = ""
    if len(title) > 16:
        warning = f"\n⚠️ Titre tronqué à 16 caractères : *{escape_md(title[:16])}*"
        title = title[:16]

    try:
        await context.bot.promote_chat_member(
            update.effective_chat.id, user.id,
            can_delete_messages=True, can_restrict_members=True,
            can_pin_messages=True, can_invite_users=True, can_manage_chat=True,
        )
        await context.bot.set_chat_administrator_custom_title(update.effective_chat.id, user.id, title)
        await update.message.reply_text(
            f"👑 *{escape_md(user.username or user.first_name)}* est désormais *{escape_md(title)}* dans les Abysses\\.\n_Un nouveau Gardien s'éveille\\.\\.\\._" + warning,
            parse_mode="MarkdownV2",
        )
    except Exception as e:
        await update.message.reply_text(f"❌ Erreur : {e}")

# ══════════════════════════════════════════════════════════════════════════════
#  SERVEUR HEALTH CHECK (garde Render éveillé)
# ══════════════════════════════════════════════════════════════════════════════

async def health_check(request):
    return web.Response(text="🌑 L'Antre des Abysses est éveillé.", status=200)

async def run_health_server():
    app = web.Application()
    app.router.add_get("/", health_check)
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, "0.0.0.0", PORT)
    await site.start()
    logger.info(f"✅ Health check server démarré sur le port {PORT}")

# ══════════════════════════════════════════════════════════════════════════════
#  LANCEMENT
# ══════════════════════════════════════════════════════════════════════════════

async def main():
    # Démarrer le health check server en parallèle
    await run_health_server()

    app = Application.builder().token(TOKEN).build()

    # Événements membres (bienvenue / au revoir) — un seul handler
    app.add_handler(ChatMemberHandler(on_member_update, ChatMemberHandler.CHAT_MEMBER))

    # Cache membres pour /call
    app.add_handler(MessageHandler(filters.ALL, cache_member), group=1)

    # Commandes
    app.add_handler(CommandHandler("ban",       cmd_ban))
    app.add_handler(CommandHandler("unban",     cmd_unban))
    app.add_handler(CommandHandler("mute",      cmd_mute))
    app.add_handler(CommandHandler("unmute",    cmd_unmute))
    app.add_handler(CommandHandler("call",      cmd_call))
    app.add_handler(CommandHandler("calladmin", cmd_calladmin))
    app.add_handler(CommandHandler("silence",   cmd_silence))
    app.add_handler(CommandHandler("admin",     cmd_admin))

    logger.info("🌑 L'Antre des Abysses s'éveille... Bot démarré.")

    await app.initialize()
    await app.start()
    await app.updater.start_polling(allowed_updates=Update.ALL_TYPES)

    # Garde le bot en vie indéfiniment
    await asyncio.Event().wait()

if __name__ == "__main__":
    asyncio.run(main())
