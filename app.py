from flask import Flask, render_template, request, jsonify, redirect, url_for, session, flash
import sqlite3, qrcode, os
from datetime import datetime, timedelta
from functools import wraps
from werkzeug.security import generate_password_hash, check_password_hash
from collections import defaultdict

app = Flask(__name__)
app.secret_key = 'change_this_to_random_secret_2025'

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DB = os.path.join(BASE_DIR, 'school_meals.db')
QR_FOLDER = os.path.join(BASE_DIR, 'static', 'qrcodes')
os.makedirs(QR_FOLDER, exist_ok=True)

def calc_due(from_date_str, days=30):
    try: d = datetime.strptime(from_date_str, '%Y-%m-%d')
    except: d = datetime.now()
    return (d + timedelta(days=days)).strftime('%Y-%m-%d')

def new_due(old_due_str, days=30):
    today = datetime.now()
    today_str = today.strftime('%Y-%m-%d')
    if old_due_str:
        try:
            old_due = datetime.strptime(old_due_str, '%Y-%m-%d')
            if today < old_due:
                return (old_due + timedelta(days=days)).strftime('%Y-%m-%d')
        except: pass
    return (today + timedelta(days=days)).strftime('%Y-%m-%d')

def get_settings():
    conn = sqlite3.connect(DB)
    c = conn.cursor()
    c.execute("SELECT monthly_fee_default, expiry_days, allow_unpaid, allow_partial_percent, block_unpaid FROM settings WHERE id=1")
    row = c.fetchone()
    conn.close()
    if row: return {'fee':row[0],'expiry':row[1],'allow_unpaid':row[2],'allow_partial':row[3],'block_unpaid':row[4]}
    return {'fee':95,'expiry':30,'allow_unpaid':1,'allow_partial':50,'block_unpaid':0}

def login_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if 'logged_in' not in session: return redirect(url_for('login'))
        return f(*args, **kwargs)
    return decorated_function

def admin_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if session.get('role')!='admin':
            flash('Admin only!'); return redirect(url_for('scan'))
        return f(*args, **kwargs)
    return decorated_function

def init_db():
    conn = sqlite3.connect(DB)
    c = conn.cursor()
    c.execute('''CREATE TABLE IF NOT EXISTS users (id INTEGER PRIMARY KEY AUTOINCREMENT, username TEXT UNIQUE, password TEXT, role TEXT)''')
    c.execute('''CREATE TABLE IF NOT EXISTS students (id INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT, class TEXT, admission_no TEXT UNIQUE, qr_path TEXT, amount_owed REAL DEFAULT 0, last_paid_date TEXT, due_date TEXT, monthly_fee REAL DEFAULT 95)''')
    c.execute('''CREATE TABLE IF NOT EXISTS attendance (id INTEGER PRIMARY KEY AUTOINCREMENT, admission_no TEXT, meal_type TEXT, timestamp TEXT, date TEXT)''')
    c.execute('''CREATE TABLE IF NOT EXISTS payments (id INTEGER PRIMARY KEY AUTOINCREMENT, admission_no TEXT, amount_paid REAL, date_paid TEXT, balance_after REAL)''')
    c.execute('''CREATE TABLE IF NOT EXISTS settings (id INTEGER PRIMARY KEY, monthly_fee_default REAL, expiry_days INTEGER, allow_unpaid INTEGER, allow_partial_percent INTEGER, block_unpaid INTEGER)''')
    c.execute("SELECT * FROM settings WHERE id=1")
    if not c.fetchone():
        c.execute("INSERT INTO settings (id, monthly_fee_default, expiry_days, allow_unpaid, allow_partial_percent, block_unpaid) VALUES (1,95,30,1,50,0)")
    conn.commit()
    conn.close()
init_db()

@app.route('/')
def home():
    conn = sqlite3.connect(DB)
    c = conn.cursor()
    c.execute("SELECT COUNT(*) FROM users")
    count = c.fetchone()[0]
    conn.close()
    return redirect(url_for('setup')) if count==0 else redirect(url_for('login'))

