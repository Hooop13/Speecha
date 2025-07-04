import os
from dotenv import load_dotenv

# === Загрузка переменных из .env ===
load_dotenv("api.env")

TELEGRAM_TOKEN = os.getenv("API_TOKEN")
OPENAI_KEY = os.getenv("OPENAI_API_KEY")
AZURE_KEY = os.getenv("AZURE_KEY")
AZURE_REGION = os.getenv("AZURE_REGION")

import asyncio
import openai
import datetime
import speech_recognition as sr
from pydub import AudioSegment

from dotenv import load_dotenv

from aiogram import Bot, Dispatcher, types, F
from aiogram.types import (
    Message,
    CallbackQuery,
    ReplyKeyboardMarkup,
    KeyboardButton,
    InlineKeyboardMarkup,
    InlineKeyboardButton,
)
from aiogram.filters import CommandStart
from aiogram.enums import ParseMode
from aiogram.client.default import DefaultBotProperties

# === Загрузка токена ===
load_dotenv("api.env")
API_TOKEN = os.getenv("API_TOKEN")
if not API_TOKEN:
    raise ValueError("❌ Токен не найден. Проверь файл api.env")

# === Инициализация бота ===
bot = Bot(token=API_TOKEN, default=DefaultBotProperties(parse_mode=ParseMode.HTML))
dp = Dispatcher()

# === Список языков ===
LANGUAGES = [
    ("🇷🇺 Русский", "ru-RU"),
    ("🇬🇧 English", "en-US"),
    ("🇨🇳 中文", "zh-CN"),
    ("🇰🇿 Қазақша", "kk-KZ"),
]

# === Персональные языковые настройки ===
user_languages = {}  # user_id -> {from: index, to: index}
user_states = {}        # user_id -> str (например, "recording", "idle") Это состояние пользователя
recording_tasks = {}    # user_id -> asyncio.Task Запись звука и мигание
user_last_message = {}      # user_id -> Message

# === Главная клавиатура ===
def get_main_menu(user_id: int):
    langs = user_languages.get(user_id, {"from": 0, "to": 1})
    from_lang = LANGUAGES[langs["from"]][0]
    to_lang = LANGUAGES[langs["to"]][0]
    
    return ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text=f"👂 Я говорю на: {from_lang}"),
             KeyboardButton(text=f"🗣 Переводить на: {to_lang}")],
            [KeyboardButton(text="🔁 Поменять местами")],
            [KeyboardButton(text="🔁 Перевести"), KeyboardButton(text="ℹ️ Инструкция")]
        ],
        resize_keyboard=True
    )

# === Вспомогательная функция ===
def detect_lang(text):
    try:
        return detect(text)
    except:
        return "unknown"

# === Функция перевод через Chat GPT ===    
def translate_chatgpt(text, lang_from, lang_to):
    prompt = f"Переведи с {lang_from} на {lang_to}: {text}"
    try:
        client = openai.OpenAI(api_key=OPENAI_KEY)
        response = client.chat.completions.create(
            model="gpt-3.5-turbo",
            messages=[{"role": "user", "content": prompt}]
        )
        return response.choices[0].message.content.strip()
    except Exception as e:
        return f"❌ Ошибка перевода: {e}"

# === Загрузка звукового сообщения ===
async def download_voice(file_id, user_id):
    file = await bot.get_file(file_id)
    file_path = file.file_path
    ogg_path = f"records/voice_{user_id}_{datetime.datetime.now().strftime('%Y%m%d_%H%M%S')}.ogg"
    await bot.download_file(file_path, ogg_path)
    return ogg_path

# === Распознавание речи ===
def speech_to_text(ogg_path, lang_code):
    try:
        audio = AudioSegment.from_file(ogg_path)
        wav_path = ogg_path.replace(".ogg", ".wav")
        audio.export(wav_path, format="wav")

        recognizer = sr.Recognizer()
        with sr.AudioFile(wav_path) as source:
            audio_data = recognizer.record(source)

        # language=lang_code теперь это уже готовый вид, например "ru-RU"
        text = recognizer.recognize_google(audio_data, language=lang_code)
        return text, lang_code
    except Exception as e:
        return f"❌ Ошибка распознавания: {e}", "unknown"

