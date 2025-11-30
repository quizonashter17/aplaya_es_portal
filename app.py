# app.py
from flask import Flask, render_template, request, redirect, url_for, session, flash
import os
from werkzeug.utils import secure_filename
from datetime import datetime
from supabase import create_client, Client
import smtplib
from email.message import EmailMessage
import re
import logging
from collections import defaultdict


# === FLASK SETUP ===
app = Flask(__name__)
app.secret_key = os.environ.get("FLASK_SECRET", "aplaya_secret_key")

# === SUPABASE CONNECTION ===
SUPABASE_URL = os.environ.get("SUPABASE_URL", "https://oijbypltxvdczfcootok.supabase.co")
SUPABASE_KEY = os.environ.get("SUPABASE_KEY", "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJpc3MiOiJzdXBhYmFzZSIsInJlZiI6Im9pamJ5cGx0eHZkY3pmY29vdG9rIiwicm9sZSI6ImFub24iLCJpYXQiOjE3NjEzMzMxMTQsImV4cCI6MjA3NjkwOTExNH0.OEErl2tRV9PXuZqS43staotvdb8zWPYNjYekPajh8Gs")
supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY)

# === EMAIL (GMAIL) CONFIG ===
# Option 1: set environment variables EMAIL_USER and EMAIL_PASSWORD (recommended)
# Option 2: edit below constants (NOT recommended to paste secrets into source control).
EMAIL_USER = os.environ.get("EMAIL_USER", "aplayaelementarypila@gmail.com")
EMAIL_PASSWORD = os.environ.get("EMAIL_PASSWORD", "Yfcqm vbot ooqk iukr")  # Put app password here or as env var

# === CONFIG ===
app.config['UPLOAD_FOLDER'] = 'static/uploads'
app.config['ALLOWED_EXTENSIONS'] = {'png', 'jpg', 'jpeg', 'gif'}

# basic logger
logging.basicConfig(level=logging.INFO)

# === HELPERS ===
def allowed_file(filename):
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in app.config['ALLOWED_EXTENSIONS']

def get_profile_pic():
    profile_pic_path = os.path.join(app.config['UPLOAD_FOLDER'], 'profile.jpg')
    if os.path.exists(profile_pic_path):
        return url_for('static', filename='uploads/profile.jpg')
    return url_for('static', filename='uploads/default.jpg')

def current_school_year():
    y = datetime.utcnow().year
    return f"{y}-{y+1}"

@app.context_processor
def inject_user_data():
    return {
        'user_role': session.get('user_role'),
        'username': session.get('username'),
        'profile_pic': get_profile_pic()
    }

# -----------------------------
# EMAIL SENDING UTIL
# -----------------------------
def is_email_like(s):
    if not s:
        return False
    return bool(re.search(r"[^@]+@[^@]+\.[^@]+", s))

def send_email(to_email: str, subject: str, body: str) -> bool:
    """Send email via Gmail SMTP using EMAIL_USER and EMAIL_PASSWORD.
    Returns True on success, False on failure (and logs the exception)."""
    if not to_email or not is_email_like(to_email):
        app.logger.warning("send_email: invalid to_email %r", to_email)
        return False

    try:
        msg = EmailMessage()
        msg["From"] = EMAIL_USER
        msg["To"] = to_email
        msg["Subject"] = subject
        msg.set_content(body)

        # Gmail SMTP (TLS)
        with smtplib.SMTP("smtp.gmail.com", 587) as smtp:
            smtp.ehlo()
            smtp.starttls()
            smtp.login(EMAIL_USER, EMAIL_PASSWORD)
            smtp.send_message(msg)

        app.logger.info("Email sent to %s (subject=%s)", to_email, subject)
        return True
    except Exception as e:
        app.logger.exception("Failed to send email to %s", to_email)
        return False