@app.route('/setup', methods=['GET','POST'])
def setup():
    conn = sqlite3.connect(DB)
    c = conn.cursor()
    c.execute("SELECT COUNT(*) FROM users")
    if c.fetchone()[0]>0:
        conn.close()
        return redirect(url_for('login'))
    if request.method=='POST':
        username=request.form['username']; password=request.form['password']
        fee=float(request.form.get('monthly_fee',95)); expiry=int(request.form.get('expiry_days',30))
        allow_unpaid=1 if request.form.get('allow_unpaid') else 0
        block_unpaid=1 if request.form.get('block_unpaid') else 0
        allow_partial=int(request.form.get('allow_partial',50))
        c.execute("INSERT INTO users (username,password,role) VALUES (?,?,?)", (username, generate_password_hash(password), 'admin'))
        c.execute("UPDATE settings SET monthly_fee_default=?, expiry_days=?, allow_unpaid=?, allow_partial_percent=?, block_unpaid=? WHERE id=1", (fee,expiry,allow_unpaid,allow_partial,block_unpaid))
        conn.commit(); conn.close()
        flash('Admin created! Login now.')
        return redirect(url_for('login'))
    conn.close()
    return render_template('setup.html')

@app.route('/settings', methods=['GET','POST'])
@login_required
@admin_required
def settings():
    if request.method=='POST':
        fee=float(request.form.get('monthly_fee',95)); expiry=int(request.form.get('expiry_days',30))
        allow_unpaid=1 if request.form.get('allow_unpaid') else 0
        block_unpaid=1 if request.form.get('block_unpaid') else 0
        allow_partial=int(request.form.get('allow_partial',50))
        conn=sqlite3.connect(DB)
        c=conn.cursor()
        c.execute("UPDATE settings SET monthly_fee_default=?, expiry_days=?, allow_unpaid=?, allow_partial_percent=?, block_unpaid=? WHERE id=1", (fee,expiry,allow_unpaid,allow_partial,block_unpaid))
        conn.commit(); conn.close()
        flash(f'Saved! Fee ${fee} Expiry {expiry} days')
        return redirect(url_for('settings'))
    return render_template('settings.html', s=get_settings(), role=session.get('role'))

@app.route('/login', methods=['GET','POST'])
def login():
    conn=sqlite3.connect(DB)
    c=conn.cursor()
    c.execute("SELECT COUNT(*) FROM users")
    if c.fetchone()[0]==0:
        conn.close()
        return redirect(url_for('setup'))
    conn.close()
    if request.method=='POST':
        username=request.form['username']; password=request.form['password']
        conn=sqlite3.connect(DB)
        c=conn.cursor()
        c.execute("SELECT * FROM users WHERE username=?", (username,))
        user=c.fetchone()
        conn.close()
        if user and check_password_hash(user[2], password):
            session['logged_in']=True; session['username']=user[1]; session['role']=user[3]
            return redirect(url_for('scan'))
        else: flash('Wrong credentials!')
    return render_template('login.html')

@app.route('/logout')
def logout():
    session.clear()
    return redirect(url_for('login'))

@app.route('/scan')
@login_required
def scan():
    return render_template('scan.html', role=session.get('role'), settings=get_settings())

@app.route('/register', methods=['GET','POST'])
@login_required
def register():
    s=get_settings()
    if request.method=='POST':
        adm_no=request.form['id']; name=request.form['name']; class_name=request.form['grade']
        amount_owed=float(request.form.get('amount_owed',0) or 0)
        monthly_fee=float(request.form.get('monthly_fee',s['fee']) or s['fee'])
        paying_date=request.form.get('paying_date') or datetime.now().strftime('%Y-%m-%d')
        qr_data=f"SCHOOL:{adm_no}"; qr=qrcode.make(qr_data)
        qr_filename=f"{adm_no}.png"; qr_path=os.path.join(QR_FOLDER, qr_filename); qr.save(qr_path)
        last_paid=paying_date if amount_owed==0 else None
        due_date=calc_due(paying_date, s['expiry']) if amount_owed==0 else paying_date
        conn=sqlite3.connect(DB)
        c=conn.cursor()
        try:
            c.execute("INSERT INTO students (name,class,admission_no,qr_path,amount_owed,last_paid_date,due_date,monthly_fee) VALUES (?,?,?,?,?,?,?,?)", (name,class_name,adm_no,f'/static/qrcodes/{qr_filename}',amount_owed,last_paid,due_date,monthly_fee))
            conn.commit(); flash(f'{name} Fee ${monthly_fee} Owing ${amount_owed}')
        except sqlite3.IntegrityError: flash('Adm No exists!')
        conn.close()
        return redirect(url_for('register'))
    conn=sqlite3.connect(DB); c=conn.cursor()
    c.execute("SELECT * FROM students ORDER BY class,name")
    students=c.fetchall(); conn.close()
    return render_template('register.html', students=students, role=session.get('role'), settings=s)

