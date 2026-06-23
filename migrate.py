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
        
    conn.commit()
    conn.close()
    print("Database altered successfully.")
except Exception as e:
    print("Error:", e)
