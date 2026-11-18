import os
import json
import re
import copy
import time
import asyncio
from telethon import TelegramClient
from telethon.sessions import StringSession
from telethon.errors import FloodWaitError
from telethon.tl.types import MessageActionTopicCreate, MessageEntityTextUrl, MessageEntityUrl

api_id = int(os.environ.get("API_ID"))
api_hash = os.environ.get("API_HASH")
session_str = os.environ.get("SESSION_STRING")

# =====================================================================
# ဒီ ၄ ခုကို ပြောင်းထည့်ပြီး Run ပါ (General အခန်းဆိုရင် Topic ID နေရာမှာ 1 ထည့်ပါ)
# =====================================================================
source_group = -1002222189494       # Source Group ID
source_topic_id = 54                # Source Group Topic ID

target_group = -1003834013726       # Target Group ID
target_topic_id = 400                 # Target Group Topic ID
# =====================================================================

PROGRESS_FILE = f'progress_{source_topic_id}_to_{target_topic_id}.json'
START_TIME = time.time()
MAX_EXECUTION_SECONDS = 20700  # 5.75 hours

client = TelegramClient(StringSession(session_str), api_id, api_hash)

# Telegram Message Link ပုံစံ (ဥပမာ - https://t.me/channel/123 သို့မဟုတ် https://t.me/c/12345/67)
TG_MSG_LINK_PATTERN = re.compile(
    r'(?:https?://)?(?:www\.)?(?:t\.me|telegram\.me|telegram\.dog)/(?:c/\d+/\d+(?:/\d+)?|[a-zA-Z0-9_]+/\d+(?:/\d+)?)(?:\?\S*)?',
    re.IGNORECASE
)

def _utf16_len(s: str) -> int:
    return len(s.encode('utf-16-le')) // 2

def strip_telegram_message_links(raw_text: str, entities):
    """
    စာသားထဲမှ Telegram Message Link များကိုသာ ဖြတ်ထုတ်ပြီး
    ကျန်စာသားများနှင့် မူရင်း Formatting (Bold/Italic/Links) များကို နေရာမပျက် ပြန်စီပေးခြင်း
    """
    if not raw_text:
        return "", None

    entities = copy.deepcopy(entities) if entities else []

    # 1. Hidden Hyperlink (TextUrl) ထဲတွင် Telegram Message Link ပါနေပါက URL ကို ဖြုတ်ပစ်ခြင်း (စာသားကျန်မည်)
    cleaned_entities = []
    for ent in entities:
        if isinstance(ent, MessageEntityTextUrl) and ent.url and TG_MSG_LINK_PATTERN.fullmatch(ent.url.strip()):
            continue
        cleaned_entities.append(ent)
    entities = cleaned_entities

    # 2. စာသားထဲတွင် တိုက်ရိုက်ပါနေသော Telegram Message Link များ၏ နေရာများကို ရှာခြင်း
    matches = list(TG_MSG_LINK_PATTERN.finditer(raw_text))
    if not matches:
        return raw_text, (entities if entities else None)

    # နောက်ဆုံး Match ကနေ အရှေ့ဆုံး Match ဆီ ပြောင်းပြန် ဖြတ်ထုတ်ခြင်း (Entity offset များ မလွဲစေရန်)
    new_text = raw_text
    for m in reversed(matches):
        start_py, end_py = m.span()
        start_u16 = _utf16_len(new_text[:start_py])
        end_u16 = _utf16_len(new_text[:end_py])
        removed_u16_len = end_u16 - start_u16

        new_text = new_text[:start_py] + new_text[end_py:]

        updated_entities = []
        for ent in entities:
            ent_start = ent.offset
            ent_end = ent.offset + ent.length

            # ဖြတ်လိုက်သည့် Link အတွင်း လုံးဝကျရောက်နေသော Entity (ဥပမာ MessageEntityUrl) ကို ဖယ်ရှားမည်
            if ent_start >= start_u16 and ent_end <= end_u16:
                continue
            # ဖြတ်လိုက်သည့် Link ၏ နောက်တွင် ရှိနေသော Entity များကို အရှေ့သို့ ပြန်ရွှေ့မည်
            elif ent_start >= end_u16:
                ent.offset -= removed_u16_len
            # ဖြတ်လိုက်သည့် Link ကို အုပ်မိနေသော Entity (ဥပမာ စာပိုဒ်တစ်ခုလုံး Bold လုပ်ထားခြင်း) ကို အရှည်ပြန်ညှိမည်
            elif ent_start < end_u16 and ent_end > start_u16:
                overlap = min(ent_end, end_u16) - max(ent_start, start_u16)
                ent.length -= overlap
                if ent.length <= 0:
                    continue

            updated_entities.append(ent)
        entities = updated_entities

    # အစနှင့် အဆုံးရှိ ပိုနေသော Space/Newline များကို ရှင်းလင်းခြင်း
    leading_ws = len(new_text) - len(new_text.lstrip())
    if leading_ws > 0:
        lead_u16 = _utf16_len(new_text[:leading_ws])
        new_text = new_text.lstrip()
        final_entities = []
        for ent in entities:
            ent.offset -= lead_u16
            if ent.offset < 0:
                ent.length += ent.offset
                ent.offset = 0
            if ent.length > 0:
                final_entities.append(ent)
        entities = final_entities

    new_text = new_text.rstrip()
    max_u16 = _utf16_len(new_text)
    final_entities = []
    for ent in entities:
        if ent.offset < max_u16:
            if ent.offset + ent.length > max_u16:
                ent.length = max_u16 - ent.offset
            if ent.length > 0:
                final_entities.append(ent)

    return new_text, (final_entities if final_entities else None)

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