@app.route('/edit_student/<int:student_id>', methods=['POST'])
@login_required
@admin_required
def edit_student(student_id):
    name=request.form.get('name'); class_name=request.form.get('class'); admission_no=request.form.get('admission_no')
    monthly_fee=float(request.form.get('monthly_fee',95) or 95); amount_owed=float(request.form.get('amount_owed',0) or 0)
    due_date=request.form.get('due_date'); last_paid=request.form.get('last_paid_date')
    conn=sqlite3.connect(DB); c=conn.cursor()
    c.execute("UPDATE students SET name=?, class=?, admission_no=?, monthly_fee=?, amount_owed=?, due_date=?, last_paid_date=? WHERE id=?", (name,class_name,admission_no,monthly_fee,amount_owed,due_date,last_paid,student_id))
    conn.commit(); conn.close()
    flash(f'Edited {name}'); return redirect(url_for('register'))

@app.route('/clear_fees/<int:student_id>')
@login_required
@admin_required
def clear_fees(student_id):
    s=get_settings()
    conn=sqlite3.connect(DB); c=conn.cursor()
    c.execute("SELECT due_date FROM students WHERE id=?", (student_id,))
    r=c.fetchone()
    old_due=r[0] if r else None
    nd=new_due(old_due, s['expiry'])
    today=datetime.now().strftime('%Y-%m-%d')
    c.execute("UPDATE students SET amount_owed=0, last_paid_date=?, due_date=? WHERE id=?", (today,nd,student_id))
    conn.commit(); conn.close()
    return redirect(url_for('register'))

@app.route('/pay_fees/<int:student_id>', methods=['POST'])
@login_required
@admin_required
def pay_fees(student_id):
    s=get_settings()
    amount_paid=float(request.form.get('amount_paid',0) or 0)
    paying_date=request.form.get('paying_date') or datetime.now().strftime('%Y-%m-%d')
    conn=sqlite3.connect(DB); c=conn.cursor()
    c.execute("SELECT admission_no, amount_owed, monthly_fee FROM students WHERE id=?", (student_id,))
    row=c.fetchone()
    if row:
        adm_no, old_owed, monthly_fee=row
        base=old_owed if old_owed>0 else (monthly_fee or s['fee'])
        new_owed=max(0, base-amount_paid)
        nd=calc_due(paying_date, s['expiry'])
        c.execute("UPDATE students SET amount_owed=?, last_paid_date=?, due_date=? WHERE id=?", (new_owed,paying_date,nd,student_id))
        c.execute("INSERT INTO payments (admission_no, amount_paid, date_paid, balance_after) VALUES (?,?,?,?)", (adm_no,amount_paid,paying_date,new_owed))
        conn.commit()
    conn.close()
    return redirect(url_for('register'))

@app.route('/delete_student/<int:student_id>')
@login_required
@admin_required
def delete_student(student_id):
    conn=sqlite3.connect(DB); c=conn.cursor()
    c.execute("SELECT admission_no FROM students WHERE id=?", (student_id,))
    row=c.fetchone()
    if row:
        adm_no=row[0]
        c.execute("DELETE FROM attendance WHERE admission_no=?", (adm_no,))
        c.execute("DELETE FROM payments WHERE admission_no=?", (adm_no,))
        c.execute("DELETE FROM students WHERE id=?", (student_id,))
        conn.commit()
    conn.close()
    return redirect(url_for('register'))

@app.route('/clear_attendance')
@login_required
@admin_required
def clear_attendance():
    conn=sqlite3.connect(DB); c=conn.cursor(); c.execute("DELETE FROM attendance"); conn.commit(); conn.close()
    return redirect(url_for('report'))

@app.route('/clear_attendance_date/<date>')
@login_required
@admin_required
def clear_attendance_date(date):
    conn=sqlite3.connect(DB); c=conn.cursor(); c.execute("DELETE FROM attendance WHERE date=?", (date,)); conn.commit(); conn.close()
    return redirect(url_for('report'))

@app.route('/delete_one_scan/<int:scan_id>')
@login_required
@admin_required
def delete_one_scan(scan_id):
    conn=sqlite3.connect(DB); c=conn.cursor(); c.execute("DELETE FROM attendance WHERE id=?", (scan_id,)); conn.commit(); conn.close()
    return redirect(url_for('report'))

