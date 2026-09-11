import os
from datetime import datetime, date

import psycopg2
from dotenv import load_dotenv
from flask import Flask, abort, flash, redirect, render_template, request, session
from werkzeug.security import check_password_hash, generate_password_hash

load_dotenv()

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
    public_endpoints = {"login", "register", "static"}

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


@app.route("/logout", methods=["POST"])
def logout():
    session.clear()
    return redirect("/login")


if __name__ == "__main__":
    app.run(debug=os.environ.get("FLASK_DEBUG", "0") == "1")