async def copy_single_message(msg):
    """Message တစ်ခုချင်းစီကို TG Message Link ဖြုတ်ပြီး မူရင်းအတိုင်း ကူးယူခြင်း"""
    cleaned_text, cleaned_entities = strip_telegram_message_links(msg.raw_text or "", msg.entities)
    temp_file_path = None

    # Media လည်း မပါ၊ Link ဖြတ်ပြီးနောက် စာသားလည်း ဗလာဖြစ်သွားရင် ကျော်သွားမည်
    if not msg.media and not cleaned_text:
        print(f"  [Skip - TG Link သီးသန့်ဖြစ်နေသည်] Msg ID: {msg.id}")
        return True

    reply_arg = target_topic_id if target_topic_id != 1 else None

    while True:
        try:
            if msg.media:
                try:
                    await client.send_file(
                        target_group,
                        msg.media,
                        caption=cleaned_text,
                        formatting_entities=cleaned_entities,
                        reply_to=reply_arg
                    )
                except Exception:
                    temp_file_path = await client.download_media(msg)
                    if temp_file_path:
                        await client.send_file(
                            target_group,
                            temp_file_path,
                            caption=cleaned_text,
                            formatting_entities=cleaned_entities,
                            reply_to=reply_arg
                        )
                print(f"  [Media ပို့ပြီး] Msg ID: {msg.id}")
                await asyncio.sleep(1.5)

            elif cleaned_text:
                await client.send_message(
                    target_group,
                    cleaned_text,
                    formatting_entities=cleaned_entities,
                    reply_to=reply_arg,
                    link_preview=bool(msg.web_preview)
                )
                print(f"  [စာသား ပို့ပြီး] Msg ID: {msg.id}")
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