# -----------------------------
# AUTH / LOGIN
# -----------------------------
@app.route('/login', methods=['GET', 'POST'])
def login():
    error = None
    if request.method == 'POST':
        username = request.form.get('username', '').strip()
        password = request.form.get('password', '').strip()
        try:
            # NOTE: For production, hash passwords instead of using plaintext
            result = supabase.table("users").select("*").eq("username", username).eq("password", password).execute()
            if result.data:
                user = result.data[0]
                session['user_role'] = user['role']
                session['username'] = user['username']
                session['user_id'] = user['id']
                # redirect by role
                if user['role'] == 'principal':
                    return redirect(url_for('principal_dashboard'))
                elif user['role'] == 'teacher':
                    return redirect(url_for('teacher_dashboard'))
                elif user['role'] == 'student':
                    return redirect(url_for('student_dashboard'))
                else:
                    error = "Unknown user role."
            else:
                error = "Invalid username or password."
        except Exception as e:
            app.logger.exception("Login error")
            error = f"Database error: {e}"
    return render_template('login.html', error=error)

@app.route('/logout')
def logout():
    session.clear()
    return redirect(url_for('login'))

# -----------------------------
# ROUTES: DASHBOARD
# -----------------------------
@app.route('/')
def dashboard():
    if 'user_role' not in session:
        return redirect(url_for('login'))
    role = session['user_role']
    if role == 'principal':
        return redirect(url_for('principal_dashboard'))
    elif role == 'teacher':
        return redirect(url_for('teacher_dashboard'))
    elif role == 'student':
        return redirect(url_for('student_dashboard'))
    return redirect(url_for('login'))

# -----------------------------
# PRINCIPAL: DASHBOARD & ENROLLMENTS
# -----------------------------
@app.route('/principal_dashboard')
def principal_dashboard():
    if session.get('user_role') != 'principal':
        return redirect(url_for('login'))
    return render_template('principal_dashboard.html', title="Principal Dashboard")

@app.route('/principal/enrollment_requests')
def view_enrollment_requests():
    if session.get('user_role') != 'principal':
        return redirect(url_for('login'))

    try:
        # Retrieve pending enrollment requests
        # We select all fields present in the enrollment_requests table.
        requests_list = supabase.table("enrollment_requests").select("*").eq("status", "pending").execute().data or []
    except Exception:
        app.logger.exception("Failed to load enrollment_requests")
        requests_list = []

    enriched = []
    for r in requests_list:
        # Try to attach students.user_id -> users.email as fallback for parent email
        parent_email = None
        try:
            student_row = supabase.table("students").select("*").eq("id", r.get('student_id')).execute().data or []
            student = student_row[0] if student_row else {}
            # If parent_contact is email-like, prefer it
            if is_email_like(r.get('parent_contact')):
                parent_email = r.get('parent_contact')
            else:
                # fallback to the linked user's email (if available)
                if student and student.get('user_id'):
                    u = supabase.table("users").select("email").eq("id", student.get('user_id')).execute().data or []
                    if u and u[0].get('email') and is_email_like(u[0].get('email')):
                        parent_email = u[0].get('email')
            # assemble displayed name from request or student
            display_name = (r.get('full_name') or student.get('full_name') or "").strip()
        except Exception:
            student = {}
            display_name = r.get('full_name') or ""
        enriched.append({
            "id": r.get('id'),
            "student_id": r.get('student_id'),
            "full_name": display_name,
            "age": r.get('age'),
            "birthday": r.get('birthday'),
            "gender": r.get('gender'),
            "address": r.get('address'),
            "parent_name": r.get('parent_name'),
            "parent_contact": r.get('parent_contact'),
            "parent_email": parent_email,
            "grade_level": r.get('grade_level'),
            "section": r.get('section'),
            "school_year": r.get('school_year'),
            "status": r.get('status'),
            "submitted_at": r.get('submitted_at'),
            "updated_at": r.get('updated_at')
        })

    # render principal template (principal_enrollment_requests.html expects "requests")
    return render_template('principal_enrollment_requests.html',
                           title="Enrollment Requests",
                           requests=enriched)

