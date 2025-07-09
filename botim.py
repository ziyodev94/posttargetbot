import json
import time
import logging
import asyncio
from telethon import TelegramClient, events
from telethon.errors import (
    RPCError, 
    FloodWaitError, 
    ChannelPrivateError, 
    ChannelInvalidError,
    ChatIdInvalidError
)
import aiohttp
import os
from config import (
    API_ID, API_HASH,
    SESSION_NAME_REPLY, SESSION_NAME_CHECK,
    BOT_TOKEN, BOT_OWNER_ID,
    MAIN_CHANNEL_ID, TARGET_CHAT_IDS,
    MAPPING_FILE, LAST_UPDATE_ID_FILE, TEXT_FORWARD_CONFIG
)

# === Sozlamalar ===
BASE_URL = f"https://api.telegram.org/bot{BOT_TOKEN}"
# === Loglar ===
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s",
    handlers=[
        logging.FileHandler("reply_forward_sync.log", encoding='utf-8'),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)

# === Fayl yordamchi ===
def load_mapping():
    try:
        with open(MAPPING_FILE, 'r', encoding='utf-8') as f:
            return json.load(f)
    except Exception as e:
        logger.warning(f"❌ Mapping faylni o'qib bo'lmadi: {e}")
        return {}

def save_mapping(data):
    try:
        with open(MAPPING_FILE, 'w', encoding='utf-8') as f:
            json.dump(data, f, indent=2, ensure_ascii=False)
        logger.info("💾 Mapping muvaffaqiyatli saqlandi")
    except Exception as e:
        logger.error(f"❌ Mapping saqlashda xato: {e}")

def is_text_forwarding_enabled():
    try:
        with open(TEXT_FORWARD_CONFIG, 'r') as f:
            return json.load(f).get("enabled", False)
    except:
        return False

def set_text_forwarding(state: bool):
    try:
        with open(TEXT_FORWARD_CONFIG, 'w') as f:
            json.dump({"enabled": state}, f)
        status = "yoqildi" if state else "o'chirildi"
        logger.info(f"📝 Matnli postlar {status}")
    except Exception as e:
        logger.error(f"❌ Matnli post sozlamasini saqlashda xato: {e}")

# === Telegram Botga so'rov yuborish ===
async def send_async(session, method, params):
    url = f"{BASE_URL}/{method}"
    try:
        async with session.post(url, json=params) as resp:
            return await resp.json()
    except Exception as e:
        logger.error(f"❌ API so'rovda xato ({method}): {e}")
        return {"ok": False, "error": str(e)}

# === Kanalga yangi post qo'yilganda ===
async def handle_channel_post_async(message, session):
    # Reply xabarlarni alohida boshqarish
    if "reply_to_message" in message:
        logger.info(f"↩️ Reply post e'tiborga olinmadi (ID: {message['message_id']})")
        return

    msg_id = str(message["message_id"])
    mapping = load_mapping()

    # Post allaqachon yuborilganligini tekshirish
    for m in mapping.values():
        if msg_id in m.values():
            logger.info(f"ℹ️ Post allaqachon yuborilgan (ID: {msg_id})")
            return

    mapping[msg_id] = {}
    tasks = []
    logger.info(f"🆕 Yangi post qabul qilindi (ID: {msg_id})")

    for chat_id in TARGET_CHAT_IDS:
        task = None
        if "photo" in message:
            photo = message["photo"][-1]
            task = send_async(session, "sendPhoto", {
                "chat_id": chat_id,
                "photo": photo["file_id"],
                "caption": message.get("caption", "")
            })
        elif "video" in message:
            video = message["video"]
            task = send_async(session, "sendVideo", {
                "chat_id": chat_id,
                "video": video["file_id"],
                "caption": message.get("caption", "")
            })
        elif "document" in message:
            doc = message["document"]
            task = send_async(session, "sendDocument", {
                "chat_id": chat_id,
                "document": doc["file_id"],
                "caption": message.get("caption", "")
            })
        elif "text" in message and is_text_forwarding_enabled():
            task = send_async(session, "sendMessage", {
                "chat_id": chat_id,
                "text": message["text"]
            })

        if task:
            tasks.append((chat_id, task))

    if not tasks:
        logger.info("ℹ️ Hech qanday vazifa yaratilmadi")
        return

    results = await asyncio.gather(*[t[1] for t in tasks], return_exceptions=True)

    for (chat_id, _), result in zip(tasks, results):
        if isinstance(result, dict) and result.get("ok"):
            mapping[msg_id][str(chat_id)] = result["result"]["message_id"]
            logger.info(f"✅ {chat_id} ga yuborildi (ID: {result['result']['message_id']})")
        else:
            logger.warning(f"⚠️ {chat_id} ga yuborishda xatolik: {result}")

    save_mapping(mapping)
    logger.info(f"📊 Yangi post mappingi: {json.dumps(mapping[msg_id], indent=2)}")

