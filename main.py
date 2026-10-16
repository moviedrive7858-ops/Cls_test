import os
import sys
import json
import re
import time
import asyncio
from telethon import TelegramClient
from telethon.sessions import StringSession
from telethon.errors import FloodWaitError
from telethon.tl.functions import channels
from telethon.tl.types import MessageActionTopicCreate

api_id = int(os.environ.get("API_ID"))
api_hash = os.environ.get("API_HASH")
session_str = os.environ.get("SESSION_STRING")

source_group = -1002222189494  # Source Group ID
target_group = -1003937179614  # Target Group ID

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
            return {"copied_ids": [], "topic_mapping": {}, "completed": False}
    return {"copied_ids": [], "topic_mapping": {}, "completed": False}

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
            # reply_to အတွက် Topic ID သတ်မှတ်ခြင်း (Topic မရှိလျှင် None ထားမည်)
            reply_arg = target_topic_id if target_topic_id and target_topic_id != 1 else None

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
                print(f"  [Media ပို့ပြီး] ID: {msg.id}")
                await asyncio.sleep(1.5)

            elif text_content:
                await client.send_message(
                    target_group,
                    text_content,
                    reply_to=reply_arg
                )
                print(f"  [စာသား ပို့ပြီး] ID: {msg.id}")
                await asyncio.sleep(0.5)

            return True

        except FloodWaitError as e:
            print(f"  [FloodWait] {e.seconds} စက္ကန့် စောင့်ဆိုင်းနေပါသည်...")
            await asyncio.sleep(e.seconds)

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

async def get_all_source_topics(source_entity):
    """Source Group ထဲရှိ Topics အားလုံးကို တိတိကျကျ စာရင်းထုတ်ယူခြင်း"""
    topics = []
    print("Source Group ထဲရှိ Topics များကို စစ်ဆေးနေပါသည်...")
    
    # ၁။ Telegram တရားဝင် Forum Topics API ဖြင့် အရင်စစ်ဆေးခြင်း
    try:
        result = await client(channels.GetForumTopicsRequest(
            channel=source_entity,
            offset_date=0,
            offset_id=0,
            offset_topic=0,
            limit=100
        ))
        for t in result.topics:
            topics.append({'id': t.id, 'title': t.title})
        if topics:
            print(f"GetForumTopicsRequest ဖြင့် Topic {len(topics)} ခု တွေ့ရှိပါသည်။")
            return topics
    except Exception as e:
        print(f"GetForumTopics API ခေါ်မရပါ ({e})၊ Chat History မှ ရှာပါမည်...")

    # ၂။ API မရပါက History လှန်ရှာခြင်း
    try:
        async for msg in client.iter_messages(source_entity, reverse=True):
            if isinstance(msg.action, MessageActionTopicCreate):
                topics.append({'id': msg.id, 'title': msg.action.title})
    except Exception as e:
        print(f"Topic ရှာမရပါ: {e}")

    return topics

async def create_target_topic(target_entity, title):
    try:
        created = await client(channels.CreateForumTopicRequest(
            channel=target_entity,
            title=title
        ))
        for update in created.updates:
            if hasattr(update, 'message') and hasattr(update.message, 'id'):
                return update.message.id
            elif hasattr(update, 'id'):
                return update.id
        return created.updates[0].id
    except FloodWaitError as e:
        await asyncio.sleep(e.seconds)
        return await create_target_topic(target_entity, title)
    except Exception as e:
        print(f"Topic '{title}' ဖန်တီးရာတွင် အမှား: {e}")
        return None

async def main():
    await client.connect()
    print("Telegram ချိတ်ဆက်မှု အောင်မြင်ပါသည်။")

    progress = load_progress()
    copied_set = set(progress.get("copied_ids", []))
    topic_mapping = progress.get("topic_mapping", {})

    source_entity = await client.get_entity(source_group)
    target_entity = await client.get_entity(target_group)

    source_topics = await get_all_source_topics(source_entity)
    if not source_topics:
        print("သတိပေးချက်: Source Group တွင် Topic တစ်ခုမှ ရှာမတွေ့ပါသဖြင့် General အနေဖြင့် ကူးပါမည်။")
        source_topics = [{'id': None, 'title': 'General'}]

    print(f"တွေ့ရှိသော Topic စုစုပေါင်း: {len(source_topics)} ခု")
    print(f"ယခင်ကူးပြီးသား Message: {len(copied_set)} ခု\n")

    all_completed = True

    for t in source_topics:
        if is_time_up():
            all_completed = False
            break

        s_topic_id = t['id']
        s_topic_title = t['title']
        s_topic_key = str(s_topic_id)

        print(f"\n========================================")
        print(f"စတင်လုပ်ဆောင်မည့် Topic: '{s_topic_title}' (Source ID: {s_topic_id})")

        new_target_topic_id = topic_mapping.get(s_topic_key)

        # Topic အသစ် ဆောက်ခြင်း
        if s_topic_id is not None and not new_target_topic_id:
            print(f"Target Group တွင် '{s_topic_title}' Topic အသစ် ဖွင့်နေပါသည်...")
            new_target_topic_id = await create_target_topic(target_entity, s_topic_title)
            if new_target_topic_id:
                topic_mapping[s_topic_key] = new_target_topic_id
                progress["topic_mapping"] = topic_mapping
                save_progress(progress)
                print(f"Topic အသစ် ဖွင့်ပြီးပါပြီ (Target Topic ID: {new_target_topic_id})")
            await asyncio.sleep(2)
        elif new_target_topic_id:
            print(f"ယခင် ဖန်တီးထားပြီး Target Topic ID: {new_target_topic_id} ထဲသို့ ထည့်ပါမည်။")

        iter_kwargs = {}
        if s_topic_id is not None:
            iter_kwargs['reply_to'] = s_topic_id

        messages = []
        async for msg in client.iter_messages(source_entity, **iter_kwargs):
            if isinstance(msg.action, MessageActionTopicCreate):
                continue
            messages.append(msg)

        messages.reverse()
        pending_messages = [m for m in messages if m.id not in copied_set]
        print(f"ကျန်ရှိသည့် Message: {len(pending_messages)} / စုစုပေါင်း: {len(messages)} ခု")

        for msg in pending_messages:
            if is_time_up():
                all_completed = False
                break

            success = await copy_message_safely(msg, new_target_topic_id)
            if success:
                copied_set.add(msg.id)
                progress["copied_ids"] = list(copied_set)
                save_progress(progress)

        if is_time_up():
            break

    if all_completed:
        progress["completed"] = True
        save_progress(progress)
        print("\n🎉 အားလုံး အောင်မြင်စွာ ကူးယူပြီးစီးပါပြီ!")

with client:
    client.loop.run_until_complete(main())