# Approve enrollment: update enrollment_requests.status, update student record, send email to parent (if possible)
@app.route('/approve_enrollment/<int:req_id>', methods=['POST'])
def approve_enrollment(req_id):
    if session.get('user_role') != 'principal':
        return redirect(url_for('login'))

    # Load request row
    try:
        req_rows = supabase.table("enrollment_requests").select("*").eq("id", req_id).execute().data or []
        if not req_rows:
            flash("Enrollment request not found.", "danger")
            return redirect(url_for('view_enrollment_requests'))
        req_row = req_rows[0]
    except Exception:
        app.logger.exception("Failed to fetch enrollment request")
        flash("Failed to fetch enrollment request.", "danger")
        return redirect(url_for('view_enrollment_requests'))

    student_id = req_row.get('student_id')

    # Update students table with approved grade/section/name (if present)
    try:
        supabase.table("students").update({
            "grade_level": req_row.get('grade_level'),
            "section": req_row.get('section'),
            # update full_name if request provides it
            "full_name": req_row.get('full_name') or None
        }).eq("id", student_id).execute()
    except Exception:
        app.logger.exception("Failed to update student row on approval (non-fatal)")

    # Mark request as approved
    try:
        supabase.table("enrollment_requests").update({
            "status": "approved",
            "updated_at": datetime.utcnow()
        }).eq("id", req_id).execute()
    except Exception:
        app.logger.exception("Failed to set enrollment_requests.status to approved")
        flash("Failed to approve request (DB error).", "danger")
        return redirect(url_for('view_enrollment_requests'))

    # Attempt to email the parent
    parent_email = req_row.get('parent_contact') if is_email_like(req_row.get('parent_contact')) else None
    if not parent_email:
        # try the linked users.email via students
        try:
            student_rows = supabase.table("students").select("*").eq("id", student_id).execute().data or []
            student = student_rows[0] if student_rows else {}
            if student and student.get('user_id'):
                u = supabase.table("users").select("email").eq("id", student.get('user_id')).execute().data or []
                if u and is_email_like(u[0].get('email')):
                    parent_email = u[0].get('email')
        except Exception:
            parent_email = None

    email_sent = False
    if parent_email:
        subject = "Enrollment Approved — Aplaya Elementary"
        body = f"Hello {req_row.get('parent_name') or ''},\n\n" \
               f"Good news — the enrollment request for {req_row.get('full_name')} " \
               f"({req_row.get('grade_level')} — {req_row.get('section')}) for school year {req_row.get('school_year')} " \
               "has been APPROVED.\n\n" \
               "Please contact the school if you need further assistance.\n\n" \
               "Regards,\nAplaya-ES Online"
        email_sent = send_email(parent_email, subject, body)

    flash_msg = "Enrollment approved."
    if parent_email:
        flash_msg += " Parent email " + ("sent." if email_sent else "failed to send.")
    else:
        flash_msg += " No parent email available."

    flash(flash_msg, "success")
    return redirect(url_for('view_enrollment_requests'))

# Reject enrollment: set status rejected and optionally email parent
@app.route('/reject_enrollment/<int:req_id>', methods=['POST'])
def reject_enrollment(req_id):
    if session.get('user_role') != 'principal':
        return redirect(url_for('login'))

    try:
        req_rows = supabase.table("enrollment_requests").select("*").eq("id", req_id).execute().data or []
        if not req_rows:
            flash("Enrollment request not found.", "danger")
            return redirect(url_for('view_enrollment_requests'))
        req_row = req_rows[0]
    except Exception:
        app.logger.exception("Failed to fetch enrollment request (reject)")
        flash("Failed to fetch enrollment request.", "danger")
        return redirect(url_for('view_enrollment_requests'))

    # mark rejected
    try:
        supabase.table("enrollment_requests").update({
            "status": "rejected",
            "updated_at": datetime.utcnow()
        }).eq("id", req_id).execute()
    except Exception:
        app.logger.exception("Failed to mark enrollment_requests as rejected")
        flash("Failed to reject request (DB error).", "danger")
        return redirect(url_for('view_enrollment_requests'))

    # try to email parent informing rejection
    parent_email = req_row.get('parent_contact') if is_email_like(req_row.get('parent_contact')) else None
    if not parent_email:
        try:
            student_rows = supabase.table("students").select("*").eq("id", req_row.get('student_id')).execute().data or []
            student = student_rows[0] if student_rows else {}
            if student and student.get('user_id'):
                u = supabase.table("users").select("email").eq("id", student.get('user_id')).execute().data or []
                if u and is_email_like(u[0].get('email')):
                    parent_email = u[0].get('email')
        except Exception:
            parent_email = None

    email_sent = False
    if parent_email:
        subject = "Enrollment Request Update — Aplaya Elementary"
        body = f"Hello {req_row.get('parent_name') or ''},\n\n" \
               f"We regret to inform you that the enrollment request for {req_row.get('full_name')} " \
               f"({req_row.get('grade_level')} — {req_row.get('section')}) for school year {req_row.get('school_year')} " \
               "has been rejected. Please contact the school for more details.\n\n" \
               "Regards,\nAplaya-ES Online"
        email_sent = send_email(parent_email, subject, body)

    flash_msg = "Enrollment rejected."
    if parent_email:
        flash_msg += " Parent email " + ("sent." if email_sent else "failed to send.")
    else:
        flash_msg += " No parent email available."

    flash(flash_msg, "warning")
    return redirect(url_for('view_enrollment_requests'))

