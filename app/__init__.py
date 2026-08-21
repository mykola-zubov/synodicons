from flask import Flask

def create_app():
    app = Flask(__name__,
                static_folder='static',
                template_folder='templates')

    app.secret_key = "synodikon_secret_key_slepche_2026"

    from .routes import main_bp
    app.register_blueprint(main_bp)

    return app