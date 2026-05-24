# Use official lightweight Python image as base
FROM python:3.9.21-slim

# Stop Python from writing .pyc files inside the container
ENV PYTHONDONTWRITEBYTECODE=1

# Force Python to print logs instantly to terminal (required for docker logs)
ENV PYTHONUNBUFFERED=1

# Set the working directory inside the container
WORKDIR /app

# Install system dependencies required by flask_mysqldb to connect to MySQL
# default-mysql-client provides the mysqladmin command used by wait-for-db.sh
# curl is explicitly installed here as it is not available in python:3.9-slim
# by default and is required for the Flask health check in docker-compose.yml
RUN apt-get update && apt-get install -y \
    gcc \
    default-libmysqlclient-dev \
    default-mysql-client \
    pkg-config \
    curl \
    && rm -rf /var/lib/apt/lists/*

# Copy requirements.txt first to leverage Docker layer caching
# This layer only rebuilds when requirements.txt changes
COPY app/requirements.txt .

# Install all Python dependencies including Flask, flask_mysqldb and Gunicorn
RUN pip install --no-cache-dir -r requirements.txt

# Copy the wait-for-db script into the container
COPY wait-for-db.sh .

# Copy application code,static and templates into the container
COPY app/ .

# Make script executable, create non-root user and assign ownership
# All done in one RUN layer as root before switching to appuser
RUN chmod +x wait-for-db.sh \
    && useradd -m appuser \
    && chown -R appuser:appuser /app

# Switch to non-root user for security
USER appuser

# Expose port 5000 for Flask application
EXPOSE 5000

# Use wait-for-db.sh as the entrypoint so it always runs before Gunicorn
ENTRYPOINT ["./wait-for-db.sh"]

# Command passed to wait-for-db.sh and executed after MySQL is ready
CMD ["gunicorn", "--bind", "0.0.0.0:5000", "--workers", "2", "app:app"]