# -----------------------------
# TEACHER / STUDENT ROUTES (kept largely the same)
# -----------------------------
@app.route('/teachers')
def teachers_page():
    if session.get('user_role') != 'principal':
        return redirect(url_for('login'))
    teachers = supabase.table("teachers").select("*").execute().data or []
    return render_template('teachers.html', title="Teachers", teachers=teachers)

@app.route('/add_teacher', methods=['POST'])
def add_teacher():
    if session.get('user_role') != 'principal':
        return redirect(url_for('login'))
    full_name = request.form.get('name')
    username = request.form.get('username')
    password = request.form.get('password')
    subject = request.form.get('subject')
    grade_level = request.form.get('grade_level')
    try:
        existing_user = supabase.table("users").select("id").eq("username", username).execute()
        if existing_user.data:
            return "Username already exists.", 400
        user_insert = supabase.table("users").insert({
            "username": username,
            "password": password,
            "role": "teacher"
        }).execute()
        user_id = user_insert.data[0]['id']
        supabase.table("teachers").insert({
            "user_id": user_id,
            "full_name": full_name,
            "subject": subject,
            "grade_level": grade_level
        }).execute()
        return redirect(url_for('teachers_page'))
    except Exception:
        app.logger.exception("add_teacher failed")
        return f"Error: {full_name}", 500

@app.route('/delete_teacher/<int:teacher_id>', methods=['POST'])
def delete_teacher(teacher_id):
    if session.get('user_role') != 'principal':
        return redirect(url_for('login'))
    try:
        teacher_data = supabase.table("teachers").select("user_id").eq("id", teacher_id).execute()
        if teacher_data.data:
            user_id = teacher_data.data[0]['user_id']
            supabase.table("teachers").delete().eq("id", teacher_id).execute()
            supabase.table("users").delete().eq("id", user_id).execute()
    except Exception:
        app.logger.exception("delete_teacher failed")
        return f"Error deleting teacher: {teacher_id}", 500
    return redirect(url_for('teachers_page'))

# Teacher dashboard & student endpoints...
@app.route('/teacher_dashboard')
def teacher_dashboard():
    if session.get('user_role') != 'teacher':
        return redirect(url_for('login'))
    teacher = supabase.table("teachers").select("id").eq("user_id", session['user_id']).execute()
    teacher_id = teacher.data[0]['id'] if teacher.data else None
    students = []
    if teacher_id:
        students = supabase.table("students").select("*").eq("teacher_id", teacher_id).execute().data or []
    return render_template('teacher_dashboard.html', title="Teacher Dashboard", students_count=len(students))

@app.route('/teacher/students')
def teacher_students():
    if session.get('user_role') != 'teacher':
        return redirect(url_for('login'))
    teacher = supabase.table("teachers").select("id").eq("user_id", session['user_id']).execute()
    teacher_id = teacher.data[0]['id'] if teacher.data else None
    students = []
    if teacher_id:
        students = supabase.table("students").select("*").eq("teacher_id", teacher_id).execute().data or []
    return render_template('teachers_students.html', title="My Students", students=students)

