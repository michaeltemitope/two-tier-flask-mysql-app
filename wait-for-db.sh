#!/bin/bash
# =============================================================
# wait-for-db.sh
# Purpose   : Wait for MySQL to be ready before starting Flask
# Used by   : Flask container entrypoint in docker-compose.yml
# Requires  : mysql client (installed via default-mysql-client)
# Variables : DB_HOST, DB_USER, DB_PASSWORD, DB_NAME (required)
#             DB_PORT           (optional, default: 3306)
#             DB_MAX_RETRIES    (optional, default: 30)
#             DB_RETRY_INTERVAL (optional, default: 2)
#             DB_MAX_SLEEP      (optional, default: 30)
# =============================================================

# NOTE: set -e is intentionally omitted. The readiness check
# returns a non-zero exit code each time MySQL is not ready yet.
# Using set -e would kill the script on the first failed attempt
# instead of retrying. All failures are handled explicitly below.

# -------------------------------------------------------------
# LOGGING
# Timestamped output visible in docker logs
# -------------------------------------------------------------
log() {
    echo "[$(date '+%Y-%m-%d %H:%M:%S')] $1"
}

# -------------------------------------------------------------
# NUMERIC VALIDATION HELPER
# Returns 0 (true) if value is a positive integer, 1 (false) if not
# Used to validate all numeric environment variables
# -------------------------------------------------------------
is_positive_integer() {
    case "$1" in
        ''|*[!0-9]*) return 1 ;;  # empty or contains non-digits → invalid
        0)           return 1 ;;  # zero is not a valid positive integer
        *)           return 0 ;;  # all digits and greater than zero → valid
    esac
}

# -------------------------------------------------------------
# STARTUP COMMAND VALIDATION
# "$@" preserves each argument as a separate item (safe for spaces)
# "$*" treats all arguments as one string (display only)
# Ensure a command was passed so exec "$@" has something to run
# -------------------------------------------------------------
if [ "$#" -eq 0 ]; then
    log "FATAL: No startup command provided to wait-for-db.sh."
    log "Usage: wait-for-db.sh <command> [args...]"
    log "Example: wait-for-db.sh gunicorn --bind 0.0.0.0:5000 app:app"
    exit 1
fi

# -------------------------------------------------------------
# ENVIRONMENT VARIABLE VALIDATION
# DB_PORT is optional — safe default applied in configuration block
# All numeric optional variables are validated if explicitly provided
# -------------------------------------------------------------
log "Validating required environment variables..."

MISSING_VARS=0

# These four are strictly required — no safe default exists for them
for VAR in DB_HOST DB_USER DB_PASSWORD DB_NAME; do
    if [ -z "${!VAR}" ]; then
        log "ERROR: ${VAR} environment variable is not set"
        MISSING_VARS=1
    fi
done

if [ "${MISSING_VARS}" -ne 0 ]; then
    log "FATAL: One or more required environment variables are missing."
    log "Please check your .env file or docker-compose.yml and try again."
    exit 1
fi

log "All required environment variables are present."

# -------------------------------------------------------------
# CONFIGURATION
# DB_PORT defaults to 3306 if not set — optional variable
# DB_MAX_RETRIES, DB_RETRY_INTERVAL and DB_MAX_SLEEP are
# validated if explicitly provided and must be positive integers
# -------------------------------------------------------------
DB_PORT="${DB_PORT:-3306}"
MAX_RETRIES="${DB_MAX_RETRIES:-30}"
RETRY_INTERVAL="${DB_RETRY_INTERVAL:-2}"
MAX_SLEEP="${DB_MAX_SLEEP:-30}"

# Validate DB_PORT if explicitly provided
if ! is_positive_integer "${DB_PORT}"; then
    log "FATAL: DB_PORT must be a positive integer. Got: '${DB_PORT}'"
    exit 1
fi

# Validate MAX_RETRIES if explicitly provided
if [ -n "${DB_MAX_RETRIES}" ] && ! is_positive_integer "${MAX_RETRIES}"; then
    log "FATAL: DB_MAX_RETRIES must be a positive integer. Got: '${MAX_RETRIES}'"
    exit 1
fi

