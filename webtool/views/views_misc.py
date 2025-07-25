"""
4CAT Web Tool views - pages to be viewed by the user
"""
import re
import csv
import json
import logging
import markdown2
import traceback

from pathlib import Path
from datetime import datetime

from flask import Blueprint, request, render_template, jsonify, Response, redirect, url_for, g, current_app
from flask_login import login_required
from werkzeug.exceptions import HTTPException, InternalServerError

from webtool.lib.helpers import pad_interval, error

from common.lib.helpers import get_datasource_example_keys

component = Blueprint("misc", __name__)

csv.field_size_limit(1024 * 1024 * 1024)

@component.app_errorhandler(Exception)
def log_exception(e):
    """
    Log all exceptions
    """
    if isinstance(e, HTTPException):
        status_code = e.code
        # Could handle specific HTTP errors here
    else:
        status_code = None

    # Check if it's an InternalServerError and extract the original exception
    if isinstance(e, InternalServerError) and e.original_exception:
        cause = e.original_exception
    else:
        cause = e

    if not status_code or status_code >= 500:
        # Capture the correct frame and log
        tb = traceback.extract_tb(cause.__traceback__)
        location = "→".join([f"{t.filename.split('/')[-1]}:{t.lineno}" for t in tb])

        # Get the request URL
        request_url = request.url

        msg = f"{type(cause).__name__}{(' ('+request_url+')') if request_url else ''}: {cause}"
        current_app.log.error(msg, frame=tb if tb else None)
        logging.error(msg + f" at {location}")

        return error(status_code if status_code else 500, message="An internal error occurred while processing your request.", status="error")
    else:
        # Should be just 4xx errors; return and allow Flask to handle them
        return e

@component.app_errorhandler(413)
def request_entity_too_large(this_error):
    message = "File too large; try uploading as a ZIP file instead."
    return error(413, message=message, status="error")

@component.route('/')
@login_required
def show_frontpage():
    """
    Index page: news and introduction

    :return:
    """
    page = g.config.get("ui.homepage")
    if page == "create-dataset":
        return redirect(url_for("dataset.create_dataset"))
    elif page == "datasets":
        return redirect(url_for("dataset.show_results"))
    else:
        return show_about()

@component.route("/about/")
@login_required
def show_about():
    # load corpus stats that are generated daily, if available
    stats_path = Path(g.config.get('PATH_ROOT'), "stats.json")
    if stats_path.exists():
        with stats_path.open() as stats_file:
            stats = stats_file.read()
        try:
            stats = json.loads(stats)
        except json.JSONDecodeError:
            stats = None
    else:
        stats = None

    news_path = Path(g.config.get('PATH_ROOT'), "news.json")
    if news_path.exists():
        with news_path.open() as news_file:
            news = news_file.read()
        try:
            news = json.loads(news)
            for item in news:
                if "time" not in item or "text" not in item:
                    raise RuntimeError()
        except (json.JSONDecodeError, RuntimeError):
            news = None
    else:
        news = None

    datasources = {k: v for k, v in g.modules.datasources.items() if
                   k in g.config.get("datasources.enabled") and not v["importable"]}
    importables = {k: v for k, v in g.modules.datasources.items() if (v["importable"] and k in g.config.get("datasources.enabled"))}

    return render_template("frontpage.html", stats=stats, news=news, datasources=datasources, importables=importables)


@component.route("/robots.txt")
def robots():
    """
    Display robots.txt

    Default to blocking everything, because the tool will (should) usually be
    run as an internal resource.
    """
    robots = Path(g.config.get("PATH_ROOT"), "webtool/static/robots.txt")
    if not robots.exists():
        return Response("User-agent: *\nDisallow: /", mimetype='text/plain')

    with robots.open() as infile:
        return Response(response=infile.read(), status=200, mimetype="text/plain")