@app.route('/teacher/add_student', methods=['POST'])
def add_student_teacher():
    if session.get('user_role') != 'teacher':
        return redirect(url_for('login'))
    full_name = request.form.get('full_name')
    grade_level = request.form.get('grade_level')
    section = request.form.get('section')
    try:
        username = full_name.replace(" ", "_").lower()
        existing = supabase.table("users").select("id").eq("username", username).execute()
        if existing.data:
            return "Student already exists.", 400
        user_insert = supabase.table("users").insert({
            "username": username,
            "password": "student123",
            "role": "student"
        }).execute()
        user_id = user_insert.data[0]['id']
        teacher = supabase.table("teachers").select("id").eq("user_id", session['user_id']).execute()
        teacher_id = teacher.data[0]['id'] if teacher.data else None
        if not teacher_id:
            return "Teacher record not found.", 400
        supabase.table("students").insert({
            "user_id": user_id,
            "teacher_id": teacher_id,
            "full_name": full_name,
            "grade_level": grade_level,
            "section": section
        }).execute()
        return redirect(url_for('teacher_students'))
    except Exception:
        app.logger.exception("add_student_teacher failed")
        return f"Error adding student", 500

@app.route('/teacher/edit_student/<int:student_id>', methods=['POST'])
def edit_student(student_id):
    if session.get('user_role') != 'teacher':
        return redirect(url_for('login'))
    supabase.table("students").update({
        "full_name": request.form.get('full_name'),
        "grade_level": request.form.get('grade_level'),
        "section": request.form.get('section')
    }).eq("id", student_id).execute()
    return redirect(url_for('teacher_students'))

@app.route('/teacher/delete_student/<int:student_id>', methods=['POST'])
def delete_student(student_id):
    if session.get('user_role') != 'teacher':
        return redirect(url_for('login'))
    supabase.table("students").delete().eq("id", student_id).execute()
    return redirect(url_for('teacher_students'))

# Student dashboard
@app.route('/student_dashboard')
def student_dashboard():
    if session.get('user_role') != 'student':
        return redirect(url_for('login'))
    student_data = supabase.table("students").select("*").eq("user_id", session['user_id']).execute().data or []
    return render_template('student_dashboard.html', title="Student Dashboard", student=student_data)

@app.route('/schedule')
def schedule():
    if 'user_role' not in session:
        return redirect(url_for('login'))
    return render_template('schedule.html', title="Schedule")

# Enrollment page & submit (keeps storing all fields available in DB)
@app.route('/enrollment')
def enrollment():
    return render_template('enrollment.html', title="Enrollment")

