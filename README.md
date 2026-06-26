# AI Tutor Platform

Nền tảng Gia sư Trí tuệ nhân tạo (AI Tutor) chạy đa kênh (Web App & Telegram Bot), tích hợp RAG, lộ trình học tập cá nhân hóa và lịch học tự động theo thời gian thực.

## 🎯 Mục tiêu dự án

* **Kiến trúc hướng dịch vụ (Service-based):** Rõ ràng, dễ mở rộng, tránh circular imports qua `global_services`.
* **Đa kênh đồng bộ:** Học sinh chat trực tiếp trên Web hoặc Telegram. Toàn bộ lịch sử hội thoại, tiến độ và lịch học đồng bộ qua cơ sở dữ liệu SQLite chung.
* **RAG (Retrieval-Augmented Generation):** Tải tài liệu (.pdf, .docx, .txt) để AI trả lời câu hỏi dựa trực tiếp trên nội dung tài liệu đó (ChromaDB).
* **Lộ trình học tập có cấu trúc:** AI sinh lộ trình gồm các Unit, mỗi Unit gồm 3 phần bắt buộc: **Lý thuyết → Bài tập vận dụng (5 câu) → Kiểm tra (8 câu)**. Chỉ khi điểm kiểm tra ≥ 5/10 mới mở khóa Unit tiếp theo.
* **Lịch học tự động (Scheduler):** APScheduler tự động giao bài Lý thuyết / Bài tập / Kiểm tra đúng giờ cài đặt mỗi ngày; hỗ trợ học theo ngày cụ thể trong tuần hoặc học hằng ngày.
* **Cấu hình AI linh hoạt:** Chọn AI provider (Gemini / OpenAI / OpenRouter) và nhập API Key trực tiếp trên giao diện Settings, không cần chỉnh sửa file `.env`.

---

## 📂 Cấu trúc thư mục

```text
AI_TUTOR/
├── backend/
│   ├── main.py                    # Điểm khởi chạy FastAPI, khởi tạo service, router, lifespan
│   ├── api/                       # Các routers endpoint API
│   │   ├── chat.py                # Xử lý hội thoại của học sinh
│   │   ├── upload.py              # Tải lên và trích xuất tài liệu vào ChromaDB
│   │   ├── roadmap.py             # Tạo lộ trình, cập nhật tiến độ từng chủ đề
│   │   ├── profile.py             # Đọc / cập nhật hồ sơ học sinh (tên, lịch học, v.v.)
│   │   ├── scheduler.py           # Xem danh sách, hủy lịch học đã đặt
│   │   └── settings.py            # Cấu hình AI provider, API key, kiểm tra kết nối
│   ├── services/                  # Tầng nghiệp vụ xử lý
│   │   ├── global_services.py     # Registry singleton tránh circular imports
│   │   ├── config_service.py      # Đọc / ghi cấu hình AI (data/llm_config.json)
│   │   ├── tutor_service.py       # Điều phối hội thoại, phân tích action JSON của AI
│   │   ├── llm_service.py         # Wrapper gọi Gemini / OpenAI / OpenRouter / Mock
│   │   ├── rag_service.py         # Phân đoạn văn bản, lưu vector vào ChromaDB
│   │   ├── memory_service.py      # Quản lý lịch sử chat theo phiên học
│   │   ├── roadmap_service.py     # Sinh lộ trình học tập dựa trên AI
│   │   └── scheduler_service.py   # APScheduler: lên lịch & gửi bài tự động mỗi phút
│   ├── database/                  # Quản lý cơ sở dữ liệu
│   │   ├── db.py                  # Cấu hình SQLAlchemy & SQLite engine
│   │   └── models.py              # Định nghĩa các bảng dữ liệu (xem chi tiết bên dưới)
│   ├── telegram/                  # Tích hợp Telegram Bot
│   │   ├── bot.py                 # Khởi tạo, polling và gửi tin nhắn Telegram
│   │   └── handlers.py            # Xử lý lệnh /start, /link, text và file từ Telegram
│   ├── storage/                   # Lưu trữ file SQLite database và tài liệu tải lên
│   └── tests/                     # Kịch bản kiểm thử
│       └── test_app.py
├── frontend/                      # Giao diện Jinja2 Templates & Static
│   ├── templates/
│   │   ├── onboarding.html        # Trang đăng ký / Đăng nhập
│   │   ├── dashboard.html         # Bảng điều khiển học tập chính
│   │   └── settings.html          # Trang cấu hình AI provider & API key
│   └── static/
│       ├── css/
│       │   └── style.css          # Hệ thống thiết kế UI (Glassmorphism)
│       └── images/                # Tài nguyên hình ảnh tĩnh
├── data/                          # Dữ liệu runtime (tự tạo khi chạy)
│   └── llm_config.json            # Cấu hình AI provider lưu từ giao diện Settings
├── main.py                        # Entry point thay thế (gọi uvicorn từ thư mục gốc)
├── migrate.py                     # Script tạo/cập nhật schema CSDL
├── Dockerfile                     # Docker build image
├── docker-compose.yml             # Triển khai container hóa
├── .env                           # Biến môi trường (chỉ cần TELEGRAM_BOT_TOKEN)
├── .env.example                   # File mẫu hướng dẫn cấu hình
└── requirements.txt               # Danh sách thư viện Python
```

