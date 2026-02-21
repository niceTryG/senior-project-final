from app import create_app

app = create_app()

if __name__ == "__main__":
    app.run(
        host="0.0.0.0",  # слушать на всех интерфейсах
        port=5000,       # можно оставить 5000
        debug=True
    )
