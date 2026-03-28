from flask import Flask, render_template, request, redirect, url_for, session, flash, send_from_directory
from werkzeug.utils import secure_filename
import sqlite3
import os
import urllib.parse
from datetime import datetime

app = Flask(__name__)
app.secret_key = 'super_secret_student_key'
app.config['UPLOAD_FOLDER'] = 'static/uploads'

# Service Pricing
SERVICES = {
    'Resume': 200,
    'Project Development': 1500,
    'Project Report': 150,
    'Presentation (PPT)': 200
}

# --- DATABASE SETUP ---
def get_db():
    conn = sqlite3.connect('database.db')
    conn.row_factory = sqlite3.Row
    return conn

def init_db():
    if not os.path.exists(app.config['UPLOAD_FOLDER']):
        os.makedirs(app.config['UPLOAD_FOLDER'])
        
    conn = get_db()
    conn.executescript('''
        CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            email TEXT UNIQUE NOT NULL,
            password TEXT NOT NULL,
            role TEXT DEFAULT 'user'
        );
        CREATE TABLE IF NOT EXISTS orders (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER,
            service_type TEXT,
            price INTEGER,
            status TEXT DEFAULT 'Payment Pending',
            description TEXT,
            req_file TEXT,
            completed_file TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY(user_id) REFERENCES users(id)
        );
    ''')
    # Create default admin if not exists
    admin = conn.execute("SELECT * FROM users WHERE email='admin@student.com'").fetchone()
    if not admin:
        conn.execute("INSERT INTO users (name, email, password, role) VALUES (?, ?, ?, ?)",
                     ('Admin', 'admin@student.com', 'admin123', 'admin'))
    conn.commit()
    conn.close()

# --- AD SYSTEM FLOW ---
@app.route('/start_order/<service>')
def start_order(service):
    # Flow: Order Now -> Full Page Ad -> Video Ad -> Order Form
    target = url_for('order_page', service=service)
    video_ad_url = url_for('video_ad', next_url=target)
    return redirect(url_for('full_ad', next_url=video_ad_url))

@app.route('/start_download/<int:order_id>')
def start_download(order_id):
    # Flow: Download -> Video Ad -> File
    target = url_for('download_file', order_id=order_id)
    return redirect(url_for('video_ad', next_url=target))

@app.route('/full_ad')
def full_ad():
    next_url = request.args.get('next_url', '/home')
    return render_template('full_ad.html', next_url=next_url)

@app.route('/video_ad')
def video_ad():
    next_url = request.args.get('next_url', '/home')
    return render_template('video_ad.html', next_url=next_url)

# --- AUTH ROUTES ---
@app.route('/register', methods=['GET', 'POST'])
def register():
    if request.method == 'POST':
        name = request.form['name']
        email = request.form['email']
        password = request.form['password']
        
        conn = get_db()
        try:
            conn.execute("INSERT INTO users (name, email, password) VALUES (?, ?, ?)", (name, email, password))
            conn.commit()
            flash('Registration successful! Please login.', 'success')
            return redirect(url_for('login'))
        except sqlite3.IntegrityError:
            flash('Email already exists!', 'danger')
        finally:
            conn.close()
    return render_template('register.html')

@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        email = request.form['email']
        password = request.form['password']
        
        conn = get_db()
        user = conn.execute("SELECT * FROM users WHERE email=? AND password=?", (email, password)).fetchone()
        conn.close()
        
        if user:
            session['user_id'] = user['id']
            session['user_name'] = user['name']
            session['role'] = user['role']
            if user['role'] == 'admin':
                return redirect(url_for('admin_dashboard'))
            return redirect(url_for('dashboard'))
        else:
            flash('Invalid credentials!', 'danger')
            
    return render_template('login.html')

@app.route('/logout')
def logout():
    session.clear()
    return redirect(url_for('home'))

# --- PUBLIC & USER ROUTES ---

# 1. NEW WELCOME PAGE (Splash Screen)
@app.route('/')
def welcome():
    return render_template('welcome.html')

# 2. MAIN PLATFORM (Services)
@app.route('/home')
def home():
    return render_template('index.html', services=SERVICES)

