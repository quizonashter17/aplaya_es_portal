from flask import Flask, render_template, request, redirect, url_for, session
import os
from werkzeug.utils import secure_filename
from supabase import create_client, Client

# === FLASK SETUP ===
app = Flask(__name__)
app.secret_key = "aplaya_secret_key"

# === SUPABASE CONNECTION ===
SUPABASE_URL = "https://oijbypltxvdczfcootok.supabase.co"
SUPABASE_KEY = "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJpc3MiOiJzdXBhYmFzZSIsInJlZiI6Im9pamJ5cGx0eHZkY3pmY29vdG9rIiwicm9sZSI6ImFub24iLCJpYXQiOjE3NjEzMzMxMTQsImV4cCI6MjA3NjkwOTExNH0.OEErl2tRV9PXuZqS43staotvdb8zWPYNjYekPajh8Gs"
supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY)

# === CONFIG ===
app.config['UPLOAD_FOLDER'] = 'static/uploads'
app.config['ALLOWED_EXTENSIONS'] = {'png', 'jpg', 'jpeg', 'gif'}


# === HELPERS ===
def allowed_file(filename):
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in app.config['ALLOWED_EXTENSIONS']


def get_profile_pic():
    profile_pic_path = os.path.join(app.config['UPLOAD_FOLDER'], 'profile.jpg')
    if os.path.exists(profile_pic_path):
        return url_for('static', filename='uploads/profile.jpg')
    return url_for('static', filename='uploads/default.jpg')


@app.context_processor
def inject_user_data():
    return {
        'user_role': session.get('user_role'),
        'username': session.get('username'),
        'profile_pic': get_profile_pic()
    }


# ===============================
# === LOGIN SYSTEM ===
# ===============================
@app.route('/login', methods=['GET', 'POST'])
def login():
    error = None
    if request.method == 'POST':
        username = request.form.get('username', '').strip()
        password = request.form.get('password', '').strip()

        try:
            result = supabase.table("users").select("*").eq("username", username).eq("password", password).execute()
            if result.data:
                user = result.data[0]
                session['user_role'] = user['role']
                session['username'] = user['username']
                session['user_id'] = user['id']

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
            error = f"Database error: {e}"

    return render_template('login.html', error=error)


# === LOGOUT ===
@app.route('/logout')
def logout():
    session.clear()
    return redirect(url_for('login'))


# === MAIN ROUTER ===
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


# ===============================
# === PRINCIPAL DASHBOARD ===
# ===============================
@app.route('/principal_dashboard')
def principal_dashboard():
    if session.get('user_role') != 'principal':
        return redirect(url_for('login'))
    return render_template('principal_dashboard.html', title="Principal Dashboard")


@app.route('/teachers')
def teachers_page():
    if session.get('user_role') != 'principal':
        return redirect(url_for('login'))

    teachers = supabase.table("teachers").select("*").execute().data
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
            return "Username already exists. Please choose another one.", 400

        # Create user first
        user_insert = supabase.table("users").insert({
            "username": username,
            "password": password,
            "role": "teacher"
        }).execute()

        if not user_insert.data:
            return "Error adding teacher user.", 400

        user_id = user_insert.data[0]['id']

        # Create teacher record
        supabase.table("teachers").insert({
            "user_id": user_id,
            "full_name": full_name,
            "subject": subject,
            "grade_level": grade_level
        }).execute()

        return redirect(url_for('teachers_page'))

    except Exception as e:
        print("Error adding teacher:", e)
        return f"An error occurred: {str(e)}", 500


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
    except Exception as e:
        print("Error deleting teacher:", e)
        return f"Error deleting teacher: {e}", 500

    return redirect(url_for('teachers_page'))


# ===============================
# === TEACHER DASHBOARD ===
# ===============================
@app.route('/teacher_dashboard')
def teacher_dashboard():
    if session.get('user_role') != 'teacher':
        return redirect(url_for('login'))

    # Get teacher record
    teacher = supabase.table("teachers").select("id").eq("user_id", session['user_id']).execute()
    teacher_id = teacher.data[0]['id'] if teacher.data else None

    students = []
    if teacher_id:
        students = supabase.table("students").select("*").eq("teacher_id", teacher_id).execute().data

    return render_template('teacher_dashboard.html', title="Teacher Dashboard", students_count=len(students))


# ===============================
# === TEACHER: MY STUDENTS PAGE ===
# ===============================
@app.route('/teacher/students')
def teacher_students():
    if session.get('user_role') != 'teacher':
        return redirect(url_for('login'))

    teacher = supabase.table("teachers").select("id").eq("user_id", session['user_id']).execute()
    teacher_id = teacher.data[0]['id'] if teacher.data else None

    students = []
    if teacher_id:
        students = supabase.table("students").select("*").eq("teacher_id", teacher_id).execute().data

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
            return "A student with that name already exists.", 400

        user_insert = supabase.table("users").insert({
            "username": username,
            "password": "student123",
            "role": "student"
        }).execute()

        if not user_insert.data:
            return "Error creating student user.", 400

        user_id = user_insert.data[0]['id']

        # ✅ Get correct teacher.id (not user_id)
        teacher = supabase.table("teachers").select("id").eq("user_id", session['user_id']).execute()
        teacher_id = teacher.data[0]['id'] if teacher.data else None

        if not teacher_id:
            return "Error: Teacher record not found.", 400

        supabase.table("students").insert({
            "user_id": user_id,
            "teacher_id": teacher_id,
            "full_name": full_name,
            "grade_level": grade_level,
            "section": section
        }).execute()

        return redirect(url_for('teacher_students'))

    except Exception as e:
        print("Error adding student:", e)
        return f"An error occurred: {str(e)}", 500


@app.route('/teacher/edit_student/<int:student_id>', methods=['POST'])
def edit_student(student_id):
    if session.get('user_role') != 'teacher':
        return redirect(url_for('login'))

    full_name = request.form.get('full_name')
    grade_level = request.form.get('grade_level')
    section = request.form.get('section')

    supabase.table("students").update({
        "full_name": full_name,
        "grade_level": grade_level,
        "section": section
    }).eq("id", student_id).execute()

    return redirect(url_for('teacher_students'))


@app.route('/teacher/delete_student/<int:student_id>', methods=['POST'])
def delete_student(student_id):
    if session.get('user_role') != 'teacher':
        return redirect(url_for('login'))

    supabase.table("students").delete().eq("id", student_id).execute()
    return redirect(url_for('teacher_students'))


# ===============================
# === STUDENT DASHBOARD ===
# ===============================
@app.route('/student_dashboard')
def student_dashboard():
    if session.get('user_role') != 'student':
        return redirect(url_for('login'))

    student_data = supabase.table("students").select("*").eq("user_id", session['user_id']).execute().data
    return render_template('student_dashboard.html', title="Student Dashboard", student=student_data)

@app.route('/schedule')
def schedule():
    if 'user_role' not in session:
        return redirect(url_for('login'))
    return render_template('schedule.html', title="Schedule")

@app.route('/enrollment')
def enrollment():
    if 'user_role' not in session:
        return redirect(url_for('login'))
    return render_template('enrollment.html', title="Enrollment")


# ===============================
# === SHARED PAGES ===
# ===============================
@app.route('/subjects')
def subjects():
    return render_template('subjects.html', title="Subjects Page")


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
        file.save(os.path.join(app.config['UPLOAD_FOLDER'], filename))
    return redirect(url_for('profile'))


# === MAIN RUN ===
if __name__ == '__main__':
    app.run(debug=True)
