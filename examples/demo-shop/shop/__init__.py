"""demo-shop web app."""
from flask import Flask


def create_app():
    from shop.web import bp
    app = Flask(__name__)
    app.register_blueprint(bp, url_prefix="/shop")
    return app
