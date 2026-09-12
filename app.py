import os
import hashlib
import secrets
import resend
from datetime import datetime, date, timedelta, timezone

import psycopg2
from dotenv import load_dotenv
from flask import Flask, abort, flash, redirect, render_template, request, session, url_for
from werkzeug.security import check_password_hash, generate_password_hash

load_dotenv()
resend.api_key = os.environ["RESEND_API_KEY"]
app = Flask(__name__)
app.secret_key = os.environ["SECRET_KEY"]


def get_db_connection():
    return psycopg2.connect(
        os.environ["DATABASE_URL"],
        sslmode="require",
        connect_timeout=10,
    )


def parse_tuition(value):
    value = (value or "").strip()
    if not value:
        return None
    return int(value)


@app.before_request
def require_login():
    public_endpoints = {
        "login",
        "register",
        "forgot_password",
        "reset_password",
        "static",
    }

    if request.endpoint is None:
        return

    if request.endpoint in public_endpoints:
        return

    user_id = session.get("user_id")

    if user_id is None:
        return redirect("/login")

    university_id = (request.view_args or {}).get("university_id")

    if university_id is None:
        return

    connection = get_db_connection()

    try:
        cursor = connection.cursor()

        cursor.execute(
            """
            SELECT id
            FROM universities
            WHERE id = %s
            AND user_id = %s
            """,
            (university_id, user_id),
        )

        university = cursor.fetchone()

        cursor.close()

    finally:
        connection.close()

    if university is None:
        abort(404)

@app.route("/")
def home():
    user_id = session["user_id"]
    search = request.args.get("search", "")
    country = request.args.get("country", "")
    status = request.args.get("status", "")

    connection = get_db_connection()
    cursor = connection.cursor()

    try:
        # Countries for filter
        cursor.execute(
            """
            SELECT DISTINCT country
            FROM universities
            WHERE user_id = %s
            AND country IS NOT NULL
            AND country != ''
            ORDER BY country
            """,
            (user_id,),
        )

        countries = cursor.fetchall()

        # Search + filter query
        query = "SELECT * FROM universities WHERE user_id = %s"
        values = [user_id]

        if search:
            query += """
            AND (
                name ILIKE %s
                OR country ILIKE %s
                OR course ILIKE %s
            )
            """

            search_value = "%" + search + "%"
            values.extend([search_value, search_value, search_value])

        if country:
            query += " AND country = %s"
            values.append(country)

        if status:
            query += " AND status = %s"
            values.append(status)

        # Sort by nearest deadline
        query += """
        ORDER BY
            CASE
                WHEN deadline IS NULL OR deadline = '' THEN 1
                ELSE 0
            END,
            deadline ASC
        """

        cursor.execute(query, values)
        universities = cursor.fetchall()

        # Requirement progress
        requirement_progress = {}

        for university in universities:
            university_id = university[0]

            cursor.execute(
                """
                SELECT COUNT(*)
                FROM requirements
                WHERE university_id = %s
                """,
                (university_id,),
            )
            total_requirements = cursor.fetchone()[0]

            cursor.execute(
                """
                SELECT COUNT(*)
                FROM requirements
                WHERE university_id = %s
                AND completed = 1
                """,
                (university_id,),
            )
            completed_requirements = cursor.fetchone()[0]

            if total_requirements > 0:
                percentage = int(
                    (completed_requirements / total_requirements) * 100
                )
            else:
                percentage = 0

            requirement_progress[university_id] = percentage

        # Deadline info
        deadline_info = {}
        today = date.today()

        for university in universities:
            university_id = university[0]
            deadline_text = university[4]

            if deadline_text:
                try:
                    deadline_date = datetime.strptime(
                        deadline_text,
                        "%Y-%m-%d",
                    ).date()

                    days_left = (deadline_date - today).days
                    deadline_info[university_id] = days_left

                except ValueError:
                    deadline_info[university_id] = None
            else:
                deadline_info[university_id] = None

        # Readiness
        readiness = {}

        for university in universities:
            university_id = university[0]
            progress = requirement_progress[university_id]
            days_left = deadline_info[university_id]
            university_status = university[6]

            if university_status == "Accepted":
                readiness[university_id] = "Accepted"
            elif university_status == "Rejected":
                readiness[university_id] = "Closed"
            elif days_left is not None and days_left < 0:
                readiness[university_id] = "Deadline Passed"
            elif progress == 100:
                readiness[university_id] = "Ready to Apply"
            elif progress >= 75:
                readiness[university_id] = "Almost Ready"
            else:
                readiness[university_id] = "In Progress"

        # Upcoming deadlines
        upcoming_deadlines = []

        for university in universities:
            deadline_text = university[4]

            if deadline_text:
                try:
                    deadline_date = datetime.strptime(
                        deadline_text,
                        "%Y-%m-%d",
                    ).date()

                    days_left = (deadline_date - today).days

                    if 0 <= days_left <= 30:
                        upcoming_deadlines.append(
                            (
                                university[1],
                                deadline_text,
                                days_left,
                            )
                        )

                except ValueError:
                    pass

        # Dashboard counts
        total = len(universities)
        planning = 0
        applied = 0
        accepted = 0

        for university in universities:
            if university[6] == "Planning to Apply":
                planning += 1
            elif university[6] == "Applied":
                applied += 1
            elif university[6] == "Accepted":
                accepted += 1

    finally:
        cursor.close()
        connection.close()

    return render_template(
        "index.html",
        universities=universities,
        countries=countries,
        search=search,
        country=country,
        status=status,
        total=total,
        planning=planning,
        applied=applied,
        accepted=accepted,
        upcoming_deadlines=upcoming_deadlines,
        requirement_progress=requirement_progress,
        deadline_info=deadline_info,
        readiness=readiness,
    )


