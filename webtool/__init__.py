import subprocess
import sys
import os
import logging

from functools import partial
from pathlib import Path

# first-run.py ensures everything is set up right when running 4CAT for the first time
first_run = Path(__file__).parent.parent.joinpath("helper-scripts", "first-run.py")
result = subprocess.run([sys.executable, str(first_run)], stdout=subprocess.PIPE,
                        stderr=subprocess.PIPE)

if result.returncode != 0:
    print("Unexpected error while preparing 4CAT. You may need to re-install 4CAT.")
    print("stdout:\n".join(["  " + line for line in result.stdout.decode("utf-8").split("\n")]))
    print("stderr:\n".join(["  " + line for line in result.stderr.decode("utf-8").split("\n")]))
    exit(1)

from flask import Flask
from flask_login import LoginManager
from flask_limiter import Limiter
from flask_limiter.util import get_remote_address
from werkzeug.middleware.proxy_fix import ProxyFix
from werkzeug import Request

from common.config_manager import config
from common.lib.database import Database
from common.lib.logger import Logger
from common.lib.queue import JobQueue
from common.lib.module_loader import ModuleCollector

from common.lib.user import User
from webtool.lib.helpers import generate_css_colours

# initialize global objects for interacting with all the things
login_manager = LoginManager()
app = Flask(__name__)
fourcat_modules = ModuleCollector()

# this ensures that HTTPS is properly applied to built URLs even if the app
# is running behind a proxy
# see https://stackoverflow.com/a/45333882
proxy_overrides = {param: 1 for param in config.get("flask.proxy_override")}
app.wsgi_app = ProxyFix(app.wsgi_app, **proxy_overrides)

if config.get("USING_DOCKER"):
    # rename 4cat.log to 4cat_frontend.log
    # Normally this is mostly empty; could combine it, but may be useful to identify processes running on both front and backend
    log = Logger(logger_name='4cat-frontend', filename='frontend_4cat.log')

else:
    log = Logger(logger_name='4cat-frontend')

# Set up logging for Gunicorn
if "gunicorn" in os.environ.get("SERVER_SOFTWARE", ""):
    # Add Gunicorn error log to main app logger
    gunicorn_logger = logging.getLogger('gunicorn.error')
    app.logger.handlers = gunicorn_logger.handlers
    app.logger.setLevel(gunicorn_logger.level) # debug is int 10

    # Gunicorn Error Log file
    error_file_path = Path(config.get('PATH_ROOT'), config.get('PATH_LOGS'), 'error_gunicorn.log')
    file_handler = logging.handlers.RotatingFileHandler(
                                                        filename=error_file_path,
                                                        maxBytes=int( 50 * 1024 * 1024),
                                                        backupCount= 1,
                                                        )
    logFormatter = logging.Formatter("%(asctime)s [%(levelname)-5.5s]  %(message)s")
    file_handler.setFormatter(logFormatter)
    app.logger.addHandler(file_handler)

if app.logger.getEffectiveLevel() == 10:
    # if we're in debug mode, we want to see how long it takes to load datasets
    import time
    from functools import wraps
    def time_this(func):
        @wraps(func)
        def wrapper(*args, **kwargs):
            start_time = time.time()
            r = func(*args, **kwargs)
            app.logger.debug("%s dataset took %.2f seconds" % (func.__name__, time.time() - start_time))
            return r
        return wrapper
else:
    def time_this(func):
        return func

db = Database(logger=log, dbname=config.get("DB_NAME"), user=config.get("DB_USER"),
              password=config.get("DB_PASSWORD"), host=config.get("DB_HOST"),
              port=config.get("DB_PORT"), appname="frontend")
config.with_db(db)
queue = JobQueue(logger=log, database=db)

# initialize openapi endpoint collector for later specification generation
from webtool.lib.openapi_collector import OpenAPICollector
openapi = OpenAPICollector(app)

# initialize rate limiter
limiter = Limiter(app=app, key_func=get_remote_address)

# make sure a secret key was set in the config file, for secure session cookies
if not config.get("flask.secret_key") or config.get("flask.secret_key") == "REPLACE_THIS":
    raise Exception("You need to set the flask.secret_key setting running the web tool.")

# initialize login manager
app.config.from_mapping({
    "FLASK_APP": config.get("flask.flask_app"),
    "SECRET_KEY": config.get("flask.secret_key"),
    "SERVER_NAME": config.get("flask.server_name"),
    "SERVER_HTTPS": config.get("flask.https"),
    "HOSTNAME_WHITELIST": config.get("flask.autologin.hostnames"),
    "HOSTNAME_WHITELIST_NAME": config.get("flask.autologin.name"),
    "HOSTNAME_WHITELIST_API": config.get("flask.autologin.api"),
    "PREFERRED_URL_SCHEME": "https" if config.get("flask.https") else "http"
})
login_manager.anonymous_user = partial(User.get_by_name, db=db, name="anonymous")
login_manager.init_app(app)
login_manager.login_view = "show_login"

# Set number of form parts to accept (default is 1000; affects number of files that can be uploaded)
Request.max_form_parts = config.get("flask.max_form_parts", 1000)

# import all views
import webtool.views.views_admin
import webtool.views.views_extensions
import webtool.views.views_restart
import webtool.views.views_user

import webtool.views.views_dataset
import webtool.views.views_misc
import webtool.views.views_explorer

import webtool.views.api_standalone
import webtool.views.api_tool

# import custom jinja2 template filters
import webtool.lib.template_filters

# ensure that colour definition CSS file is present
generate_css_colours()

# run it
if __name__ == "__main__":
    print('Starting server...')
    app.run(host='0.0.0.0', debug=True)
