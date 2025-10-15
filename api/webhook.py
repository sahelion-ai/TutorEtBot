import os
import json
import time
import hashlib
import base64
import firebase_admin
from firebase_admin import credentials, firestore
from telegram import Update
from telegram.ext import Application, CommandHandler, ContextTypes
from flask import Flask, request
from datetime import datetime
from dotenv import load_dotenv

# =========================
# 🔧 ENVIRONMENT CONFIG
# =========================
load_dotenv()

BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
ADMIN_IDS = [int(x) for x in os.getenv("ADMIN_USER_IDS", "").split(",") if x]
FIREBASE_CREDENTIALS_B64 = os.getenv("FIREBASE_CREDENTIALS")
WEBHOOK_URL = os.getenv("WEBHOOK_URL")

if not BOT_TOKEN or not FIREBASE_CREDENTIALS_B64:
    raise ValueError("Missing environment variables! Check TELEGRAM_BOT_TOKEN and FIREBASE_CREDENTIALS")

# =========================
# 🔥 FIREBASE INIT
# =========================
if not firebase_admin._apps:
    firebase_creds = json.loads(base64.b64decode(FIREBASE_CREDENTIALS_B64))
    cred = credentials.Certificate(firebase_creds)
    firebase_admin.initialize_app(cred)
# Firebase references
db = firestore.client()
STUDENTS_COL = db.collection("students")

# =========================
# 🤖 FLASK APP FOR VERCEL
# =========================
app = Flask(__name__)

# =========================
# 🧠 DEVICE FINGERPRINTING
# =========================
def build_fingerprint_components(user_id, language, timezone, headers, timestamp):
    """
    Creates a robust fingerprint hash from multiple system identifiers.
    Even identical phone models produce unique hashes due to differences in:
      - OS version
      - Telegram version
      - Language + timezone
      - Random entropy from installation time
    """
    ua = headers.get("User-Agent", "UnknownUA")
    tg_version = headers.get("Telegram-Version", "UnknownVersion")
    platform = headers.get("Platform", "UnknownPlatform")

    raw_fingerprint = f"{user_id}|{ua}|{tg_version}|{platform}|{language}|{timezone}|{timestamp}"
    hash_value = hashlib.sha256(raw_fingerprint.encode()).hexdigest()

    return {
        "ua": ua,
        "tg_version": tg_version,
        "platform": platform,
        "language": language,
        "timezone": timezone,
        "hash": hash_value,
    }

# =========================
# 🔒 DEVICE VERIFICATION
# =========================
def verify_device_for_student(user_id, current_hash):
    student_ref = STUDENTS_REF.child(str(user_id))
    data = student_ref.get()
    if not data:
        return False
    device_hashes = [data.get("device_1_hash"), data.get("device_2_hash")]
    return current_hash in device_hashes

def update_last_active_and_increment(user_id):
    student_ref = STUDENTS_REF.child(str(user_id))
    data = student_ref.get()
    if not data:
        return
    access_count = data.get("access_count", 0)
    student_ref.update({
        "last_active": datetime.utcnow().isoformat(),
        "access_count": access_count + 1
    })

# =========================
# 💬 BOT COMMANDS
# =========================

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    user = update.effective_user

    ref = STUDENTS_REF.child(str(user_id))
    data = ref.get()

    if not data or not data.get("approved"):
        await update.message.reply_text(
            "👋 Welcome!\n\nTo access the videos, please contact the admin for manual payment approval.\n"
            "After payment, admin will approve you. Use /how_to_join for detailed steps."
        )
        return

    # Build fingerprint for this device
    comps = build_fingerprint_components(
        user_id, user.language_code, "", {}, int(time.time())
    )
    current_hash = comps.get("hash")

    # Register device
    if not data.get("device_1_hash"):
        ref.update({
            "device_1_hash": current_hash,
            "device_1_fingerprint": str(comps),
            "device_1_name": "Device 1",
            "registration_date": datetime.utcnow().isoformat()
        })
        await update.message.reply_text("✅ Device 1 registered successfully.")
    elif not data.get("device_2_hash"):
        if current_hash == data.get("device_1_hash"):
            await update.message.reply_text("⚠️ This device is already registered.")
            return
        ref.update({
            "device_2_hash": current_hash,
            "device_2_fingerprint": str(comps),
            "device_2_name": "Device 2"
        })
        await update.message.reply_text("✅ Device 2 registered successfully.")
    else:
        await update.message.reply_text("❌ You have reached the maximum of 2 registered devices.")

async def how_to_join(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "💰 **How to Join:**\n\n"
        "1️⃣ Message the admin directly and ask for payment instructions.\n"
        "2️⃣ Send your payment proof to the admin.\n"
        "3️⃣ Admin will manually approve you.\n"
        "4️⃣ After approval, use /start to register your device.\n"
        "5️⃣ Then you can access videos using /watch or channel buttons."
    )

