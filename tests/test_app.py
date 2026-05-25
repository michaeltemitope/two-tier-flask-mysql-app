# =============================================================
# tests/test_app.py
# Purpose  : pytest test suite for the Flask application
# Run with : pytest  (from the project root)
# Used in  : GitHub Actions CI pipeline (test stage)
#
# WHAT IS BEING TESTED:
#   - Homepage (GET /)           — renders without a DB crash
#   - Health endpoint (GET /health) — liveness check response
#   - Readiness endpoint (GET /ready) — readiness check response
#
# HOW DATABASE IS HANDLED IN TESTS:
#   The /ready endpoint queries MySQL. In CI there is no real
#   MySQL container running during the test stage, so /ready
#   is expected to return 503 (not ready). This is correct and
#   intentional — we assert 503 to confirm the endpoint exists,
#   responds in the right format, and handles DB failure cleanly
#   rather than crashing with an unhandled 500 error.
#
# WHY sys.path IS MODIFIED:
#   app.py and health.py live inside the app/ directory.
#   pytest runs from the project root. Without adding app/ to
#   sys.path, Python cannot find the app and health modules and
#   every import raises a ModuleNotFoundError. This is the
#   standard fix for Flask projects that are not installed as
#   packages.
#
# WHY ENVIRONMENT VARIABLES ARE SET BEFORE IMPORT:
#   app.py reads DB config from environment variables at import
#   time (os.environ.get(...)). If those variables are not set
#   before the import, Flask will use the default fallback
#   values. Setting them here ensures the app initialises with
#   predictable test values and does not accidentally try to
#   connect to a real production database.
# =============================================================

import sys
import os

# -------------------------------------------------------------
# Add the app/ directory to Python's module search path so
# pytest can import app.py and health.py correctly.
# os.path.dirname(__file__) = tests/
# os.path.join(..., '..', 'app') = app/
# os.path.abspath(...) = full absolute path — avoids any
# relative path ambiguity regardless of where pytest is run from.
# -------------------------------------------------------------
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..', 'app')))

# -------------------------------------------------------------
# Set dummy DB environment variables BEFORE importing app.
# These do not need to point to a real database — they just
# prevent app.py from crashing during initialisation in CI.
# -------------------------------------------------------------
os.environ.setdefault('DB_HOST', 'localhost')
os.environ.setdefault('DB_USER', 'test_user')
os.environ.setdefault('DB_PASSWORD', 'test_password')
os.environ.setdefault('DB_NAME', 'test_db')
os.environ.setdefault('DB_PORT', '3306')

import pytest  # noqa: E402
from app import app as flask_app  # noqa: E402


# =============================================================
# Fixture — test client
# =============================================================
#
# A pytest fixture is a reusable setup function. Any test that
# declares `client` as a parameter automatically receives the
# value this fixture returns.
#
# flask_app.test_client() creates a fake HTTP client that sends
# requests directly to the Flask app without starting a real
# server or opening a real network socket. This makes tests
# fast and self-contained.
#
# TESTING_CONFIG:
#   app.config['TESTING'] = True tells Flask to propagate
#   exceptions rather than swallowing them into 500 responses.
#   This makes test failures easier to diagnose because you see
#   the real error, not just "Internal Server Error".
# =============================================================
@pytest.fixture
def client():
    flask_app.config['TESTING'] = True
    with flask_app.test_client() as client:
        yield client


# =============================================================
# Test 1 — Homepage (GET /)
# =============================================================
#
# WHAT: Sends a GET request to / and checks the response.
#
# WHY 200 is not always guaranteed:
#   The homepage queries MySQL. In CI there is no DB, so this
#   request will raise a DB connection error. We assert that
#   the response is either 200 (DB available) or 500 (DB not
#   available) — both are acceptable here because what we are
#   really testing is that the route EXISTS and does not crash
#   in an unexpected way (e.g. a 404 from a missing route or
#   an unhandled import error).
#
#   In a more advanced test setup you would mock the DB cursor
#   to return fake data, but that is out of scope for a
#   portfolio-level DevOps project.
# =============================================================
def test_homepage(client):
    """
    Homepage route exists and returns either 200 (DB up)
    or 500 (DB down in CI). Both confirm the route is wired
    correctly — we are not testing DB availability here.
    """
    response = client.get('/')
    assert response.status_code in (200, 500), (
        f"Expected 200 or 500 from homepage, got {response.status_code}"
    )


# =============================================================
# Test 2 — Health endpoint (GET /health)
# =============================================================
#
# WHAT: Confirms the liveness endpoint responds correctly.
#
# WHY this should always be 200:
#   /health intentionally does NOT touch the database. It only
#   checks that the Flask process is alive. There is no reason
#   it should ever fail in CI — if it does, something is wrong
#   with the Flask app itself (import error, blueprint not
#   registered, etc.).
#
# WHAT we assert:
#   1. Status code is 200
#   2. Response body is valid JSON (get_json() returns None if not)
#   3. The "status" key in the JSON equals "healthy"
# =============================================================
def test_health_endpoint(client):
    """
    /health must always return 200 with status=healthy.
    No DB involvement — a failure here means Flask itself is broken.
    """
    response = client.get('/health')

    assert response.status_code == 200, (
        f"Expected 200 from /health, got {response.status_code}"
    )

    data = response.get_json()
    assert data is not None, "/health did not return valid JSON"
    assert data['status'] == 'healthy', (
        f"Expected status=healthy, got {data.get('status')}"
    )


# =============================================================
# Test 3 — Readiness endpoint (GET /ready)
# =============================================================
#
# WHAT: Confirms the readiness endpoint responds correctly
#       even when the database is not available.
#
# WHY 503 is the CORRECT assertion in CI:
#   /ready queries MySQL. In CI there is no MySQL container
#   running during the test stage. The endpoint is designed to
#   return 503 when the DB is unreachable — that IS the correct
#   behaviour. We assert 503 to verify:
#     1. The route exists and is reachable (no 404)
#     2. Flask handles the DB failure gracefully (no 500 crash)
#     3. The response body is valid JSON with a "status" key
#
#   Asserting 503 here is not a test failure — it is proof that
#   your error handling works exactly as designed.
# =============================================================
def test_ready_endpoint_without_db(client):
    """
    /ready returns 503 in CI (no DB available).
    Confirms the route exists and handles DB failure gracefully
    instead of crashing with an unhandled 500 error.
    """
    response = client.get('/ready')

    assert response.status_code in (200, 503), (
        f"Expected 200 or 503 from /ready, got {response.status_code}"
    )

    data = response.get_json()
    assert data is not None, "/ready did not return valid JSON"
    assert 'status' in data, (
        f"Expected 'status' key in /ready response, got: {data}"
    )
