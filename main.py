import asyncio
import glob
import json
import os
import re
from collections.abc import MutableSequence
from hashlib import md5
from mmap import mmap, ACCESS_READ
from pathlib import Path
from urllib.parse import urljoin
import argparse
import sys
from azure.servicebus.aio import ServiceBusClient
from azure.servicebus import ServiceBusMessage

NAMESPACE_CONNECTION_STR = os.getenv("NAMESPACE_CONNECTION_STR")
QUEUE_NAME = os.getenv("QUEUE_NAME")
CONTENT_DIR = os.getenv("CONTENT_DIR")
CONTENT_URL = os.getenv("CONTENT_URL")


class Filter:
    language_id: str
    resource_id: str
    book_slug: str | None = None
    chapter: int | None = None
    exclude_format: MutableSequence[str] = []
    exclude_quality: MutableSequence[str] = []
    exclude_grouping: MutableSequence[str] = []
    dry_run: bool


class Parts:
    def __init__(self, language_id: str, resource_id: str, book_slug: str, chapter: str | None):
        self.language_id = language_id
        self.resource_id = resource_id
        self.book_slug = book_slug
        self.chapter = chapter



def create_arg_parser():
    parser = argparse.ArgumentParser()

    parser.add_argument("--language_id", type=str, required=True)
    parser.add_argument("--resource_id", type=str, required=True)
    parser.add_argument("--book_slug", type=str, default=None)
    parser.add_argument("--chapter", type=int, default=None)
    parser.add_argument("--exclude_format", nargs='*', default=[])
    parser.add_argument("--exclude_quality", nargs='*', default=[])
    parser.add_argument("--exclude_grouping", nargs='*', default=[])
    parser.add_argument('--dry_run', action=argparse.BooleanOptionalAction)


    return parser.parse_args(); 

async def read_content(content_filter: Filter):
    items = []
    print(CONTENT_DIR, content_filter.language_id, content_filter.resource_id)
    target_dir = os.path.join(CONTENT_DIR, content_filter.language_id, content_filter.resource_id)

    # Narrow to book or chapter only level: 
    if content_filter.book_slug is not None:
        target_dir = os.path.join(target_dir, content_filter.book_slug)
        if content_filter.chapter is not None:
            target_dir = os.path.join(target_dir, str(content_filter.chapter))

    with open("./book_catalog.json", "r") as json_file:
        books = json.load(json_file)

    exclude_verse = True if "verse" in content_filter.exclude_grouping else False
    exclude_chapter = True if "chapter" in content_filter.exclude_grouping else False
    exclude_book = True if "book" in content_filter.exclude_grouping else False

    exclude_hi = True if "hi" in content_filter.exclude_quality else False
    exclude_low = True if "low" in content_filter.exclude_quality else False

    exclude_mp3 = True if "mp3" in content_filter.exclude_format else False
    exclude_wav = True if "wav" in content_filter.exclude_format else False
    exclude_cue = True if "cue" in content_filter.exclude_format else False
    exclude_tr = True if "tr" in content_filter.exclude_format else False

    # Common data for each bus message goes on message
    message = None
    all_files = []
    for filename in glob.iglob(target_dir + '**/**', recursive=True):
        if not os.path.isdir(filename):
            all_files.append(filename)

    # sort for debugging logs
    all_files.sort(); 
    print(f"all files on cdn len is {len(all_files)}")
    for filename in all_files: 
            if "/verse/" in filename and exclude_verse:
                continue

            if "/chapter/" in filename and exclude_chapter:
                continue

            if "/book/" in filename and exclude_book:
                continue

            if "/hi/" in filename and exclude_hi:
                continue

            if "/low/" in filename and exclude_low:
                continue

            if filename.endswith(".mp3") and exclude_mp3:
                continue

            if filename.endswith(".wav") and exclude_wav:
                continue

            if filename.endswith(".cue") and exclude_cue:
                continue

            if filename.endswith(".tr") and exclude_tr:
                continue

            parts = extract_parts(filename)

            if message is None:
                message = {
                    "languageIetf": parts.language_id,
                    "name": f"{parts.language_id}_{parts.resource_id}",
                    "type": "audio",
                    "domain": "scripture",
                    "resourceType": "bible",
                    "namespace": "audio_biel",
                    "files": [],
                    # The session identifier of the message for a sessionful entity. The creates FIFO behavior for subscriptions
                    "session_id": f"audio_biel_{parts.language_id}_{parts.resource_id}"
                }

            item = {
                "size": os.path.getsize(filename),
                "url": path_to_url(filename),
                "fileType": Path(filename).suffix[1:],
                "hash": calc_md5_hash(filename),
                "isWholeBook": parts.chapter is None,
                "isWholeProject": False,
                "bookName": get_book_name(books, parts.book_slug),
                "bookSlug": parts.book_slug.capitalize(),
                "chapter": parts.chapter
            }
            print(item['url'])
            items.append(item)
    messages = []
    print(f"items len is {len(items)}")

    if message is not None:
        # chunks are done in about this size because azure service bus has a 256kb  size limit, and unchunked a nt in all file types and qualities is 3000+ files, would be over limit. Some prelim testing saw this number of urls consistently come in around 225 kb give or take a little. 
        chunks = split_array(items, 700)
        for i, chunk in enumerate(chunks):
            chunk_message = message.copy()
            # Just for debugging fifo in local dev
            chunk_message["order"] = i+1; 
            chunk_message["files"] = chunk
            messages.append(chunk_message)

    if not content_filter.dry_run:
        print(f"Sending {len(messages)} messages")
        await send_messages(messages)
    else:
      print(f"Created {len(messages)} messages")  
      print(messages)  
      return messages


