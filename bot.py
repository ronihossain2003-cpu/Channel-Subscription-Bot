import os
import logging
from datetime import datetime, timedelta, timezone

from flask import Flask
from threading import Thread

import firebase_admin
from firebase_admin import credentials, firestore

from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    Application,
    CommandHandler,
    CallbackQueryHandler,
    MessageHandler,
    ContextTypes,
    filters,
)

from dotenv import load_dotenv


# ============================================================
# CONFIG
# ============================================================

load_dotenv()

BOT_TOKEN = os.getenv("BOT_TOKEN")
ADMIN_ID = int(os.getenv("ADMIN_ID", "0"))

# Payment numbers shown to users
BKASH_NUMBER = os.getenv("BKASH_NUMBER", "01XXXXXXXXX")
NAGAD_NUMBER = os.getenv("NAGAD_NUMBER", "01XXXXXXXXX")

PORT = int(os.getenv("PORT", "10000"))

if not BOT_TOKEN:
    raise ValueError("BOT_TOKEN is missing in .env")

if ADMIN_ID == 0:
    raise ValueError("ADMIN_ID is missing in .env")


# ============================================================
# LOGGING
# ============================================================

logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO,
)

logger = logging.getLogger(__name__)


# ============================================================
# FIREBASE
# ============================================================

firebase_key = os.getenv("FIREBASE_KEY")

if firebase_key:
    import json

    firebase_credentials = credentials.Certificate(
        json.loads(firebase_key)
    )
else:
    firebase_credentials = credentials.Certificate("firebase_key.json")


if not firebase_admin._apps:
    firebase_admin.initialize_app(firebase_credentials)

db = firestore.client()


# ============================================================
# FLASK HEALTH SERVER
# ============================================================

app = Flask(__name__)


@app.route("/")
def home():
    return "Telegram Subscription Bot is running."


@app.route("/health")
def health():
    return "OK"


def run_web_server():
    app.run(host="0.0.0.0", port=PORT)


def start_web_server():
    thread = Thread(target=run_web_server)
    thread.daemon = True
    thread.start()


# ============================================================
# SUBSCRIPTION PLANS
# ============================================================

PLANS = {
    "premium": {
        "name": "Premium",
        "price": 99,
        "days": 30,
        "features": [
            "Watch",
            "Request",
        ],
    },
    "premium_plus": {
        "name": "Premium Plus",
        "price": 225,
        "days": 30,
        "features": [
            "Download",
            "Watch",
            "Request",
            "Other Language",
        ],
    },
    "premium_star": {
        "name": "Premium Star",
        "price": 499,
        "days": 30,
        "features": [
            "Download",
            "Watch",
            "Request",
            "4K",
            "Other Language",
        ],
    },
}


# ============================================================
# FIREBASE HELPERS
# ============================================================

def user_ref(user_id):
    return db.collection("users").document(str(user_id))


def payment_ref(payment_id):
    return db.collection("payments").document(payment_id)


def save_user(user):
    ref = user_ref(user.id)

    data = {
        "user_id": user.id,
        "username": user.username or "",
        "first_name": user.first_name or "",
        "updated_at": firestore.SERVER_TIMESTAMP,
    }

    if not ref.get().exists:
        data["created_at"] = firestore.SERVER_TIMESTAMP
        data["subscription"] = "none"
        data["subscription_expiry"] = None

    ref.set(data, merge=True)


def get_user(user_id):
    doc = user_ref(user_id).get()

    if doc.exists:
        return doc.to_dict()

    return None


def get_active_subscription(user_id):
    data = get_user(user_id)

    if not data:
        return None

    plan = data.get("subscription")

    expiry = data.get("subscription_expiry")

    if not plan or plan == "none" or not expiry:
        return None

    try:
        expiry_datetime = expiry

        if hasattr(expiry_datetime, "replace"):
            expiry_datetime = expiry_datetime.replace(tzinfo=timezone.utc)

        if expiry_datetime > datetime.now(timezone.utc):
            return {
                "plan": plan,
                "expiry": expiry_datetime,
            }

    except Exception as e:
        logger.error("Subscription check error: %s", e)

    return None


