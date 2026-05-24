# =============================================================
# health.py
# Purpose  : Health and readiness check logic for the Flask app
# Location : app/health.py  (same folder as app.py)
# Used by  : app.py — imported and registered as a Blueprint
#
# WHY a separate file?
#   app.py is already responsible for routing, DB config, and
#   the main application logic. Health logic has its own job:
#   answering infrastructure questions ("is the app alive?",
#   "is the app ready to take traffic?"). Keeping it separate
#   means you can find, read, and update it instantly without
#   scrolling through unrelated code. This is the single
#   responsibility principle — one file, one job.
#
# HOW it plugs into app.py:
#   Flask Blueprints let you define routes in one file and
#   register them onto the main app object in another file.
#   Think of a Blueprint like a mini-app that gets attached
#   to the real app at startup. Two lines in app.py are all
#   you need:
#       from health import health_bp
#       app.register_blueprint(health_bp)
# =============================================================

import time

from flask import Blueprint, jsonify, current_app

# Create a Blueprint named 'health'.
# The first argument is the blueprint's internal name (used by Flask
# internally for url_for() and route registration — not visible to users).
# The second argument is always __name__ — it tells Flask which Python
# file this Blueprint lives in, so Flask can resolve relative paths correctly.
health_bp = Blueprint('health', __name__)


# =============================================================
# /health — Liveness Check
# =============================================================
#
# PURPOSE:
#   Answer one single question: "Is the Flask process alive?"
#   This endpoint does the absolute minimum — it returns a
#   fixed JSON response. No database. No external calls.
#   If this endpoint responds, the process is running.
#
# WHAT PROBLEM IT SOLVES:
#   Docker's healthcheck, AWS ALBs, and Kubernetes liveness
#   probes all need a fast, lightweight endpoint to hit every
#   few seconds. If you make them query the database, you add
#   unnecessary load and risk false negatives (e.g. the DB is
#   slow but the Flask process is perfectly fine). Separating
#   liveness from readiness is a core production practice.
#
# HTTP STATUS CODES:
#   200 OK — Flask is alive and responding.
#
# =============================================================
@health_bp.route('/health')
def health():
    """
    Liveness check — confirms the Flask process is running.
    No database check. Intentionally lightweight.
    Used by: Docker HEALTHCHECK, uptime monitors, load balancers.
    """
    return jsonify({
        "status": "healthy",
        "service": "flask-app",
    }), 200


# =============================================================
# /ready — Readiness Check
# =============================================================
#
# PURPOSE:
#   Answer a harder question: "Is the app ready to serve real
#   user traffic?" This means Flask is up AND the database
#   connection works AND the required table exists and is
#   queryable.
#
# WHAT PROBLEM IT SOLVES:
#   During startup, Flask boots in a few milliseconds but MySQL
#   can take 10–30 seconds to initialise. Without a readiness
#   check, a load balancer might route traffic to a container
#   whose DB connection isn't established yet, giving users
#   500 errors. The readiness check lets infrastructure hold
#   traffic back until the app is truly ready.
#
#   This is also useful after a DB restart or network blip —
#   the readiness check will return 503, the load balancer
#   stops sending traffic, and resumes only when the DB is
#   reachable again.
#
# HOW IT WORKS INTERNALLY (step by step):
#   1. Record the start time — used to measure how long the
#      DB check takes. This appears in the response body so
#      you can spot slow DB responses over time.
#
#   2. Import the mysql object directly from app.py.
#      flask_mysqldb does not register itself in Flask's
#      standard app.extensions dictionary in a way that's
#      reliably retrievable by a string key. Importing mysql
#      from app directly is the correct, simple pattern for
#      this project's architecture.
#
#   3. Open a cursor — this is the object that sends SQL
#      queries to MySQL and retrieves results. A cursor is
#      like a temporary channel to the database.
#
#   4. Run "SELECT 1" — the simplest possible connectivity
#      test. It touches no table; it just asks MySQL "are you
#      there?" and MySQL replies with the number 1. If this
#      raises an exception, the DB connection is broken.
#
#   5. Run "SELECT 1 FROM messages LIMIT 1" — confirms that
#      the 'messages' table (the one this app depends on)
#      exists and is readable. LIMIT 1 means MySQL stops
#      after one row, so it is fast regardless of table size.
#      If the table is missing, MySQL raises an exception.
#
#   6. If both queries succeed, return HTTP 200 with a JSON
#      body showing what was checked and how long it took.
#
#   7. If anything fails, catch the exception, log it to
#      Gunicorn's stdout (visible via `docker compose logs`),
#      and return HTTP 503 with a JSON body that describes
#      exactly what failed — so you can diagnose problems
#      from the response body without grepping logs.
#
# HTTP STATUS CODES:
#   200 OK               — App is fully ready to serve traffic.
#   503 Service          — App is running but DB is unreachable
#       Unavailable        or the messages table is missing.
#
# =============================================================
@health_bp.route('/ready')
def ready():
    """
    Readiness check — confirms Flask AND MySQL are operational.

    Runs two queries against the live database:
      1. SELECT 1            — pure connectivity ping
      2. SELECT 1 FROM messages LIMIT 1 — confirms the required
         table exists and is readable

    Returns 200 if both pass, 503 if either fails.
    Used by: Docker HEALTHCHECK, load balancers, CI smoke tests.
    """
    # Step 1: Record start time so we can report response latency.
    start_time = time.time()

    try:
        # Step 2: Import mysql from app.py directly.
        # flask_mysqldb's MySQL object is not reliably accessible via
        # Flask's app.extensions dict, so we import it by name instead.
        # This works because app.py and health.py are in the same directory
        # and the mysql object is a module-level variable in app.py.
        from app import mysql  # noqa: PLC0415 (intentional deferred import)

        # Step 3: Open a cursor — our channel to the MySQL database.
        cursor = mysql.connection.cursor()

        # Step 4: Connectivity ping. Raises an exception if MySQL is down.
        cursor.execute("SELECT 1")
        cursor.fetchone()  # consume the result to keep the cursor clean

        # Step 5: Table existence check. Raises an exception if the
        # 'messages' table is missing or the user has no SELECT privilege.
        # LIMIT 1 keeps this fast even on large tables.
        cursor.execute("SELECT 1 FROM messages LIMIT 1")
        cursor.fetchone()  # consume the result

        cursor.close()

        # Step 6: Both checks passed. Calculate elapsed time and return 200.
        elapsed_ms = round((time.time() - start_time) * 1000, 2)

        return jsonify({
            "status": "ready",
            "checks": {
                "mysql_connection": "ok",
                "messages_table": "ok",   # key matches the actual table name
            },
            "response_time_ms": elapsed_ms,
        }), 200

    except Exception as e:
        # Step 7: Something failed. Log it and return 503.
        #
        # current_app.logger writes to Flask's built-in logger, which
        # Gunicorn forwards to stdout — visible in `docker compose logs`.
        # The error message is also included in the response body so you
        # can diagnose the problem without leaving your terminal.
        current_app.logger.error("Readiness check failed: %s", str(e))

        elapsed_ms = round((time.time() - start_time) * 1000, 2)

        # HTTP 503 — "I am running but I am not ready to take traffic."
        return jsonify({
            "status": "not ready",
            "reason": str(e),
            "checks": {
                "mysql_connection": "failed",
                "messages_table": "unknown",  # we don't know — step 4 failed first
            },
            "response_time_ms": elapsed_ms,
        }), 503
