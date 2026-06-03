"""Flask Web 复盘页面入口。用法: python app.py"""
from flask import Flask
from web.routes import web


def create_app():
    app = Flask(__name__)
    app.register_blueprint(web)
    return app


if __name__ == "__main__":
    app = create_app()
    print("选股复盘页面启动: http://127.0.0.1:5000")
    app.run(host="0.0.0.0", port=5000, debug=False)
