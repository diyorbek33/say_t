import json
import random
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

# Conversation states
ANSWERING = 1


def get_session_questions():
    return random.sample(ALL_QUESTIONS, min(QUESTIONS_PER_SESSION, len(ALL_QUESTIONS)))


def shuffle_answers(q):
    answers = q["answers"][:]
    random.shuffle(answers)
    return answers, q["correct"]


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
        # retry phase — current question is always retry_queue[0]
        q = data["retry_queue"][0]
        total = data["retry_total"]
        done = total - len(data["retry_queue"])
        prefix = f"🔄 Xato savol {done + 1}/{total} (qayta)"

    answers, correct = shuffle_answers(q)
    data["current_correct"] = correct
    data["current_answers"] = answers

    keyboard = [[a] for a in answers]
    reply_markup = ReplyKeyboardMarkup(keyboard, one_time_keyboard=True, resize_keyboard=True)

    await update.message.reply_text(
        f"{prefix}\n\n❓ {q['question']}",
        reply_markup=reply_markup
    )


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data.clear()
    await update.message.reply_text(
        "👋 Salom! Bu dasturlash bo'yicha test boti.\n\n"
        "📌 30 ta tasodifiy savol beriladi.\n"
        "📊 Oxirida nechta to'g'ri javob berganligi ko'rsatiladi.\n"
        "🔄 Xato qilgan savollar qayta takrorlanadi — to'g'ri javob berguncha!\n\n"
        "▶️ Boshlash: /quiz\n"
        "⏹ To'xtatish: /stop"
    )


async def quiz(update: Update, context: ContextTypes.DEFAULT_TYPE):
    questions = get_session_questions()
    context.user_data.clear()
    context.user_data["questions"] = questions
    context.user_data["index"] = 0
    context.user_data["correct_count"] = 0
    context.user_data["wrong"] = []
    context.user_data["phase"] = "main"
    context.user_data["retry_queue"] = []
    context.user_data["retry_total"] = 0
    context.user_data["current_correct"] = None
    context.user_data["current_answers"] = []

    await update.message.reply_text(
        f"🚀 Test boshlanmoqda! {len(questions)} ta savol.\n"
        f"⏹ To'xtatish uchun /stop",
        reply_markup=ReplyKeyboardRemove()
    )
    await send_question(update, context)
    return ANSWERING