async def approve(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    if user_id not in ADMIN_IDS:
        await update.message.reply_text("⛔ You are not authorized to approve students.")
        return

    if not context.args:
        await update.message.reply_text("Usage: /approve @username or /approve user_id")
        return

    target = context.args[0].replace("@", "")
    all_students = STUDENTS_REF.get() or {}
    target_id = None

    # Search student by username or ID
    for sid, data in all_students.items():
        if data.get("username") == target or sid == target:
            target_id = sid
            break

    if not target_id:
        await update.message.reply_text(f"❌ Student {target} not found.")
        return

    STUDENTS_REF.child(target_id).update({
        "approved": True,
        "approved_by": str(user_id),
        "approved_at": datetime.utcnow().isoformat()
    })

    await update.message.reply_text(f"✅ Approved {target} (ID: {target_id})")
    try:
        await context.bot.send_message(int(target_id), "✅ You’ve been approved! Use /start to register your device.")
    except:
        pass

async def my_devices(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    data = STUDENTS_REF.child(str(user_id)).get()
    if not data:
        await update.message.reply_text("❌ You are not registered.")
        return

    text = "📱 Registered Devices:\n\n"
    if data.get("device_1_hash"):
        text += f"• Device 1: {data.get('device_1_name')}\nHash: {data.get('device_1_hash')[:10]}...\n\n"
    if data.get("device_2_hash"):
        text += f"• Device 2: {data.get('device_2_name')}\nHash: {data.get('device_2_hash')[:10]}...\n\n"

    await update.message.reply_text(text)

async def watch(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    ref = STUDENTS_REF.child(str(user_id))
    data = ref.get()
    if not data or not data.get("approved"):
        await update.message.reply_text("❌ You are not approved. Contact admin first.")
        return

    if not context.args:
        await update.message.reply_text("Usage: /watch [lecture_number]")
        return

    lecture = context.args[0]
    comps = build_fingerprint_components(user_id, "", "", {}, int(time.time()))
    current_hash = comps.get("hash")

    if not verify_device_for_student(user_id, current_hash):
        await update.message.reply_text("❌ This device is not registered. Use /start first.")
        return

    videos = {
        "1": "https://t.me/c/123456789/45",
        "2": "https://t.me/c/123456789/46",
        "3": "https://t.me/c/123456789/47"
    }

    if lecture not in videos:
        await update.message.reply_text("❌ Invalid lecture number.")
        return

    update_last_active_and_increment(user_id)
    await update.message.reply_text(f"🎥 Lecture {lecture}:\n{videos[lecture]}")

# =========================
# 🎯 DEEP LINK HANDLER
# =========================
def handle_unit_deeplink(msg: dict, unit: str):
    user_id = msg.get("from", {}).get("id")
    ref = STUDENTS_REF.child(str(user_id))
    doc = ref.get()

    if not doc or not doc.get("approved"):
        return {"reply": "❌ Please contact admin for approval first. Use /how_to_join for details."}

    comps = build_fingerprint_components(user_id, msg.get("from", {}).get("language_code"), "", {}, int(time.time()))
    current_hash = comps.get("hash")

    if not verify_device_for_student(user_id, current_hash):
        return {"reply": "❌ Device not registered. Use /start to register first."}

    unit_videos = {
        'unit1': [
            "Lecture 1: https://t.me/c/123456789/45",
            "Lecture 2: https://t.me/c/123456789/46",
            "Practice: https://t.me/c/123456789/47"
        ],
        'unit2': [
            "Lecture 3: https://t.me/c/123456789/48",
            "Lecture 4: https://t.me/c/123456789/49",
            "Practice: https://t.me/c/123456789/50"
        ],
        'unit3': [
            "Lecture 5: https://t.me/c/123456789/51",
            "Lecture 6: https://t.me/c/123456789/52",
            "Practice: https://t.me/c/123456789/53"
        ]
    }

    if unit in unit_videos:
        update_last_active_and_increment(user_id)
        videos_text = "\n".join(unit_videos[unit])
        return {"reply": f"📚 {unit.upper()} Videos:\n\n{videos_text}"}
    else:
        return {"reply": "Unit not found. Use /start to register."}

# =========================
# 🌐 FLASK WEBHOOK ROUTE
# =========================
@app.route("/api/webhook", methods=["POST"])
def webhook():
    data = request.get_json()
    if not data:
        return "No data", 400

    message = data.get("message")
    if not message:
        return "No message", 400

    text = message.get("text", "")
    if not text:
        return "OK", 200

    parts = text.split()
    cmd = parts[0]
    args = parts[1:]

    if cmd == "/start":
        if args and args[0] in ['unit1', 'unit2', 'unit3']:
            res = handle_unit_deeplink(message, args[0])
            send_telegram_message(message["chat"]["id"], res["reply"])
        else:
            # Default start handler
            pass

    return "OK", 200

# =========================
# 📤 SEND MESSAGE HELPER
# =========================
def send_telegram_message(chat_id, text):
    import requests
    url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"
    requests.post(url, json={"chat_id": chat_id, "text": text})

# =========================
# 🧭 VERCEL HANDLER
# =========================
def handler(request):
    with app.test_request_context(request.path, method=request.method, data=request.get_data(), headers=request.headers):
        return app.full_dispatch_request()

# =========================
# 🔥 MAIN
# =========================
if __name__ == "__main__":
    app.run(debug=True)