# === Oddiy post tahrirlanganda (reply bo'lmagan) ===
async def handle_channel_edit_async(message, session):
    msg_id = str(message["message_id"])
    mapping = load_mapping()
    logger.info(f"✏️ Post tahrirlash so'rovi (ID: {msg_id})")

    if msg_id not in mapping:
        logger.warning(f"⚠️ Tahrirlangan post mappingda topilmadi: {msg_id}")
        logger.info(f"🔍 Mappingdagi kalitlar: {list(mapping.keys())}")
        return

    caption = message.get("caption", "")
    tasks = []
    logger.info(f"🔁 {msg_id} ID li post yangilanmoqda")
    logger.info(f"🔍 Mappingdagi guruhlar: {list(mapping[msg_id].keys())}")

    for chat_id_str, fwd_msg_id in mapping[msg_id].items():
        try:
            chat_id = int(chat_id_str)
            logger.info(f"🔄 {chat_id} guruhiga yangilash yuborilmoqda...")
            
            if "photo" in message:
                photo = message["photo"][-1]["file_id"]
                task = send_async(session, "editMessageMedia", {
                    "chat_id": chat_id,
                    "message_id": int(fwd_msg_id),
                    "media": {
                        "type": "photo",
                        "media": photo,
                        "caption": caption
                    }
                })
            elif "video" in message:
                video = message["video"]["file_id"]
                task = send_async(session, "editMessageMedia", {
                    "chat_id": chat_id,
                    "message_id": int(fwd_msg_id),
                    "media": {
                        "type": "video",
                        "media": video,
                        "caption": caption
                    }
                })
            elif "document" in message:
                doc = message["document"]["file_id"]
                task = send_async(session, "editMessageMedia", {
                    "chat_id": chat_id,
                    "message_id": int(fwd_msg_id),
                    "media": {
                        "type": "document",
                        "media": doc,
                        "caption": caption
                    }
                })
            elif "text" in message and is_text_forwarding_enabled():
                task = send_async(session, "editMessageText", {
                    "chat_id": chat_id,
                    "message_id": int(fwd_msg_id),
                    "text": message["text"]
                })
            else:
                logger.info(f"ℹ️ {chat_id} guruhida yangilash uchun hech qanday kontent topilmadi")
                continue

            tasks.append((chat_id, task))
        except Exception as e:
            logger.error(f"❌ {chat_id_str} guruh ID sini int ga o'tkazishda xato: {e}")

    if not tasks:
        logger.info("ℹ️ Yangilash uchun hech qanday vazifa yaratilmadi")
        return

    results = await asyncio.gather(*[t[1] for t in tasks], return_exceptions=True)

    for (chat_id, _), result in zip(tasks, results):
        if isinstance(result, dict) and result.get("ok"):
            logger.info(f"✏️ Yangilandi → {chat_id} (ID: {result['result']['message_id']})")
        else:
            logger.warning(f"⚠️ Yangilash xatosi {chat_id}: {result}")
            