@app.route('/dashboard')
def dashboard():
    if 'user_id' not in session: return redirect(url_for('login'))
    
    conn = get_db()
    orders = conn.execute("SELECT * FROM orders WHERE user_id=? ORDER BY id DESC", (session['user_id'],)).fetchall()
    conn.close()
    return render_template('dashboard.html', orders=orders)

@app.route('/order/<service>', methods=['GET'])
def order_page(service):
    if 'user_id' not in session: return redirect(url_for('login'))
    base_price = SERVICES.get(service, 0)
    return render_template('order_form.html', service=service, base_price=base_price)

@app.route('/submit_order', methods=['POST'])
def submit_order():
    if 'user_id' not in session: return redirect(url_for('login'))
    
    service_type = request.form['service']
    fast_delivery = 100 if request.form.get('fast_delivery') else 0
    price = SERVICES.get(service_type, 0) + fast_delivery
    description = request.form['description']
    
    # Handle user requirement file
    req_file = request.files.get('req_file')
    req_filename = ""
    if req_file and req_file.filename != '':
        req_filename = secure_filename(req_file.filename)
        req_file.save(os.path.join(app.config['UPLOAD_FOLDER'], req_filename))

    conn = get_db()
    conn.execute('''INSERT INTO orders (user_id, service_type, price, description, req_file)
                    VALUES (?, ?, ?, ?, ?)''', 
                 (session['user_id'], service_type, price, description, req_filename))
    conn.commit()
    conn.close()

    # Generate WhatsApp URL
    message = f"Hello, I have placed an order for {service_type} worth ₹{price}. Please provide payment details. Name: {session['user_name']}"
    encoded_message = urllib.parse.quote(message)
    wa_url = f"https://wa.me/917377412114?text={encoded_message}"
    
    return render_template('wa_redirect.html', wa_url=wa_url)

@app.route('/download/<int:order_id>')
def download_file(order_id):
    if 'user_id' not in session: return redirect(url_for('login'))
    conn = get_db()
    order = conn.execute("SELECT * FROM orders WHERE id=?", (order_id,)).fetchone()
    conn.close()
    if order and order['completed_file']:
        return send_from_directory(app.config['UPLOAD_FOLDER'], order['completed_file'], as_attachment=True)
    return "File not found."

# --- ADMIN ROUTES ---
@app.route('/admin')
def admin_dashboard():
    if session.get('role') != 'admin': return redirect(url_for('home'))
    
    conn = get_db()
    users_count = conn.execute("SELECT COUNT(*) FROM users WHERE role='user'").fetchone()[0]
    orders_count = conn.execute("SELECT COUNT(*) FROM orders").fetchone()[0]
    # Revenue calc (only paid or delivered)
    revenue = conn.execute("SELECT SUM(price) FROM orders WHERE status != 'Payment Pending'").fetchone()[0] or 0
    conn.close()
    
    return render_template('admin_dashboard.html', u_count=users_count, o_count=orders_count, rev=revenue)

@app.route('/admin/orders', methods=['GET', 'POST'])
def admin_orders():
    if session.get('role') != 'admin': return redirect(url_for('home'))
    
    conn = get_db()
    if request.method == 'POST':
        order_id = request.form['order_id']
        new_status = request.form['status']
        
        file = request.files.get('completed_file')
        filename = ""
        if file and file.filename != '':
            filename = secure_filename(file.filename)
            file.save(os.path.join(app.config['UPLOAD_FOLDER'], filename))
            conn.execute("UPDATE orders SET status=?, completed_file=? WHERE id=?", (new_status, filename, order_id))
        else:
            conn.execute("UPDATE orders SET status=? WHERE id=?", (new_status, order_id))
        conn.commit()
        flash('Order updated successfully.', 'success')
        
    orders = conn.execute('''SELECT orders.*, users.name as user_name 
                             FROM orders JOIN users ON orders.user_id = users.id 
                             ORDER BY orders.id DESC''').fetchall()
    conn.close()
    return render_template('admin_orders.html', orders=orders)

@app.route('/admin/users')
def admin_users():
    if session.get('role') != 'admin': return redirect(url_for('home'))
    conn = get_db()
    users = conn.execute("SELECT * FROM users WHERE role='user'").fetchall()
    conn.close()
    return render_template('admin_users.html', users=users)

if __name__ == '__main__':
    init_db()
    app.run(debug=True)