"""Shop web app."""
from flask import Flask

from app.views import bp


def create_app():
    app = Flask(__name__)
    app.register_blueprint(bp, url_prefix="/shop")
    return app