# Validate RETRY_INTERVAL if explicitly provided
if [ -n "${DB_RETRY_INTERVAL}" ] && ! is_positive_integer "${RETRY_INTERVAL}"; then
    log "FATAL: DB_RETRY_INTERVAL must be a positive integer. Got: '${RETRY_INTERVAL}'"
    exit 1
fi

# Validate MAX_SLEEP if explicitly provided
if [ -n "${DB_MAX_SLEEP}" ] && ! is_positive_integer "${MAX_SLEEP}"; then
    log "FATAL: DB_MAX_SLEEP must be a positive integer. Got: '${MAX_SLEEP}'"
    exit 1
fi

# Track wall clock time for accurate elapsed reporting
# SECONDS is a built-in bash variable that increments automatically
START_TIME="${SECONDS}"

attempt=1

# -------------------------------------------------------------
# READINESS WAIT LOOP
# Runs SELECT 1 to confirm MySQL is fully ready for real queries
# Uses incremental backoff capped at DB_MAX_SLEEP seconds
# MYSQL_PWD passes password safely without exposing it in args
# NOTE: Jitter (randomised sleep) is intentionally omitted here
# as this runs as a single container. In multi-replica environments
# consider adding: SLEEP_TIME=$(( SLEEP_TIME + RANDOM % 3 ))
# to prevent synchronised retry storms across containers
# -------------------------------------------------------------
log "Waiting for MySQL to be ready at ${DB_HOST}:${DB_PORT}..."
log "Settings — Max attempts: ${MAX_RETRIES} | Base interval: ${RETRY_INTERVAL}s | Sleep cap: ${MAX_SLEEP}s"

while [ "${attempt}" -le "${MAX_RETRIES}" ]; do

    # Run SELECT 1 as a real query to confirm MySQL is fully ready
    # stderr suppressed to keep logs clean during expected failures
    if MYSQL_PWD="${DB_PASSWORD}" mysql \
        --host="${DB_HOST}" \
        --port="${DB_PORT}" \
        --user="${DB_USER}" \
        --connect-timeout=3 \
        --execute="SELECT 1;" \
        "${DB_NAME}" > /dev/null 2>&1; then

        ELAPSED=$(( SECONDS - START_TIME ))

        # ---------------------------------------------------------
        # SUCCESS
        # ---------------------------------------------------------
        log "============================================"
        log "SUCCESS: MySQL is ready and accepting queries."
        log "Host      : ${DB_HOST}"
        log "Port      : ${DB_PORT}"
        log "Database  : ${DB_NAME}"
        log "Attempts  : ${attempt}"
        log "Elapsed   : ${ELAPSED}s"
        log "============================================"

        # $* used here for display only — safe for logging
        log "Starting application: $*"

        # exec replaces this shell process with the app process
        # "$@" preserves each argument separately — required for
        # correct handling of arguments that contain spaces
        exec "$@"
    fi

    # Incremental backoff — sleep grows with each attempt
    # Capped at MAX_SLEEP to keep total wait time predictable
    SLEEP_TIME=$(( RETRY_INTERVAL * attempt ))
    if [ "${SLEEP_TIME}" -gt "${MAX_SLEEP}" ]; then
        SLEEP_TIME="${MAX_SLEEP}"
    fi

    log "Attempt ${attempt}/${MAX_RETRIES} — MySQL not ready. Retrying in ${SLEEP_TIME}s..."
    attempt=$(( attempt + 1 ))
    sleep "${SLEEP_TIME}"

done

# -------------------------------------------------------------
# FAILURE
# Reached only if MySQL never became ready within the retry limit
# SECONDS - START_TIME gives accurate elapsed time regardless
# of backoff strategy — more honest than attempt * interval
# -------------------------------------------------------------
ELAPSED=$(( SECONDS - START_TIME ))

log "============================================"
log "FATAL: MySQL not ready after ${ELAPSED}s."
log "Host      : ${DB_HOST}"
log "Port      : ${DB_PORT}"
log "Database  : ${DB_NAME}"
log "Attempts  : $((attempt - 1))"
log "Troubleshooting: run 'docker logs <mysql_container_name>'"
log "============================================"
exit 1
