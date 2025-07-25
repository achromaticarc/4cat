"""
Actions to execute the first time a 4CAT instance is run

There are some things that should be done once, and only once, in the life of
a 4CAT instance. These are set-up actions that cannot be handled by e.g.
running pip or setup.py because they rely on things not available to those
processes or that could interfere with other processes run at that time.

This file is only fully  executed if the file .current-version does NOT exist
in the 4CAT root folder. The file is created if it does not exist yet, ensuring
the set-up actions in this file are only ever run once.

It should not be necessary to run this file directly; it is run automatically
by 4CAT while starting up. Note that it never runs in a Docker context, since
Docker runs migrate.py whenever a container starts, and that essentially does
the same job as this script (and a lot more, which is why this lightweight
version also exists, since we don't need that extra code to also run when
running 4CAT from the command line manually).
"""
import shutil
import sys
from pathlib import Path

# make sure version files are in order
version_file = Path(__file__).resolve().parent.parent.joinpath("VERSION")
if not version_file.exists():
    # this file should ALWAYS exist, because it is part of the repository, and
    # required by other parts of 4CAT. If it's absent, something has gone
    # wrong, and the preferred course of action is restarting from scratch
    print("VERSION file not found. You should re-install 4CAT before continuing.", file=sys.stderr)
    exit(1)

# If any .current-version file exists, we don't need to do anything (though the sys admin may need to run migrate.py)
current_version_files = [".current-version", "config/.current-version"]
for current_version_file in current_version_files:
    current_version_file = version_file.parent.joinpath(current_version_file)
    if current_version_file.exists():
        # this file does not exist by default, so if it does, that means we don't
        # need to do further on-boarding since 4CAT has already been run
        exit(0)

shutil.copy(version_file, current_version_file)

# Now check for presence of required NLTK packages
import nltk  # noqa: E402
nltk_downloads = ("wordnet", "punkt_tab", "omw-1.4")
for package in nltk_downloads:
    # if it already exists, .download() will just NOP
    try:
        nltk.download(package)
    except FileExistsError:
        pass 
