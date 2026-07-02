import os
import json
import logging
from typing import Dict, Any, List

logger = logging.getLogger(__name__)

class LLMService:
    def __init__(self):
        self.gemini_client = None
        self.openai_client = None
        self.openrouter_client = None
        self.reload_config()

    def reload_config(self):
        """Re-read LLM settings from environment (after .env update from UI)."""
        self.api_provider = os.getenv("LLM_PROVIDER", "mock").lower()
        self.openai_key = os.getenv("OPENAI_API_KEY")
        self.gemini_key = os.getenv("GEMINI_API_KEY")
        self.openrouter_key = os.getenv("OPENROUTER_API_KEY")
        self.openai_model = os.getenv("OPENAI_MODEL", "gpt-4o-mini")
        self.gemini_model = os.getenv("GEMINI_MODEL", "gemini-2.5-flash")
        self.openrouter_model = os.getenv("OPENROUTER_MODEL", "google/gemma-3-27b-it:free")

        self.gemini_client = None
        self.openai_client = None
        self.openrouter_client = None

        if self.gemini_key:
            try:
                import google.generativeai as genai
                genai.configure(api_key=self.gemini_key)
                self.gemini_client = genai
                logger.info("Gemini LLM Client initialized successfully.")
            except ImportError:
                logger.warning("google-generativeai package not installed.")

        if self.openai_key:
            try:
                from openai import OpenAI
                self.openai_client = OpenAI(api_key=self.openai_key)
                logger.info("OpenAI LLM Client initialized successfully.")
            except ImportError:
                logger.warning("openai package not installed.")

        if self.openrouter_key:
            try:
                from openai import OpenAI
                self.openrouter_client = OpenAI(
                    api_key=self.openrouter_key,
                    base_url="https://openrouter.ai/api/v1"
                )
                logger.info(f"OpenRouter LLM Client initialized with model: {self.openrouter_model}")
            except ImportError:
                logger.warning("openai package not installed.")

        from backend.services.config_service import _mask_key, _terminal_log
        logger.info(f"LLM provider active: {self.api_provider}")
        _terminal_log(
            f"[LLM Config] Da reload - provider: {self.api_provider} | "
            f"Gemini: {_mask_key(self.gemini_key or '') or '-'} | "
            f"OpenAI: {_mask_key(self.openai_key or '') or '-'} | "
            f"OpenRouter: {_mask_key(self.openrouter_key or '') or '-'}"
        )

    async def generate_response(self, system_prompt: str, user_prompt: str, chat_history: List[Dict[str, str]] = None) -> str:
        if self.api_provider == "mock":
            self.last_token_usage = {"prompt_tokens": 15, "completion_tokens": 45, "total_tokens": 60}
            return self.get_mock_fallback(system_prompt, user_prompt)

        # Build ordered list of providers to try: primary first, then others as fallback
        provider_order = [self.api_provider]
        for p in ["gemini", "openrouter", "openai"]:
            if p not in provider_order:
                provider_order.append(p)

        for provider in provider_order:
            result = await self._try_provider(provider, system_prompt, user_prompt, chat_history)
            if result is not None:
                return result

        logger.warning("All LLM providers failed. Using mock fallback.")
        self.last_token_usage = {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0}
        return self.get_mock_fallback(system_prompt, user_prompt)

    async def analyze_page_image(self, image_bytes: bytes, prompt: str) -> str:
        if self.api_provider == "mock":
            self.last_token_usage = {"prompt_tokens": 250, "completion_tokens": 50, "total_tokens": 300}
            return "[Mock AI Image Description: Mô tả hình ảnh trang tài liệu học tập, bao gồm các hình vẽ và bài tập toán học.]"

        provider_order = [self.api_provider]
        for p in ["gemini", "openrouter", "openai"]:
            if p not in provider_order:
                provider_order.append(p)

        for provider in provider_order:
            result = await self._try_provider_image(provider, image_bytes, prompt)
            if result is not None:
                return result

        logger.warning("All LLM providers failed to analyze image. Returning fallback message.")
        return "[Lỗi: Tất cả các nhà cung cấp AI đều không thể phân tích ảnh này.]"

    async def _try_provider_image(self, provider: str, image_bytes: bytes, prompt: str) -> str:
        if provider == "gemini" and self.gemini_client:
            try:
                import io
                from PIL import Image
                image = Image.open(io.BytesIO(image_bytes))
                
                model = self.gemini_client.GenerativeModel(model_name=self.gemini_model)
                response = model.generate_content([image, prompt])
                if hasattr(response, 'usage_metadata'):
                    self.last_token_usage = {
                        "prompt_tokens": getattr(response.usage_metadata, 'prompt_token_count', 0),
                        "completion_tokens": getattr(response.usage_metadata, 'candidates_token_count', 0),
                        "total_tokens": getattr(response.usage_metadata, 'total_token_count', 0)
                    }
                return response.text
            except Exception as e:
                logger.error(f"Gemini image analysis failed: {e}")
                return None

        elif provider == "openai" and self.openai_client:
            try:
                import base64
                base64_image = base64.b64encode(image_bytes).decode('utf-8')
                
                messages = [
                    {
                        "role": "user",
                        "content": [
                            {"type": "text", "text": prompt},
                            {
                                "type": "image_url",
                                "image_url": {
                                    "url": f"data:image/png;base64,{base64_image}"
                                }
                            }
                        ]
                    }
                ]
                
                response = self.openai_client.chat.completions.create(
                    model=self.openai_model,
                    messages=messages,
                    max_tokens=1000
                )
                if hasattr(response, 'usage') and response.usage:
                    self.last_token_usage = {
                        "prompt_tokens": getattr(response.usage, 'prompt_tokens', 0),
                        "completion_tokens": getattr(response.usage, 'completion_tokens', 0),
                        "total_tokens": getattr(response.usage, 'total_tokens', 0)
                    }
                return response.choices[0].message.content
            except Exception as e:
                logger.error(f"OpenAI image analysis failed: {e}")
                return None

        elif provider == "openrouter" and self.openrouter_client:
            try:
                import base64
                base64_image = base64.b64encode(image_bytes).decode('utf-8')
                
                messages = [
                    {
                        "role": "user",
                        "content": [
                            {"type": "text", "text": prompt},
                            {
                                "type": "image_url",
                                "image_url": {
                                    "url": f"data:image/png;base64,{base64_image}"
                                }
                            }
                        ]
                    }
                ]
                
                response = self.openrouter_client.chat.completions.create(
                    model=self.openrouter_model,
                    messages=messages,
                    max_tokens=1000
                )
                if hasattr(response, 'usage') and response.usage:
                    self.last_token_usage = {
                        "prompt_tokens": getattr(response.usage, 'prompt_tokens', 0),
                        "completion_tokens": getattr(response.usage, 'completion_tokens', 0),
                        "total_tokens": getattr(response.usage, 'total_tokens', 0)
                    }
                return response.choices[0].message.content
            except Exception as e:
                logger.error(f"OpenRouter image analysis failed: {e}")
                return None

        return None

    async def _try_provider(self, provider: str, system_prompt: str, user_prompt: str, chat_history: List[Dict[str, str]] = None) -> str:
        """Try a single provider. Returns response string on success, None on failure."""
        if provider == "gemini" and self.gemini_client:
            try:
                import google.generativeai as genai
                model = genai.GenerativeModel(
                    model_name=self.gemini_model,
                    system_instruction=system_prompt if system_prompt else None
                )

                is_json_required = "valid JSON object" in system_prompt if system_prompt else False
                generation_config = {}
                if is_json_required:
                    generation_config["response_mime_type"] = "application/json"

                contents = []
                if chat_history:
                    for msg in chat_history:
                        role = "user" if msg["role"] == "user" else "model"
                        contents.append({"role": role, "parts": [msg["content"]]})
                contents.append({"role": "user", "parts": [user_prompt]})

                response = model.generate_content(contents, generation_config=generation_config if generation_config else None)
                if hasattr(response, 'usage_metadata'):
                    self.last_token_usage = {
                        "prompt_tokens": getattr(response.usage_metadata, 'prompt_token_count', 0),
                        "completion_tokens": getattr(response.usage_metadata, 'candidates_token_count', 0),
                        "total_tokens": getattr(response.usage_metadata, 'total_token_count', 0)
                    }
                return response.text
            except Exception as e:
                logger.error(f"Gemini API call failed: {e}. Trying next provider...")
                return None

        elif provider == "openai" and self.openai_client:
            try:
                is_json_required = "valid JSON object" in system_prompt if system_prompt else False
                messages = self._build_openai_messages(system_prompt, user_prompt, chat_history)
                kwargs = {
                    "model": self.openai_model,
                    "messages": messages,
                    "temperature": 0.7
                }
                if is_json_required:
                    kwargs["response_format"] = {"type": "json_object"}
                    
                response = self.openai_client.chat.completions.create(**kwargs)
                if hasattr(response, 'usage') and response.usage:
                    self.last_token_usage = {
                        "prompt_tokens": getattr(response.usage, 'prompt_tokens', 0),
                        "completion_tokens": getattr(response.usage, 'completion_tokens', 0),
                        "total_tokens": getattr(response.usage, 'total_tokens', 0)
                    }
                return response.choices[0].message.content
            except Exception as e:
                logger.error(f"OpenAI API call failed: {e}. Trying next provider...")
                return None

        elif provider == "openrouter" and self.openrouter_client:
            try:
                is_json_required = "valid JSON object" in system_prompt if system_prompt else False
                messages = self._build_openai_messages(system_prompt, user_prompt, chat_history)
                kwargs = {
                    "model": self.openrouter_model,
                    "messages": messages,
                    "temperature": 0.7
                }
                if is_json_required:
                    kwargs["response_format"] = {"type": "json_object"}

                response = self.openrouter_client.chat.completions.create(**kwargs)
                if hasattr(response, 'usage') and response.usage:
                    self.last_token_usage = {
                        "prompt_tokens": getattr(response.usage, 'prompt_tokens', 0),
                        "completion_tokens": getattr(response.usage, 'completion_tokens', 0),
                        "total_tokens": getattr(response.usage, 'total_tokens', 0)
                    }
                return response.choices[0].message.content
            except Exception as e:
                logger.error(f"OpenRouter API call failed: {e}. Trying next provider...")
                return None

        return None  # Provider not available

    def _build_openai_messages(self, system_prompt: str, user_prompt: str, chat_history: List[Dict[str, str]] = None) -> list:
        """Build messages array for OpenAI-compatible APIs."""
        messages = []
        if system_prompt:
            messages.append({"role": "system", "content": system_prompt})
        if chat_history:
            for msg in chat_history:
                role = "user" if msg["role"] == "user" else "assistant"
                messages.append({"role": role, "content": msg["content"]})
        messages.append({"role": "user", "content": user_prompt})
        return messages


    def get_mock_fallback(self, system_prompt: str, user_prompt: str) -> str:
        # Check if this is a structured curriculum design request
        sys_lower = system_prompt.lower() if system_prompt else ""
        if "curriculum designer" in sys_lower or "raw json list" in sys_lower:
            subject = "Python Basics"
            try:
                for line in user_prompt.split("\n"):
                    if "subject:" in line.lower():
                        subject = line.split(":", 1)[1].strip()
                        break
            except Exception:
                pass
            return json.dumps([
                {"title": f"Introduction to {subject}", "description": f"Learn the basics and setup for {subject}.", "estimated_hours": 4},
                {"title": f"Core Concepts of {subject}", "description": f"Understand the fundamental syntax and concepts of {subject}.", "estimated_hours": 8},
                {"title": f"Advanced {subject} & Projects", "description": f"Build practical hands-on exercises in {subject}.", "estimated_hours": 12}
            ], ensure_ascii=False)
        
        return self._generate_mock_response(user_prompt)

    def _generate_mock_response(self, user_prompt: str) -> str:
        # Structured mock response that returns correct actions based on prompts
        user_prompt_lower = user_prompt.lower()
        
        # Check for scheduling requests
        if any(keyword in user_prompt_lower for keyword in ["schedule", "giao bài tập", "hẹn giờ", "bài tập", "homework"]):
            # Detect minutes/seconds or default
            delay = 60
            # Default topic if we cannot extract a specific one
            topic = "Lập trình Python cơ bản"
            # Try to extract a custom topic from the user prompt
            import re
            match = re.search(r"bài tập\s+([^,.!?\n]+)", user_prompt, re.IGNORECASE)
            if match:
                extracted = match.group(1).strip()
                # Clean up trailing words like "sau" or "trong" if present
                extracted = re.split(r"\s+(sau|trong)\s+", extracted)[0].strip()
                if extracted:
                    topic = extracted
            # Adjust delay and possibly topic based on time keywords
            if "phút" in user_prompt_lower or "minute" in user_prompt_lower:
                delay = 60
                # keep extracted topic if any, otherwise fallback
            elif "2 phút" in user_prompt_lower or "2 minutes" in user_prompt_lower:
                delay = 120
                # keep extracted topic if any, otherwise fallback
            
            from datetime import datetime, timedelta
            scheduled_time = (datetime.now() + timedelta(seconds=delay)).isoformat()
            
            return json.dumps({
                "reply": f"Chào bạn! Tôi đã nhận được yêu cầu lên lịch bài tập của bạn. Hệ thống sẽ tự động giao bài tập về **{topic}** sau {delay} giây nữa thông qua chat/Telegram.\n\nNgoài ra, bạn cũng có thể tự hẹn giờ giao bài tập bất kỳ lúc nào bằng biểu mẫu **Lịch bài tập đã hẹn** ở góc dưới bên phải: Nhập chủ đề, chọn thời gian và bấm nút **Đặt lịch**.",
                "action": {
                    "type": "schedule_homework",
                    "params": {
                        "topic": topic,
                        "scheduled_time": scheduled_time,
                        "job_type": "practice"
                    }
                }
            }, ensure_ascii=False)
            
        # Check for roadmap requests
        elif any(keyword in user_prompt_lower for keyword in ["roadmap", "lộ trình", "curriculum"]):
            subject = "Python"
            if "web" in user_prompt_lower:
                subject = "Lập trình Web (HTML/CSS/JS)"
            elif "data" in user_prompt_lower:
                subject = "Khoa học Dữ liệu (Data Science)"
                
            return json.dumps({
                "reply": f"Chào bạn! Tôi đã thiết kế lộ trình học chi tiết môn **{subject}** và đồng bộ lên thanh tiến độ học tập ở cột bên phải.\n\nNgoài ra, bạn cũng có thể tự tạo lộ trình học mới bằng cách nhập tên môn học vào ô nhập ở mục **Lộ trình học tập** ở góc trên bên phải và nhấn nút **Tạo**.",
                "action": {
                    "type": "generate_roadmap",
                    "params": {
                        "subject": subject
                    }
                }
            }, ensure_ascii=False)
            
        # Check for profile updates
        elif any(keyword in user_prompt_lower for keyword in ["đổi mục tiêu", "update profile", "mục tiêu học", "level"]):
            new_goal = "Machine Learning & AI"
            new_level = "Intermediate"
            
            return json.dumps({
                "reply": f"Tôi đã cập nhật mục tiêu học tập của bạn thành **{new_goal}** và trình độ thành **{new_level}**.\n\nBạn cũng có thể chỉnh sửa thông tin này trực tiếp bất kỳ lúc nào bằng cách sử dụng biểu mẫu **Thông tin học tập** ở góc trên bên trái: thay đổi Tên hiển thị, Mục tiêu học tập, hoặc Trình độ, sau đó bấm **Cập nhật thông tin**.",
                "action": {
                    "type": "update_profile",
                    "params": {
                        "learning_goals": new_goal,
                        "skill_level": new_level
                    }
                }
            }, ensure_ascii=False)
            
        elif any(keyword in user_prompt_lower for keyword in ["đổi lịch", "lịch học", "hằng ngày", "mỗi ngày", "cập nhật lịch"]):
            return json.dumps({
                "reply": "Tôi đã cập nhật lịch học của bạn thành **Hàng ngày** với các khung giờ:\n- Lý thuyết: 19:00\n- Bài tập: 19:30\n- Kiểm tra: 20:00.\n\nLịch học hôm nay và danh sách bài tập đã được làm mới ở cột bên phải.",
                "action": {
                    "type": "update_profile",
                    "params": {
                        "learning_frequency": "Hàng ngày",
                        "theory_time": "19:00",
                        "practice_time": "19:30",
                        "exam_time": "20:00"
                    }
                }
            }, ensure_ascii=False)
            
        # Standard conversation
        else:
            return json.dumps({
                "reply": "Chào bạn! Tôi là AI Tutor của bạn. Tôi có thể hỗ trợ giải đáp mọi thắc mắc kiến thức hoặc hướng dẫn bạn học tập.\n\n"
                         "Khi muốn thực hiện các thao tác trên hệ thống, bạn có thể tự mình thao tác trực tiếp trên giao diện Dashboard:\n"
                         "- 👤 **Cập nhật mục tiêu/trình độ**: Hãy sử dụng biểu mẫu **Thông tin học tập** ở góc trái.\n"
                         "- 📚 **Tải tài liệu học tập (RAG)**: Nhấn nút **Tải tài liệu lên** ở góc trái để tải lên tài liệu học tập của bạn.\n"
                         "- 🗺️ **Tạo lộ trình học**: Nhập tên môn học vào ô dưới mục **Lộ trình học tập** ở góc phải rồi nhấn **Tạo**.\n"
                         "- ⏰ **Đặt lịch giao bài tập**: Điền chủ đề và thời gian tại mục **Lịch bài tập đã hẹn** ở góc phải rồi nhấn **Đặt lịch**.\n"
                         "- 💬 **Liên kết Telegram**: Lấy mã code ở phần **Liên kết Telegram** (góc trái) gửi cho Telegram Bot để nhận tin nhắn và bài tập qua điện thoại.\n\n"
                         "Hôm nay bạn muốn trao đổi hay học tập về nội dung nào? Hãy nhắn cho tôi nhé!",
                "action": None
            }, ensure_ascii=False)