@app.route('/submit_enrollment', methods=['POST'])
def submit_enrollment():
    # read form fields
    full_name = (request.form.get('full_name') or "").strip()
    age = request.form.get('age') or None
    birthday = request.form.get('birthday') or None
    gender = request.form.get('gender') or None
    address = request.form.get('address') or None
    parent_name = request.form.get('parent_name') or None
    parent_contact = request.form.get('parent_contact') or None
    grade_level = (request.form.get('grade_level') or "").strip()
    section = request.form.get('section') or None
    school_year = request.form.get('school_year') or current_school_year()

    if not full_name or not grade_level:
        return "Full name and grade level are required.", 400

    user_id = session.get('user_id')

    try:
        # if guest, create new user record and set session
        if not user_id:
            base_username = full_name.replace(" ", "_").lower()
            username = base_username
            suffix = 1
            while True:
                exists = supabase.table("users").select("id").eq("username", username).execute()
                if not exists.data:
                    break
                username = f"{base_username}{suffix}"
                suffix += 1
            default_password = "student123"
            user_insert = supabase.table("users").insert({
                "username": username,
                "password": default_password,
                "role": "student",
                "email": None
            }).execute()
            if not user_insert.data:
                app.logger.exception("Failed to create user for enrollment")
                return "Failed to create user account.", 500
            user_id = user_insert.data[0]['id']
            session['user_id'] = user_id
            session['user_role'] = 'student'
            session['username'] = username

        # ensure students row exists
        student_record = supabase.table("students").select("*").eq("user_id", user_id).execute()
        if not student_record.data:
            created = supabase.table("students").insert({
                "user_id": user_id,
                "teacher_id": None,
                "full_name": full_name,
                "grade_level": grade_level,
                "section": section,
                "age": int(age) if age else None,
                "birthday": birthday if birthday else None,
                "gender": gender,
                "address": address,
                "parent_name": parent_name,
                "parent_contact": parent_contact
            }).execute()
            if not created.data:
                app.logger.exception("Failed to create student record during enrollment")
                return "Failed to create student record.", 500
            student_id = created.data[0]['id']
        else:
            student_id = student_record.data[0]['id']
            try:
                supabase.table("students").update({
                    "full_name": full_name,
                    "grade_level": grade_level,
                    "section": section,
                    "age": int(age) if age else None,
                    "birthday": birthday if birthday else None,
                    "gender": gender,
                    "address": address,
                    "parent_name": parent_name,
                    "parent_contact": parent_contact
                }).eq("id", student_id).execute()
            except Exception:
                app.logger.exception("Non-fatal: failed to update existing student record")

        # insert enrollment_requests (store full details)
        try:
            supabase.table("enrollment_requests").insert({
                "student_id": student_id,
                "full_name": full_name,
                "age": int(age) if age else None,
                "birthday": birthday if birthday else None,
                "gender": gender,
                "address": address,
                "parent_name": parent_name,
                "parent_contact": parent_contact,
                "grade_level": grade_level,
                "section": section,
                "school_year": school_year,
                "status": "pending"
            }).execute()
        except Exception as e:
            app.logger.exception("Enrollment insert failed")
            err_txt = str(e)
            if "unique_student_year" in err_txt or "duplicate" in err_txt.lower():
                return "You already submitted an enrollment request for this school year.", 400
            return f"Enrollment failed: {e}", 400

    except Exception:
        app.logger.exception("submit_enrollment failed")
        return "Error processing enrollment.", 500

    flash("Enrollment submitted. Waiting for principal approval.", "info")
    return redirect(url_for('student_dashboard'))

# SHARED PAGES
@app.route('/subjects')
def subjects():
    return render_template('subjects.html', title="Subjects")

@app.route('/report_card')
def report_card():
    return render_template('report_card.html', title="Report Card")

@app.route('/settings')
def settings():
    return render_template('settings.html', title="Settings")

@app.route('/profile')
def profile():
    if 'user_role' not in session:
        return redirect(url_for('login'))
    return render_template('profile.html', title="My Profile")

@app.route('/upload_profile', methods=['POST'])
def upload_profile():
    if 'profile_pic' not in request.files:
        return redirect(url_for('profile'))
    file = request.files['profile_pic']
    if file and allowed_file(file.filename):
        filename = secure_filename('profile.jpg')
        os.makedirs(app.config['UPLOAD_FOLDER'], exist_ok=True)
        file.save(os.path.join(app.config['UPLOAD_FOLDER'], filename))
    return redirect(url_for('profile'))

# -------------------------
# CLASS LIST + SCHEDULE ROUTES
# -------------------------
@app.route('/class_list')
def class_list():
    if 'user_role' not in session or session['user_role'] not in ('teacher', 'principal'):
        return redirect(url_for('login'))

    class_load = supabase.table("class_load").select("*").execute().data or []
    sections = {s["id"]: s for s in supabase.table("sections").select("*").execute().data or []}
    subjects = {s["id"]: s for s in supabase.table("subjects").select("*").execute().data or []}

    # Students use SECTION NAME, not section_id
    students = supabase.table("students").select("*").execute().data or []
    students_by_section = defaultdict(int)

    for st in students:
        sec = st.get("section")  # <-- YOUR DATABASE FIELD
        if sec:
            students_by_section[sec] += 1

    rows = []
    for cl in class_load:
        sec = sections.get(cl.get("section_id"), {})
        subj = subjects.get(cl.get("subject_id"), {})

        section_name = sec.get("section_name", "Unknown Section")

        rows.append({
            "section": section_name,
            "subject_code": subj.get("subject_code"),
            "subject_name": subj.get("subject_name"),
            "course_code": subj.get("course_code") or "",
            "course": subj.get("course") or "",
            "units": cl.get("units") or subj.get("units") or 0,
            "total_students": students_by_section.get(section_name, 0)
        })

    return render_template("class_list.html", title="Class List", rows=rows)

