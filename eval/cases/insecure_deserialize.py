import pickle

from flask import Flask, request

app = Flask(__name__)


@app.route("/restore", methods=["POST"])
def restore():
    state = pickle.loads(request.data)  # expect: security
    return {"keys": list(state)}
