from app import create_app

app = create_app()

if __name__ == '__main__':
    # Используем порт 5001, чтобы не конфликтовать с TEI Publisher (порт 8080)
    app.run(debug=True, port=5001)