def extract_parts(path_str: str) -> Parts:
    # dependent on cdn file structure
    parts = re.search(re.escape(CONTENT_DIR) + r"/(.+?)/(.+?)/(.+?)(?:/(\d+))?/.*?", path_str)
    return Parts(
        language_id=parts.group(1),
        resource_id=parts.group(2),
        book_slug=parts.group(3),
        chapter=None if parts.group(4) is None else parts.group(4)
    )


def calc_md5_hash(file_path) -> str:
    try:
        with open(file_path, "rb") as file, mmap(file.fileno(), 0, access=ACCESS_READ) as file:
            return md5(file).hexdigest()
    except ValueError:
        return ""


def get_book_name(books, slug) -> str:
    book = next((sub for sub in books if sub["slug"] == slug), None)
    return book["name"] if book is not None else slug.capitalize()


def path_to_url(file_path) -> str:
    return urljoin(CONTENT_URL, file_path)


def split_array(in_array, size):
    return [in_array[i:i + size] for i in range(0, len(in_array), size)]


async def send_messages(messages):
    async with ServiceBusClient.from_connection_string(
        conn_str=NAMESPACE_CONNECTION_STR,
        logging_enable=True
    ) as service_bus_client:
        sender = service_bus_client.get_topic_sender(topic_name=QUEUE_NAME)
        async with sender:
            batch_message = await sender.create_message_batch()
            for message in messages:
                try:
                    bus_message = ServiceBusMessage(
                        json.dumps(message), 
                        session_id=message["session_id"]
                        );
                    batch_message.add_message(bus_message)
                except ValueError:
                    break

            await sender.send_messages(batch_message)



async def main():
    print("Starting...")
    content_filter = create_arg_parser()
    print("Args: ", content_filter)
    required_vars = ["NAMESPACE_CONNECTION_STR", "QUEUE_NAME", "CONTENT_DIR", "CONTENT_DIR"]
    for var in required_vars:
        if var not in os.environ:
            sys.exit(f"{var} is not defined")
    await read_content(content_filter)
    sys.exit(0)

if __name__ == "__main__":
    asyncio.run(main())