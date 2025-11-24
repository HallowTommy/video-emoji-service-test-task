import os
import asyncio
import tempfile
from pathlib import Path
import mimetypes

import aiohttp
from aiogram import Bot, Dispatcher, F
from aiogram.types import Message, FSInputFile

BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
BACKEND_URL = os.getenv("BACKEND_URL", "http://backend:8000")

if not BOT_TOKEN:
    raise RuntimeError("TELEGRAM_BOT_TOKEN is not set")  # noqa

bot = Bot(BOT_TOKEN)
dp = Dispatcher()

# Простое хранилище состояния: user_id -> данные о видео
USER_VIDEOS: dict[int, dict] = {}


def _detect_extension_from_tg(file_obj) -> str:
    """Определяем расширение видео из имени или mime-типа."""
    name = getattr(file_obj, "file_name", "") or ""
    ext = Path(name).suffix.lower()
    if ext:
        return ext

    mime = getattr(file_obj, "mime_type", "") or ""
    if mime:
        guessed = mimetypes.guess_extension(mime)
        if guessed:
            return guessed

    return ".mp4"


@dp.message(F.text == "/start")
async def cmd_start(message: Message):
    await message.answer(
        "Привет! 👋\n\n"
        "1) Пришлите мне видеофайл.\n"
        "2) Затем — эмодзи, которое нужно добавить в центр видео."
    )


@dp.message(F.video | F.document)
async def handle_video(message: Message):
    file_obj = message.video or message.document

    mime = getattr(file_obj, "mime_type", "") or ""
    if not mime.startswith("video/"):
        await message.answer("Пришлите, пожалуйста, видеофайл (любой формат) 🙂")
        return

    ext = _detect_extension_from_tg(file_obj)
    suffix = ext or ".mp4"

    # создаём временный файл, который НЕ удалится автоматически
    fd, tmp_in_path = tempfile.mkstemp(suffix=suffix)
    os.close(fd)

    try:
        # скачиваем видео из Telegram
        tg_file = await bot.get_file(file_obj.file_id)
        # важно: передаём file_path, а не объект File
        await bot.download_file(tg_file.file_path, destination=tmp_in_path)
    except Exception as e:
        print("DOWNLOAD ERROR:", repr(e))
        if os.path.exists(tmp_in_path):
            os.remove(tmp_in_path)
        await message.answer("Не удалось скачать видео, попробуйте ещё раз.")
        return

    # сохраняем состояние для пользователя
    USER_VIDEOS[message.from_user.id] = {
        "path": tmp_in_path,
        "mime": mime,
        "suffix": suffix,
    }

    await message.answer(
        "Видео получил ✅\n"
        "Теперь отправьте эмодзи (один смайлик), который добавить в центр видео."
    )


@dp.message(F.text)
async def handle_emoji(message: Message):
    state = USER_VIDEOS.get(message.from_user.id)
    if not state:
        await message.answer("Сначала пришлите видео, потом эмодзи 🙂")
        return

    emoji_text = (message.text or "").strip()
    if not emoji_text:
        await message.answer("Отправьте эмодзи, которое нужно добавить на видео.")
        return

    await message.answer("Обрабатываю видео, подождите немного…")

    tmp_in_path = state["path"]
    mime = state["mime"]
    suffix = state["suffix"]

    # создаём временный файл для результата
    with tempfile.NamedTemporaryFile(suffix=suffix, delete=False) as tmp_out:
        tmp_out_path = tmp_out.name

    try:
        # отправляем исходное видео + эмодзи на backend
        async with aiohttp.ClientSession() as session:
            with open(tmp_in_path, "rb") as f:
                form = aiohttp.FormData()
                form.add_field(
                    "file",
                    f,
                    filename=f"video{suffix}",
                    content_type=mime or "application/octet-stream",
                )
                form.add_field("emoji", emoji_text)

                async with session.post(
                    f"{BACKEND_URL}/api/add-emoji",
                    data=form,
                ) as resp:
                    if resp.status != 200:
                        text = await resp.text()
                        await message.answer(
                            f"Ошибка при обработке видео 😕\n{resp.status}: {text}"
                        )
                        return

                    data = await resp.read()
                    with open(tmp_out_path, "wb") as out_f:
                        out_f.write(data)

        # отправляем результат пользователю
        video_file = FSInputFile(tmp_out_path)
        await message.answer_video(video=video_file)
    finally:
        # чистим временные файлы и состояние
        if os.path.exists(tmp_in_path):
            os.remove(tmp_in_path)
        if os.path.exists(tmp_out_path):
            os.remove(tmp_out_path)
        USER_VIDEOS.pop(message.from_user.id, None)


async def main():
    await dp.start_polling(bot)


if __name__ == "__main__":
    asyncio.run(main())