def activate_subscription(user_id, plan_id):
    plan = PLANS[plan_id]

    now = datetime.now(timezone.utc)

    current = get_active_subscription(user_id)

    if current:
        start_date = current["expiry"]
    else:
        start_date = now

    expiry = start_date + timedelta(days=plan["days"])

    user_ref(user_id).set(
        {
            "subscription": plan_id,
            "subscription_expiry": expiry,
            "subscription_updated": firestore.SERVER_TIMESTAMP,
        },
        merge=True,
    )

    return expiry


# ============================================================
# KEYBOARDS
# ============================================================

def main_menu():
    keyboard = [
        [
            InlineKeyboardButton(
                "💎 Subscription Plans",
                callback_data="plans",
            )
        ],
        [
            InlineKeyboardButton(
                "📅 My Subscription",
                callback_data="my_subscription",
            )
        ],
        [
            InlineKeyboardButton(
                "💳 Payment",
                callback_data="payment",
            )
        ],
        [
            InlineKeyboardButton(
                "📞 Support",
                callback_data="support",
            )
        ],
    ]

    return InlineKeyboardMarkup(keyboard)


def plans_menu():
    keyboard = []

    for plan_id, plan in PLANS.items():
        keyboard.append(
            [
                InlineKeyboardButton(
                    f"{plan['name']} - ৳{plan['price']}",
                    callback_data=f"plan_{plan_id}",
                )
            ]
        )

    keyboard.append(
        [
            InlineKeyboardButton(
                "⬅️ Back",
                callback_data="home",
            )
        ]
    )

    return InlineKeyboardMarkup(keyboard)


# ============================================================
# START
# ============================================================

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):

    user = update.effective_user

    save_user(user)

    text = (
        f"👋 Welcome {user.first_name}!\n\n"
        "🎬 Welcome to our Premium Membership Bot.\n\n"
        "Choose an option below:"
    )

    await update.message.reply_text(
        text,
        reply_markup=main_menu(),
    )


# ============================================================
# HELP
# ============================================================

async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):

    await update.message.reply_text(
        "Available commands:\n\n"
        "/start - Open bot\n"
        "/plans - Subscription plans\n"
        "/myplan - Check subscription\n"
        "/payment - Payment information\n"
        "/help - Help"
    )


# ============================================================
# PLANS COMMAND
# ============================================================

async def plans_command(update: Update, context: ContextTypes.DEFAULT_TYPE):

    await update.message.reply_text(
        "💎 Subscription Plans",
        reply_markup=plans_menu(),
    )


# ============================================================
# MY PLAN
# ============================================================

async def myplan_command(update: Update, context: ContextTypes.DEFAULT_TYPE):

    user = update.effective_user

    save_user(user)

    subscription = get_active_subscription(user.id)

    if not subscription:

        await update.message.reply_text(
            "❌ You don't have an active subscription.\n\n"
            "Use /plans to choose a plan."
        )

        return

    plan_id = subscription["plan"]

    plan = PLANS.get(plan_id)

    expiry = subscription["expiry"]

    await update.message.reply_text(
        f"💎 Your Subscription\n\n"
        f"Plan: {plan['name']}\n"
        f"Price: ৳{plan['price']}\n"
        f"Expires: {expiry.strftime('%Y-%m-%d %H:%M UTC')}"
    )


# ============================================================
# PAYMENT COMMAND
# ============================================================