@app.route("/add", methods=["POST"])
def add_university():
    name = request.form["name"]
    country = request.form["country"]
    course = request.form["course"]
    deadline = request.form["deadline"]
    tuition = parse_tuition(request.form.get("tuition"))
    status = request.form["status"]
    scholarship = request.form["scholarship"]
    requirements = request.form["requirements"]
    notes = request.form["notes"]

    connection = get_db_connection()
    cursor = connection.cursor()

    try:
        cursor.execute(
            """
            INSERT INTO universities
            (
                name, country, course, deadline, tuition,
                status, scholarship, requirements, notes, user_id
            )
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            """,
            (
                name,
                country,
                course,
                deadline,
                tuition,
                status,
                scholarship,
                requirements,
                notes,
                session["user_id"],
            ),
        )

        connection.commit()

    except Exception:
        connection.rollback()
        raise

    finally:
        cursor.close()
        connection.close()

    flash("University added successfully.", "success")
    return redirect("/")


@app.route("/delete/<int:university_id>", methods=["POST"])
def delete_university(university_id):
    user_id = session["user_id"]
    connection = get_db_connection()
    cursor = connection.cursor()

    try:
        # Requirements are deleted automatically because the PostgreSQL
        # foreign key uses ON DELETE CASCADE.
        cursor.execute(
            """
            DELETE FROM universities
            WHERE id = %s
            AND user_id = %s
            """,
            (university_id, user_id),
        )

        if cursor.rowcount == 0:
            connection.rollback()
            abort(404)

        connection.commit()

    except Exception:
        connection.rollback()
        raise

    finally:
        cursor.close()
        connection.close()

    flash("University and its requirements deleted.", "success")
    return redirect("/")


@app.route("/edit/<int:university_id>")
def edit_university(university_id):
    connection = get_db_connection()
    cursor = connection.cursor()

    try:
        cursor.execute(
            """
            SELECT * FROM universities
            WHERE id = %s
            AND user_id = %s
            """,
            (university_id, session["user_id"]),
        )

        university = cursor.fetchone()

    finally:
        cursor.close()
        connection.close()

    if university is None:
        abort(404)

    return render_template("edit.html", university=university)


@app.route("/update/<int:university_id>", methods=["POST"])
def update_university(university_id):
    name = request.form["name"]
    country = request.form["country"]
    course = request.form["course"]
    deadline = request.form["deadline"]
    tuition = parse_tuition(request.form.get("tuition"))
    status = request.form["status"]
    scholarship = request.form["scholarship"]
    requirements = request.form["requirements"]
    notes = request.form["notes"]

    connection = get_db_connection()
    cursor = connection.cursor()

    try:
        cursor.execute(
            """
            UPDATE universities
            SET name = %s,
                country = %s,
                course = %s,
                deadline = %s,
                tuition = %s,
                status = %s,
                scholarship = %s,
                requirements = %s,
                notes = %s
            WHERE id = %s
            AND user_id = %s
            """,
            (
                name,
                country,
                course,
                deadline,
                tuition,
                status,
                scholarship,
                requirements,
                notes,
                university_id,
                session["user_id"],
            ),
        )

        if cursor.rowcount == 0:
            connection.rollback()
            abort(404)

        connection.commit()

    except Exception:
        connection.rollback()
        raise

    finally:
        cursor.close()
        connection.close()

    flash("University updated successfully.", "success")
    return redirect("/")


