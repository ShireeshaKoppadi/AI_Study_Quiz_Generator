from flask import Flask, render_template, request, redirect, url_for, session, flash
from dotenv import load_dotenv
from google import genai
from werkzeug.security import generate_password_hash, check_password_hash
from werkzeug.utils import secure_filename

import os
import json
import re
import random
import sqlite3
from PyPDF2 import PdfReader


# =========================
# LOAD ENVIRONMENT VARIABLES
# =========================

load_dotenv()

app = Flask(__name__)

app.secret_key = os.getenv(
    "SECRET_KEY",
    "default_secret_key_change_this"
)

api_key = os.getenv("GEMINI_API_KEY")

if not api_key:
    raise ValueError("GEMINI_API_KEY not found in .env file")

client = genai.Client(api_key=api_key)


# =========================
# FOLDERS
# =========================

UPLOAD_FOLDER = "uploads"

if not os.path.exists(UPLOAD_FOLDER):
    os.makedirs(UPLOAD_FOLDER)

app.config["UPLOAD_FOLDER"] = UPLOAD_FOLDER


# =========================
# DATABASE
# =========================

DATABASE = "quiz.db"


def get_db():

    conn = sqlite3.connect(DATABASE)
    conn.row_factory = sqlite3.Row

    return conn


def init_db():

    conn = get_db()

    cursor = conn.cursor()

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            username TEXT NOT NULL UNIQUE,
            email TEXT NOT NULL UNIQUE,
            password TEXT NOT NULL
        )
    """)

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS quiz_history (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            subject TEXT,
            score INTEGER,
            total INTEGER,
            percentage REAL,
            grade TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)

    conn.commit()
    conn.close()


init_db()


# =========================
# LOGIN REQUIRED
# =========================

def login_required():

    if "user_id" not in session:
        return False

    return True


# =========================
# GEMINI MODEL
# =========================

MODEL_NAME = "gemini-3.1-flash-lite"


# =========================
# HOME PAGE
# =========================

@app.route("/")
def home():

    return render_template("index.html")


# =========================
# REGISTER
# =========================

@app.route("/register", methods=["GET", "POST"])
def register():

    if request.method == "POST":

        username = request.form.get("username", "").strip()
        email = request.form.get("email", "").strip()
        password = request.form.get("password", "")

        if not username or not email or not password:

            flash("Please fill all fields.")

            return redirect(url_for("register"))

        hashed_password = generate_password_hash(password)

        try:

            conn = get_db()

            conn.execute(
                """
                INSERT INTO users (username, email, password)
                VALUES (?, ?, ?)
                """,
                (username, email, hashed_password)
            )

            conn.commit()
            conn.close()

            flash("Registration successful! Please login.")

            return redirect(url_for("login"))

        except sqlite3.IntegrityError:

            flash("Username or email already exists.")

            return redirect(url_for("register"))

    return render_template("register.html")


# =========================
# LOGIN
# =========================

@app.route("/login", methods=["GET", "POST"])
def login():

    if request.method == "POST":

        email = request.form.get("email", "").strip()
        password = request.form.get("password", "")

        conn = get_db()

        user = conn.execute(
            "SELECT * FROM users WHERE email = ?",
            (email,)
        ).fetchone()

        conn.close()

        if user and check_password_hash(
            user["password"],
            password
        ):

            session["user_id"] = user["id"]
            session["username"] = user["username"]

            flash("Login successful!")

            return redirect(url_for("home"))

        else:

            flash("Invalid email or password.")

    return render_template("login.html")


# =========================
# LOGOUT
# =========================

@app.route("/logout")
def logout():

    session.clear()

    flash("You have logged out.")

    return redirect(url_for("home"))


# =========================
# READ PDF
# =========================

def read_pdf(file):

    reader = PdfReader(file)

    text = ""

    for page in reader.pages:

        page_text = page.extract_text()

        if page_text:
            text += page_text + "\n"

    return text


# =========================
# CLEAN JSON
# =========================

def clean_json(text):

    text = text.strip()

    text = re.sub(
        r"^```json\s*",
        "",
        text,
        flags=re.IGNORECASE
    )

    text = re.sub(
        r"^```\s*",
        "",
        text
    )

    text = re.sub(
        r"\s*```$",
        "",
        text
    )

    return text.strip()


# =========================
# GENERATE QUIZ
# =========================

@app.route("/generate", methods=["POST"])
def generate_quiz():

    study_material = request.form.get(
        "study_material",
        ""
    ).strip()

    subject = request.form.get(
        "subject",
        "General"
    ).strip()

    num_questions = request.form.get(
        "num_questions",
        "5"
    )

    difficulty = request.form.get(
        "difficulty",
        "Medium"
    )

    pdf_file = request.files.get("pdf_file")


    # PDF FILE
    if pdf_file and pdf_file.filename:

        if pdf_file.filename.lower().endswith(".pdf"):

            try:

                pdf_text = read_pdf(pdf_file)

                study_material += "\n" + pdf_text

            except Exception as e:

                return render_template(
                    "index.html",
                    error=f"Error reading PDF: {str(e)}"
                )

        else:

            return render_template(
                "index.html",
                error="Please upload only a PDF file."
            )


    if not study_material:

        return render_template(
            "index.html",
            error="Please enter study material or upload a PDF."
        )


    prompt = f"""
You are an expert AI quiz generator.