@app.route('/add_student', methods=['GET', 'POST'])
def add_student():
    if 'user_role' not in session or session['user_role'] not in ('principal', 'teacher'):
        return redirect(url_for('login'))

    sections = supabase.table("sections").select("*").execute().data or []

    if request.method == 'POST':
        data = {
            "last_name": request.form['last_name'],
            "first_name": request.form['first_name'],
            "middle_name": request.form.get('middle_name'),
            "age": request.form.get('age'),
            "birthday": request.form.get('birthday'),
            "gender": request.form.get('gender'),
            "address": request.form.get('address'),
            "parent_name": request.form.get('parent_name'),
            "parent_contact": request.form.get('parent_contact'),
            "grade_level": request.form['grade_level'],
            "section": request.form['section']
        }

        supabase.table("students").insert(data).execute()
        return redirect(url_for('class_list'))

    return render_template('add_student.html', sections=sections)

@app.route('/schedule_view')
def schedule_view():
    # Only teachers/principal allowed
    if 'user_role' not in session or session['user_role'] not in ('teacher', 'principal'):
        return redirect(url_for('login'))

    class_load = supabase.table("class_load").select("*").execute().data or []
    sections = {s['id']: s for s in (supabase.table("sections").select("*").execute().data or [])}
    subjects = {s['id']: s for s in (supabase.table("subjects").select("*").execute().data or [])}

    schedule = defaultdict(list)

    for cl in class_load:
        day = cl.get('day') or 'Unscheduled'
        subj = subjects.get(cl.get('subject_id'), {})
        sec = sections.get(cl.get('section_id'), {})

        schedule[day].append({
            'start': cl.get('start_time'),
            'end': cl.get('end_time'),
            'subject_code': subj.get('subject_code') or subj.get('subject_name'),
            'subject_name': subj.get('subject_name'),
            'section': sec.get('section_name'),
            'room': cl.get('room') or ""
        })

    # Sort by time
    for day, events in schedule.items():
        try:
            events.sort(key=lambda e: datetime.strptime(e['start'], "%H:%M"))
        except:
            pass

    weekday_order = ['Monday','Tuesday','Wednesday','Thursday','Friday','Saturday','Sunday']

    return render_template('schedule_view.html', title="Schedule", schedule=schedule, weekday_order=weekday_order)

@app.route('/add_subject', methods=['GET', 'POST'])
def add_subject():
    if 'user_role' not in session or session['user_role'] not in ('principal', 'teacher'):
        return redirect(url_for('login'))

    if request.method == 'POST':
        data = {
            "subject_code": request.form['subject_code'],
            "subject_name": request.form['subject_name'],
            "units": request.form.get('units'),
            "course_code": request.form.get('course_code'),
            "course": request.form.get('course')
        }
        supabase.table("subjects").insert(data).execute()
        return redirect(url_for('class_list'))

    return render_template('add_subject.html')

@app.route('/add_class_load', methods=['GET', 'POST'])
def add_class_load():
    if 'user_role' not in session or session['user_role'] not in ('principal', 'teacher'):
        return redirect(url_for('login'))

    sections = supabase.table("sections").select("*").execute().data or []
    subjects = supabase.table("subjects").select("*").execute().data or []

    if request.method == 'POST':
        data = {
            "section_id": request.form['section_id'],
            "subject_id": request.form['subject_id'],
            "units": request.form.get('units'),
            "day": request.form.get('day'),
            "start_time": request.form.get('start_time'),
            "end_time": request.form.get('end_time'),
            "room": request.form.get('room')
        }
        supabase.table("class_load").insert(data).execute()
        return redirect(url_for('class_list'))

    return render_template('add_class_load.html', sections=sections, subjects=subjects)

# === MAIN RUN ===
if __name__ == '__main__':
    # NOTE: For production, set debug=False and use a proper WSGI server.
    app.run(debug=True)