# === Reply post tahrirlanganda ===
async def handle_reply_edit_async(message, session):
    msg_id = str(message["message_id"])
    mapping = load_mapping()
    logger.info(f"✏️ Reply tahrirlash so'rovi (ID: {msg_id})")

    if msg_id not in mapping:
        logger.warning(f"⚠️ Reply tahriri mappingda topilmadi: {msg_id}")
        logger.info(f"🔍 Mappingdagi kalitlar: {list(mapping.keys())}")
        return

    # Yangilangan matnni olish
    new_text = ""
    if "text" in message:
        new_text = message["text"]
    elif "caption" in message:
        new_text = message["caption"]
    else:
        logger.warning("⚠️ Reply da matn yoki caption topilmadi")
        return
    
    tasks = []
    logger.info(f"🔁 {msg_id} ID li reply yangilanmoqda")
    logger.info(f"🔍 Mappingdagi guruhlar: {list(mapping[msg_id].keys())}")
    logger.info(f"📝 Yangi matn: {new_text[:50]}...")

    for chat_id_str, fwd_msg_id in mapping[msg_id].items():
        try:
            chat_id = int(chat_id_str)
            logger.info(f"🔄 {chat_id} guruhiga reply yangilash yuborilmoqda...")
            
            # Reply uchun har doim editMessageText ishlatamiz
            task = send_async(session, "editMessageText", {
                "chat_id": chat_id,
                "message_id": int(fwd_msg_id),
                "text": new_text
            })
            tasks.append((chat_id, task))
        except Exception as e:
            logger.error(f"❌ {chat_id_str} guruh ID sini int ga o'tkazishda xato: {e}")

    if not tasks:
        logger.info("ℹ️ Reply yangilash uchun hech qanday vazifa yaratilmadi")
        return

    results = await asyncio.gather(*[t[1] for t in tasks], return_exceptions=True)

    for (chat_id, _), result in zip(tasks, results):
        if isinstance(result, dict) and result.get("ok"):
            logger.info(f"✏️ Reply yangilandi → {chat_id} (ID: {result['result']['message_id']})")
        else:
            logger.warning(f"⚠️ Reply yangilash xatosi {chat_id}: {result}")
            if isinstance(result, dict):
                logger.warning(f"❌ Xato tafsiloti: {result}")

# === Yangilanishlarni qabul qilish ===
async def poll_updates(session):
    def get_last_update_id():
        try:
            with open(LAST_UPDATE_ID_FILE, 'r') as f:
                return int(f.read().strip())
        except:
            return 0

    def save_last_update_id(update_id):
        with open(LAST_UPDATE_ID_FILE, 'w') as f:
            f.write(str(update_id))

    last_id = get_last_update_id()
    logger.info(f"🔄 Yangilanishlar kuzatilmoqda (Oxirgi ID: {last_id})")
    
    while True:
        try:
            url = f"{BASE_URL}/getUpdates"
            params = {
                "offset": last_id + 1,
                "timeout": 30,
                "allowed_updates": ["channel_post", "edited_channel_post"]
            }
            async with session.post(url, json=params) as resp:
                data = await resp.json()

            if data and data.get("ok"):
                updates = data["result"]
                if updates:
                    logger.info(f"📥 {len(updates)} ta yangilanish qabul qilindi")
                
                for upd in updates:
                    last_id = max(last_id, upd["update_id"])
                    save_last_update_id(last_id)
                    
                    # Xabarni qayta ishlash
                    if "channel_post" in upd:
                        message = upd["channel_post"]
                        if str(message["chat"]["id"]) == str(MAIN_CHANNEL_ID):
                            logger.info(f"📨 Yangi post (ID: {message['message_id']})")
                            await handle_channel_post_async(message, session)
                    elif "edited_channel_post" in upd:
                        message = upd["edited_channel_post"]
                        if str(message["chat"]["id"]) == str(MAIN_CHANNEL_ID):
                            # Reply tahrirlash va oddiy post tahrirlashni farqlash
                            if "reply_to_message" in message:
                                logger.info(f"✏️ Reply tahrirlash aniqlandi (ID: {message['message_id']})")
                                await handle_reply_edit_async(message, session)
                            else:
                                logger.info(f"✏️ Oddiy post tahrirlash (ID: {message['message_id']})")
                                await handle_channel_edit_async(message, session)
            await asyncio.sleep(2)
        except Exception as e:
            logger.error(f"❌ Poll xatolik: {e}")
            await asyncio.sleep(6)