@app.route('/mark_attendance', methods=['POST'])
@login_required
def mark_attendance():
    s=get_settings()
    data=request.get_json()
    adm_no=data['admission_no']; meal_type=data['meal_type']
    now=datetime.now(); date_str=now.strftime('%Y-%m-%d'); time_str=now.strftime('%Y-%m-%d %H:%M:%S')
    today_date=datetime.strptime(date_str, '%Y-%m-%d')
    conn=sqlite3.connect(DB, timeout=10); c=conn.cursor()
    c.execute("SELECT admission_no, due_date, monthly_fee FROM students WHERE due_date<? AND amount_owed=0", (date_str,))
    for r in c.fetchall():
        fee=r[2] if r[2] and r[2]>0 else s['fee']
        c.execute("UPDATE students SET amount_owed=?, due_date=? WHERE admission_no=?", (fee, calc_due(r[1], s['expiry']), r[0]))
    conn.commit()
    c.execute("SELECT name, amount_owed, due_date, monthly_fee FROM students WHERE admission_no=?", (adm_no,))
    student=c.fetchone()
    if not student:
        conn.close(); return jsonify({'status':'not_found'})
    name, amount_owed, due_date, monthly_fee=student
    amount_owed=amount_owed or 0; monthly_fee=monthly_fee or s['fee']
    is_blocked=False
    if s['block_unpaid']==1 and amount_owed>0:
        paid_percent=((monthly_fee-amount_owed)/monthly_fee*100) if monthly_fee>0 else 0
        if paid_percent < s['allow_partial']: is_blocked=True
    c.execute("SELECT * FROM attendance WHERE admission_no=? AND meal_type=? AND date=?", (adm_no,meal_type,date_str))
    if c.fetchone():
        conn.close()
        if is_blocked: return jsonify({'status':'blocked','name':name,'amount_owed':amount_owed,'due_date':due_date,'monthly_fee':monthly_fee})
        if amount_owed>0: return jsonify({'status':'already_marked_owing','name':name,'amount_owed':amount_owed,'due_date':due_date})
        return jsonify({'status':'already_marked','name':name,'amount_owed':amount_owed,'due_date':due_date})
    if is_blocked:
        conn.close()
        return jsonify({'status':'blocked','name':name,'amount_owed':amount_owed,'due_date':due_date,'monthly_fee':monthly_fee})
    days_left=999
    try:
        if due_date: days_left=(datetime.strptime(due_date,'%Y-%m-%d')-today_date).days
    except: days_left=0
    c.execute("INSERT INTO attendance (admission_no, meal_type, timestamp, date) VALUES (?,?,?,?)", (adm_no,meal_type,time_str,date_str))
    conn.commit(); conn.close()
    if amount_owed>0:
        if days_left<0: return jsonify({'status':'expired_owing','name':name,'amount_owed':amount_owed,'due_date':due_date,'days_left':days_left})
        elif days_left==0: return jsonify({'status':'expired_today_owing','name':name,'amount_owed':amount_owed,'due_date':due_date})
        else: return jsonify({'status':'owing','name':name,'amount_owed':amount_owed,'due_date':due_date,'days_left':days_left})
    else:
        if days_left<0: return jsonify({'status':'expired_cleared','name':name,'amount_owed':amount_owed,'due_date':due_date})
        elif days_left==0: return jsonify({'status':'expired_today','name':name,'amount_owed':amount_owed,'due_date':due_date})
        elif days_left<=3: return jsonify({'status':'expiring_soon','name':name,'amount_owed':amount_owed,'due_date':due_date,'days_left':days_left})
        else: return jsonify({'status':'success','name':name,'amount_owed':amount_owed,'due_date':due_date,'days_left':days_left})

@app.route('/dashboard')
@login_required
def dashboard():
    conn=sqlite3.connect(DB); c=conn.cursor()
    today=datetime.now().strftime('%Y-%m-%d')
    c.execute("SELECT COUNT(DISTINCT admission_no) FROM attendance WHERE date=?", (today,))
    present=c.fetchone()[0]; c.execute("SELECT COUNT(*) FROM students"); total=c.fetchone()[0]
    c.execute("SELECT SUM(amount_owed) FROM students"); debt=c.fetchone()[0] or 0
    conn.close()
    return render_template('dashboard.html', present=present,total=total,debt=debt,role=session.get('role'),settings=get_settings())

@app.route('/report')
@login_required
def report():
    conn=sqlite3.connect(DB); c=conn.cursor()
    c.execute("SELECT a.id,s.name,s.class,s.admission_no,a.meal_type,a.timestamp,s.amount_owed,s.due_date,a.date,s.monthly_fee FROM attendance a JOIN students s ON a.admission_no=s.admission_no ORDER BY a.date DESC,a.timestamp DESC LIMIT 1000")
    records=c.fetchall(); conn.close()
    grouped=defaultdict(list)
    for r in records: grouped[r[8]].append(r)
    sorted_dates=sorted(grouped.keys(), reverse=True)
    return render_template('report.html', grouped=grouped,sorted_dates=sorted_dates,records=records,role=session.get('role'))

if __name__=='__main__':
    app.run(debug=True)