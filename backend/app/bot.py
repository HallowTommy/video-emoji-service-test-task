import os
import asyncio
import tempfile

import aiohttp
from aiogram import Bot, Dispatcher, F
from aiogram.types import Message

BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
BACKEND_URL = os.getenv("BACKEND_URL", "http://backend:8000")

if not BOT_TOKEN:
  raise RuntimeError("TELEGRAM_BOT_TOKEN is not set")


bot = Bot(BOT_TOKEN)
dp = Dispatcher()


@dp.message(F.video | F.document)
async def handle_video(message: Message):
    file_obj = message.video or message.document

    # принимаем только mp4
    if getattr(file_obj, "mime_type", None) != "video/mp4":
        await message.answer("Пришлите, пожалуйста, видео в формате .mp4 🙂")
        return

    await message.answer("Обрабатываю видео, подождите немного…")

    # временные файлы для входа и выхода
    with tempfile.NamedTemporaryFile(suffix=".mp4") as tmp_in, \
         tempfile.NamedTemporaryFile(suffix=".mp4") as tmp_out:

        # скачиваем видео из Telegram
        file = await bot.get_file(file_obj.file_id)
        await bot.download_file(file, destination=tmp_in.name)

        # шлём в backend /api/add-emoji
        async with aiohttp.ClientSession() as session:
            with open(tmp_in.name, "rb") as f:
                form = aiohttp.FormData()
                form.add_field(
                    "file",
                    f,
                    filename="video.mp4",
                    content_type="video/mp4",
                )
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
                    tmp_out.write(await resp.read())
                    tmp_out.flush()

        # отправляем результат
        await message.answer_video(video=open(tmp_out.name, "rb"))


async def main():
    await dp.start_polling(bot)


if __name__ == "__main__":
    asyncio.run(main())
