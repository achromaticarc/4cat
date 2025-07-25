"""
Create a new 4CAT user and send them a registration e-mail
"""

import argparse
import psycopg2
import json
import time
import sys
import re
import os

sys.path.insert(0, os.path.abspath(os.path.dirname(__file__)) + "/..")

from common.lib.database import Database
from common.lib.logger import Logger
from common.lib.user import User
from common.config_manager import CoreConfigManager, ConfigManager

log = Logger()
config = CoreConfigManager()
try:
    db = Database(logger=log, dbname=config.DB_NAME, user=config.DB_USER, password=config.DB_PASSWORD, host=config.DB_HOST, port=config.DB_PORT, appname="4cat-create-user")
except psycopg2.OperationalError:
    print(
        "Could not connect to database. Check that config.ini contains the correct database authentication details."
    )
    sys.exit(1)

cli = argparse.ArgumentParser()
cli.add_argument(
    "-u", "--username", required=True, help="Name of user (must be unique)"
)
cli.add_argument(
    "-p",
    "--password",
    help="Password (if left empty an e-mail will be sent to the user to reset it)",
)
cli.add_argument(
    "-e", "--noemail", help="Do not force an e-mail as username", action="store_true"
)
cli.add_argument(
    "-a", "--admin", help="Make this user an admin user", action="store_true"
)

args = cli.parse_args()

if __name__ != "__main__":
    sys.exit(1)

if not args.noemail and not re.match(r"[^@]+\@.*?\.[a-zA-Z]+", args.username):
    print("Please provide an e-mail address as username.")
    sys.exit(1)

try:
    tags = json.dumps(["admin"]) if args.admin else "[]"
    db.insert(
        "users",
        data={
            "name": args.username,
            "timestamp_token": int(time.time()),
            "timestamp_created": int(time.time()),
            "tags": json.dumps(tags),
        },
    )
except psycopg2.IntegrityError:
    print("Error: User %s already exists." % args.username)
    sys.exit(1)

user = User.get_by_name(db, args.username)
if user is None:
    print("Warning: User not created properly. No password reset e-mail sent.")
    sys.exit(1)


if args.password:
    user.set_password(args.password)
    print("User created and password set!")
else:
    if args.noemail:
        user.generate_token()
        print("User created! No registration e-mail will be sent.")
        print(
            "%s can complete their registration via the following token:\n%s"
            % (args.username, user.get_token())
        )
    else:
        try:
            db_config = ConfigManager()
            user.with_config(db_config)
            user.email_token(new=True)
            print(
                "An e-mail containing a link through which the registration can be completed has been sent to %s."
                % args.username
            )
        except (ValueError, RuntimeError) as e:
            print(
                """
WARNING: User created but no e-mail was sent. The following exception was raised:
   %s
	   
%s can complete their registration via the following token:
   %s"""
                % (e, args.username, user.get_token())
            )
