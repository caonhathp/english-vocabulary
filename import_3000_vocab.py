import re
import pdfplumber
from supabase import create_client, Client

# ==================== 1. CẤU HÌNH SUPABASE ====================
SUPABASE_URL = "https://xxx.supabase.co"
SUPABASE_KEY = "xxx"
supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY)

# Tên file PDF 3000 từ vựng theo chủ đề (đặt cùng thư mục với script này)
PDF_FILENAME = "Oxford_3000.pdf"

# Regex nhận diện tiêu đề chủ đề (VD: "1. Từ vựng về đồ dùng học tập")
TOPIC_PATTERN = re.compile(r'^\d+\.\s*(?:Từ vựng về\s*)?(.+)', re.IGNORECASE)

def clean_text(text):
    """Làm sạch ký tự null byte và chuẩn hóa khoảng trắng"""
    if not text:
        return ""
    text = text.replace('\x00', '')
    text = text.replace('\n', ' ').replace('\r', ' ').replace('\t', ' ')
    # Tự động thêm khoảng trắng sau dấu phẩy nếu bị dính (vd: Cầm,nắm -> Cầm, nắm)
    text = re.sub(r',([^\s])', r', \1', text)
    # Chuẩn hóa khoảng trắng liền kề
    return re.sub(r'\s+', ' ', text).strip()

def parse_pdf():
    extracted_data = []
    current_topic = "Chung"
    seen_in_pdf = set()

    # ĐIỀU CHỈNH QUAN TRỌNG:
    # Hạ text_x_tolerance xuống 1.5pt để nhận diện khoảng cách ~2.5pt của PDF thành dấu cách
    table_settings = {
        "text_x_tolerance": 1.5,
        "text_y_tolerance": 2.0
    }

    print(f"1. Đang đọc và bóc tách dữ liệu từ file '{PDF_FILENAME}'...")
    with pdfplumber.open(PDF_FILENAME) as pdf:
        total_pages = len(pdf.pages)
        print(f"-> Tổng số trang: {total_pages}")

        for page_idx in range(2, total_pages):
            page = pdf.pages[page_idx]

            # Quét tiêu đề chủ đề
            text = page.extract_text(x_tolerance=1.5) or ""
            for line in text.split("\n"):
                line_clean = clean_text(line)
                match = TOPIC_PATTERN.match(line_clean)
                if match:
                    topic_name = match.group(1).strip()
                    topic_name = re.sub(r'[\.\|].*$', '', topic_name).strip()
                    current_topic = topic_name
                    break

            # Bóc tách bảng với cấu hình nhận diện dấu cách mới
            tables = page.extract_tables(table_settings)
            for table in tables:
                for row in table:
                    if not row or len(row) < 4:
                        continue

                    word = clean_text(row[0])
                    ipa = clean_text(row[2])
                    meaning = clean_text(row[3])

                    if not word or word.lower() in ["từ vựng", "vocabulary", "word"]:
                        continue

                    word_key = word.lower()
                    if word_key not in seen_in_pdf:
                        seen_in_pdf.add(word_key)
                        extracted_data.append({
                            "word": word,
                            "ipa": ipa,
                            "meaning": meaning,
                            "topic": current_topic,
                            "level": "Oxford 3000",
                            "learned": False
                        })

    print(f"-> Bóc tách thành công {len(extracted_data)} từ vựng (đã phân tách dấu cách chuẩn xác).\n")
    return extracted_data

def get_existing_words():
    print("2. Đang kiểm tra các từ vựng đã tồn tại trên Supabase...")
    existing = set()
    page_size = 1000
    start = 0

    while True:
        try:
            res = supabase.table("vocabulary").select("word").range(start, start + page_size - 1).execute()
            rows = res.data or []
            for r in rows:
                if r.get("word"):
                    existing.add(r["word"].strip().lower())
            
            if len(rows) < page_size:
                break
            start += page_size
        except Exception as e:
            print(f"Lỗi khi đọc dữ liệu cũ từ Supabase: {e}")
            break

    print(f"-> Đã tìm thấy {len(existing)} từ đang có sẵn trên Database.\n")
    return existing

def main():
    all_pdf_words = parse_pdf()
    if not all_pdf_words:
        print("Không bóc tách được dữ liệu.")
        return

    existing_words = get_existing_words()

    words_to_insert = [
        item for item in all_pdf_words 
        if item["word"].lower() not in existing_words
    ]

    total_new = len(words_to_insert)
    print(f"3. Tổng số từ MỚI cần nạp: {total_new} từ.")

    if total_new == 0:
        print("Tất cả từ đã có trên Database. Không cần nạp thêm!")
        return

    batch_size = 200
    print(f"Bắt đầu đẩy {total_new} từ mới lên Supabase...")

    for i in range(0, total_new, batch_size):
        batch = words_to_insert[i : i + batch_size]
        try:
            supabase.table("vocabulary").insert(batch).execute()
            print(f"-> Đã lưu: {min(i + batch_size, total_new)}/{total_new} từ")
        except Exception as e:
            print(f"Lỗi tại đợt {i}: {e}")

    print("\nHoàn tất nạp dữ liệu chuẩn xác lên Supabase!")

if __name__ == "__main__":
    main()