async def payment_command(update: Update, context: ContextTypes.DEFAULT_TYPE):

    await update.message.reply_text(
        "💳 Payment Methods\n\n"
        f"bKash: `{BKASH_NUMBER}`\n"
        f"Nagad: `{NAGAD_NUMBER}`\n\n"
        "After payment, press the Payment button and submit:\n\n"
        "1. Your selected plan\n"
        "2. Transaction ID\n\n"
        "Your payment will be manually verified by admin.",
        parse_mode="Markdown",
        reply_markup=main_menu(),
    )


# ============================================================
# CALLBACK HANDLER
# ============================================================

async def callback_handler(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
):

    query = update.callback_query

    await query.answer()

    user = query.from_user

    save_user(user)

    data = query.data

    # --------------------------------------------------------
    # HOME
    # --------------------------------------------------------

    if data == "home":

        await query.edit_message_text(
            "🏠 Main Menu",
            reply_markup=main_menu(),
        )

        return

    # --------------------------------------------------------
    # PLANS
    # --------------------------------------------------------

    if data == "plans":

        await query.edit_message_text(
            "💎 Choose your subscription plan:",
            reply_markup=plans_menu(),
        )

        return

    # --------------------------------------------------------
    # SELECT PLAN
    # --------------------------------------------------------

    if data.startswith("plan_"):

        plan_id = data.replace("plan_", "")

        if plan_id not in PLANS:
            return

        plan = PLANS[plan_id]

        features = "\n".join(
            f"✅ {feature}"
            for feature in plan["features"]
        )

        keyboard = [
            [
                InlineKeyboardButton(
                    "💳 Buy This Plan",
                    callback_data=f"buy_{plan_id}",
                )
            ],
            [
                InlineKeyboardButton(
                    "⬅️ Back",
                    callback_data="plans",
                )
            ],
        ]

        await query.edit_message_text(
            f"💎 {plan['name']}\n\n"
            f"💰 Price: ৳{plan['price']}\n"
            f"📅 Duration: {plan['days']} days\n\n"
            f"Features:\n{features}",
            reply_markup=InlineKeyboardMarkup(keyboard),
        )

        return

    # --------------------------------------------------------
    # BUY PLAN
    # --------------------------------------------------------

    if data.startswith("buy_"):

        plan_id = data.replace("buy_", "")

        if plan_id not in PLANS:
            return

        plan = PLANS[plan_id]

        context.user_data["selected_plan"] = plan_id

        await query.edit_message_text(
            f"💳 Payment for {plan['name']}\n\n"
            f"Amount: ৳{plan['price']}\n\n"
            f"bKash: `{BKASH_NUMBER}`\n"
            f"Nagad: `{NAGAD_NUMBER}`\n\n"
            "After sending the money, send your "
            "transaction ID in the format:\n\n"
            "`TXID YOUR_TRANSACTION_ID`\n\n"
            "Example:\n"
            "`TXID 9A8B7C6D`",
            parse_mode="Markdown",
        )

        return

    # --------------------------------------------------------
    # PAYMENT BUTTON
    # --------------------------------------------------------

    if data == "payment":

        await query.edit_message_text(
            "💳 Payment\n\n"
            f"bKash: `{BKASH_NUMBER}`\n"
            f"Nagad: `{NAGAD_NUMBER}`\n\n"
            "Choose a plan first, then send:\n\n"
            "`TXID YOUR_TRANSACTION_ID`",
            parse_mode="Markdown",
            reply_markup=plans_menu(),
        )

        return

    # --------------------------------------------------------
    # MY SUBSCRIPTION
    # --------------------------------------------------------

    if data == "my_subscription":

        subscription = get_active_subscription(user.id)

        if not subscription:

            await query.edit_message_text(
                "❌ No active subscription.\n\n"
                "Choose a plan to subscribe.",
                reply_markup=plans_menu(),
            )

            return

        plan = PLANS[subscription["plan"]]

        expiry = subscription["expiry"]

        await query.edit_message_text(
            f"💎 Active Subscription\n\n"
            f"Plan: {plan['name']}\n"
            f"Price: ৳{plan['price']}\n"
            f"Expires: {expiry.strftime('%Y-%m-%d %H:%M UTC')}",
            reply_markup=main_menu(),
        )

        return

    # --------------------------------------------------------
    # SUPPORT
    # --------------------------------------------------------

    if data == "support":

        await query.edit_message_text(
            "📞 Support\n\n"
            "If you have a payment or subscription problem, "
            "contact the administrator.",
            reply_markup=main_menu(),
        )

        return