# === Reply va Delete xizmati ===
async def reply_and_delete_worker():
    reply_client = TelegramClient(SESSION_NAME_REPLY, API_ID, API_HASH)
    delete_client = TelegramClient(SESSION_NAME_CHECK, API_ID, API_HASH)
    await reply_client.start()
    await delete_client.start()
    logger.info("🤖 Reply va Delete xizmatlari ishga tushdi")

    @reply_client.on(events.NewMessage(pattern='/restart'))
    async def handle_restart(event):
        if event.sender_id != BOT_OWNER_ID:
            await event.reply("❌ Ruxsat yo'q")
            return
        await event.reply("♻️ Bot qayta ishga tushmoqda...")
        await reply_client.disconnect()
        raise SystemExit

    @reply_client.on(events.NewMessage(pattern='/enabletext'))
    async def enable_text(event):
        if event.sender_id == BOT_OWNER_ID:
            set_text_forwarding(True)
            await event.reply("✅ Matnli postlar endi yuboriladi.")
        else:
            await event.reply("❌ Ruxsat yo'q")

    @reply_client.on(events.NewMessage(pattern='/disabletext'))
    async def disable_text(event):
        if event.sender_id == BOT_OWNER_ID:
            set_text_forwarding(False)
            await event.reply("🚫 Matnli postlar yuborilmaydi.")
        else:
            await event.reply("❌ Ruxsat yo'q")

    @reply_client.on(events.NewMessage(chats=MAIN_CHANNEL_ID))
    async def handle_reply(event):
        if event.is_reply:
            logger.info(f"🔁 Reply qabul qilindi (ID: {event.id})")
            mapping = load_mapping()
            reply_msg = await event.get_reply_message()
            
            if not reply_msg:
                logger.warning("⚠️ Reply xabar topilmadi")
                return
            
            reply_to_id = str(reply_msg.id)
            new_text = event.raw_text
            msg_id = str(event.id)
            
            logger.info(f"🔗 Reply berilayotgan post ID: {reply_to_id}")
            logger.info(f"📝 Yangi reply ID: {msg_id}")
            logger.info(f"📄 Reply matni: {new_text[:50]}...")
            
            if reply_to_id in mapping:
                logger.info(f"🔍 {reply_to_id} ID li post mappingda topildi")
                
                # Yangi reply uchun mapping bo'limini yaratamiz
                if msg_id not in mapping:
                    mapping[msg_id] = {}
                
                for chat_id_str, forwarded_reply_id in mapping[reply_to_id].items():
                    try:
                        chat_id = int(chat_id_str)
                        logger.info(f"🔄 {chat_id} ga reply yuborilmoqda...")
                        
                        sent = await reply_client.send_message(
                            chat_id, 
                            new_text, 
                            reply_to=int(forwarded_reply_id)
                        )
                        
                        # Har bir guruh uchun yuborilgan xabarning ID sini saqlaymiz
                        mapping[msg_id][str(chat_id)] = sent.id
                        logger.info(f"✅ Reply yuborildi → {chat_id} (Yangi ID: {sent.id})")
                    except Exception as e:
                        logger.error(f"⚠️ Reply yuborishda xato {chat_id}: {e}")
                        # Xato chiqqanda ham boshqa guruhlarga urinishni davom ettiramiz
                
                save_mapping(mapping)
                logger.info(f"💾 Mapping yangilandi (Qo'shilgan ID: {msg_id})")
                logger.info(f"📊 Yangi mapping: {json.dumps(mapping[msg_id], indent=2)}")
            else:
                logger.warning(f"⚠️ {reply_to_id} ID li post mappingda topilmadi")
                logger.info(f"🔍 Mavjud mappinglar: {list(mapping.keys())}")

    # Reply tahrirlash uchun alohida handler
    @reply_client.on(events.MessageEdited(chats=MAIN_CHANNEL_ID))
    async def handle_reply_edit_telethon(event):
        if event.is_reply:
            logger.info(f"✏️ Telethon orqali Reply tahrirlash aniqlandi (ID: {event.id})")
            mapping = load_mapping()
            msg_id = str(event.id)
            new_text = event.raw_text
            
            if msg_id in mapping:
                logger.info(f"🔍 {msg_id} ID li reply mappingda topildi")
                logger.info(f"📝 Yangi matn: {new_text[:50]}...")
                
                for chat_id_str, fwd_msg_id in mapping[msg_id].items():
                    try:
                        chat_id = int(chat_id_str)
                        logger.info(f"🔄 {chat_id} ga reply tahrirlash yuborilmoqda...")
                        
                        await reply_client.edit_message(
                            chat_id,
                            int(fwd_msg_id),
                            new_text
                        )
                        
                        logger.info(f"✅ Reply tahrirlandi → {chat_id} (ID: {fwd_msg_id})")
                    except Exception as e:
                        logger.error(f"⚠️ Reply tahrirlashda xato {chat_id}: {e}")
            else:
                logger.warning(f"⚠️ {msg_id} ID li reply mappingda topilmadi")

    async def delete_checker():
        while True:
            logger.info("🔍 O'chirilgan postlarni tekshirish boshlandi...")
            try:
                mapping = load_mapping()
                updated = False

                for msg_id in list(mapping.keys()):
                    logger.info(f"🔍 Post {msg_id} holati tekshirilmoqda...")
                    try:
                        msg = await delete_client.get_messages(MAIN_CHANNEL_ID, ids=int(msg_id))
                        if not msg or getattr(msg, "empty", False):
                            raise ValueError("Post yo'q yoki bo'sh")
                        logger.info(f"✅ Post {msg_id} hali mavjud")
                    except Exception as e:
                        logger.warning(f"🛑 Post {msg_id} o'chirilgan deb topildi: {e}")
                        for chat_id_str, fwd_id in mapping[msg_id].items():
                            try:
                                chat_id = int(chat_id_str)
                                await delete_client.delete_messages(chat_id, int(fwd_id))
                                logger.info(f"🗑️ O'chirildi → {chat_id}:{fwd_id}")
                            except FloodWaitError as fw:
                                logger.warning(f"⌛ FloodWait {fw.seconds} sekund. Kutyapman...")
                                await asyncio.sleep(fw.seconds)
                            except (ChannelPrivateError, ChannelInvalidError, ChatIdInvalidError):
                                logger.warning(f"❌ Noto'g'ri chat ID yoki kanalga kirish yo'q: {chat_id}")
                            except Exception as err:
                                logger.warning(f"⚠️ O'chirishda xato {chat_id}: {err}")
                        del mapping[msg_id]
                        updated = True

                if updated:
                    save_mapping(mapping)
                    logger.info("💾 Mapping yangilandi.")
                else:
                    logger.info("ℹ️ Mappingda o'zgarish yo'q, yozilmadi.")

                logger.info("✅ Tekshiruv tugadi. 60 soniya kuting...")
                await asyncio.sleep(60)

            except Exception as e:
                logger.error(f"❌ Umumiy delete_checker xatolik: {e}")
                await asyncio.sleep(60)

    asyncio.create_task(delete_checker())
    await reply_client.run_until_disconnected()

# === Asosiy ===
async def main_async():
    logger.info("🚀 Bot ishga tushmoqda...")
    async with aiohttp.ClientSession() as session:
        await asyncio.gather(
            reply_and_delete_worker(),
            poll_updates(session)
        )

def main():
    while True:
        try:
            asyncio.run(main_async())
        except SystemExit:
            logger.info("♻️ Bot qayta ishga tushmoqda...")
            time.sleep(5)
        except Exception as e:
            logger.error(f"❌ Asosiy funksiyada xatolik: {e}")
            logger.info("♻️ 10 soniyadan so'ng qayta urinilmoqda...")
            time.sleep(10)

if __name__ == '__main__':
    main()