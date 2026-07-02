# 📖 Giải thích Kỹ thuật Hệ thống AI Tutor

> Tài liệu này giải thích chi tiết 4 câu hỏi kỹ thuật cốt lõi của dự án AI Tutor,
> có tham chiếu trực tiếp đến code thực tế trong codebase.

---

## Câu hỏi 1: Phân chia Context cho từng User như thế nào?

### Tóm tắt
Mỗi user (học sinh) có **ngữ cảnh riêng biệt hoàn toàn**, không dùng chung với nhau.

### Cơ chế phân chia

#### 1.1 Phân chia theo `student_id`
Mỗi học sinh khi đăng nhập được gán một `student_id` duy nhất (lưu trong cookie).
Toàn bộ dữ liệu trong hệ thống đều được lọc theo `student_id` này.

```python
# memory_service.py — Lưu tin nhắn RIÊNG cho từng học sinh
def add_message(self, db, student_id: int, sender: str, message: str):
    db_msg = ChatMessage(
        student_id=student_id,   # <-- khóa phân chia
        sender=sender,
        message=message
    )

# Lấy lịch sử chat CHỈ của học sinh đó
def get_chat_history(self, db, student_id: int, limit: int = 10):
    messages = db.query(ChatMessage)\
        .filter(ChatMessage.student_id == student_id)\  # <-- lọc theo ID
        .order_by(ChatMessage.created_at.desc())\
        .limit(limit).all()
```

#### 1.2 Collection RAG riêng trong ChromaDB
Mỗi học sinh có một **collection ChromaDB độc lập** chứa tài liệu họ đã upload:

```python
# rag_service.py
def get_collection(self, student_id: int):
    collection_name = f"student_{student_id}_docs"  # Ví dụ: "student_3_docs"
    return self.client.get_or_create_collection(
        name=collection_name,
        ...
    )
```

Học sinh A upload file Toán lớp 8 → lưu vào `student_1_docs`.  
Học sinh B upload file Vật lý lớp 10 → lưu vào `student_2_docs`.  
Khi chat, mỗi người chỉ truy xuất được tài liệu của chính họ.

#### 1.3 System Prompt được cá nhân hóa theo từng người
Mỗi lần gọi LLM, `tutor_service.py` xây dựng một `system_prompt` duy nhất
chứa thông tin profile của **đúng học sinh đó**:

```python
# tutor_service.py — handle_message()
student = db.query(Student).filter(Student.id == student_id).first()
student_name    = student.name
skill_level     = student.skill_level
learning_goals  = student.learning_goals
grade_level     = student.grade_level

system_prompt = f"""
You are an AI Math Tutor for a student with the following profile:
- Name: {student_name}
- Current Level: {skill_level}
- Grade Level: {grade_level}
- Learning Goals: {learning_goals}
- Current Unit: {current_unit_text}
...
"""
```

#### 1.4 Sơ đồ tổng quan

```
Học sinh A (student_id=1) ──> ChatMessage (student_id=1)
                           ──> student_1_docs (ChromaDB)
                           ──> Progress (student_id=1)
                           ──> system_prompt riêng của A

Học sinh B (student_id=2) ──> ChatMessage (student_id=2)
                           ──> student_2_docs (ChromaDB)
                           ──> Progress (student_id=2)
                           ──> system_prompt riêng của B
```

> **Kết luận:** Hệ thống không dùng chung context. Mỗi học sinh có bộ dữ liệu
> hoàn toàn cô lập: lịch sử chat, tài liệu RAG, lộ trình học, hồ sơ cá nhân.

---

## Câu hỏi 2: Khi đổi Provider/Model, làm sao giữ được Context?

### Tóm tắt
Context **không lưu trong model** mà lưu trong **database (SQLite)**.
Khi đổi provider, model mới đọc lại lịch sử từ DB nên không bị mất ngữ cảnh.

### Cơ chế chi tiết

#### 2.1 LLM là "stateless" — không nhớ gì
Các LLM API (Gemini, OpenAI, OpenRouter) đều là **stateless**: mỗi lần gọi là
một request độc lập, model không tự nhớ cuộc trò chuyện trước.  
Vì vậy, toàn bộ lịch sử chat phải được **inject vào mỗi lần gọi**.

