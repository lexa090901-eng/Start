import os
import logging
from pathlib import Path
from aiogram import Bot, Dispatcher, F
from aiogram.filters import CommandStart, Command
from aiogram.types import Message, CallbackQuery, LabeledPrice, InlineKeyboardMarkup, InlineKeyboardButton, PreCheckoutQuery, FSInputFile
from aiogram.utils.keyboard import InlineKeyboardBuilder
from aiogram.webhook.aiohttp_server import SimpleRequestHandler, setup_application
from aiohttp import web

logging.basicConfig(level=logging.INFO)
TOKEN = os.getenv('TELEGRAM_BOT_TOKEN', '').strip()
if not TOKEN:
    raise RuntimeError('Set TELEGRAM_BOT_TOKEN in environment variables. Never put it into public code.')

BASE = Path(__file__).parent
# Telegram Stars prices are in XTR, not rubles. Adjust only after deciding the final pricing.
PRODUCTS = {
    'posts': {'title': '30 готовых постов для Telegram', 'description': 'Набор шаблонов и постов для запуска канала.', 'stars': 99, 'file': BASE / 'products' / '30_posts_telegram.pdf'},
    'freelance': {'title': 'Фриланс: быстрый старт', 'description': 'Практический план первых шагов и поиск первых заказов.', 'stars': 149, 'file': BASE / 'products' / 'freelance_start.pdf'},
    'bundle': {'title': 'СТАРТ — полный комплект', 'description': 'Оба материала в одном комплекте.', 'stars': 199, 'file': BASE / 'products' / 'start_bundle.pdf'},
}

TERMS = (
    'Условия покупки СТАРТ\n\n'
    'Продукты являются цифровыми материалами и выдаются в электронном виде после подтверждённой оплаты. '
    'Перед оплатой проверьте название и описание продукта. Если файл не пришёл или возникла проблема с оплатой, '
    'напишите через /support. Не отправляйте в чат данные банковской карты, пароли или коды. '
    'Покупатель отвечает за соблюдение применимого законодательства. Условия возврата и обязательные сведения о продавце '
    'нужно дополнить до запуска продаж в соответствии с требованиями, применимыми к продавцу и покупателю.'
)
SUPPORT = 'Поддержка СТАРТ: опишите проблему одним сообщением. Не присылайте данные карты, пароли или одноразовые коды. Для возврата/вопроса по платежу укажите дату, название продукта и Telegram ID платежа, если он есть.'


def main_menu():
    kb = InlineKeyboardBuilder()
    for key, p in PRODUCTS.items():
        kb.button(text=f"{p['title']} — {p['stars']} ⭐", callback_data=f"buy:{key}")
    kb.button(text='📚 Бесплатный чек-лист', callback_data='free')
    kb.button(text='🌐 Сайт СТАРТ', url='https://headless-wbipkhvfryh-alexeyivolga09-140e.wix-site-host.com/')
    kb.button(text='Условия покупки', callback_data='terms')
    kb.adjust(1)
    return kb.as_markup()

bot = Bot(TOKEN)
dp = Dispatcher()

@dp.message(CommandStart())
async def start(message: Message):
    await message.answer(
        'Привет! Это СТАРТ — практические цифровые материалы для тех, кто осваивает Telegram и фриланс.\n\n'
        'Выбери материал ниже. Цифровые покупки внутри Telegram оплачиваются Telegram Stars (⭐). '
        'Перед запуском продаж владелец должен заполнить и проверить юридические сведения и условия.',
        reply_markup=main_menu()
    )

@dp.message(Command('terms'))
async def terms(message: Message):
    await message.answer(TERMS)

@dp.message(Command('support', 'paysupport'))
async def support(message: Message):
    await message.answer(SUPPORT)

@dp.callback_query(F.data == 'terms')
async def terms_button(call: CallbackQuery):
    await call.message.answer(TERMS)
    await call.answer()

@dp.callback_query(F.data == 'free')
async def free_checklist(call: CallbackQuery):
    await call.message.answer(
        'Бесплатный чек-лист для старта во фрилансе:\n'
        '1. Выбери одну услугу, которую реально можешь выполнить.\n'
        '2. Сделай 2–3 примера работ.\n'
        '3. Напиши короткое предложение: задача, результат, срок.\n'
        '4. Найди 10 потенциальных клиентов и отправь персональное сообщение без спама.\n'
        '5. После каждого отклика улучшай портфолио и предложение.\n\n'
        'Не плати за обещания гарантированного заработка и не передавай незнакомым людям доступ к банку.'
    )
    await call.answer()