# ============================================================
# TRANSACTION ID HANDLER
# ============================================================

async def transaction_handler(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
):

    user = update.effective_user

    save_user(user)

    text = update.message.text.strip()

    if not text.upper().startswith("TXID "):

        await update.message.reply_text(
            "❌ Invalid format.\n\n"
            "Please send:\n"
            "`TXID YOUR_TRANSACTION_ID`\n\n"
            "Example:\n"
            "`TXID 9A8B7C6D`",
            parse_mode="Markdown",
        )

        return

    txid = text[5:].strip()

    if not txid:

        await update.message.reply_text(
            "❌ Transaction ID cannot be empty."
        )

        return

    plan_id = context.user_data.get("selected_plan")

    if not plan_id:

        await update.message.reply_text(
            "❌ Please select a subscription plan first.",
            reply_markup=plans_menu(),
        )

        return

    plan = PLANS[plan_id]

    # Check duplicate transaction
    existing = (
        db.collection("payments")
        .where("transaction_id", "==", txid)
        .limit(1)
        .stream()
    )

    for doc in existing:

        await update.message.reply_text(
            "❌ This transaction ID has already been submitted."
        )

        return

    payment_data = {
        "user_id": user.id,
        "username": user.username or "",
        "first_name": user.first_name or "",
        "plan_id": plan_id,
        "plan_name": plan["name"],
        "amount": plan["price"],
        "transaction_id": txid,
        "status": "pending",
        "created_at": firestore.SERVER_TIMESTAMP,
    }

    payment_document = db.collection("payments").document()

    payment_document.set(payment_data)

    payment_id = payment_document.id

    await update.message.reply_text(
        "✅ Payment submitted!\n\n"
        f"Plan: {plan['name']}\n"
        f"Amount: ৳{plan['price']}\n"
        f"Transaction ID: {txid}\n\n"
        "⏳ Waiting for admin approval."
    )

    # Notify admin
    keyboard = [
        [
            InlineKeyboardButton(
                "✅ APPROVE",
                callback_data=f"approve_{payment_id}",
            ),
            InlineKeyboardButton(
                "❌ REJECT",
                callback_data=f"reject_{payment_id}",
            ),
        ]
    ]

    await context.bot.send_message(
        chat_id=ADMIN_ID,
        text=(
            "🔔 NEW PAYMENT\n\n"
            f"👤 User: {user.first_name}\n"
            f"🆔 User ID: {user.id}\n"
            f"👤 Username: @{user.username or 'None'}\n\n"
            f"💎 Plan: {plan['name']}\n"
            f"💰 Amount: ৳{plan['price']}\n"
            f"🧾 TXID: {txid}\n\n"
            "Choose an action:"
        ),
        reply_markup=InlineKeyboardMarkup(keyboard),
    )


# ============================================================
# ADMIN APPROVAL / REJECTION
# ============================================================