#### 2.2 Chat history được lưu vào DB, không vào model
```python
# memory_service.py
def add_message(self, db, student_id, sender, message):
    db_msg = ChatMessage(student_id=student_id, sender=sender, message=message)
    db.add(db_msg)
    db.commit()  # <-- Lưu vĩnh viễn vào SQLite
```

Mỗi tin nhắn (cả của user và AI) đều được lưu vào bảng `ChatMessage` trong SQLite.

#### 2.3 Trước mỗi lần gọi LLM, lịch sử được đọc lại từ DB
```python
# tutor_service.py — handle_message()
chat_history = self.memory_service.get_chat_history(db, student_id, limit=10)
# → Lấy 10 tin nhắn gần nhất từ DB (không phụ thuộc vào provider nào)

response_text = await self.llm_service.generate_response(
    system_prompt, user_prompt, chat_history  # <-- Đẩy toàn bộ lịch sử vào
)
```

#### 2.4 Lịch sử được gắn vào request theo đúng format của từng provider
```python
# llm_service.py — _try_provider() cho Gemini
contents = []
if chat_history:
    for msg in chat_history:
        role = "user" if msg["role"] == "user" else "model"
        contents.append({"role": role, "parts": [msg["content"]]})
contents.append({"role": "user", "parts": [user_prompt]})
response = model.generate_content(contents, ...)

# llm_service.py — _build_openai_messages() cho OpenAI/OpenRouter
messages = [{"role": "system", "content": system_prompt}]
for msg in chat_history:
    role = "user" if msg["role"] == "user" else "assistant"
    messages.append({"role": role, "content": msg["content"]})
messages.append({"role": "user", "content": user_prompt})
```

#### 2.5 Đổi provider chỉ cần `reload_config()`
```python
# llm_service.py
def reload_config(self):
    self.api_provider = os.getenv("LLM_PROVIDER", "mock").lower()
    # Khởi tạo lại client cho provider mới
    # Lịch sử chat vẫn nằm nguyên trong DB — KHÔNG bị ảnh hưởng
```

#### 2.6 Luồng khi đổi từ Gemini sang OpenAI

```
Trước khi đổi:
  User: "Dạy tôi phép nhân"   → Gemini → trả lời → lưu vào DB

Sau khi đổi provider sang OpenAI:
  User: "Tiếp tục giải thích"
    └─> memory_service.get_chat_history() → đọc từ SQLite (vẫn có)
    └─> llm_service._build_openai_messages() → đính kèm lịch sử
    └─> OpenAI nhận được đầy đủ ngữ cảnh → hiểu được "tiếp tục"
```

#### 2.7 Lưu ý về giới hạn token
Lịch sử chỉ lấy **10 tin nhắn gần nhất** (`limit=10`) để tránh vượt context
window và tốn token. Nếu muốn context dài hơn/ngắn hơn, chỉ cần thay đổi
tham số `limit` trong `get_chat_history()`.

> **Kết luận:** Context không bị mất khi đổi provider vì nó được lưu trong SQLite,
> không phải trong model. Model mới được "nạp" lại lịch sử qua request mỗi lần chat.

---

## Câu hỏi 3: Tại sao File Upload lưu vào Chroma dạng Vector mà vẫn truy xuất được bằng Text?

### Tóm tắt
Đây là kỹ thuật **RAG (Retrieval-Augmented Generation)**. Text được chuyển thành
vector để so sánh ngữ nghĩa, không phải tìm kiếm từ khóa đơn thuần.

### Cơ chế từng bước

#### 3.1 Khi Upload: Text → Chunks → Vector → Lưu vào ChromaDB

**Bước 1:** File được parse ra text thuần:
```python
# upload.py
# PDF: dùng PyMuPDF hoặc pypdf
# DOCX: dùng python-docx
# TXT: đọc trực tiếp
content = ""  # Toàn bộ nội dung file dạng text
```

**Bước 2:** Text được cắt thành các **chunk** nhỏ (~500 từ, overlap 100 từ):
```python
# rag_service.py — _chunk_text()
def _chunk_text(self, text, chunk_size=500, chunk_overlap=100):
    words = text.split()
    chunks = []
    for i in range(0, len(words), chunk_size - chunk_overlap):
        chunk = " ".join(words[i:i + chunk_size])
        chunks.append(chunk)
    return chunks
    # Ví dụ: 1 file 2000 từ → ~5 chunks
```

