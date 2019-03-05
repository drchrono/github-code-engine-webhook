#!/usr/bin/env python
import io
import os
import re
import sys
import json
import subprocess
import requests
import ipaddress
import hmac
import alooma

from hashlib import sha1
from flask import Flask, request, abort


"""
Conditionally import ProxyFix from werkzeug if the USE_PROXYFIX environment
variable is set to true.  If you intend to import this as a module in your own
code, use os.environ to set the environment variable before importing this as a
module.

.. code:: python

    os.environ['USE_PROXYFIX'] = 'true'
    import flask-github-webhook-handler.index as handler

"""
if os.environ.get('USE_PROXYFIX', None) == 'true':
    from werkzeug.contrib.fixers import ProxyFix

app = Flask(__name__)
app.debug = os.environ.get('DEBUG') == 'true'

REPOS_JSON_PATH = os.environ['REPOS_JSON_PATH']
FILE_PATH = os.environ['CODE_ENGINE_FILE_PATH']
API_KEY = os.environ['ALOOMA_API_KEY']

ALOOMA_API = alooma.Client(api_key=API_KEY)


def upload_alooma_code_engine(file_path):
    """ Uploads Code Engine Script to Alooma """
    contents = {}
    for module in os.listdir(file_path):
        print(module, file=sys.stderr)
        if not os.path.isfile(os.path.join(file_path, module)):
            continue
        if not module.endswith(".py"):
            continue
        if module == "__init__.py":
            continue
        with open(os.path.join(file_path, module), "r") as f:
            contents[re.sub("/", ".", module)[-:3]] = f.read()
    return ALOOMA_API.set_code_engine_code(contents)


@app.route("/", methods=['GET', 'POST'])
def index():
    if request.method == 'GET':
        return 'OK'
    elif request.method == 'POST':
        # Store the IP address of the requester

        if request.headers.get('X-GitHub-Event') == "ping":
            return json.dumps({'msg': 'Hi!'})
        if request.headers.get('X-GitHub-Event') != "push":
            return json.dumps({'msg': "wrong event type"})

        repos = json.loads(io.open(REPOS_JSON_PATH, 'r').read())

        payload = request.get_json()
        repo_meta = {
            'name': payload['repository']['name'],
            'owner': payload['repository']['owner']['name'],
        }

        # Try to match on branch as configured in repos.json
        match = re.match(r"refs/heads/(?P<branch>.*)", payload['ref'])
        if match:
            repo_meta['branch'] = match.groupdict()['branch']
            repo = repos.get(
                '{owner}/{name}/branch:{branch}'.format(**repo_meta), None)

            # Fallback to plain owner/name lookup
            if not repo:
                repo = repos.get('{owner}/{name}'.format(**repo_meta), None)

        if repo and repo.get('path', None):
            # Check if POST request signature is valid
            key = repo.get('key', None)
            if key:
                signature = request.headers.get('X-Hub-Signature').split(
                    '=')[1]
                key = bytes(key, "utf-8")
                mac = hmac.new(key, msg=request.data, digestmod=sha1)
                if not hmac.compare_digest(mac.hexdigest(), signature):
                    abort(403)

        if repo.get('action', None):
            for action in repo['action']:
                subp = subprocess.Popen(action, cwd=repo.get('path', '.'))
                subp.wait()
        upload_alooma_code_engine(FILE_PATH)
        return 'OK'


if __name__ == "__main__":
    try:
        port_number = int(sys.argv[1])
    except:
        port_number = 8080
    if os.environ.get('USE_PROXYFIX', None) == 'true':
        app.wsgi_app = ProxyFix(app.wsgi_app)
    app.run(host='0.0.0.0', port=port_number)
