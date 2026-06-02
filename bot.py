import json
import random
import asyncio
import os
from telegram import Update, ReplyKeyboardMarkup, ReplyKeyboardRemove
from telegram.ext import (
    Application, CommandHandler, MessageHandler,
    filters, ContextTypes, ConversationHandler
)

# Load questions
with open("questions.json", "r", encoding="utf-8") as f:
    ALL_QUESTIONS = json.load(f)

QUESTIONS_PER_SESSION = 30

# States
ANSWERING = 1
RETRY_ANSWERING = 2

def get_session_questions():
    """Pick 30 random questions"""
    return random.sample(ALL_QUESTIONS, min(QUESTIONS_PER_SESSION, len(ALL_QUESTIONS)))

def shuffle_answers(q):
    """Return answers in random order, and the correct answer text"""
    answers = q["answers"][:]
    random.shuffle(answers)
    return answers, q["correct"]

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data.clear()
    await update.message.reply_text(
        "👋 Salom! Bu dasturlash bo'yicha test boti.\n\n"
        "30 ta tasodifiy savol beriladi.\n"
        "Oxirida nechta to'g'ri javob berganligi ko'rsatiladi.\n"
        "Xato qilgan savollar qayta takrorlanadi — javobni yodlab olguncha!\n\n"
        "Boshlash uchun /quiz yozing."
    )

async def quiz(update: Update, context: ContextTypes.DEFAULT_TYPE):
    questions = get_session_questions()
    context.user_data["questions"] = questions
    context.user_data["index"] = 0
    context.user_data["correct_count"] = 0
    context.user_data["wrong"] = []      # questions answered wrong
    context.user_data["phase"] = "main"  # main or retry
    context.user_data["retry_index"] = 0
    context.user_data["retry_wrong"] = []

    await update.message.reply_text(
        f"🚀 Test boshlanmoqda! {len(questions)} ta savol.\n\nHar bir savolda 4 ta variant beriladi.",
        reply_markup=ReplyKeyboardRemove()
    )
    await send_question(update, context)
    return ANSWERING

async def send_question(update: Update, context: ContextTypes.DEFAULT_TYPE):
    data = context.user_data
    phase = data["phase"]

    if phase == "main":
        questions = data["questions"]
        idx = data["index"]
        total = len(questions)
        q = questions[idx]
        prefix = f"📝 Savol {idx + 1}/{total}"
    else:
        questions = data["retry_wrong"]
        idx = data["retry_index"]
        total = len(questions)
        q = questions[idx]
        prefix = f"🔄 Xato savol {idx + 1}/{total} (qayta)"

    answers, correct = shuffle_answers(q)
    data["current_correct"] = correct
    data["current_answers"] = answers

    keyboard = [[a] for a in answers]
    reply_markup = ReplyKeyboardMarkup(keyboard, one_time_keyboard=True, resize_keyboard=True)

    await update.message.reply_text(
        f"{prefix}\n\n❓ {q['question']}",
        reply_markup=reply_markup
    )

async def handle_answer(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_answer = update.message.text.strip()
    data = context.user_data
    phase = data["phase"]
    correct = data["current_correct"]
    answers = data["current_answers"]

    # Validate it's one of the options
    if user_answer not in answers:
        await update.message.reply_text("⚠️ Iltimos, quyidagi variantlardan birini tanlang.")
        return ANSWERING

    if user_answer == correct:
        await update.message.reply_text("✅ To'g'ri!")
        if phase == "main":
            data["correct_count"] += 1
            data["index"] += 1
            if data["index"] >= len(data["questions"]):
                # Main phase done — check if there are mistakes
                await finish_main(update, context)
                return ConversationHandler.END
            else:
                await send_question(update, context)
                return ANSWERING
        else:
            # Retry phase
            data["retry_index"] += 1
            if data["retry_index"] >= len(data["retry_wrong"]):
                # All retries passed
                await update.message.reply_text(
                    "🎉 Barcha xato savollarni to'g'ri yechdiniz! Tabriklaymiz!\n\n"
                    "Yangi test uchun /quiz yozing.",
                    reply_markup=ReplyKeyboardRemove()
                )
                return ConversationHandler.END
            else:
                await send_question(update, context)
                return ANSWERING
    else:
        await update.message.reply_text(
            f"❌ Noto'g'ri!\n✅ To'g'ri javob: {correct}"
        )
        if phase == "main":
            q = data["questions"][data["index"]]
            if q not in data["wrong"]:
                data["wrong"].append(q)
            data["index"] += 1
            if data["index"] >= len(data["questions"]):
                await finish_main(update, context)
                return ConversationHandler.END
            else:
                await send_question(update, context)
                return ANSWERING
        else:
            # Wrong in retry — keep this question in retry_wrong for next round
            q = data["retry_wrong"][data["retry_index"]]
            data["retry_wrong"].pop(data["retry_index"])
            data["retry_wrong"].append(q)  # move to end
            # Don't increment index since we removed current and added to end
            # But avoid infinite loop if only 1 left
            if len(data["retry_wrong"]) == 1:
                pass  # same question again
            await update.message.reply_text("📌 Bu savol yana takrorlanadi.")
            await send_question(update, context)
            return ANSWERING

async def finish_main(update: Update, context: ContextTypes.DEFAULT_TYPE):
    data = context.user_data
    total = len(data["questions"])
    correct = data["correct_count"]
    wrong_count = len(data["wrong"])

    percent = round(correct / total * 100)
    if percent >= 90:
        emoji = "🏆"
    elif percent >= 70:
        emoji = "👍"
    elif percent >= 50:
        emoji = "😐"
    else:
        emoji = "😢"

    text = (
        f"{emoji} Test yakunlandi!\n\n"
        f"✅ To'g'ri javoblar: {correct}/{total} ({percent}%)\n"
        f"❌ Xato javoblar: {wrong_count}/{total}"
    )

    if wrong_count == 0:
        text += "\n\n🎉 Barcha savollar to'g'ri! Ajoyib natija!"
        await update.message.reply_text(text, reply_markup=ReplyKeyboardRemove())
        await update.message.reply_text("Yangi test uchun /quiz yozing.")
    else:
        text += f"\n\n🔄 Endi {wrong_count} ta xato savol qayta takrorlanadi.\nJavobni yodlab olguncha davom etadi!"
        await update.message.reply_text(text)
        # Start retry phase
        data["phase"] = "retry"
        data["retry_wrong"] = data["wrong"][:]
        random.shuffle(data["retry_wrong"])
        data["retry_index"] = 0
        await send_question(update, context)

async def cancel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data.clear()
    await update.message.reply_text(
        "❌ Test bekor qilindi. Qayta boshlash uchun /quiz yozing.",
        reply_markup=ReplyKeyboardRemove()
    )
    return ConversationHandler.END

def main():
    token = os.environ.get("BOT_TOKEN")
    if not token:
        raise ValueError("BOT_TOKEN environment variable not set!")

    app = Application.builder().token(token).build()

    conv_handler = ConversationHandler(
        entry_points=[CommandHandler("quiz", quiz)],
        states={
            ANSWERING: [MessageHandler(filters.TEXT & ~filters.COMMAND, handle_answer)],
        },
        fallbacks=[CommandHandler("cancel", cancel)],
    )

    app.add_handler(CommandHandler("start", start))
    app.add_handler(conv_handler)

    print("Bot started!")
    app.run_polling()

if __name__ == "__main__":
    main()
