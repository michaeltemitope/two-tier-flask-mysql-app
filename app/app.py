import os
import logging
from flask import Flask, render_template, request, redirect, url_for, jsonify
from flask_mysqldb import MySQL

# ============================================================
# LOGGING SETUP — add this once at the top, before anything else
# ============================================================
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [%(levelname)s] %(message)s'
)
logger = logging.getLogger(__name__)
# ============================================================

app = Flask(__name__)

# Configure MySQL from environment variables
app.config['MYSQL_HOST'] = os.environ.get('DB_HOST', 'localhost')
app.config['MYSQL_USER'] = os.environ.get('DB_USER', 'default_user')
app.config['MYSQL_PASSWORD'] = os.environ.get('DB_PASSWORD', 'default_password')
app.config['MYSQL_DB'] = os.environ.get('DB_NAME', 'default_db')

# Initialize MySQL
mysql = MySQL(app)

def init_db():
    with app.app_context():
        logger.info("Initializing database...")  # 👈 LOG
        cur = mysql.connection.cursor()
        cur.execute('''
        CREATE TABLE IF NOT EXISTS messages (
            id INT AUTO_INCREMENT PRIMARY KEY,
            message TEXT
        );
        ''')
        mysql.connection.commit()
        cur.close()
        logger.info("Database initialized successfully.")  # 👈 LOG

@app.route('/')
def hello():
    logger.info("Homepage visited — fetching messages from DB")  # 👈 LOG
    cur = mysql.connection.cursor()
    cur.execute('SELECT message FROM messages')
    messages = cur.fetchall()
    cur.close()
    return render_template('index.html', messages=messages)

@app.route('/submit', methods=['POST'])
def submit():
    new_message = request.form.get('new_message')
    logger.info(f"New message submitted: '{new_message}'")  # 👈 LOG
    cur = mysql.connection.cursor()
    cur.execute('INSERT INTO messages (message) VALUES (%s)', [new_message])
    mysql.connection.commit()
    cur.close()
    logger.info("Message saved to DB successfully.")  # 👈 LOG
    return jsonify({'message': new_message})

@app.route('/health')
def health():
    logger.info("Health check endpoint hit")  # 👈 LOG
    try:
        cur = mysql.connection.cursor()
        cur.execute('SELECT COUNT(*) FROM messages')
        count = cur.fetchone()[0]
        cur.close()
        logger.info(f"Health check passed — message count: {count}")  # 👈 LOG
        return jsonify({
            'status': 'healthy',
            'database': 'connected',
            'message_count': count
        }), 200
    except Exception as e:
        logger.error(f"Health check FAILED — DB error: {str(e)}")  # 👈 LOG
        return jsonify({
            'status': 'unhealthy',
            'database': str(e)
        }), 500

if __name__ == '__main__':
    # NOTE:
    # This block is only used for local development/testing.
    # In production (Docker), the app is served via Gunicorn (see Dockerfile).
    init_db()
    app.run(host='0.0.0.0', port=5000, debug=True)
