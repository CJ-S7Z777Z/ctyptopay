
import logging
import asyncio
import requests
from telegram import Update
from telegram.constants import ParseMode
from telegram.ext import (
    ApplicationBuilder,
    CommandHandler,
    ContextTypes,
)
from typing import Dict, Optional

# Настройка логирования
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO  # Можно изменить на DEBUG для более подробного логирования
)
logger = logging.getLogger(__name__)

# Конфигурация
TELEGRAM_TOKEN = '7993581170:AAFqnpKlD-JK2XRrzlatk5UqXfRz-MI1y9M'  # Замените на ваш токен
CRYPTOPAY_API_TOKEN = '27581:AAyUURcdI6iHSfnPKTstudG9AC3FX3rMhX0'  # Замените на ваш API токен
IMAGE_PATH = '21.png'  # Путь к вашему изображению
CURRENCY_TYPE = 'crypto'  # Или 'fiat', в зависимости от требований
ASSET = 'USDT'  # Замените на нужную криптовалюту
PAYMENT_AMOUNT = '0.5'  # Сумма платежа
DESCRIPTION = 'Оплата за доступ к изображению'
HIDDEN_MESSAGE = 'Спасибо за оплату!'
CHECK_INTERVAL = 60  # Интервал проверки в секундах

# Тип данных для хранения информации о платежах
class PaymentInfo:
    def __init__(self, chat_id: int, status: str = 'pending'):
        self.chat_id = chat_id
        self.status = status

# Хранилище для сопоставления invoice_id и chat_id
# В продакшене рекомендуется использовать базу данных
payment_database: Dict[str, PaymentInfo] = {}

async def create_invoice(chat_id: int) -> Optional[Dict]:
    url = 'https://testnet-pay.crypt.bot/api/createInvoice'
    headers = {
        'Crypto-Pay-API-Token': CRYPTOPAY_API_TOKEN,
        'Content-Type': 'application/json'
    }
    payload = {
        "currency_type": CURRENCY_TYPE,
        "asset": ASSET,
        "amount": PAYMENT_AMOUNT,
        "description": DESCRIPTION,
        "hidden_message": HIDDEN_MESSAGE,
        "payload": str(chat_id)  # Используем chat_id как payload для сопоставления
    }

    try:
        response = requests.post(url, json=payload, headers=headers)
        response.raise_for_status()
        data = response.json()
        if data.get('ok'):
            result = data.get('result', {})
            logger.info(f"Инвойс успешно создан: {result}")
            return result
        else:
            logger.error(f"Ошибка при создании инвойса: {data}")
            return None
    except Exception as e:
        logger.exception(f"Exception при создании инвойса: {e}")
        return None

async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    invoice = await create_invoice(chat_id)
    if invoice:
        # Используем актуальное поле для платежного URL, предпочтительно bot_invoice_url
        payment_address = invoice.get('bot_invoice_url') or invoice.get('pay_url')
        invoice_id = str(invoice.get('invoice_id'))  # Преобразуем в строку для использования в качестве ключа
        if payment_address and invoice_id:
            # Сохраняем сопоставление invoice_id и chat_id
            payment_database[invoice_id] = PaymentInfo(chat_id=chat_id)

            # Отправляем пользователю адрес для оплаты
            await update.message.reply_text(
                f"Пожалуйста, оплатите {PAYMENT_AMOUNT} {ASSET} на следующий адрес:\n\n{payment_address}",
                parse_mode=ParseMode.HTML
            )
        else:
            await update.message.reply_text("Ошибка получения данных платежа. Попробуйте позже.")
    else:
        await update.message.reply_text("Не удалось создать платеж. Попробуйте позже.")

async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("Используйте /start для начала оплаты.")

async def check_payments(application):
    while True:
        if payment_database:
            logger.info("Проверка статусов платежей...")
            for invoice_id, info in list(payment_database.items()):
                if info.status != 'pending':
                    continue  # Пропускаем уже обработанные платежи

                url = 'https://testnet-pay.crypt.bot/api/getInvoices'  # Используем правильный URL для тестнета
                headers = {
                    'Crypto-Pay-API-Token': CRYPTOPAY_API_TOKEN
                }
                params = {
                    'invoice_ids': invoice_id,
                    # 'status': 'active,paid'  # Удалено для избежания ошибки 400
                }

                try:
                    logger.debug(f"Запрос к API: {url} с параметрами {params}")
                    response = requests.get(url, headers=headers, params=params)
                    logger.debug(f"Ответ от API: Status Code={response.status_code}, Body={response.text}")
                    response.raise_for_status()
                    data = response.json()

                    if data.get('ok'):
                        results = data.get('result', {})
                        logger.debug(f"Полученные результаты: {results}")

                        # Проверяем наличие ключа 'items' и является ли он списком
                        items = results.get('items', [])
                        if not isinstance(items, list):
                            logger.warning(f"Неверный формат 'items': {items}")
                            continue

                        # Ищем инвойс с нужным invoice_id
                        invoice = next((item for item in items if str(item.get('invoice_id')) == invoice_id), None)

                        if not invoice:
                            logger.warning(f"Инвойс {invoice_id} не найден в ответе API.")
                            continue

                        if isinstance(invoice, dict):
                            status = invoice.get('status')
                            if status == 'paid':
                                chat_id = info.chat_id
                                # Отправка изображения
                                try:
                                    with open(IMAGE_PATH, 'rb') as photo:
                                        await application.bot.send_photo(
                                            chat_id=chat_id,
                                            photo=photo,
                                            caption="Спасибо за оплату!",
                                            parse_mode=ParseMode.HTML
                                        )
                                    # Обновляем статус платежа
                                    payment_database[invoice_id].status = 'completed'
                                    logger.info(f"Отправлено изображение пользователю {chat_id} по платежу {invoice_id}")
                                except Exception as e:
                                    logger.exception(f"Ошибка при отправке изображения: {e}")
                            elif status in ['expired', 'cancelled']:
                                # Обновляем статус платежа
                                payment_database[invoice_id].status = status
                                logger.info(f"Платеж {invoice_id} имеет статус {status}")
                            else:
                                logger.info(f"Платеж {invoice_id} имеет статус {status}, ожидаем оплаты.")
                        else:
                            logger.warning(f"Инвойс {invoice_id} имеет неожидаемый формат: {invoice}")
                    else:
                        logger.error(f"Ошибка при проверке платежа {invoice_id}: {data}")
                except requests.exceptions.HTTPError as http_err:
                    logger.error(f"HTTP ошибка при проверке платежа {invoice_id}: {http_err}")
                    logger.debug(f"Тело ответа: {response.text}")  # Логируем тело ответа для отладки
                except Exception as e:
                    logger.exception(f"Exception при проверке платежа {invoice_id}: {e}")

        await asyncio.sleep(CHECK_INTERVAL)

def main():
    application = ApplicationBuilder().token(TELEGRAM_TOKEN).build()

    # Регистрация обработчиков команд
    application.add_handler(CommandHandler("start", start_command))
    application.add_handler(CommandHandler("help", help_command))

    # Запуск фонового задания для проверки платежей
    application.job_queue.run_repeating(
        callback=lambda context: asyncio.create_task(check_payments(application)),
        interval=CHECK_INTERVAL,
        first=10
    )

    # Запуск бота
    application.run_polling()

if __name__ == '__main__':
    main()
