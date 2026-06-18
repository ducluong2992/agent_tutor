# AI Tutor Platform MVP

Một phiên bản Gia sư Trí tuệ nhân tạo (AI Tutor) tinh gọn, chạy đa kênh (Web App & Telegram Bot), tích hợp công nghệ RAG để hỗ trợ học sinh học tập cá nhân hóa.

## 🎯 Mục tiêu dự án
* **Đơn giản & Tinh gọn:** Không lạm dụng multi-agent phức tạp; sử dụng kiến trúc Hướng dịch vụ (Service-based Architecture) rõ ràng.
* **Đa kênh đồng bộ:** Học sinh có thể chat trực tiếp trên giao diện Web hoặc ứng dụng Telegram. Lịch bài tập và tiến độ đồng bộ 100% qua cơ sở dữ liệu SQLite chung.
* **RAG (Retrieval-Augmented Generation):** Tải lên tài liệu (.pdf, .docx, .txt) để AI gia sư trả lời câu hỏi trực tiếp dựa trên nội dung tài liệu đó.
* **Giao bài tập động (Dynamic Scheduling):** Lên lịch bài tập linh hoạt dựa trên yêu cầu chat của người dùng (ví dụ: "giao bài tập Python sau 1 phút") bằng APScheduler, không cấu hình cứng nhắc giờ cố định.

---

## 📂 Cấu trúc thư mục
```text
ai_tutor/
├── backend/
│   ├── main.py                  # Điểm khởi chạy FastAPI & Telegram Bot
│   ├── api/                     # Các routers endpoint API
│   │   ├── chat.py              # Xử lý hội thoại của học sinh
│   │   ├── upload.py            # Tải lên và trích xuất tài liệu
│   │   ├── roadmap.py           # Tạo lộ trình học tập và đánh giá tiến độ
│   │   ├── profile.py           # Quản lý hồ sơ học sinh
│   │   └── scheduler.py         # Lên lịch giao bài tập về nhà
│   ├── services/                # Tầng nghiệp vụ xử lý
│   │   ├── global_services.py   # Registry chia sẻ singleton tránh circular imports
│   │   ├── tutor_service.py     # Điều phối hội thoại, phân tích action của AI
│   │   ├── llm_service.py       # Wrapper gọi Gemini API / OpenAI API / Mock offline
│   │   ├── rag_service.py       # Phân đoạn văn bản và lưu trữ vector vào ChromaDB
│   │   ├── memory_service.py    # Quản lý lịch sử chat
│   │   ├── roadmap_service.py   # Thiết kế chương trình học dựa trên AI
│   │   └── scheduler_service.py # Lên lịch APScheduler & Gửi tin nhắn tự động
│   ├── database/                # Quản lý cơ sở dữ liệu
│   │   ├── db.py                # Cấu hình SQLAlchemy & SQLite engine
│   │   └── models.py            # Định nghĩa các bảng (Student, Messages, Docs, v.v.)
│   ├── telegram/                # Tích hợp Telegram Bot
│   │   ├── bot.py               # Khởi tạo và thiết lập polling Bot
│   │   └── handlers.py          # Lắng nghe text, tài liệu, lệnh /start, /link
│   ├── storage/                 # Lưu trữ SQLite db và file upload
│   └── tests/                   # Kịch bản kiểm thử tự động
│       └── test_app.py
├── frontend/                    # Giao diện Jinja2 Templates & Static
│   ├── templates/
│   │   ├── onboarding.html      # Trang đăng ký / Đăng nhập
│   │   └── dashboard.html       # Bảng điều khiển học tập đa năng
│   └── static/
│       └── css/
│           └── style.css        # Hệ thống thiết kế UI Glassmorphism cao cấp
├── Dockerfile                   # Docker build
├── docker-compose.yml           # Triển khai container hóa
├── .env                         # Tệp cấu hình môi trường hoạt động
├── .env.example                 # Tệp mẫu hướng dẫn cấu hình
└── requirements.txt             # Danh sách thư viện Python
```

---

## 🛠️ Hướng dẫn cài đặt & Chạy ứng dụng

### 1. Cài đặt môi trường Python cục bộ
Yêu cầu Python từ phiên bản **3.10 trở lên**.

```bash
# Tạo môi trường ảo
python -m venv venv
venv\Scripts\activate

# Cài đặt các thư viện cần thiết
pip install -r requirements.txt
```

### 2. Thiết lập cấu hình `.env`
Sao chép `.env.example` thành `.env` và tùy chỉnh:
* Để chạy offline giả lập không cần API key, giữ nguyên `LLM_PROVIDER=mock`.
* Để sử dụng AI thực tế, đổi `LLM_PROVIDER=gemini` và điền `GEMINI_API_KEY`, hoặc sử dụng `openai` tương ứng.
* Điền `TELEGRAM_BOT_TOKEN` từ @BotFather nếu muốn tích hợp Telegram.

### 3. Chạy kiểm thử tự động
Chạy pytest để đảm bảo toàn bộ hệ thống hoạt động ổn định:
```bash
pytest backend/tests/
```

### 4. Khởi chạy dự án
```bash
uvicorn backend.main:app --reload
```
Truy cập trang Web Dashboard tại địa chỉ: [http://localhost:8000/](http://localhost:8000/)

---

## 🐳 Triển khai với Docker Compose
Đảm bảo bạn đã cài đặt Docker và Docker Compose.

```bash
# Xây dựng và khởi chạy container
docker-compose up --build -d

# Theo dõi logs hoạt động
docker logs -f ai_tutor_app
```

---

## 🚀 Các tính năng chính và cách trải nghiệm
1. **Đăng ký / Onboarding:** Truy cập giao diện web, chọn **Đăng ký** để khởi tạo học sinh mới. Hệ thống sinh ngẫu nhiên một mã liên kết Telegram (vd: `TUTOR-ABC123`).
2. **Liên kết Telegram Bot:** 
   * Tìm Telegram bot của bạn, gõ lệnh `/start TUTOR-ABC123` để liên kết.
   * Sau khi liên kết thành công, mọi đoạn chat trên Telegram hoặc Web đều sẽ lưu chung lịch sử.
3. **Chat và học cùng AI:** Hỏi các câu hỏi lý thuyết. Hệ thống sử dụng prompt hướng cấu trúc JSON để phát hiện ý định người dùng.
4. **Hỏi đáp tài liệu (RAG):**
   * Trên Web: Chọn tải tài liệu (.pdf, .docx, .txt) ở cột trái.
   * Trên Telegram: Gửi trực tiếp file tài liệu vào khung chat bot.
   * AI sẽ tự học tài liệu này và dùng nó làm ngữ cảnh trả lời khi bạn hỏi.
5. **Giao bài tập động (APScheduler):**
   * Thử nhắn: `"Giao bài tập về Python sau 1 phút"` vào chat.
   * AI sẽ phản hồi xác nhận và một lịch trình mới xuất hiện ở danh sách lịch bài tập.
   * Đúng 1 phút sau, hệ thống sẽ tự sinh bài tập thông qua AI và gửi tin nhắn (hoặc tin Telegram) trực tiếp cho bạn!
6. **Lộ trình học (Roadmap):**
   * Nhập tên môn học (ví dụ: `Data Science`) ở cột phải rồi nhấn **Tạo**, AI thiết lập lộ trình các bước chi tiết.
   * Tích chọn hoàn thành để tăng phần trăm hiển thị trên thanh tiến độ.