@app.route("/requirements/<int:university_id>")
def requirements_page(university_id):
    connection = get_db_connection()
    cursor = connection.cursor()

    try:
        cursor.execute(
            """
            SELECT * FROM universities
            WHERE id = %s
            AND user_id = %s
            """,
            (university_id, session["user_id"]),
        )

        university = cursor.fetchone()

        if university is None:
            abort(404)

        cursor.execute(
            """
            SELECT * FROM requirements
            WHERE university_id = %s
            ORDER BY id
            """,
            (university_id,),
        )

        requirements = cursor.fetchall()

        total_requirements = len(requirements)
        completed_requirements = 0

        for requirement in requirements:
            if requirement[3] == 1:
                completed_requirements += 1

        if total_requirements > 0:
            completion_percentage = int(
                (completed_requirements / total_requirements) * 100
            )
        else:
            completion_percentage = 0

    finally:
        cursor.close()
        connection.close()

    return render_template(
        "requirements.html",
        university=university,
        requirements=requirements,
        completion_percentage=completion_percentage,
    )


@app.route("/requirements/<int:university_id>/add", methods=["POST"])
def add_requirement(university_id):
    requirement_name = request.form["requirement_name"]

    connection = get_db_connection()
    cursor = connection.cursor()

    try:
        cursor.execute(
            """
            INSERT INTO requirements
            (university_id, requirement_name, completed)
            VALUES (%s, %s, 0)
            """,
            (university_id, requirement_name),
        )

        connection.commit()

    except Exception:
        connection.rollback()
        raise

    finally:
        cursor.close()
        connection.close()

    return redirect("/requirements/" + str(university_id))


@app.route(
    "/requirements/<int:university_id>/toggle/<int:requirement_id>",
    methods=["POST"],
)
def toggle_requirement(university_id, requirement_id):
    connection = get_db_connection()
    cursor = connection.cursor()

    try:
        cursor.execute(
            """
            SELECT completed
            FROM requirements
            WHERE id = %s
            AND university_id = %s
            """,
            (requirement_id, university_id),
        )

        requirement = cursor.fetchone()

        if requirement is None:
            abort(404)

        if requirement[0] == 0:
            new_status = 1
        else:
            new_status = 0

        cursor.execute(
            """
            UPDATE requirements
            SET completed = %s
            WHERE id = %s
            AND university_id = %s
            """,
            (
                new_status,
                requirement_id,
                university_id,
            ),
        )

        connection.commit()

    except Exception:
        connection.rollback()
        raise

    finally:
        cursor.close()
        connection.close()

    return redirect("/requirements/" + str(university_id))


@app.route(
    "/requirements/<int:university_id>/delete/<int:requirement_id>",
    methods=["POST"],
)
def delete_requirement(university_id, requirement_id):
    connection = get_db_connection()
    cursor = connection.cursor()

    try:
        cursor.execute(
            """
            DELETE FROM requirements
            WHERE id = %s
            AND university_id = %s
            """,
            (requirement_id, university_id),
        )

        if cursor.rowcount == 0:
            connection.rollback()
            abort(404)

        connection.commit()

    except Exception:
        connection.rollback()
        raise

    finally:
        cursor.close()
        connection.close()

    return redirect("/requirements/" + str(university_id))


@app.route("/register", methods=["GET", "POST"])
def register():
    error = None
    username = ""
    email = ""

    if request.method == "POST":
        username = request.form.get("username", "").strip()
        email = request.form.get("email", "").strip().lower()
        password = request.form.get("password", "")

        if not username or not email or not password:
            error = "Please fill in all fields."
        else:
            password_hash = generate_password_hash(password)
            connection = get_db_connection()
            cursor = connection.cursor()

            try:
                cursor.execute(
                    """
                    INSERT INTO users
                    (username, email, password_hash)
                    VALUES (%s, %s, %s)
                    """,
                    (
                        username,
                        email,
                        password_hash,
                    ),
                )

                connection.commit()

            except psycopg2.IntegrityError:
                connection.rollback()
                error = "That username or email is already in use."

            finally:
                cursor.close()
                connection.close()

            if error is None:
                return redirect("/login")

    return render_template(
        "register.html",
        error=error,
        username=username,
        email=email,
    )


