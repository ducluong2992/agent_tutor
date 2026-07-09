import sqlite3

try:
    conn = sqlite3.connect('backend/storage/tutor.db')
    c = conn.cursor()
    try:
        c.execute('ALTER TABLE students ADD COLUMN theory_time VARCHAR')
    except Exception as e:
        print("theory_time:", e)
        
    try:
        c.execute('ALTER TABLE students ADD COLUMN practice_time VARCHAR')
    except Exception as e:
        print("practice_time:", e)
        
    try:
        c.execute('ALTER TABLE students ADD COLUMN exam_time VARCHAR')
    except Exception as e:
        print("exam_time:", e)
        
    try:
        c.execute('ALTER TABLE students ADD COLUMN learning_frequency VARCHAR')
    except Exception as e:
        print("learning_frequency:", e)
        
    try:
        c.execute('ALTER TABLE students ADD COLUMN password_hash VARCHAR')
    except Exception as e:
        print("password_hash:", e)

    try:
        c.execute('ALTER TABLE students ADD COLUMN is_verified BOOLEAN DEFAULT 0')
    except Exception as e:
        print("is_verified:", e)

    try:
        c.execute('ALTER TABLE students ADD COLUMN otp_code VARCHAR')
    except Exception as e:
        print("otp_code:", e)

    try:
        c.execute('ALTER TABLE students ADD COLUMN age INTEGER')
    except Exception as e:
        print("age:", e)

    try:
        c.execute('ALTER TABLE students ADD COLUMN strengths_weaknesses TEXT')
    except Exception as e:
        print("strengths_weaknesses:", e)
        
    conn.commit()
    conn.close()
    print("Database altered successfully.")
except Exception as e:
    print("Error:", e)
