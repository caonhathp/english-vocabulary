import os
import re
import time
import requests
from pypdf import PdfReader
from deep_translator import GoogleTranslator
from supabase import create_client, Client
import urllib.parse

# ==================== 1. CẤU HÌNH SUPABASE ====================
# Điền thông tin lấy ở Bước 2 vào đây:
SUPABASE_URL = "https://xxx.supabase.co"
SUPABASE_KEY = "xxx"
supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY)

# Tên file PDF nằm cùng thư mục
PDF_FILENAME = "Oxford_5000.pdf"

# ==================== 2. QUY TẮC BÓC TÁCH & PHÂN LOẠI ====================
# ==================== 2. QUY TẮC BÓC TÁCH ====================
POS_TAGS = r'\b(v|n|adj|adv|prep|conj|pron|number)\b\.?'
WORD_PATTERN = re.compile(rf'^([a-zA-Z\s\-\'\(\)]+?)\s+{POS_TAGS}', re.IGNORECASE)

TOPIC_KEYWORDS = {
    "Business & Finance": ["revenue", "market", "economy", "bank", "invest", "trade", "profit", "commerce", "corporate", "money", "audit", "tax", "retail", "costly", "bonus", "merger"],
    "Politics & Law": ["law", "court", "legal", "judge", "crime", "police", "senate", "policy", "govern", "vote", "elect", "treaty", "violate", "prosecut", "regime", "sanction"],
    "Technology & Science": ["tech", "comput", "data", "software", "network", "digital", "device", "mechan", "electron", "cell", "gene", "acid", "formula", "laser", "radiation"],
    "Health & Medicine": ["health", "medic", "diseas", "doctor", "clinic", "symptom", "infect", "treat", "patient", "virus", "therap", "pill", "injur", "kidney", "surgery"],
    "Environment & Nature": ["nature", "animal", "plant", "forest", "pollut", "climate", "ecolog", "sea", "ocean", "wild", "planet", "habitat", "tsunami", "flood", "species"],
    "Society & Education": ["school", "learn", "teach", "student", "social", "communit", "culture", "societ", "relig", "moral", "ethic", "class", "academy", "thesis"]
}

def guess_topic(word, meaning):
    text_check = f"{word} {meaning}".lower()
    for topic, keywords in TOPIC_KEYWORDS.items():
        if any(kw in text_check for kw in keywords):
            return topic
    return "General"

def extract_words_from_pdf():
    reader = PdfReader(PDF_FILENAME)
    extracted = []
    seen = set()
    current_level = "B2"

    for page in reader.pages:
        text = page.extract_text()
        if not text:
            continue

        for line in text.split("\n"):
            line = line.strip()
            if not line or "Oxford University Press" in line or "CEFR level" in line:
                continue

            if line == "B2":
                current_level = "B2"
                continue
            elif line == "C1":
                current_level = "C1"
                continue

            match = WORD_PATTERN.match(line)
            if match:
                raw_word = match.group(1).strip()
                clean_word = re.sub(r'[\d\'\(\)]', '', raw_word).strip()
                if clean_word and len(clean_word) > 1 and clean_word.lower() not in seen:
                    seen.add(clean_word.lower())
                    extracted.append((clean_word, current_level))

    return extracted

# ==================== 3. HÀM LẤY PHIÊN ÂM VÀ DỊCH NGHĨA CHUẨN ====================
session = requests.Session()
session.headers.update({
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/115.0.0.0 Safari/537.36"
})

def translate_to_vietnamese(word):
    # Cách 1: Dùng Lingva Scraper (ổn định, không bị giới hạn IP)
    try:
        encoded = urllib.parse.quote(word)
        url = f"https://lingva.ml/api/v1/en/vi/{encoded}"
        res = session.get(url, timeout=4)
        if res.status_code == 200:
            data = res.json()
            if "translation" in data and data["translation"]:
                return data["translation"].strip().lower()
    except Exception:
        pass

    # Cách 2: Dự phòng bằng MyMemory API nếu cách 1 lỗi
    try:
        url = "https://api.mymemory.translated.net/get"
        params = {"q": word, "langpair": "en|vi"}
        res = session.get(url, params=params, timeout=4)
        if res.status_code == 200:
            data = res.json()
            trans = data.get("responseData", {}).get("translatedText", "")
            # Lọc bỏ các kết quả cảnh báo giới hạn của MyMemory nếu có
            if trans and "MYMEMORY WARNING" not in trans:
                return trans.strip().lower()
    except Exception:
        pass

    return ""

def get_word_details(word):
    # 1. Lấy phiên âm IPA
    ipa = ""
    try:
        res = session.get(f"https://api.dictionaryapi.dev/api/v2/entries/en/{word}", timeout=4)
        if res.status_code == 200:
            data = res.json()
            if data and isinstance(data, list):
                if data[0].get("phonetic"):
                    ipa = data[0]["phonetic"]
                elif data[0].get("phonetics"):
                    for p in data[0]["phonetics"]:
                        if p.get("text"):
                            ipa = p["text"]
                            break
    except Exception:
        ipa = ""

    # 2. Lấy nghĩa Tiếng Việt
    meaning = translate_to_vietnamese(word)

    return ipa, meaning

# ==================== 4. QUÁ TRÌNH NẠP DỮ LIỆU ====================
def main():
    print("1. Đang bóc tách từ vựng từ PDF...")
    words_data = extract_words_from_pdf()
    total = len(words_data)
    print(f"-> Tổng cộng tìm thấy: {total} từ.\n")

    batch = []
    batch_size = 25

    print("2. Bắt đầu lấy IPA, dịch nghĩa và gửi lên Supabase...")
    for idx, (word, level) in enumerate(words_data, 1):
        ipa, meaning = get_word_details(word)
        topic = guess_topic(word, meaning)

        batch.append({
            "word": word,
            "ipa": ipa,
            "meaning": meaning,
            "level": level,
            "topic": topic,
            "learned": False
        })

        # In log ra màn hình để theo dõi nghĩa có được điền hay không
        print(f"[{idx}/{total}] [{level}] {word} {ipa} => '{meaning}' ({topic})")

        if len(batch) >= batch_size or idx == total:
            try:
                supabase.table("vocabulary").insert(batch).execute()
                print(f"-> Đã lưu thành công lô đến từ thứ {idx} vào Database.")
            except Exception as e:
                print(f"Lỗi khi đẩy vào Supabase: {e}")
            batch = []

        # Giữ khoảng nghỉ nhẹ để tránh bị chặn
        time.sleep(0.08)

    print("\nHoàn tất nạp dữ liệu!")

if __name__ == "__main__":
    main()