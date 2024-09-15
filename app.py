from flask import Flask, render_template, request, redirect, url_for, session
import smtplib
from email.mime.text import MIMEText
import random
import string
from models import db, User, EmailSettings

app = Flask(__name__)
app.secret_key = 'supersecretkey'
app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///users.db'
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
db.init_app(app)

confirmation_tokens = {}
reset_tokens = {}

@app.route('/')
def index():
    return redirect(url_for('login'))

@app.route('/register', methods=['GET', 'POST'])
def register():
    if request.method == 'POST':
        email = request.form['email']
        password = request.form['password']
        user = User.query.filter_by(email=email).first()
        if user:
            return render_template('register.html', error='Пользователь с таким email уже существует')
        new_user = User(email=email)
        new_user.set_password(password)
        db.session.add(new_user)
        db.session.commit()
        token = generate_token()
        confirmation_tokens[token] = email
        send_confirmation_email(email, token)
        return redirect(url_for('confirm_email'))
    return render_template('register.html')

@app.route('/confirm_email')
def confirm_email():
    return render_template('confirm_email.html')

@app.route('/confirm/<token>')
def confirm(token):
    if token in confirmation_tokens:
        email = confirmation_tokens.pop(token)
        user = User.query.filter_by(email=email).first()
        if user:
            user.confirmed = True
            db.session.commit()
            return render_template('confirm_success.html')
    return render_template('confirm_fail.html')

@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        email = request.form['email']
        password = request.form['password']
        user = User.query.filter_by(email=email).first()
        if user and user.check_password(password) and user.confirmed:
            session['email'] = email
            return redirect(url_for('user_data'))
        else:
            return render_template('login.html', error='Неверный email или пароль')
    return render_template('login.html')

@app.route('/reset_password', methods=['GET', 'POST'])
def reset_password():
    if request.method == 'POST':
        email = request.form['email']
        user = User.query.filter_by(email=email).first()
        if user:
            token = generate_token()
            reset_tokens[token] = email
            send_reset_password_email(email, token)
        return redirect(url_for('login'))
    return render_template('reset_password.html')

@app.route('/reset/<token>', methods=['GET', 'POST'])
def reset(token):
    if token in reset_tokens:
        email = reset_tokens.pop(token)
        user = User.query.filter_by(email=email).first()
        if user and request.method == 'POST':
            new_password = request.form['password']
            user.set_password(new_password)
            db.session.commit()
            return redirect(url_for('login'))
        return render_template('reset_password_form.html')
    return render_template('reset_fail.html')

@app.route('/user_data')
def user_data():
    if 'email' in session:
        return render_template('user_data.html', email=session['email'])
    return redirect(url_for('login'))

def generate_token(length=32):
    return ''.join(random.choices(string.ascii_letters + string.digits, k=length))

def send_confirmation_email(email, token):
    subject = "Подтверждение регистрации"
    body = f"Пожалуйста, подтвердите вашу регистрацию по ссылке: http://127.0.0.1:5000/confirm/{token}"
    send_email(email, subject, body)

def send_reset_password_email(email, token):
    subject = "Сброс пароля"
    body = f"Пожалуйста, сбросьте ваш пароль по ссылке: http://127.0.0.1:5000/reset/{token}"
    send_email(email, subject, body)

def send_email(to_email, subject, body):
    email_settings = EmailSettings.query.first()
    if not email_settings:
        raise ValueError("Email settings not found in the database")

    from_email = email_settings.from_email
    from_password = email_settings.from_password

    msg = MIMEText(body)
    msg['Subject'] = subject
    msg['From'] = from_email
    msg['To'] = to_email

    with smtplib.SMTP_SSL('smtp.gmail.com', 465) as server:
        server.login(from_email, from_password)
        server.sendmail(from_email, to_email, msg.as_string())

if __name__ == '__main__':
    with app.app_context():
        db.create_all()
        # Добавьте учетные данные для отправки электронной почты в базу данных
        if not EmailSettings.query.first():
            email_settings = EmailSettings(from_email="", from_password="")
            db.session.add(email_settings)
            db.session.commit()
    app.run(debug=True)
