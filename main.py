import os
import json
import re
import time
import asyncio
from telethon import TelegramClient
from telethon.sessions import StringSession
from telethon.errors import FloodWaitError
from telethon.tl.types import MessageActionTopicCreate

api_id = int(os.environ.get("API_ID"))
api_hash = os.environ.get("API_HASH")
session_str = os.environ.get("SESSION_STRING")

source_group = -1002222189494  # Source Group ID
target_group = -1003937179614  # Target Group ID

# =====================================================================
# ဒီနေရာမှာ သင်ကိုယ်တိုင် ဖွင့်ထားတဲ့ Topic ID တွေကို ချိတ်ပေးပါ
# ပုံစံ ->  Source_Topic_ID : Target_Topic_ID
# General အခန်းအတွက် ID 1 ကို သုံးပါ (မကူးချင်ရင် 1: 1 ကို ဖျက်ထားလို့ရပါတယ်)
# =====================================================================
TOPIC_MAP = {
    1: 1,       # Source General -> Target General
    12: 4,      # ဥပမာ- Source Topic 12 -> Target Topic 4
    25: 8,      # ဥပမာ- Source Topic 25 -> Target Topic 8
    # လိုသလောက် ထပ်ထည့်ပါ...
}

PROGRESS_FILE = 'progress.json'
START_TIME = time.time()
MAX_EXECUTION_SECONDS = 20700  # 5.75 hours

client = TelegramClient(StringSession(session_str), api_id, api_hash)

def clean_links(text: str) -> str:
    if not text:
        return ""
    return re.sub(r'https?://\S+|www\.\S+|t\.me/\S+', '', text).strip()

def load_progress():
    if os.path.exists(PROGRESS_FILE):
        try:
            with open(PROGRESS_FILE, 'r', encoding='utf-8') as f:
                return json.load(f)
        except Exception:
            pass
    return {"copied_ids": [], "completed": False}

def save_progress(progress_data):
    with open(PROGRESS_FILE, 'w', encoding='utf-8') as f:
        json.dump(progress_data, f, ensure_ascii=False, indent=2)

def is_time_up() -> bool:
    return (time.time() - START_TIME) >= MAX_EXECUTION_SECONDS

async def copy_message_safely(msg, target_topic_id):
    raw_text = msg.text or ""
    text_content = clean_links(raw_text)
    temp_file_path = None

    if not msg.media and not text_content:
        return True

    while True:
        try:
            # General (1) ဖြစ်ရင် reply_to=None ထားမည်၊ ကျန်တဲ့ Topic ဆိုရင် target_topic_id ထည့်မည်
            reply_arg = target_topic_id if target_topic_id != 1 else None

            if msg.media:
                try:
                    await client.send_file(
                        target_group,
                        msg.media,
                        caption=text_content,
                        reply_to=reply_arg
                    )
                except Exception:
                    temp_file_path = await client.download_media(msg)
                    if temp_file_path:
                        await client.send_file(
                            target_group,
                            temp_file_path,
                            caption=text_content,
                            reply_to=reply_arg
                        )
                print(f"  [Media ပို့ပြီး] Msg ID: {msg.id} -> Target Topic: {target_topic_id}")
                await asyncio.sleep(1.5)

            elif text_content:
                await client.send_message(
                    target_group,
                    text_content,
                    reply_to=reply_arg
                )
                print(f"  [စာသား ပို့ပြီး] Msg ID: {msg.id} -> Target Topic: {target_topic_id}")
                await asyncio.sleep(0.5)

            return True

        except FloodWaitError as e:
            print(f"  [FloodWait] {e.seconds} စက္ကန့် စောင့်ဆိုင်းနေပါသည်...")
            await asyncio.sleep(e.seconds + 1)

        except Exception as e:
            print(f"  [Error] Message ID {msg.id}: {e}")
            await asyncio.sleep(3)
            return False

        finally:
            if temp_file_path and os.path.exists(temp_file_path):
                try:
                    os.remove(temp_file_path)
                except Exception:
                    pass

async def main():
    await client.connect()
    if not await client.is_user_authorized():
        print("❌ Error: SESSION_STRING မမှန်ပါ သို့မဟုတ် သက်တမ်းကုန်နေပါသည်။")
        return

    print("Telegram ချိတ်ဆက်မှု အောင်မြင်ပါသည်။")

    progress = load_progress()
    copied_set = set(progress.get("copied_ids", []))

    source_entity = await client.get_entity(source_group)
    print(f"ယခင်ကူးပြီးသား Message စုစုပေါင်း: {len(copied_set)} ခု\n")

    all_completed = True

    for s_topic_id, t_topic_id in TOPIC_MAP.items():
        if is_time_up():
            all_completed = False
            break

        print(f"\n========================================")
        print(f"Source Topic ID: {s_topic_id} ---> Target Topic ID: {t_topic_id} သို့ စတင်ကူးယူနေပါသည်...")

        messages = []
        if s_topic_id == 1:
            # General အခန်းထဲက Message များကိုသာ ယူခြင်း
            async for msg in client.iter_messages(source_entity):
                if isinstance(msg.action, MessageActionTopicCreate):
                    continue
                if msg.reply_to and getattr(msg.reply_to, 'forum_topic', False):
                    top_id = getattr(msg.reply_to, 'reply_to_top_id', None) or getattr(msg.reply_to, 'reply_to_msg_id', None)
                    if top_id and top_id != 1:
                        continue
                messages.append(msg)
        else:
            # သတ်မှတ်ထားသော Topic ID ထဲက Message များကိုသာ ယူခြင်း
            async for msg in client.iter_messages(source_entity, reply_to=s_topic_id):
                if isinstance(msg.action, MessageActionTopicCreate):
                    continue
                messages.append(msg)

        messages.reverse()
        pending_messages = [m for m in messages if m.id not in copied_set]
        print(f"ကျန်ရှိသည့် Message: {len(pending_messages)} / စုစုပေါင်း: {len(messages)} ခု")

        unsaved_count = 0
        for msg in pending_messages:
            if is_time_up():
                all_completed = False
                break

            success = await copy_message_safely(msg, t_topic_id)
            if success:
                copied_set.add(msg.id)
                unsaved_count += 1
                if unsaved_count >= 10:
                    progress["copied_ids"] = list(copied_set)
                    save_progress(progress)
                    unsaved_count = 0

        progress["copied_ids"] = list(copied_set)
        save_progress(progress)

        if is_time_up():
            break

    if all_completed:
        progress["completed"] = True
        save_progress(progress)
        print("\n🎉 သတ်မှတ်ထားသော Topic များအားလုံး အောင်မြင်စွာ ကူးယူပြီးစီးပါပြီ!")

with client:
    client.loop.run_until_complete(main())