Create exactly {num_questions} multiple choice questions.

Subject:
{subject}

Difficulty:
{difficulty}

Study Material:
{study_material}

Rules:

1. Create exactly {num_questions} questions.
2. Every question must have exactly 4 options.
3. Only one option must be correct.
4. Difficulty must match: {difficulty}.
5. Create a short and simple explanation for every answer.
6. Return ONLY valid JSON.
7. Do not use markdown.
8. Do not use ```json.

Use exactly this JSON format:

[
    {{
        "question": "Question text",
        "options": [
            "Option 1",
            "Option 2",
            "Option 3",
            "Option 4"
        ],
        "answer": "Correct option",
        "explanation": "Simple explanation"
    }}
]
"""


    try:

        response = client.models.generate_content(
            model=MODEL_NAME,
            contents=prompt
        )

        response_text = clean_json(response.text)

        quiz = json.loads(response_text)


        # SHUFFLE QUESTIONS
        random.shuffle(quiz)


        # SHUFFLE OPTIONS
        for item in quiz:

            random.shuffle(item["options"])


        # SAVE QUIZ FOR RETAKE
        session["quiz"] = quiz
        session["subject"] = subject
        session["difficulty"] = difficulty


        return render_template(
            "quiz.html",
            quiz=quiz,
            subject=subject,
            difficulty=difficulty
        )


    except Exception as e:

        return render_template(
            "index.html",
            error=f"Error generating quiz: {str(e)}"
        )


# =========================
# SUBMIT QUIZ
# =========================

@app.route("/submit", methods=["POST"])
def submit_quiz():

    quiz = session.get("quiz")

    if not quiz:

        flash("Quiz session expired. Please generate a new quiz.")

        return redirect(url_for("home"))


    score = 0
    results = []


    for i, item in enumerate(quiz, start=1):

        user_answer = request.form.get(
            f"question_{i}"
        )

        correct_answer = item["answer"]

        if user_answer == correct_answer:

            score += 1
            is_correct = True

        else:

            is_correct = False


        results.append({
            "question_number": i,
            "question": item["question"],
            "user_answer": user_answer,
            "correct_answer": correct_answer,
            "explanation": item.get(
                "explanation",
                "No explanation available."
            ),
            "is_correct": is_correct
        })


    total = len(quiz)

    wrong = total - score

    percentage = round(
        (score / total) * 100,
        2
    )


    # GRADE
    if percentage >= 90:

        grade = "A+"

    elif percentage >= 80:

        grade = "A"

    elif percentage >= 70:

        grade = "B"

    elif percentage >= 60:

        grade = "C"

    elif percentage >= 50:

        grade = "D"

    else:

        grade = "F"


    # PERFORMANCE
    if percentage >= 90:

        performance = "Excellent! Outstanding performance!"

    elif percentage >= 75:

        performance = "Great job! You have a strong understanding."

    elif percentage >= 60:

        performance = "Good job! Keep practicing to improve further."

    elif percentage >= 40:

        performance = "Average performance. Review the topic and try again."

    else:

        performance = "You need more practice. Study the topic and retake the quiz."


    subject = session.get("subject", "General")


    # SAVE HISTORY ONLY IF LOGGED IN
    if "user_id" in session:

        conn = get_db()

        conn.execute(
            """
            INSERT INTO quiz_history
            (user_id, subject, score, total, percentage, grade)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (
                session["user_id"],
                subject,
                score,
                total,
                percentage,
                grade
            )
        )

        conn.commit()
        conn.close()


    return render_template(
        "result.html",
        score=score,
        total=total,
        wrong=wrong,
        percentage=percentage,
        grade=grade,
        performance=performance,
        results=results,
        subject=subject
    )


# =========================
# RETAKE QUIZ
# =========================

@app.route("/retake")
def retake_quiz():

    quiz = session.get("quiz")

    if not quiz:

        flash("No quiz available to retake.")

        return redirect(url_for("home"))


    subject = session.get(
        "subject",
        "General"
    )

    difficulty = session.get(
        "difficulty",
        "Medium"
    )


    return render_template(
        "quiz.html",
        quiz=quiz,
        subject=subject,
        difficulty=difficulty
    )


# =========================
# QUIZ HISTORY
# =========================

@app.route("/history")
def history():

    if not login_required():

        flash("Please login to view quiz history.")

        return redirect(url_for("login"))


    conn = get_db()

    history_data = conn.execute(
        """
        SELECT *
        FROM quiz_history
        WHERE user_id = ?
        ORDER BY id DESC
        """,
        (session["user_id"],)
    ).fetchall()

    conn.close()


    return render_template(
        "history.html",
        history=history_data
    )


# =========================
# LEADERBOARD
# =========================

@app.route("/leaderboard")
def leaderboard():

    conn = get_db()

    leaders = conn.execute(
        """
        SELECT
            users.username,
            quiz_history.subject,
            quiz_history.score,
            quiz_history.total,
            quiz_history.percentage,
            quiz_history.grade

        FROM quiz_history

        JOIN users
        ON users.id = quiz_history.user_id

        ORDER BY quiz_history.percentage DESC,
                 quiz_history.score DESC

        LIMIT 10
        """
    ).fetchall()

    conn.close()


    return render_template(
        "leaderboard.html",
        leaders=leaders
    )


# =========================
# RUN APP
# =========================

if __name__ == "__main__":

    app.run(debug=True)