@dp.callback_query(F.data.startswith('buy:'))
async def buy(call: CallbackQuery):
    key = call.data.split(':', 1)[1]
    product = PRODUCTS.get(key)
    if not product:
        await call.answer('Товар не найден.', show_alert=True)
        return
    if not product['file'].exists():
        await call.answer('Файл продукта пока не установлен. Напишите в поддержку.', show_alert=True)
        return
    await bot.send_invoice(
        chat_id=call.message.chat.id,
        title=product['title'][:32],
        description=product['description'][:255],
        payload=f"start:{key}:v1",
        provider_token='',
        currency='XTR',
        prices=[LabeledPrice(label=product['title'], amount=product['stars'])],
        start_parameter=f"start_{key}"
    )
    await call.answer()

@dp.pre_checkout_query()
async def pre_checkout(query: PreCheckoutQuery):
    payload = query.invoice_payload
    parts = payload.split(':')
    if len(parts) != 3 or parts[0] != 'start' or parts[1] not in PRODUCTS:
        await query.answer(ok=False, error_message='Не удалось проверить заказ. Откройте каталог и попробуйте ещё раз.')
        return
    p = PRODUCTS[parts[1]]
    if query.currency != 'XTR' or query.total_amount != p['stars']:
        await query.answer(ok=False, error_message='Цена заказа не совпала. Создайте новый заказ из каталога.')
        return
    await query.answer(ok=True)

@dp.message(F.successful_payment)
async def successful_payment(message: Message):
    payment = message.successful_payment
    parts = payment.invoice_payload.split(':')
    if len(parts) != 3 or parts[0] != 'start' or parts[1] not in PRODUCTS:
        await message.answer('Оплата получена, но не удалось определить товар. Напишите /paysupport.')
        return
    p = PRODUCTS[parts[1]]
    # Verify successful payment payload before delivering. Keep charge ID for support/refunds.
    if payment.currency != 'XTR' or payment.total_amount != p['stars']:
        await message.answer('Платёж получен, но требуется ручная проверка. Напишите /paysupport.')
        return
    charge_id = payment.telegram_payment_charge_id
    logging.info('Successful Stars payment user=%s product=%s charge_id=%s', message.from_user.id, parts[1], charge_id)
    if p['file'].exists():
        await message.answer_document(FSInputFile(p['file']), caption=f"Спасибо за покупку «{p['title']}»! Сохрани файл на устройстве.")
    else:
        await message.answer('Оплата подтверждена, но файл не найден. Напишите /paysupport; заказ будет проверен.')

async def on_startup(bot: Bot):
    public_url = os.getenv('RENDER_EXTERNAL_URL', '').rstrip('/')
    webhook_secret = os.getenv('WEBHOOK_SECRET', '').strip()
    if not public_url or not webhook_secret:
        raise RuntimeError('Webhook mode requires RENDER_EXTERNAL_URL and WEBHOOK_SECRET.')
    await bot.set_webhook(
        url=f"{public_url}/telegram/webhook",
        secret_token=webhook_secret,
        drop_pending_updates=False,
    )
    logging.info('Telegram webhook configured for %s', public_url)

async def on_shutdown(bot: Bot):
    await bot.delete_webhook(drop_pending_updates=False)
    await bot.session.close()

async def main():
    import asyncio
    public_url = os.getenv('RENDER_EXTERNAL_URL', '').strip()
    webhook_secret = os.getenv('WEBHOOK_SECRET', '').strip()
    if public_url and webhook_secret:
        dp.startup.register(on_startup)
        dp.shutdown.register(on_shutdown)
        app = web.Application()
        SimpleRequestHandler(
            dispatcher=dp,
            bot=bot,
            secret_token=webhook_secret,
        ).register(app, path='/telegram/webhook')
        setup_application(app, dp, bot=bot)
        web.run_app(app, host='0.0.0.0', port=int(os.getenv('PORT', '10000')))
    else:
        logging.warning('No Render webhook configuration found; starting local polling mode.')
        await dp.start_polling(bot)

if __name__ == '__main__':
    import asyncio
    asyncio.run(main())
