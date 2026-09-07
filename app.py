# Part 1: imports + Adding all of the security and anti-spam measures against bots, long fieild characters,profanity, etc. and adding autodeletion of entries via TTL.

from flask import (
    Flask,
    Response,
    request,
    jsonify,
    render_template,
    redirect,
    url_for,
    flash,
)
from bson.objectid import ObjectId
from bson.errors import InvalidId
from bson.json_util import dumps
from datetime import datetime, timezone
from collections import Counter
import string
import os
import re

from flask_limiter import Limiter
from flask_limiter.util import get_remote_address
from db import db

from dotenv import load_dotenv
from werkzeug.middleware.proxy_fix import ProxyFix  # Imports the proxy fix

load_dotenv()

app = Flask(__name__)

# 1. Avoiding the Render Proxy IP issue
app.wsgi_app = ProxyFix(app.wsgi_app, x_for=1, x_proto=1, x_host=1, x_prefix=1)

# 2. Prevents a crash if Render environment variable is missing
app.config["SECRET_KEY"] = os.environ.get("SECRET_KEY") or os.urandom(24)

# 3. Prevents memory DDoS attacks (caps incoming data at 2 Megabytes)
app.config["MAX_CONTENT_LENGTH"] = 2 * 1024 * 1024

# Setting up the limiter and tell it to use that link to store IPs on our MongoDB server
# So as to correctly enforce rate-limiter
LIMITER_DB_LINK = os.environ.get("MONGODB_URI")

limiter = Limiter(
    key_func=get_remote_address,
    storage_uri=LIMITER_DB_LINK,
    strategy="fixed-window"
)
limiter.init_app(app)

# Creating TTL indexes to auto-delete entries older than 30 days (30 days = 2592000 seconds)
db.feedbacks.create_index("created_at", expireAfterSeconds=2592000)
db.students.create_index("created_at", expireAfterSeconds=2592000)

# Setting maximum lengths for each field and setting allowed/required field :
MAX_NAME_LENGTH = 50
MAX_BIO_LENGTH = 200
MAX_MESSAGE_LENGTH = 300
MAX_COUNTRY_LENGTH = 50
MAX_CITY_LENGTH = 50
MAX_SKILLS_LENGTH = 200
ALLOWED_FIELDS = ("name", "country", "city", "birthyear", "skills", "bio")
REQUIRED_FIELDS = ("name",)
# Reads profanity list from the .env file locally or from the env variables set on Render
PROFANITY_LIST = os.environ.get("PROFANITY_LIST", "").split(",")
# Removes any empty strings if the variable is not set
PROFANITY_LIST = [word.strip() for word in PROFANITY_LIST if word.strip()]

# Part 2 :  Validation functions + Home/About/Students


def contains_url(text):
    """
    Return True if the text contains a URL anywhere in it.
    Scans for http://, https://, www., or domain-like patterns with common TLDs.
    """
    if not text:
        return False
    if not isinstance(text, str):
        text = str(text) if text is not None else ""

    # Matches http://, https://, www., or domain-like patterns with common TLDs :
    url_pattern = r"https?://[^\s]+|www\.[^\s]+|[a-zA-Z0-9-]+\.(?:com|org|net|io|co|in|edu|gov)\b(?:/[^\s]*)?"
    return bool(re.search(url_pattern, text))


def validate_length(text, max_len, field_name):
    if text is None:
        return True, ""
    if not isinstance(text, str):
        text = str(text)
    if len(text) > max_len:
        return False, f"{field_name} exceeds maximum length of {max_len} characters."
    return True, ""


def contains_profanity(text):
    if not text:
        return False
    if not isinstance(text, str):
        text = str(text) if text is not None else ""
    text_lower = text.lower()
    for word in PROFANITY_LIST:
        pattern = rf"\b{re.escape(word)}\b"
        if re.search(pattern, text_lower):
            return True
    return False


def any_profanity(text_list):
    """Return True if any string in the list contains profanity."""
    if not text_list:
        return False
    for text in text_list:
        if contains_profanity(text):
            return True
    return False


def validate_birthyear(year_str):
    """Return True if year is a 4-digit number between 1900 and current year."""
    if not year_str:
        return True  # optional field, empty is fine
    if not year_str.isdigit():
        return False
    year = int(year_str)
    current_year = datetime.now(timezone.utc).year
    return 1900 <= year <= current_year


def parse_skills(value):
    if value is None:
        return []
    if isinstance(value, str):
        return [s.strip() for s in value.split(",") if s.strip()]
    if isinstance(value, list):
        return [str(s).strip() for s in value if str(s).strip()]
    return []