async def handle_answer(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_answer = update.message.text.strip()
    data = context.user_data

    # Safety check — if no active question
    if not data.get("current_correct"):
        await update.message.reply_text("Test boshlash uchun /quiz yozing.")
        return ConversationHandler.END

    correct = data["current_correct"]
    answers = data["current_answers"]
    phase = data["phase"]

    # Must be one of the shown options
    if user_answer not in answers:
        await update.message.reply_text("⚠️ Iltimos, quyidagi variantlardan birini tanlang.")
        return ANSWERING

    # ── CORRECT ANSWER ──────────────────────────────────────────────────────────
    if user_answer == correct:
        await update.message.reply_text("✅ To'g'ri!")

        if phase == "main":
            data["correct_count"] += 1
            data["index"] += 1

            if data["index"] >= len(data["questions"]):
                return await finish_main(update, context)
            else:
                await send_question(update, context)
                return ANSWERING

        else:  # retry phase
            # Remove the successfully answered question from the front
            data["retry_queue"].pop(0)

            if len(data["retry_queue"]) == 0:
                # All retry questions solved!
                await update.message.reply_text(
                    "🎉 Barcha xato savollarni to'g'ri yechdiniz! Ajoyib!\n\n"
                    "Yangi test uchun /quiz yozing.",
                    reply_markup=ReplyKeyboardRemove()
                )
                data.clear()
                return ConversationHandler.END
            else:
                await send_question(update, context)
                return ANSWERING

    # ── WRONG ANSWER ────────────────────────────────────────────────────────────
    else:
        await update.message.reply_text(
            f"❌ Noto'g'ri!\n✅ To'g'ri javob: {correct}"
        )

        if phase == "main":
            q = data["questions"][data["index"]]
            # Add to wrong list (avoid duplicates)
            if q not in data["wrong"]:
                data["wrong"].append(q)
            data["index"] += 1

            if data["index"] >= len(data["questions"]):
                return await finish_main(update, context)
            else:
                await send_question(update, context)
                return ANSWERING

        else:  # retry phase
            # Move the failed question to the END of retry_queue
            q = data["retry_queue"].pop(0)
            data["retry_queue"].append(q)
            await update.message.reply_text("📌 Bu savol oxiriga surildi, qayta keladi.")
            await send_question(update, context)
            return ANSWERING


async def finish_main(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Called when main 30 questions are done. Show stats, then start retry if needed."""
    data = context.user_data
    total = len(data["questions"])
    correct_count = data["correct_count"]
    wrong_list = data["wrong"]
    wrong_count = len(wrong_list)
    percent = round(correct_count / total * 100)

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
        f"✅ To'g'ri javoblar: {correct_count}/{total} ({percent}%)\n"
        f"❌ Xato javoblar: {wrong_count}/{total}"
    )

    if wrong_count == 0:
        text += "\n\n🎉 Barcha savollar to'g'ri! Mukammal natija!"
        await update.message.reply_text(text, reply_markup=ReplyKeyboardRemove())
        await update.message.reply_text("Yangi test uchun /quiz yozing.")
        data.clear()
        return ConversationHandler.END
    else:
        text += (
            f"\n\n🔄 Endi {wrong_count} ta xato savol qayta takrorlanadi.\n"
            f"Har birini to'g'ri javob berguncha davom etadi!\n"
            f"⏹ To'xtatish: /stop"
        )
        await update.message.reply_text(text)

        # Switch to retry phase
        retry_queue = wrong_list[:]
        random.shuffle(retry_queue)
        data["phase"] = "retry"
        data["retry_queue"] = retry_queue
        data["retry_total"] = len(retry_queue)

        await send_question(update, context)
        return ANSWERING   # ← KEY FIX: must stay in ANSWERING state


async def stop(update: Update, context: ContextTypes.DEFAULT_TYPE):
    data = context.user_data

    # Show partial stats if quiz was running
    if data.get("phase") == "main" and data.get("questions"):
        total = len(data["questions"])
        correct_count = data.get("correct_count", 0)
        answered = data.get("index", 0)
        msg = (
            f"⏹ Test to'xtatildi.\n\n"
            f"📊 Natija: {correct_count}/{answered} savol to'g'ri ({answered}/{total} javoblandi)\n\n"
            f"Yangi test uchun /quiz yozing."
        )
    elif data.get("phase") == "retry":
        remaining = len(data.get("retry_queue", []))
        total = data.get("retry_total", 0)
        done = total - remaining
        msg = (
            f"⏹ Takrorlash to'xtatildi.\n\n"
            f"📊 {done}/{total} xato savol yechildi\n\n"
            f"Yangi test uchun /quiz yozing."
        )
    else:
        msg = "⏹ To'xtatildi.\n\nBoshlash uchun /quiz yozing."

    data.clear()
    await update.message.reply_text(msg, reply_markup=ReplyKeyboardRemove())
    return ConversationHandler.END


async def cancel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    return await stop(update, context)


def main():
    token = os.environ.get("BOT_TOKEN")
    if not token:
        raise ValueError("BOT_TOKEN muhit o'zgaruvchisi o'rnatilmagan!\n"
                         "Ishga tushirish: BOT_TOKEN='tokeningiz' python bot.py")

    app = Application.builder().token(token).build()

    conv_handler = ConversationHandler(
        entry_points=[CommandHandler("quiz", quiz)],
        states={
            ANSWERING: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, handle_answer)
            ],
        },
        fallbacks=[
            CommandHandler("stop", stop),
            CommandHandler("cancel", cancel),
            CommandHandler("quiz", quiz),  # restart mid-quiz
        ],
    )

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("stop", stop))  # also outside conversation
    app.add_handler(conv_handler)

    print("✅ Bot ishga tushdi!")
    app.run_polling()


if __name__ == "__main__":
    main()