async def copy_album_messages(album_msgs):
    """Album (ပုံ/ဗီဒီယို အတွဲလိုက်) များကို TG Message Link ဖြုတ်ပြီး မူရင်းအတိုင်း ကူးယူခြင်း"""
    reply_arg = target_topic_id if target_topic_id != 1 else None
    temp_files = []

    caption_text = ""
    caption_entities = None
    for m in album_msgs:
        if m.raw_text:
            caption_text, caption_entities = strip_telegram_message_links(m.raw_text, m.entities)
            break

    while True:
        try:
            try:
                media_list = [m.media for m in album_msgs if m.media]
                await client.send_file(
                    target_group,
                    media_list,
                    caption=caption_text,
                    formatting_entities=caption_entities,
                    reply_to=reply_arg
                )
            except Exception:
                temp_files = []
                for m in album_msgs:
                    if m.media:
                        path = await client.download_media(m)
                        if path:
                            temp_files.append(path)
                if temp_files:
                    await client.send_file(
                        target_group,
                        temp_files,
                        caption=caption_text,
                        formatting_entities=caption_entities,
                        reply_to=reply_arg
                    )

            print(f"  [Album ပို့ပြီး ({len(album_msgs)} ခု)] Msg IDs: {[m.id for m in album_msgs]}")
            await asyncio.sleep(2.0)
            return True

        except FloodWaitError as e:
            print(f"  [FloodWait] {e.seconds} စက္ကန့် စောင့်ဆိုင်းနေပါသည်...")
            await asyncio.sleep(e.seconds + 1)

        except Exception as e:
            print(f"  [Error Album] Msg IDs {[m.id for m in album_msgs]}: {e}")
            await asyncio.sleep(3)
            return False

        finally:
            for path in temp_files:
                if path and os.path.exists(path):
                    try:
                        os.remove(path)
                    except Exception:
                        pass

async def main():
    await client.connect()
    if not await client.is_user_authorized():
        print("❌ Error: SESSION_STRING မမှန်ပါ သို့မဟုတ် သက်တမ်းကုန်နေပါသည်။")
        return

    print("Telegram ချိတ်ဆက်မှု အောင်မြင်ပါသည်။")
    print(f"Source: {source_group} (Topic: {source_topic_id}) ---> Target: {target_group} (Topic: {target_topic_id})")

    progress = load_progress()
    copied_set = set(progress.get("copied_ids", []))
    print(f"ယခင်ကူးပြီးသား Message: {len(copied_set)} ခု\n")

    source_entity = await client.get_entity(source_group)

    messages = []
    if source_topic_id == 1:
        async for msg in client.iter_messages(source_entity):
            if isinstance(msg.action, MessageActionTopicCreate):
                continue
            if msg.reply_to and getattr(msg.reply_to, 'forum_topic', False):
                top_id = getattr(msg.reply_to, 'reply_to_top_id', None) or getattr(msg.reply_to, 'reply_to_msg_id', None)
                if top_id and top_id != 1:
                    continue
            messages.append(msg)
    else:
        async for msg in client.iter_messages(source_entity, reply_to=source_topic_id):
            if isinstance(msg.action, MessageActionTopicCreate):
                continue
            messages.append(msg)

    messages.reverse()
    pending_messages = [m for m in messages if m.id not in copied_set]
    print(f"ကျန်ရှိသည့် Message: {len(pending_messages)} / စုစုပေါင်း: {len(messages)} ခု\n")

    grouped_batches = []
    i = 0
    while i < len(pending_messages):
        curr = pending_messages[i]
        if curr.grouped_id:
            album = [curr]
            j = i + 1
            while j < len(pending_messages) and pending_messages[j].grouped_id == curr.grouped_id:
                album.append(pending_messages[j])
                j += 1
            grouped_batches.append(album)
            i = j
        else:
            grouped_batches.append([curr])
            i += 1

    all_completed = True
    unsaved_count = 0

    for batch in grouped_batches:
        if is_time_up():
            all_completed = False
            print("\n⏰ အချိန်ပြည့်သွားပါပြီ။ နောက်တစ်ကြိမ် ပြန် Run ရင် ကျန်တဲ့နေရာက ဆက်ကူးပါမည်။")
            break

        if len(batch) > 1:
            success = await copy_album_messages(batch)
        else:
            success = await copy_single_message(batch[0])

        if success:
            for m in batch:
                copied_set.add(m.id)
            unsaved_count += len(batch)
            if unsaved_count >= 10:
                progress["copied_ids"] = list(copied_set)
                save_progress(progress)
                unsaved_count = 0

    progress["copied_ids"] = list(copied_set)
    if all_completed:
        progress["completed"] = True
        print(f"\n🎉 Topic ({source_topic_id} -> {target_topic_id}) အားလုံး အောင်မြင်စွာ ကူးယူပြီးစီးပါပြီ!")
    save_progress(progress)

with client:
    client.loop.run_until_complete(main())
