import os
import smtplib
from email.mime.text import MIMEText
import logging

logger = logging.getLogger(__name__)

def send_otp_email(to_email: str, otp_code: str):
    sender_email = os.getenv("SMTP_EMAIL")
    app_password = os.getenv("SMTP_APP_PASSWORD")

    if not sender_email or not app_password:
        logger.warning("SMTP_EMAIL hoặc SMTP_APP_PASSWORD chưa được cấu hình. OTP được in ra console thay thế.")
        print(f"=== MÃ OTP CHO EMAIL {to_email} LÀ: {otp_code} ===")
        return False

    try:
        msg = MIMEText(f"Chào bạn,\n\nMã xác thực OTP của bạn tại nền tảng AI Tutor là: {otp_code}\n\nTrân trọng,\nAI Tutor Team")
        msg["Subject"] = "Mã xác thực OTP - AI Tutor"
        msg["From"] = sender_email
        msg["To"] = to_email

        server = smtplib.SMTP("smtp.gmail.com", 587)
        server.starttls()
        server.login(sender_email, app_password)
        server.send_message(msg)
        server.quit()
        logger.info(f"Đã gửi OTP đến {to_email} thành công.")
        return True
    except Exception as e:
        logger.error(f"Lỗi khi gửi email OTP tới {to_email}: {e}")
        print(f"=== LỖI GỬI MAIL. MÃ OTP DỰ PHÒNG LÀ: {otp_code} ===")
        return False