@app.route("/login", methods=["GET", "POST"])
def login():
    error = None
    email = ""

    if request.method == "POST":
        email = request.form.get("email", "").strip().lower()
        password = request.form.get("password", "")

        connection = get_db_connection()
        cursor = connection.cursor()

        try:
            cursor.execute(
                """
                SELECT * FROM users
                WHERE email = %s
                """,
                (email,),
            )

            user = cursor.fetchone()

        finally:
            cursor.close()
            connection.close()

        if user and check_password_hash(user[3], password):
            session.clear()
            session["user_id"] = user[0]
            session["username"] = user[1]
            return redirect("/")

        error = "Incorrect email or password."

    return render_template(
        "login.html",
        error=error,
        email=email,
    )

@app.route("/settings")
def settings():
    user_id = session["user_id"]

    connection = get_db_connection()
    cursor = connection.cursor()

    try:
        cursor.execute(
            """
            SELECT username, email
            FROM users
            WHERE id = %s
            """,
            (user_id,),
        )

        user = cursor.fetchone()

    finally:
        cursor.close()
        connection.close()

    if user is None:
        session.clear()
        return redirect("/login")

    return render_template(
        "settings.html",
        user=user,
    )


@app.route("/settings/username", methods=["POST"])
def update_username():
    user_id = session["user_id"]

    new_username = request.form.get(
        "username",
        "",
    ).strip()

    if not new_username:
        flash(
            "Username cannot be empty.",
            "error",
        )
        return redirect("/settings")

    if len(new_username) < 2:
        flash(
            "Username must be at least 2 characters.",
            "error",
        )
        return redirect("/settings")

    connection = get_db_connection()
    cursor = connection.cursor()

    try:
        # Check whether another account already uses it
        cursor.execute(
            """
            SELECT id
            FROM users
            WHERE LOWER(username) = LOWER(%s)
            AND id != %s
            """,
            (
                new_username,
                user_id,
            ),
        )

        existing_user = cursor.fetchone()

        if existing_user:
            flash(
                "That username is already in use.",
                "error",
            )

            return redirect("/settings")

        cursor.execute(
            """
            UPDATE users
            SET username = %s
            WHERE id = %s
            """,
            (
                new_username,
                user_id,
            ),
        )

        connection.commit()

    except Exception:
        connection.rollback()
        raise

    finally:
        cursor.close()
        connection.close()

    # Update the username shown everywhere immediately
    session["username"] = new_username

    flash(
        "Username updated successfully.",
        "success",
    )

    return redirect("/settings")


@app.route("/settings/password", methods=["POST"])
def update_password():
    user_id = session["user_id"]

    current_password = request.form.get(
        "current_password",
        "",
    )

    new_password = request.form.get(
        "new_password",
        "",
    )

    confirm_password = request.form.get(
        "confirm_password",
        "",
    )

    if not current_password or not new_password or not confirm_password:
        flash(
            "Please fill in all password fields.",
            "error",
        )

        return redirect("/settings")

    if new_password != confirm_password:
        flash(
            "New passwords do not match.",
            "error",
        )

        return redirect("/settings")

    if len(new_password) < 8:
        flash(
            "New password must be at least 8 characters.",
            "error",
        )

        return redirect("/settings")

    connection = get_db_connection()
    cursor = connection.cursor()

    try:
        cursor.execute(
            """
            SELECT password_hash
            FROM users
            WHERE id = %s
            """,
            (user_id,),
        )

        user = cursor.fetchone()

        if user is None:
            session.clear()
            return redirect("/login")

        current_hash = user[0]

        if not check_password_hash(
            current_hash,
            current_password,
        ):
            flash(
                "Current password is incorrect.",
                "error",
            )

            return redirect("/settings")

        new_password_hash = generate_password_hash(
            new_password
        )

        cursor.execute(
            """
            UPDATE users
            SET password_hash = %s
            WHERE id = %s
            """,
            (
                new_password_hash,
                user_id,
            ),
        )

        connection.commit()

    except Exception:
        connection.rollback()
        raise

    finally:
        cursor.close()
        connection.close()

    flash(
        "Password changed successfully.",
        "success",
    )

    return redirect("/settings")