@component.route('/data-overview/')
@component.route('/data-overview/<string:datasource>')
@login_required
def data_overview(datasource=None):
    """
    Main tool frontend
    """
    datasources = {datasource: metadata for datasource, metadata in g.modules.datasources.items() if
                   metadata["has_worker"] and datasource in g.config.get("datasources.enabled")}

    if datasource not in datasources:
        datasource = None

    github_url = g.config.get("4cat.github_url")

    # Get information for a specific data source
    datasource_id = None
    description = None
    total_counts = None
    daily_counts = None
    references = None
    labels = None
    example_keys = None

    if datasource:

        datasource_id = datasource
        worker_class = g.modules.workers.get(datasource_id + "-search")
        # Database IDs may be different from the Datasource ID (e.g. the datasource "4chan" became "fourchan" but the database ID remained "4chan")
        database_db_id = worker_class.prefix if hasattr(worker_class, "prefix") else datasource_id

        # Get description
        description_path = Path(datasources[datasource_id].get("path"), "DESCRIPTION.md")
        if description_path.exists():
            with description_path.open(encoding="utf-8") as description_file:
                description = description_file.read()

        # Status labels to display in query form
        labels = []
        is_local = "local" if hasattr(worker_class, "is_local") and worker_class.is_local else "external"
        is_static = True if hasattr(worker_class, "is_static") and worker_class.is_static else False
        labels.append(is_local)

        if is_static:
            labels.append("static")

        if hasattr(worker_class, "is_from_zeeschuimer"):
            labels.append("zeeschuimer")

        # Get example keys for the datasource
        if datasource_id not in ["upload"]: # ignore upload as keys are variable
            example_keys = get_datasource_example_keys(db=g.db, modules=g.modules, dataset_type=datasource_id + "-search")

        # Get daily post counts for local datasource to display in a graph
        if is_local == "local":

            total_counts = g.db.fetchall("SELECT board, SUM(count) AS post_count FROM metrics WHERE metric = 'posts_per_day' AND datasource = %s GROUP BY board", (database_db_id,))

            if total_counts:
                
                total_counts = {d["board"]: d["post_count"] for d in total_counts}
                
                boards = set(total_counts.keys())
                
                # Fetch date counts per board from the database
                db_counts = g.db.fetchall("SELECT board, date, count FROM metrics WHERE metric = 'posts_per_day' AND datasource = %s", (database_db_id,))

                # Get the first and last days for padding
                all_dates = [datetime.strptime(row["date"], "%Y-%m-%d").timestamp() for row in db_counts]
                first_date = datetime.fromtimestamp(min(all_dates))
                
                # Format the dates in a regular dictionary to be used by Highcharts
                daily_counts = {"first_date": (first_date.year, first_date.month, first_date.day)}
                for board in boards:
                    daily_counts[board] = {row["date"]: row["count"] for row in db_counts if row["board"] == board}
                    # Then make sure the empty dates are filled with 0
                    # and each board has the same amount of values.
                    daily_counts[board] = [v for k, v in pad_interval(daily_counts[board], first_interval=first_date)[1].items()]

        references = worker_class.references if hasattr(worker_class, "references") else None        

    return render_template('data-overview.html', datasources=datasources, datasource_id=datasource_id, description=description, labels=labels, total_counts=total_counts, daily_counts=daily_counts, github_url=github_url, references=references, example_keys=example_keys)

@component.route('/get-boards/<string:datasource>/')
@login_required
def getboards(datasource):
    if datasource not in g.config.get("datasources.enabled"):
        result = False
    else:
        result = g.config.get(datasource + "-search.boards", False)

    return jsonify(result)

@component.route('/page/<string:page>/')
def show_page(page):
    """
    Display a markdown page within the 4CAT UI

    To make adding static pages easier, they may be saved as markdown files
    in the pages subdirectory, and then called via this view. The markdown
    will be parsed to HTML and displayed within the layout template.

    :param page: ID of the page to load, should correspond to a markdown file
    in the pages/ folder (without the .md extension)
    :return:  Rendered template
    """
    page = re.sub(r"[^a-zA-Z0-9-_]*", "", page)
    page_class = "page-" + page
    page_folder = Path(g.config.get('PATH_ROOT'), "webtool", "pages")
    page_path = page_folder.joinpath(page + ".md")

    if not page_path.exists():
        return error(404, error="Page not found")

    with page_path.open(encoding="utf-8") as file:
        page_raw = file.read()
        page_parsed = markdown2.markdown(page_raw)
        page_parsed = re.sub(r"<h2>(.*)</h2>", r"<h2><span>\1</span></h2>", page_parsed)

        if g.config.get("mail.admin_email"):
            # replace this one explicitly instead of doing a generic config
            # filter, to avoid accidentally exposing config values
            admin_email = g.config.get("mail.admin_email", "4cat-admin@example.com")
            page_parsed = page_parsed.replace("%%ADMIN_EMAIL%%", admin_email)

    return render_template("page.html", body_content=page_parsed, body_class=page_class, page_name=page)