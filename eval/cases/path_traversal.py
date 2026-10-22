import os

from flask import Flask, request, send_file

app = Flask(__name__)
UPLOAD_DIR = "/srv/uploads"


@app.route("/download")
def download():
    name = request.args["name"]
    return send_file(os.path.join(UPLOAD_DIR, name))  # expect: security