def validate_student_data(student):
    """
    Validate all fields of a student document.
    Returns (is_valid, error_message).
    """

    # Safely converts fields to strings, handling None and non-string types
    def safe_str(value):
        if value is None:
            return ""
        if isinstance(value, (int, float)):
            return str(value)
        if isinstance(value, str):
            return value
        return ""  # fallback for any other type (list, dict, etc.)

    name = safe_str(student.get("name")).strip()
    bio = safe_str(student.get("bio")).strip()
    country = safe_str(student.get("country")).strip()
    city = safe_str(student.get("city")).strip()
    skills = safe_str(student.get("skills")).strip()
    birthyear = safe_str(student.get("birthyear")).strip()

    # Non-empty name
    if not name:
        return False, "Name is required."

    # Length limits
    valid, msg = validate_length(name, MAX_NAME_LENGTH, "Name")
    if not valid:
        return False, msg
    valid, msg = validate_length(bio, MAX_BIO_LENGTH, "Bio")
    if not valid:
        return False, msg
    valid, msg = validate_length(country, MAX_COUNTRY_LENGTH, "Country")
    if not valid:
        return False, msg
    valid, msg = validate_length(city, MAX_CITY_LENGTH, "City")
    if not valid:
        return False, msg
    valid, msg = validate_length(skills, MAX_SKILLS_LENGTH, "Skills")
    if not valid:
        return False, msg

    # Profanity check
    if any_profanity([name, bio, country, city, skills]):
        return False, "Inappropriate content detected."

    # URL check
    if (
        contains_url(name)
        or contains_url(bio)
        or contains_url(country)
        or contains_url(city)
        or contains_url(skills)
    ):
        return False, "Links are not allowed."

    # Birthyear validation
    if birthyear and not validate_birthyear(birthyear):
        return False, "Birth year must be a 4-digit year between 1900 and current year."

    return True, ""


@app.route("/", methods=["GET"])
def index():
    techs = ["HTML", "CSS", "Flask", "Python", "MongoDB"]
    return render_template("index.html", techs=techs, title="Home")


@app.route("/about")
def about():
    return render_template("about.html", title="About Us")


@app.route("/students", methods=["GET"])
def students_page():
    # Safely gets integers, defaults to 1 and 50 if user types nonsense
    page = request.args.get("page", 1, type=int)
    limit = request.args.get("limit", 50, type=int)

    # Prevents negative numbers and caps the limit at 100 max
    page = max(1, page)
    limit = max(1, min(limit, 100))
    skip_amount = (page - 1) * limit

    students = list(db.students.find().skip(skip_amount).limit(limit))
    return render_template("students.html", students=students, title="Students")


# Part 3 : Join_page fully hardened :


@app.route("/join", methods=["GET", "POST"])
@limiter.limit("5 per hour", methods=["POST"])
def join_page():
    msg = ""
    if request.method == "POST":
        
        # Honeypot check
        if request.form.get("honeypot"):
            return "Suspicious activity detected", 400

        # Retrieving data :
        student = {f: request.form.get(f, "") for f in ALLOWED_FIELDS}

        # Validating using central function :
        valid, msg = validate_student_data(student)
        if not valid:
            return (
                render_template("join.html", error=msg, submitted=False, title="Join"),
                400,
            )

        # Processing skills and inserting :
        student["skills"] = parse_skills(student["skills"])
        student["created_at"] = datetime.now(timezone.utc)
        db.students.insert_one(student)
        flash("Thanks for joining!", "success")
        return redirect(url_for("students_page"))
    return render_template("join.html", submitted=False, error=msg, title="Join")


# Part 4 : text_analyzer :


def analyze_text(content):
    word_count = len(content.split())
    char_count = len(content)
    cleaned = content.lower()
    for punct in string.punctuation:
        cleaned = cleaned.replace(punct, " ")
    words = cleaned.split()
    most_common = Counter(words).most_common(3)
    return {
        "word_count": word_count,
        "char_count": char_count,
        "most_common": most_common,
    }


@app.route("/text-analyzer", methods=["GET", "POST"])
def text_analyzer():
    if request.method != "POST":
        return render_template("text_analyzer.html", title="Text Analyzer")
    text = request.form.get("text", "")
    analysis = analyze_text(text)
    return render_template(
        "text_analyzer.html", text=text, title="Text Analyzer", **analysis
    )


# Part 5 : feedback_page fully harderned :


@app.route("/feedback", methods=["GET", "POST"])
@limiter.limit("5 per hour", methods=["POST"])
def feedback_page():
    msg = ""
    status_code = 200
    if request.method == "POST":
       
        # Honeypot check
        if request.form.get("honeypot"):
            return "Suspicious activity detected", 400

        name = request.form.get("name", "").strip()
        message = request.form.get("message", "").strip()

        # Non-empty name check :
        if not name:
            msg = "Name is required."
        elif not message:
            msg = "Message is required."
        else:
            valid_name, msg_name = validate_length(name, MAX_NAME_LENGTH, "Name")
            valid_msg, msg_msg = validate_length(message, MAX_MESSAGE_LENGTH, "Message")

            # Validating lengths, profanity and URL check :
            if not valid_name:
                msg = msg_name
            elif not valid_msg:
                msg = msg_msg
            elif contains_profanity(name) or contains_profanity(message):
                msg = "Inappropriate content detected."
            elif contains_url(name) or contains_url(message):
                msg = "Links are not allowed."

        if msg:
            status_code = 400
        else:
            # Inserting the feedback :
            db.feedbacks.insert_one(
                {
                    "name": name,
                    "message": message,
                    "created_at": datetime.now(timezone.utc),
                }
            )
            return redirect(url_for("feedback_page"))

    # Single database call for both GET and failed POST requests
    feedbacks = list(db.feedbacks.find().sort("created_at", -1).limit(100))
    return (
        render_template(
            "feedback.html", feedbacks=feedbacks, error=msg, title="Feedbacks"
        ),
        status_code,
    )