@app.route("/forgot-password", methods=["GET", "POST"])
def forgot_password():
    message = None
    error = None
    email = ""

    if request.method == "POST":
        email = request.form.get("email", "").strip().lower()

        if not email:
            error = "Please enter your email address."

        else:
            connection = get_db_connection()
            cursor = connection.cursor()

            try:
                cursor.execute(
                    """
                    SELECT id
                    FROM users
                    WHERE LOWER(email) = LOWER(%s)
                    """,
                    (email,),
                )

                user = cursor.fetchone()

                if user:
                    user_id = user[0]

                    # Old unused links become invalid
                    cursor.execute(
                        """
                        UPDATE password_reset_tokens
                        SET used = TRUE
                        WHERE user_id = %s
                        AND used = FALSE
                        """,
                        (user_id,),
                    )

                    token = secrets.token_urlsafe(32)

                    token_hash = hashlib.sha256(
                        token.encode("utf-8")
                    ).hexdigest()

                    expires_at = (
                        datetime.now(timezone.utc)
                        + timedelta(minutes=45)
                    )

                    cursor.execute(
                        """
                        INSERT INTO password_reset_tokens
                        (user_id, token_hash, expires_at)
                        VALUES (%s, %s, %s)
                        """,
                        (
                            user_id,
                            token_hash,
                            expires_at,
                        ),
                    )

                    connection.commit()

                    reset_link = url_for(
                        "reset_password",
                        token=token,
                        _external=True,
                    )

                    # TEMPORARY:
                    # We will email this later.
                    resend.Emails.send({
                        "from": "UniTrack <onboarding@resend.dev>",
                        "to": [email],
                        "subject": "Reset your UniTrack password",
                        "html": f"""
                            <div style="font-family: Arial, sans-serif; max-width: 520px; margin: auto;">
                                <h2>Reset your UniTrack password</h2>

                                <p>
                                    We received a request to reset the password for your
                                    UniTrack account.
                                </p>

                                <p>
                                    Click the button below to choose a new password.
                                </p>

                                <a href="{reset_link}"
                                    style="
                                        display: inline-block;
                                        padding: 12px 20px;
                                        background: #635bff;
                                        color: white;
                                        text-decoration: none;
                                        border-radius: 8px;
                                        font-weight: bold;
                                    ">
                                    Reset Password
                                </a>

                                <p style="margin-top: 24px; color: #666;">
                                    This link expires in 45 minutes.
                                </p>

                                <p style="color: #666;">
                                    If you didn't request a password reset,
                                    you can ignore this email.
                                </p>

                                <p style="margin-top: 30px;">
                                    — UniTrack
                                </p>
                            </div>
                        """,
                    })

                message = (
                    "If an account exists with that email, "
                    "a password reset link has been created."
                )

            except Exception:
                connection.rollback()
                raise

            finally:
                cursor.close()
                connection.close()

    return render_template(
        "forgot_password.html",
        message=message,
        error=error,
        email=email,
    )


@app.route(
    "/reset-password/<token>",
    methods=["GET", "POST"],
)
def reset_password(token):
    token_hash = hashlib.sha256(
        token.encode("utf-8")
    ).hexdigest()

    connection = get_db_connection()
    cursor = connection.cursor()

    try:
        cursor.execute(
            """
            SELECT id, user_id
            FROM password_reset_tokens
            WHERE token_hash = %s
            AND used = FALSE
            AND expires_at > NOW()
            """,
            (token_hash,),
        )

        reset_record = cursor.fetchone()

        if reset_record is None:
            return render_template(
                "reset_password.html",
                invalid=True,
                error=None,
            )

        reset_id = reset_record[0]
        user_id = reset_record[1]

        error = None

        if request.method == "POST":
            new_password = request.form.get(
                "new_password",
                "",
            )

            confirm_password = request.form.get(
                "confirm_password",
                "",
            )

            if not new_password or not confirm_password:
                error = "Please fill in both password fields."

            elif len(new_password) < 8:
                error = (
                    "Password must be at least 8 characters."
                )

            elif new_password != confirm_password:
                error = "Passwords do not match."

            else:
                new_password_hash = generate_password_hash(
                    new_password
                )

                cursor.execute(
                    """
                    UPDATE users
                    SET password_hash = %s
                    WHERE id = %s
                    """,
                    (
                        new_password_hash,
                        user_id,
                    ),
                )

                # Invalidate every reset token for this account
                cursor.execute(
                    """
                    UPDATE password_reset_tokens
                    SET used = TRUE
                    WHERE user_id = %s
                    """,
                    (user_id,),
                )

                connection.commit()

                flash(
                    "Password reset successfully. You can now log in.",
                    "success",
                )

                return redirect("/login")

        return render_template(
            "reset_password.html",
            invalid=False,
            error=error,
        )

    except Exception:
        connection.rollback()
        raise

    finally:
        cursor.close()
        connection.close()


@app.route("/logout", methods=["POST"])
def logout():
    session.clear()
    return redirect("/login")


if __name__ == "__main__":
    app.run(debug=os.environ.get("FLASK_DEBUG", "0") == "1")