async def admin_payment_handler(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
):

    query = update.callback_query

    await query.answer()

    if query.from_user.id != ADMIN_ID:

        await query.answer(
            "❌ You are not authorized.",
            show_alert=True,
        )

        return

    data = query.data

    if data.startswith("approve_"):

        payment_id = data.replace("approve_", "")

        doc_ref = payment_ref(payment_id)

        doc = doc_ref.get()

        if not doc.exists:

            await query.edit_message_text(
                "❌ Payment not found."
            )

            return

        payment = doc.to_dict()

        if payment.get("status") != "pending":

            await query.edit_message_text(
                "⚠️ This payment has already been processed."
            )

            return

        plan_id = payment["plan_id"]

        expiry = activate_subscription(
            payment["user_id"],
            plan_id,
        )

        doc_ref.update(
            {
                "status": "approved",
                "approved_at": firestore.SERVER_TIMESTAMP,
                "approved_by": ADMIN_ID,
            }
        )

        await query.edit_message_text(
            "✅ PAYMENT APPROVED\n\n"
            f"User ID: {payment['user_id']}\n"
            f"Plan: {payment['plan_name']}\n"
            f"Amount: ৳{payment['amount']}\n"
            f"TXID: {payment['transaction_id']}\n"
            f"Expires: {expiry.strftime('%Y-%m-%d %H:%M UTC')}"
        )

        try:

            await context.bot.send_message(
                chat_id=payment["user_id"],
                text=(
                    "🎉 Payment Approved!\n\n"
                    f"💎 Plan: {payment['plan_name']}\n"
                    f"💰 Amount: ৳{payment['amount']}\n\n"
                    "✅ Your subscription is now active.\n\n"
                    f"📅 Expires: "
                    f"{expiry.strftime('%Y-%m-%d %H:%M UTC')}"
                ),
            )

        except Exception as e:

            logger.error(
                "Could not notify user: %s",
                e,
            )

        return

    if data.startswith("reject_"):

        payment_id = data.replace("reject_", "")

        doc_ref = payment_ref(payment_id)

        doc = doc_ref.get()

        if not doc.exists:

            await query.edit_message_text(
                "❌ Payment not found."
            )

            return

        payment = doc.to_dict()

        if payment.get("status") != "pending":

            await query.edit_message_text(
                "⚠️ This payment has already been processed."
            )

            return

        doc_ref.update(
            {
                "status": "rejected",
                "rejected_at": firestore.SERVER_TIMESTAMP,
                "rejected_by": ADMIN_ID,
            }
        )

        await query.edit_message_text(
            "❌ PAYMENT REJECTED\n\n"
            f"User ID: {payment['user_id']}\n"
            f"Plan: {payment['plan_name']}\n"
            f"TXID: {payment['transaction_id']}"
        )

        try:

            await context.bot.send_message(
                chat_id=payment["user_id"],
                text=(
                    "❌ Payment Rejected.\n\n"
                    "Your transaction could not be verified.\n"
                    "Please contact admin/support."
                ),
            )

        except Exception as e:

            logger.error(
                "Could not notify user: %s",
                e,
            )


# ============================================================
# ERROR HANDLER
# ============================================================

async def error_handler(
    update: object,
    context: ContextTypes.DEFAULT_TYPE,
):

    logger.error(
        "Exception while handling update:",
        exc_info=context.error,
    )


# ============================================================
# MAIN
# ============================================================

def main():

    start_web_server()

    application = (
        Application.builder()
        .token(BOT_TOKEN)
        .build()
    )

    application.add_handler(
        CommandHandler("start", start)
    )

    application.add_handler(
        CommandHandler("help", help_command)
    )

    application.add_handler(
        CommandHandler("plans", plans_command)
    )

    application.add_handler(
        CommandHandler("myplan", myplan_command)
    )

    application.add_handler(
        CommandHandler("payment", payment_command)
    )

    application.add_handler(
        CallbackQueryHandler(
            admin_payment_handler,
            pattern=r"^(approve_|reject_)",
        )
    )

    application.add_handler(
        CallbackQueryHandler(
            callback_handler
        )
    )

    application.add_handler(
        MessageHandler(
            filters.TEXT & ~filters.COMMAND,
            transaction_handler,
        )
    )

    application.add_error_handler(error_handler)

    logger.info("Bot started.")

    application.run_polling(
        allowed_updates=Update.ALL_TYPES
    )


if __name__ == "__main__":
    main()