# === Озвучка Azure ===    
def synthesize_azure(text, lang_code):
    try:
        import azure.cognitiveservices.speech as speechsdk
        import datetime
        import os

        # Конфигурация синтеза
        speech_config = speechsdk.SpeechConfig(subscription=AZURE_KEY, region=AZURE_REGION)
        speech_config.speech_synthesis_language = lang_code  # Прямо передаём из LANGUAGES
        speech_config.set_speech_synthesis_output_format(
            speechsdk.SpeechSynthesisOutputFormat.Ogg16Khz16BitMonoOpus
        )

        # Формируем путь к аудиофайлу
        filename = f"azure_{datetime.datetime.now().strftime('%Y%m%d_%H%M%S')}.ogg"
        audio_path = os.path.join("records", filename)
        audio_output = speechsdk.audio.AudioOutputConfig(filename=audio_path)

        # Синтез
        synthesizer = speechsdk.SpeechSynthesizer(speech_config=speech_config, audio_config=audio_output)
        result = synthesizer.speak_text_async(text).get()

        if result.reason == speechsdk.ResultReason.SynthesizingAudioCompleted:
            return audio_path
        else:
            print("❌ Azure TTS не выполнился:", result.reason)
            return None

    except Exception as e:
        print("❌ Ошибка Azure TTS:", e)
        return None
  
# === Инлайн клавиатура для выбора языка ===
def get_language_inline_keyboard(prefix: str):
    return InlineKeyboardMarkup(
        inline_keyboard=[
            *[
                [InlineKeyboardButton(text=name, callback_data=f"{prefix}_{i}")]
                for i, (name, code) in enumerate(LANGUAGES)
            ],
            [InlineKeyboardButton(text="❌ Отмена", callback_data="cancel_lang")]
        ]
    )

# === Команда /start ===
@dp.message(CommandStart())
async def start_handler(message: Message):
    user_id = message.from_user.id
    if user_id not in user_languages:
        user_languages[user_id] = {"from": 0, "to": 1}
    await message.answer(
    "👋 Привет! Я Speecha — голосовой переводчик.\n\n"
    "⚙️ Выберите языки для перевода и озвучивания.\n"
    "🎤 Отправьте голосовое сообщение или напишите текст.\n\n"
    "🔁 Затем нажмите Перевести.\n",
    reply_markup=get_main_menu(user_id)
)

# === Обработка кнопки "🔁 Перевести" ===
#@dp.message(F.text == "🔁 Перевести")
#async def handle_speak(message: Message):
#        await message.answer("Секунду, сейчас переведу и озвучу!")

# === Обработка кнопки "🔁 Перевести" ===
@dp.message(F.text == "🔁 Перевести")
async def handle_translate(message: Message):
    user_id = message.from_user.id
    last_msg = user_last_message.get(user_id)

    if not last_msg:
        await message.answer("❌ Нет сообщения для перевода. Отправьте текст или голос.")
        return

    langs = user_languages.get(user_id, {"from": 0, "to": 1})
    lang_from = LANGUAGES[langs["from"]][1]
    lang_to = LANGUAGES[langs["to"]][1]

    if last_msg.text:
        detected_lang = detect_lang(last_msg.text)
        if detected_lang == lang_to:
            await message.answer(f"🔁 Язык совпадает. Вот текст:\n<b>{last_msg.text}</b>")
            return

        translated = translate_chatgpt(last_msg.text, detected_lang, lang_to)
        await message.answer(f"<b>Перевод:</b> {translated}")

    elif last_msg.voice:
        ogg_path = await download_voice(last_msg.voice.file_id, user_id)
        recognized_text, lang_voice = speech_to_text(ogg_path, lang_from)

        if lang_voice == lang_to:
            await message.answer(f"🔁 Язык совпадает. Вы сказали:\n<b>{recognized_text}</b>")
            return

        translated = translate_chatgpt(recognized_text, lang_voice, lang_to)
        await message.answer(f"<i>Вы сказали:</i> {recognized_text}\n<b>Перевод:</b> {translated}")

        audio_path = synthesize_azure(translated, lang_to)

        if audio_path and os.path.exists(audio_path):
            await message.answer_voice(voice=types.FSInputFile(audio_path))
        else:
            await message.answer("❌ Ошибка озвучки. Файл не создан.")