> **Tại sao phải chunk?** LLM có giới hạn context window. Không thể nhét toàn
> bộ tài liệu vào mỗi lần hỏi. Chunk nhỏ cho phép chỉ lấy phần liên quan nhất.

**Bước 3:** Mỗi chunk được ChromaDB **embed thành vector** và lưu:
```python
# rag_service.py — add_document()
collection.add(
    documents=chunks,          # Text gốc
    ids=ids,                   # "doc_3_chunk_0", "doc_3_chunk_1", ...
    metadatas=metadatas        # {"filename": "toan8.pdf", "document_id": 3}
)
# ChromaDB tự động: chunk_text → embedding_vector → lưu vào disk
```

**Vector là gì?**  
Vector là một mảng số thực biểu diễn **"ý nghĩa ngữ nghĩa"** của đoạn text.
Hai đoạn có ý nghĩa tương đồng sẽ có vector **gần nhau** trong không gian nhiều chiều.

```
"Phép cộng hai số nguyên"   → [0.23, -0.11, 0.87, 0.04, ...]
"Tính tổng các số nguyên"   → [0.21, -0.09, 0.85, 0.06, ...]
"Diện tích hình tròn"       → [-0.55, 0.72, -0.13, 0.91, ...]
             ↑ gần nhau               ↑ xa nhau
```

#### 3.2 Khi User Nhập Text: Query → Vector → So sánh → Trả về Chunks liên quan

```python
# rag_service.py — query_documents()
def query_documents(self, student_id, query, limit=4):
    collection = self.get_collection(student_id)
    query_results = collection.query(
        query_texts=[query],   # Câu hỏi của học sinh
        n_results=limit        # Lấy 4 chunk gần nhất
    )
    # ChromaDB tự làm:
    # 1. Embed câu hỏi thành vector
    # 2. Tính khoảng cách cosine với tất cả vector đã lưu
    # 3. Trả về top-4 chunk có vector gần nhất
```

#### 3.3 Chunk được đưa vào System Prompt của LLM

```python
# tutor_service.py — handle_message()
rag_results = self.rag_service.query_documents(student_id, message_content, limit=3)
if rag_results:
    rag_context = "\n--- Context from uploaded documents ---\n"
    for res in rag_results:
        rag_context += f"Source: {res['filename']}\nContent: {res['content']}\n\n"

user_prompt = f"{rag_context}Student Message: {message_content}"
# LLM sẽ dùng context này để trả lời chính xác hơn
```

#### 3.4 Luồng hoàn chỉnh (Sơ đồ)

```
[UPLOAD]
File PDF/DOCX/TXT
    │
    ▼ parse text
"Chương 1: Phương trình bậc nhất..."
    │
    ▼ chunk (500 từ/chunk)
Chunk_0: "Chương 1: Phương trình bậc nhất..."
Chunk_1: "...ví dụ: giải phương trình 2x + 3 = 7..."
Chunk_2: "...bài tập: tìm x biết 3x - 5 = 10..."
    │
    ▼ embed (mỗi chunk → vector)
ChromaDB lưu: [vector_0, vector_1, vector_2] + text gốc

─────────────────────────────────────────────────────

[USER HỎI] "Làm thế nào để giải phương trình?"
    │
    ▼ embed câu hỏi
vector_query = embed("Làm thế nào để giải phương trình?")
    │
    ▼ cosine similarity với tất cả vector
vector_query ≈ vector_1 (chunk về ví dụ giải pt)
    │
    ▼ trả về top-3 chunks liên quan
→ Chunk_1 + Chunk_2 đưa vào prompt của LLM
→ LLM trả lời dựa trên tài liệu đã upload
```

#### 3.5 Lưu ý về dự án hiện tại (SimpleDummyEmbeddingFunction)
Trong code hiện tại, hàm embedding là **dummy** (trả về vector toàn số 0):
```python
# rag_service.py
class SimpleDummyEmbeddingFunction:
    def __call__(self, input):
        return [[0.0] * 384 for _ in input]  # Vector giả
```
Điều này có nghĩa ChromaDB chưa thực sự so sánh ngữ nghĩa — nó sẽ fallback
về tìm kiếm từ khóa đơn giản. Để hệ thống RAG hoạt động đúng nghĩa vector,
cần thay bằng model embedding thực (ví dụ: `all-MiniLM-L6-v2` từ
`sentence-transformers`, hoặc `text-embedding-3-small` của OpenAI).

