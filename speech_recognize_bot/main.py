import logging
from pathlib import Path
from aiogram import Bot, Dispatcher, types
from aiogram.filters import Command
from aiogram.types import FSInputFile
from tasks.process_media_task import process_media
import asyncio
import ffmpeg
import os
from gtts import gTTS

from env import TOKEN_KEY, FOLDER_PATH, RESULT_PATH

logging.basicConfig(level=logging.INFO)

bot = Bot(token=TOKEN_KEY)
dp = Dispatcher()

TEMP_DIR = Path(FOLDER_PATH)
RESULTS_DIR = Path(RESULT_PATH)
TEMP_DIR.mkdir(exist_ok=True)
RESULTS_DIR.mkdir(exist_ok=True)

async def check_results_periodically():
    """Периодическая проверка результатов"""
    while True:
        for result_file in RESULTS_DIR.glob("*.txt"):
            try:
                parts = result_file.stem.split("_")
                if len(parts) == 2:
                    user_id, task_id = int(parts[0]), parts[1]
                    
                    with open(result_file, "r", encoding="utf-8") as f:
                        text = f.read()
                        print(text)
                    
                    await bot.send_message(user_id, f"Результат обработки:\n{text}")
                    result_file.unlink()
                    
            except Exception as e:
                logging.error(f"Ошибка обработки файла {result_file}: {str(e)}")
        
        await asyncio.sleep(1)

@dp.message(Command("start"))
async def cmd_start(message: types.Message):
    await message.answer("Привет! Отправь мне аудио или видео сообщение, и я преобразую его в текст.")

def convert_media(input_file, output_file):
    (
        ffmpeg
        .input(input_file)
        .output(output_file, acodec='pcm_s16le', ar=16000, format='wav')
        .run(overwrite_output=True)
    )

@dp.message(lambda message: message.audio or message.voice)
async def handle_audio(message: types.Message):
    file_id = message.audio.file_id if message.audio else message.voice.file_id
    file = await bot.get_file(file_id)
    input_file = TEMP_DIR / f"audio_{message.message_id}.ogg"
    output_file = TEMP_DIR / f"audio_{message.message_id}.wav"

    await bot.download_file(file.file_path, destination=input_file)

    try:
        convert_media(str(input_file), str(output_file))
    except Exception as e:
        logging.error(f"Ошибка конвертации: {str(e)}")
        await message.answer("❌ Произошла ошибка при обработке файла.")
        return

    task = process_media.delay(
        str(output_file),
        message.from_user.id,
        task_id=str(message.message_id)
    )
    await message.answer(f"✅ Аудио принято. Ожидайте результат!")
    
@dp.message(Command("tts"))
async def text_to_speech(message: types.Message):
    text = message.text.split(maxsplit=1)[1] if len(message.text.split()) > 1 else ""
    if not text:
        await message.answer("Пожалуйста, укажите текст для преобразования.")
        return

    try:
        tts = gTTS(text=text, lang="ru")
        audio_file = TEMP_DIR / f"tts_{message.message_id}.mp3"
        tts.save(audio_file)

        voice_file = FSInputFile(audio_file)
        await bot.send_voice(chat_id=message.chat.id, voice=voice_file)

        os.remove(audio_file)

    except Exception as e:
        logging.error(f"Ошибка при создании голосового сообщения: {str(e)}")
        await message.answer("Произошла ошибка при создании голосового сообщения.")

@dp.message(lambda message: message.video or message.video_note)
async def handle_video(message: types.Message):
    file_id = message.video.file_id if message.video else message.video_note.file_id
    file = await bot.get_file(file_id)
    file_path = TEMP_DIR / f"video_{message.message_id}.mp4"
    await bot.download_file(file.file_path, destination=file_path)
    
    task = process_media.delay(
        str(file_path),
        message.from_user.id,
        task_id=str(message.message_id),
        is_video=True
    )
    await message.answer(f"🎥 Видео принято. Ожидайте результат!")

async def main():
    asyncio.create_task(check_results_periodically())
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())