import uvicorn
from dotenv import load_dotenv

# Load environmental variables
load_dotenv()

if __name__ == "__main__":
    # Khởi chạy server uvicorn từ backend/main.py
    uvicorn.run("backend.main:app", host="127.0.0.1", port=8000, reload=True)