---

## 🗄️ Mô hình dữ liệu

| Bảng | Mô tả |
|---|---|
| `students` | Thông tin học sinh: tên, email, lớp, mục tiêu, mã Telegram, lịch học (`theory_time`, `practice_time`, `exam_time`, `learning_frequency`) |
| `chat_messages` | Lịch sử hội thoại (user / ai), liên kết với `students` |
| `documents` | Tài liệu đã tải lên (.pdf, .docx, .txt), dùng cho RAG |
| `roadmaps` | Lộ trình học tập (JSON), mỗi học sinh có thể có nhiều lộ trình |
| `progress` | Tiến độ từng chủ đề: `not_started`, `in_progress`, `completed`; lưu điểm tốt nhất, số lần làm bài |
| `homework_submissions` | Từng lần nộp bài kiểm tra: điểm, phản hồi AI |
| `scheduled_jobs` | Lịch bài tập đã đặt: loại (`theory`, `practice`, `exam`, `free_practice`), giờ chạy, trạng thái |

---

## 🛠️ Hướng dẫn cài đặt & Chạy ứng dụng

### 1. Yêu cầu hệ thống
* Python **3.10** trở lên

### 2. Cài đặt môi trường

```bash
# Tạo môi trường ảo
python -m venv venv

# Kích hoạt (Windows)
venv\Scripts\activate

# Kích hoạt (Linux/macOS)
source venv/bin/activate

# Cài đặt thư viện
pip install -r requirements.txt
```

### 3. Thiết lập cấu hình `.env`

Sao chép `.env.example` thành `.env`:

```bash
cp .env.example .env
```

Nội dung `.env` chỉ cần một biến duy nhất:

```env
# Để trống nếu không dùng Telegram Bot
TELEGRAM_BOT_TOKEN=
```

> **Lưu ý:** Cấu hình AI provider (Gemini / OpenAI / OpenRouter) và API Key được quản lý **hoàn toàn qua giao diện** tại `/settings`. Không cần chỉnh sửa `.env` cho phần này.

### 4. Cấu hình AI (qua giao diện)

1. Khởi chạy ứng dụng (bước 5 bên dưới).
2. Truy cập **Dashboard → biểu tượng ⚙️ Settings** hoặc truy cập trực tiếp `/settings`.
3. Chọn **AI Provider** (Gemini / OpenAI / OpenRouter / Mock) và nhập **API Key**.
4. Nhấn **Lưu & Kiểm tra kết nối** để áp dụng ngay lập tức (không cần khởi động lại server).

> **Chế độ Mock:** Nếu không có API Key, hệ thống tự động chạy ở chế độ Mock — phù hợp để thử nghiệm giao diện.

### 5. Khởi chạy ứng dụng

```bash
uvicorn backend.main:app --reload
```