> **Kết luận:** File upload → parse text → chunk → vector → lưu ChromaDB.
> Khi user hỏi → câu hỏi cũng được vector hóa → so sánh khoảng cách
> cosine với các chunk → lấy phần liên quan nhất đưa vào prompt LLM.

---

## Câu hỏi 4: Cơ chế Chat Text thay đổi Lịch học trong DB như thế nào?

### Tóm tắt
LLM đóng vai trò **bộ não phân tích intent**, trả về JSON có trường `action`.
Backend đọc `action` đó rồi thực thi thay đổi vào DB — không phải LLM trực tiếp ghi DB.

### Cơ chế chi tiết (Agent Pattern: Intent → Action → DB)

#### 4.1 Bước 1: User nhập text → LLM phân tích intent

User nhắn: *"Cho tôi học vào thứ 2, 4, 6, lý thuyết lúc 8h, bài tập 9h, kiểm tra 10h"*

LLM đọc system prompt (trong đó có mô tả các `action` được hỗ trợ) và trả về JSON:

```json
{
  "reply": "Tôi đã cập nhật lịch học của bạn thành...",
  "action": {
    "type": "update_profile",
    "params": {
      "learning_frequency": "Thứ 2, Thứ 4, Thứ 6",
      "theory_time": "08:00",
      "practice_time": "09:00",
      "exam_time": "10:00"
    }
  }
}
```

#### 4.2 Bước 2: Backend parse JSON và đọc `action`

```python
# tutor_service.py — handle_message()
response_text = await self.llm_service.generate_response(...)

# Parse JSON response
data = json.loads(response_text)
reply  = data.get("reply", "")
action = data.get("action", None)   # <-- Đây là "lệnh" từ LLM
```

#### 4.3 Bước 3: Backend thực thi `action` → Ghi vào DB

```python
# tutor_service.py
if action and isinstance(action, dict):
    action_type = action.get("type")
    params      = action.get("params", {})

    if action_type == "update_profile":
        # Cập nhật tần suất học
        if "learning_frequency" in params:
            student.learning_frequency = params["learning_frequency"]

        # Cập nhật các khung giờ (có normalize format HH:MM)
        for t_field in ["theory_time", "practice_time", "exam_time"]:
            if t_field in params:
                val = str(params[t_field]).strip()
                val = val.lower().replace('h', ':').replace('g', ':')
                # Chuẩn hóa về "HH:MM"
                parts = val.split(':')
                h, m = int(parts[0]), int(parts[1])
                val = f"{h:02d}:{m:02d}"
                setattr(student, t_field, val)   # Ghi vào object Student

        db.commit()  # <-- Lưu vào SQLite

        # Cập nhật lại lịch APScheduler
        if self.scheduler_service:
            await self.scheduler_service.update_schedule(student_id)
```

#### 4.4 Bước 4: `update_schedule()` xóa job cũ và tạo job mới

```python
# scheduler_service.py — update_schedule()
async def update_schedule(self, student_id):
    # 1. Hủy toàn bộ job tự động đang chờ
    jobs = db.query(ScheduledJob).filter(
        ScheduledJob.student_id == student_id,
        ScheduledJob.status == "pending",
        ScheduledJob.is_auto == True
    ).all()
    for job in jobs:
        job.status = "cancelled"
        self.scheduler.remove_job(job.apscheduler_job_id)  # Xóa khỏi APScheduler

    # 2. Đọc lại lịch mới từ student profile (vừa được cập nhật)
    student = db.query(Student).filter(Student.id == student_id).first()
    theory_time  = student.theory_time   # "08:00"
    practice_time = student.practice_time  # "09:00"
    exam_time    = student.exam_time     # "10:00"

    # 3. Tính các ngày học trong tương lai dựa trên learning_frequency
    dates = self._get_learning_dates(student, now, len(uncompleted_topics), exam_time)

    # 4. Tạo job mới cho Theory, Practice, Exam của từng topic
    for topic in uncompleted_topics:
        for job_type, time_str in [("theory", theory_time), ("practice", practice_time), ("exam", exam_time)]:
            run_time = ...  # Kết hợp ngày + giờ
            await self.schedule_homework(student_id, topic, run_time, is_auto=True, job_type=job_type)
```

