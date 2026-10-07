from flask import Flask, render_template, request, redirect, url_for, session, flash
import sqlite3
import os
from functools import wraps
from datetime import datetime, timedelta
from werkzeug.security import generate_password_hash, check_password_hash

app = Flask(__name__)

# ---------------------------------------------------------
# APP CONFIGURATION
# ---------------------------------------------------------

app.secret_key = "flask_config_manager_secret_key"

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DATABASE = os.path.join(BASE_DIR, "config_manager.db")


# ---------------------------------------------------------
# DATABASE CONNECTION
# ---------------------------------------------------------

def get_db():
    conn = sqlite3.connect(DATABASE)
    conn.row_factory = sqlite3.Row
    return conn


# ---------------------------------------------------------
# DATABASE INITIALIZATION
# ---------------------------------------------------------

def init_database():
    conn = get_db()
    cursor = conn.cursor()

    # Users table
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            username TEXT UNIQUE NOT NULL,
            password TEXT NOT NULL
        )
    """)

    # Configuration table
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS configuration (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            app_name TEXT NOT NULL,
            environment TEXT NOT NULL,
            debug_mode INTEGER NOT NULL DEFAULT 0,
            version TEXT NOT NULL,
            max_users INTEGER DEFAULT 100,
            session_timeout INTEGER DEFAULT 30
        )
    """)

    # Activities table
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS activities (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            action TEXT NOT NULL,
            description TEXT,
            time TEXT NOT NULL
        )
    """)

    # Add is_read column to old databases
    cursor.execute("PRAGMA table_info(activities)")
    activity_columns = [row["name"] for row in cursor.fetchall()]

    if "is_read" not in activity_columns:
        cursor.execute("""
            ALTER TABLE activities
            ADD COLUMN is_read INTEGER NOT NULL DEFAULT 0
     """)

    # -----------------------------------------------------
    # Add missing columns to old databases
    # -----------------------------------------------------

    cursor.execute("PRAGMA table_info(configuration)")
    columns = [row["name"] for row in cursor.fetchall()]

    if "max_users" not in columns:
        cursor.execute("""
            ALTER TABLE configuration
            ADD COLUMN max_users INTEGER DEFAULT 100
        """)

    if "session_timeout" not in columns:
        cursor.execute("""
            ALTER TABLE configuration
            ADD COLUMN session_timeout INTEGER DEFAULT 30
        """)

    # -----------------------------------------------------
    # Create default admin user
    # -----------------------------------------------------

    cursor.execute("SELECT id FROM users WHERE username = ?", ("admin",))
    user = cursor.fetchone()

    if user is None:
        password_hash = generate_password_hash("admin123")

        cursor.execute("""
            INSERT INTO users (username, password)
            VALUES (?, ?)
        """, ("admin", password_hash))

    # -----------------------------------------------------
    # Create default configuration
    # -----------------------------------------------------

    cursor.execute("SELECT id FROM configuration LIMIT 1")
    config = cursor.fetchone()

    if config is None:
        cursor.execute("""
            INSERT INTO configuration
            (
                app_name,
                environment,
                debug_mode,
                version,
                max_users,
                session_timeout
            )
            VALUES (?, ?, ?, ?, ?, ?)
        """, (
            "Flask Configuration Manager",
            "Development",
            1,
            "1.0.0",
            100,
            30
        ))

    conn.commit()
    conn.close()


# ---------------------------------------------------------
# ACTIVITY MANAGEMENT
# ---------------------------------------------------------

def add_activity(action, description):
    conn = get_db()

    current_time = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    conn.execute("""
        INSERT INTO activities (action, description, time,is_read
        )
        VALUES (?,?,?,?)
    """, 
    (
        action,
        description,
        current_time,        
        0
    )
)

    conn.commit()
    conn.close()


def get_activities(limit=None):
    conn = get_db()

    if limit:
        activities = conn.execute("""
            SELECT
                *,
                time AS created_at
            FROM activities
            ORDER BY id DESC
            LIMIT ?
        """, (limit,)).fetchall()
    else:
        activities = conn.execute("""
            SELECT
                *,
                time AS created_at
            FROM activities
            ORDER BY id DESC
        """).fetchall()

    conn.close()

    return activities


# ---------------------------------------------------------
# LOGIN REQUIRED DECORATOR
# ---------------------------------------------------------

def login_required(function):
    @wraps(function)
    def decorated_function(*args, **kwargs):

        if "user_id" not in session:
            flash("Please login first.", "warning")
            return redirect(url_for("login"))

        return function(*args, **kwargs)

    return decorated_function


# ---------------------------------------------------------
# ACTIVITY CHART
# ---------------------------------------------------------

def get_activity_chart():
    conn = get_db()

    chart = []

    today = datetime.now().date()

    for i in range(6, -1, -1):

        current_date = today - timedelta(days=i)

        start_time = datetime.combine(
            current_date,
            datetime.min.time()
        ).strftime("%Y-%m-%d %H:%M:%S")

        end_time = datetime.combine(
            current_date,
            datetime.max.time()
        ).strftime("%Y-%m-%d %H:%M:%S")

        result = conn.execute("""
            SELECT COUNT(*) AS count
            FROM activities
            WHERE time >= ?
            AND time <= ?
        """, (
            start_time,
            end_time
        )).fetchone()

        chart.append({
            "date": current_date.strftime("%a"),
            "count": result["count"]
        })

    conn.close()

    return chart


# ---------------------------------------------------------
# HOME / DASHBOARD
# ---------------------------------------------------------

@app.route("/")
@login_required
def home():

    return redirect(url_for("dashboard"))


@app.route("/dashboard")
@login_required
def dashboard():

    conn = get_db()

    config = conn.execute("""
        SELECT *
        FROM configuration
        LIMIT 1
    """).fetchone()

    user = conn.execute("""
        SELECT *
        FROM users
        WHERE id = ?
    """, (
        session["user_id"],
    )).fetchone()

    activity_count = conn.execute("""
        SELECT COUNT(*) AS count
        FROM activities
    """).fetchone()["count"]

    recent_activities = conn.execute("""
        SELECT
            *,
            time AS created_at
        FROM activities
        WHERE is_read = 0
        ORDER BY id DESC
        LIMIT 10
    """).fetchall()

    conn.close()

    activity_chart = get_activity_chart()

    return render_template(
        "index.html",
        config=config,
        user=user,
        username=session.get("username", "User"),
        activity_count=activity_count,
        recent_activities=recent_activities,
        activity_chart=activity_chart
    )


# ---------------------------------------------------------
# LOGIN
# ---------------------------------------------------------

@app.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        username = request.form.get("username", "").strip()
        password = request.form.get("password", "")

        if username == "admin" and password == "admin123":
            session["user_id"] = 1
            session["username"] = "admin"

            add_activity(
                "Login",
                "User admin logged in successfully"
            )

            return redirect(url_for("dashboard"))

        flash("Invalid username or password", "error")

    return render_template("login.html")


# ---------------------------------------------------------
# LOGOUT
# ---------------------------------------------------------

@app.route("/logout")
@app.route("/logout/")
def logout():

    username = session.get("username", "User")

    if "user_id" in session:

        add_activity(
            "Logout",
            f"User {username} logged out"
        )

    session.clear()

    flash("You have been logged out.", "success")

    return redirect(url_for("login"))


# ---------------------------------------------------------
# CONFIGURATION PAGE
# ---------------------------------------------------------

@app.route("/config", methods=["GET", "POST"])
@login_required
def config():

    conn = get_db()

    current_config = conn.execute("""
        SELECT *
        FROM configuration
        LIMIT 1
    """).fetchone()

    if current_config is None:

        conn.execute("""
            INSERT INTO configuration
            (
                app_name,
                environment,
                debug_mode,
                version,
                max_users,
                session_timeout
            )
            VALUES (?, ?, ?, ?, ?, ?)
        """, (
            "Flask Configuration Manager",
            "Development",
            1,
            "1.0.0",
            100,
            30
        ))

        conn.commit()

        current_config = conn.execute("""
            SELECT *
            FROM configuration
            LIMIT 1
        """).fetchone()

    if request.method == "POST":

        app_name = request.form.get(
            "app_name",
            current_config["app_name"]
        ).strip()

        environment = request.form.get(
            "environment",
            current_config["environment"]
        ).strip()

        version = request.form.get(
            "version",
            current_config["version"]
        ).strip()

        debug_value = request.form.get("debug_mode")

        if debug_value is None:
            debug_mode = current_config["debug_mode"]
        else:
            debug_mode = 1 if debug_value in [
                "1",
                "true",
                "True",
                "on",
                "yes"
            ] else 0

        # Preserve old values if these fields are not
        # present in the HTML form
        max_users = current_config["max_users"]

        if "max_users" in request.form:
            try:
                max_users = int(request.form.get("max_users"))
            except (TypeError, ValueError):
                flash("Max users must be a number.", "danger")
                conn.close()
                return render_template(
                    "config.html",
                    config=current_config
                )

        session_timeout = current_config["session_timeout"]

        if "session_timeout" in request.form:
            try:
                session_timeout = int(
                    request.form.get("session_timeout")
                )
            except (TypeError, ValueError):
                flash(
                    "Session timeout must be a number.",
                    "danger"
                )
                conn.close()
                return render_template(
                    "config.html",
                    config=current_config
                )

        if not app_name:
            flash("Application name cannot be empty.", "danger")
            conn.close()
            return render_template(
                "config.html",
                config=current_config
            )

        if not environment:
            flash("Environment cannot be empty.", "danger")
            conn.close()
            return render_template(
                "config.html",
                config=current_config
            )

        if not version:
            flash("Version cannot be empty.", "danger")
            conn.close()
            return render_template(
                "config.html",
                config=current_config
            )

        conn.execute("""
            UPDATE configuration
            SET
                app_name = ?,
                environment = ?,
                debug_mode = ?,
                version = ?,
                max_users = ?,
                session_timeout = ?
            WHERE id = ?
        """, (
            app_name,
            environment,
            debug_mode,
            version,
            max_users,
            session_timeout,
            current_config["id"]
        ))

        conn.commit()
        conn.close()

        add_activity(
            "Configuration Updated",
            "Application configuration was updated"
        )

        flash(
            "Configuration updated successfully!",
            "success"
        )

        return redirect(url_for("config"))

    conn.close()

    return render_template(
        "config.html",
        config=current_config
    )


# ---------------------------------------------------------
# VIEW CONFIGURATION
# ---------------------------------------------------------

@app.route("/view-config")
@login_required
def view_config():

    conn = get_db()

    config = conn.execute("""
        SELECT *
        FROM configuration
        LIMIT 1
    """).fetchone()

    conn.close()

    return render_template(
        "view_config.html",
        config=config
    )


# ---------------------------------------------------------
# PROFILE
# ---------------------------------------------------------

@app.route("/profile")
@login_required
def profile():

    conn = get_db()

    user = conn.execute("""
        SELECT *
        FROM users
        WHERE id = ?
    """, (
        session["user_id"],
    )).fetchone()

    conn.close()

    return render_template(
        "profile.html",
        user=user,
        username=session.get("username", "User")
    )


# ---------------------------------------------------------
# CHANGE PASSWORD
# ---------------------------------------------------------
@app.route("/change-password", methods=["GET", "POST"])
@login_required
def change_password():

    if request.method == "POST":

        current_password = request.form.get("current_password", "")
        new_password = request.form.get("new_password", "")
        confirm_password = request.form.get("confirm_password", "")

        if not current_password:
            flash("Please enter your current password.", "danger")
            return render_template("change-password.html")

        if not new_password:
            flash("Please enter a new password.", "danger")
            return render_template("change-password.html")

        if len(new_password) < 6:
            flash(
                "New password must contain at least 6 characters.",
                "danger"
            )
            return render_template("change-password.html")

        if new_password != confirm_password:
            flash(
                "New passwords do not match.",
                "danger"
            )
            return render_template("change-password.html")

        conn = get_db()

        user = conn.execute(
            "SELECT * FROM users WHERE id = ?",
            (session["user_id"],)
        ).fetchone()

        if user is None:
            conn.close()
            session.clear()

            flash("User account not found.", "danger")
            return redirect(url_for("login"))

        # Check current password safely
        stored_password = user["password"]

        try:
            password_correct = check_password_hash(
                stored_password,
                current_password
            )
        except Exception:
            password_correct = False

        if not password_correct:
            conn.close()

            flash(
                "Current password is incorrect.",
                "danger"
            )

            return render_template("change-password.html")

        # Create new password hash
        new_password_hash = generate_password_hash(
            new_password
        )

        conn.execute(
            """
            UPDATE users
            SET password = ?
            WHERE id = ?
            """,
            (
                new_password_hash,
                session["user_id"]
            )
        )

        conn.commit()
        conn.close()

        add_activity(
            "Password Changed",
            f"User {session.get('username', 'User')} changed password"
        )

        flash(
            "Password changed successfully!",
            "success"
        )

        return redirect(url_for("profile"))

    return render_template("change-password.html")

# ---------------------------------------------------------
# ACTIVITY HISTORY
# ---------------------------------------------------------

@app.route("/activity-history")
@login_required
def activity_history():

    activities = get_activities()

    return render_template(
        "activity_history.html",
        activities=activities
    )

# ---------------------------------------------------------
# MARK NOTIFICATIONS AS READ
# ---------------------------------------------------------

@app.route("/mark-notifications-read", methods=["POST"])
@login_required
def mark_notifications_read():

    conn = get_db()

    conn.execute("""
        UPDATE activities
        SET is_read = 1
        WHERE is_read = 0
    """)

    conn.commit()
    conn.close()

    return {"success": True}


# ---------------------------------------------------------
# CLEAR ACTIVITY HISTORY
# ---------------------------------------------------------

@app.route("/clear-activity-history", methods=["POST"])
@login_required
def clear_activity_history():

    conn = get_db()

    conn.execute("""
        DELETE FROM activities
    """)

    conn.commit()
    conn.close()

    flash(
        "Activity history cleared successfully.",
        "success"
    )

    return redirect(url_for("activity_history"))


# ---------------------------------------------------------
# RESET CONFIGURATION
# ---------------------------------------------------------

@app.route("/reset-config", methods=["POST"])
@login_required
def reset_config():

    conn = get_db()

    current_config = conn.execute("""
        SELECT *
        FROM configuration
        LIMIT 1
    """).fetchone()

    if current_config:

        conn.execute("""
            UPDATE configuration
            SET
                app_name = ?,
                environment = ?,
                debug_mode = ?,
                version = ?,
                max_users = ?,
                session_timeout = ?
            WHERE id = ?
        """, (
            "Flask Configuration Manager",
            "Development",
            1,
            "1.0.0",
            100,
            30,
            current_config["id"]
        ))

    else:

        conn.execute("""
            INSERT INTO configuration
            (
                app_name,
                environment,
                debug_mode,
                version,
                max_users,
                session_timeout
            )
            VALUES (?, ?, ?, ?, ?, ?)
        """, (
            "Flask Configuration Manager",
            "Development",
            1,
            "1.0.0",
            100,
            30
        ))

    conn.commit()
    conn.close()

    add_activity(
        "Configuration Reset",
        "Application configuration was reset to default values"
    )

    flash(
        "Configuration reset successfully!",
        "success"
    )

    return redirect(url_for("config"))


# ---------------------------------------------------------
# 404 ERROR
# ---------------------------------------------------------

@app.errorhandler(404)
def page_not_found(error):

    return render_template(
        "404.html"
    ), 404


# ---------------------------------------------------------
# 500 ERROR
# ---------------------------------------------------------

@app.errorhandler(500)
def internal_server_error(error):

    return render_template(
        "500.html"
    ), 500


# ---------------------------------------------------------
# INITIALIZE DATABASE
# ---------------------------------------------------------

init_database()


# ---------------------------------------------------------
# RUN APPLICATION
# ---------------------------------------------------------

if __name__ == "__main__":

    app.run(
        host="127.0.0.1",
        port=5000,
        debug=True
    )