Truy cập Dashboard tại: [http://localhost:8000/](http://localhost:8000/)

### 6. Chạy kiểm thử

```bash
pytest backend/tests/
```

---

## 🐳 Triển khai với Docker Compose

```bash
# Xây dựng và khởi chạy container
docker-compose up --build -d

# Theo dõi logs
docker logs -f ai_tutor_app
```

---

## 🚀 Hướng dẫn trải nghiệm

### Bước 1 — Đăng ký / Đăng nhập
Truy cập `/onboarding`, nhập email để tạo tài khoản. Hệ thống tự sinh mã liên kết Telegram (ví dụ: `TUTOR-AB12CD`).

### Bước 2 — Liên kết Telegram Bot (tùy chọn)
Tìm bot Telegram của bạn, gõ: `/start TUTOR-AB12CD`
Sau khi liên kết, toàn bộ lịch sử chat và bài tập được đồng bộ giữa Web và Telegram.

### Bước 3 — Tạo lộ trình học tập
Trên Dashboard, nhập môn học (ví dụ: `Toán lớp 10`) và nhấn **Tạo lộ trình**. AI sẽ sinh danh sách Unit có cấu trúc:
- 📚 **Lý thuyết** — AI giảng bài
- ✏️ **Bài tập vận dụng** — 5 câu luyện tập (không tính điểm tiến trình)
- 📝 **Kiểm tra** — 8 câu, điểm ≥ 5/10 mới mở khóa Unit tiếp theo

### Bước 4 — Cài đặt lịch học tự động
Nhắn với AI: `"Tôi muốn học hằng ngày, lý thuyết lúc 7:00, bài tập lúc 14:00, kiểm tra lúc 19:00"`
AI sẽ lưu lịch và widget **Lịch học hôm nay** trên Dashboard sẽ cập nhật ngay.

APScheduler kiểm tra mỗi phút và tự động gửi đúng loại bài (lý thuyết / bài tập / kiểm tra) vào đúng giờ.

### Bước 5 — Hỏi đáp tài liệu (RAG)
- **Trên Web:** Tải file tài liệu (.pdf, .docx, .txt) qua nút Upload.
- **Trên Telegram:** Gửi trực tiếp file vào chat bot.

AI sẽ phân đoạn, lưu vector vào ChromaDB và dùng tài liệu đó làm ngữ cảnh khi bạn đặt câu hỏi.

### Bước 6 — Đặt bài tập tự do
Nhắn: `"Giao cho tôi 5 bài tập về phương trình bậc 2 ngay bây giờ"`
AI xác nhận và scheduler sẽ gửi bài trong vài giây.

---

## ⚙️ Các API Endpoint chính

| Method | Endpoint | Mô tả |
|---|---|---|
| `GET/POST` | `/onboarding` | Đăng ký / Đăng nhập |
| `GET` | `/` | Dashboard chính |
| `GET` | `/settings` | Trang cài đặt AI |
| `GET` | `/logout` | Đăng xuất |
| `POST` | `/api/chat` | Gửi tin nhắn đến AI Tutor |
| `POST` | `/api/upload` | Tải tài liệu lên ChromaDB |
| `GET/POST` | `/api/roadmap` | Lấy / Tạo lộ trình học tập |
| `PATCH` | `/api/roadmap/progress` | Cập nhật tiến độ chủ đề |
| `GET/POST` | `/api/profile` | Xem / Cập nhật hồ sơ học sinh |
| `GET` | `/api/scheduler/jobs` | Xem danh sách lịch đã đặt |
| `DELETE` | `/api/scheduler/jobs/{id}` | Hủy lịch học |
| `GET/POST` | `/api/settings` | Xem / Lưu cấu hình AI provider |
| `GET` | `/api/settings/test` | Kiểm tra kết nối AI provider |

---

## 📦 Thư viện chính

| Thư viện | Mục đích |
|---|---|
| `fastapi` | Web framework API |
| `uvicorn` | ASGI server |
| `sqlalchemy` | ORM & SQLite |
| `apscheduler` | Lên lịch giao bài tự động |
| `chromadb` | Vector store cho RAG |
| `python-telegram-bot` | Tích hợp Telegram Bot |
| `google-generativeai` | Gọi Gemini API |
| `openai` | Gọi OpenAI / OpenRouter API |
| `pypdf` + `python-docx` | Trích xuất nội dung tài liệu |
| `jinja2` | Template HTML |
| `httpx` | HTTP client async |