#### 4.5 Luồng hoàn chỉnh (Sơ đồ)

```
User: "Học thứ 2,4,6 lúc 8h/9h/10h"
    │
    ▼ tutor_service.handle_message()
    │
    ├─ [1] Xây dựng system_prompt (mô tả action "update_profile")
    ├─ [2] Gọi LLM → LLM phân tích intent → trả về JSON + action
    ├─ [3] Parse action: type="update_profile", params={...}
    ├─ [4] Ghi vào DB: student.theory_time="08:00", ...  → db.commit()
    └─ [5] Gọi scheduler_service.update_schedule(student_id)
               ├─ Xóa job cũ (APScheduler + DB)
               ├─ Tính lịch mới (Thứ 2, 4, 6 sắp tới)
               └─ Tạo job mới: Theory@08:00, Practice@09:00, Exam@10:00

→ Kết quả: DB và APScheduler đều được cập nhật
→ Dashboard reload → hiển thị lịch học mới
```

#### 4.6 Các Action Type được hỗ trợ
| Action Type | Tác động vào DB |
|---|---|
| `update_profile` | Cập nhật `Student.theory_time`, `practice_time`, `exam_time`, `learning_frequency` |
| `generate_roadmap` | Tạo mới `Roadmap` + `Progress` records |
| `schedule_homework` | Tạo `ScheduledJob` mới + thêm job vào APScheduler |
| `grade_exam` | Cập nhật `Progress.score`, `Progress.status`, tạo `HomeworkSubmission` |
| `grade_homework` | Tạo `HomeworkSubmission` (không chạm `Progress`) |
| `update_subtask` | Cập nhật `Progress.theory_completed` hoặc `exercise_completed` |

> **Kết luận:** Chat text → LLM phân tích ý định và trả về JSON chứa `action` →
> Backend execute action → ghi vào DB → cập nhật APScheduler. LLM đóng vai trò
> "phiên dịch ngôn ngữ tự nhiên sang lệnh cấu trúc", không trực tiếp truy cập DB.

---

## Tổng kết kiến trúc

```
┌─────────────────────────────────────────────────────────────────┐
│                        AI TUTOR SYSTEM                          │
├─────────────────────────────────────────────────────────────────┤
│  User Input (text)                                              │
│       │                                                         │
│       ▼                                                         │
│  [TutorService.handle_message()]                                │
│       │                                                         │
│       ├── [MemoryService] Lấy 10 tin nhắn gần nhất từ SQLite   │
│       │        (riêng cho student_id này)                       │
│       │                                                         │
│       ├── [RAGService] Tìm chunks liên quan từ ChromaDB        │
│       │        (collection "student_N_docs" riêng biệt)        │
│       │                                                         │
│       ├── Build system_prompt (profile + roadmap + actions)    │
│       │                                                         │
│       ├── [LLMService] Gọi provider hiện tại                   │
│       │        (Gemini / OpenAI / OpenRouter)                   │
│       │        → Trả về JSON {reply, action}                   │
│       │                                                         │
│       ├── Parse action → Execute → Ghi DB                      │
│       │        (update_profile, grade_exam, schedule, ...)      │
│       │                                                         │
│       └── [MemoryService] Lưu cả 2 tin nhắn vào SQLite        │
│                (user + ai reply, để làm context lần sau)       │
└─────────────────────────────────────────────────────────────────┘
```

| Thành phần | File | Vai trò |
|---|---|---|
| `MemoryService` | `memory_service.py` | Lưu/đọc lịch sử chat per-user |
| `RAGService` | `rag_service.py` | Vector store per-user cho tài liệu |
| `LLMService` | `llm_service.py` | Gọi LLM, hỗ trợ đa provider |
| `TutorService` | `tutor_service.py` | Orchestrator: kết nối tất cả services |
| `SchedulerService` | `scheduler_service.py` | Lên lịch & trigger bài học tự động |
