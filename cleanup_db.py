import sqlite3
import os

DATABASE = 'database.sqlite'

def cleanup_db():
    if not os.path.exists(DATABASE):
        print(f"Database {DATABASE} not found.")
        return

    db = sqlite3.connect(DATABASE)
    try:
        with db:
            print("Clearing users...")
            db.execute('DELETE FROM users')
            print("Clearing candidates...")
            db.execute('DELETE FROM candidates')
            print("Clearing interviews...")
            db.execute('DELETE FROM interviews')
            print("Clearing final_scores...")
            db.execute('DELETE FROM final_scores')
            print("Clearing email_verifications...")
            db.execute('DELETE FROM email_verifications')
            
            # Reset autoincrement
            db.execute("DELETE FROM sqlite_sequence WHERE name IN ('users', 'candidates', 'interviews', 'email_verifications')")
            
        print("Database cleanup successful.")
    except Exception as e:
        print(f"Error during cleanup: {e}")
    finally:
        db.close()

if __name__ == '__main__':
    cleanup_db()