# Part 6 : JSON API - GET & POST :


@app.route("/api/v1.0/students", methods=["GET"])
def get_students():
    # Safely gets integers, defaults to 1 and 50 if user types nonsense
    page = request.args.get("page", 1, type=int)
    limit = request.args.get("limit", 50, type=int)

    # Prevents negative numbers and caps the limit at 100 max
    page = max(1, page)
    limit = max(1, min(limit, 100))
    skip_amount = (page - 1) * limit

    students = list(db.students.find().skip(skip_amount).limit(limit))
    return Response(dumps(students), mimetype="application/json")


@app.route("/api/v1.0/students/<id>", methods=["GET"])
def get_student(id):
    try:
        student = db.students.find_one({"_id": ObjectId(id)})
    except InvalidId:
        return jsonify({"error": "That id is not a valid MongoDB ObjectId"}), 400
    if student is None:
        return jsonify({"error": "No student found with that id"}), 404
    return Response(dumps(student), mimetype="application/json")


@app.route("/api/v1.0/students", methods=["POST"])
@limiter.limit("5 per hour")
def create_student():
    data = request.get_json(silent=True) or request.form

    if not isinstance(data, dict):
        return jsonify({"error": "Invalid payload format. Expected JSON object."}), 400

    # Checking only REQUIRED_FIELDS, not ALLOWED_FIELDS, so someone can only input their name
    missing = [f for f in REQUIRED_FIELDS if f not in data]
    if missing:
        return jsonify({"error": f'Missing required fields: {", ".join(missing)}'}), 400

    student = {field: data[field] for field in ALLOWED_FIELDS if field in data}

    # Validating the fields in API as well :
    valid, msg = validate_student_data(student)
    if not valid:
        return jsonify({"error": msg}), 400

    student["skills"] = parse_skills(student["skills"])
    student["created_at"] = datetime.now(timezone.utc)

    result = db.students.insert_one(student)
    return jsonify({"result": "Student created", "id": str(result.inserted_id)}), 201


# PART 7 : JSON API - PUT, DELETE + entry point :


@app.route("/api/v1.0/students/<id>", methods=["PUT"])
@limiter.limit("5 per hour")
def update_student(id):

    # API KEY CHECK :
    admin_key = os.environ.get("ADMIN_API_KEY")
    provided_key = request.headers.get("x-api-key")

    if not admin_key or provided_key != admin_key:
        return jsonify({"error": "Unauthorized. Admin API key required."}), 403

    try:
        query = {"_id": ObjectId(id)}
    except InvalidId:
        return jsonify({"error": "That id is not a valid MongoDB ObjectId"}), 400

    data = request.get_json(silent=True) or request.form
    if not isinstance(data, dict):
        return jsonify({"error": "Invalid payload format. Expected JSON object."}), 400

    updates = {f: data[f] for f in ALLOWED_FIELDS if f in data}

    if not updates:
        return jsonify({"error": "No valid fields supplied to update"}), 400

    # 1. Merging and validating the raw string data first :
    existing = db.students.find_one({"_id": ObjectId(id)})
    if existing:
        merged = {**existing, **updates}
        # If existing['skills'] is already a list from the DB, converting it temporarily back to a string for validation,
        # or adjusting validate_student_data to handle lists.
        if isinstance(merged.get("skills"), list):
            merged["skills"] = ", ".join(merged["skills"])

        valid, msg = validate_student_data(merged)
        if not valid:
            return jsonify({"error": msg}), 400

    # 2. Processing updates after validation :
    if "skills" in updates:
        updates["skills"] = parse_skills(updates["skills"])

    result = db.students.update_one(query, {"$set": updates})
    if result.matched_count == 0:
        return jsonify({"error": "No student found with that id"}), 404
    return jsonify({"result": "Student updated"}), 200


@app.route("/api/v1.0/students/<id>", methods=["DELETE"])
@limiter.limit("5 per hour")
def delete_student(id):

    # API KEY CHECK :
    admin_key = os.environ.get("ADMIN_API_KEY")
    provided_key = request.headers.get("x-api-key")

    if not admin_key or provided_key != admin_key:
        return jsonify({"error": "Unauthorized. Admin API key required."}), 403

    try:
        query = {"_id": ObjectId(id)}
    except InvalidId:
        return jsonify({"error": "That id is not a valid MongoDB ObjectId"}), 400

    result = db.students.delete_one(query)
    if result.deleted_count == 0:
        return jsonify({"error": "No student found with that id"}), 404
    return jsonify({"result": "Student deleted"}), 200


if __name__ == "__main__":
    debug_mode = os.environ.get("FLASK_DEBUG", "0") == "1"
    host = os.environ.get("FLASK_HOST", "127.0.0.1")
    port = int(os.environ.get("PORT", 5000))
    app.run(debug=debug_mode, host=host, port=port)