# === Обработка кнопки "ℹ️ Инструкция" ===
@dp.message(F.text == "ℹ️ Инструкция")
async def handle_write(message: Message):
    user_id = message.from_user.id
    await message.answer(
    "👋 Привет! Я Speecha — голосовой переводчик.\n\n"
    "⚙️ Выберите языки для перевода и озвучивания.\n"
    "🎤 Отправьте голосовое сообщение или напишите текст.\n\n"
    "🔁 Затем нажмите Перевести.\n",
    reply_markup=get_main_menu(user_id)
    )

# === Обработка кнопки "Я говорю на" ===
@dp.message(F.text.startswith("👂 Я говорю на:"))
async def choose_from_lang(message: Message):
    await message.answer("Выберите язык, на котором вы говорите:", reply_markup=get_language_inline_keyboard("from"))

# === Обработка кнопки "Переводить на" ===
@dp.message(F.text.startswith("🗣 Переводить на:"))
async def choose_to_lang(message: Message):
    await message.answer("Выберите язык, на который переводить:", reply_markup=get_language_inline_keyboard("to"))

# === Обработка инлайн выбора языка ===
@dp.callback_query(F.data.startswith(("from_", "to_")))
async def set_language_callback(call: CallbackQuery):
    user_id = call.from_user.id
    langs = user_languages.get(user_id, {"from": 0, "to": 1})
    prefix, index = call.data.split("_")
    index = int(index)

    # Выбрали тот же язык — ничего не делаем
    if (prefix == "from" and index == langs["from"]) or (prefix == "to" and index == langs["to"]):
        await call.answer("⛔ Этот язык уже выбран.", show_alert=False)
        return

    if prefix == "from":
        # если совпадает с "to", заменить "to" на первый другой
        if index == langs["to"]:
            # Меняем местами
            langs["from"], langs["to"] = langs["to"], langs["from"]
        else:
            langs["from"] = index

    elif prefix == "to":
        if index == langs["from"]:
            langs["from"], langs["to"] = langs["to"], langs["from"]
        else:
            langs["to"] = index

    user_languages[user_id] = langs

    await call.message.delete()
    await call.message.answer("✅ Язык обновлён.", reply_markup=get_main_menu(user_id))

# === Поменять местами языки ===
@dp.message(F.text == "🔁 Поменять местами")
async def swap_languages(message: Message):
    user_id = message.from_user.id
    langs = user_languages.get(user_id, {"from": 0, "to": 1})
    langs["from"], langs["to"] = langs["to"], langs["from"]
    user_languages[user_id] = langs
    await message.answer("🔄 Языки поменялись местами", reply_markup=get_main_menu(user_id))

# === Обработка кнопки отмена ===
@dp.callback_query(F.data == "cancel_lang")
async def cancel_language_selection(call: CallbackQuery):
    await call.message.delete()
    await call.message.answer("❌ Отменено", reply_markup=get_main_menu(call.from_user.id))

# === Обработчик всех входящих сообщений ===
@dp.message()
async def catch_user_message(message: Message):
    if message.text in ["🔁 Перевести", "ℹ️ Инструкция", "🔁 Поменять местами"]:
        return  # не сохраняем команды
    user_last_message[message.from_user.id] = message

# === Запуск ===
async def main():
    print("✅ Бот запущен")
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
