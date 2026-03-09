from app import create_app, init_db
import logging

# Ensure the database is initialized
init_db()

app = create_app()

if __name__ == "__main__":
    app.run()
