from flask import Flask, render_template, request, jsonify
import requests
from datetime import datetime, timedelta
from flask_sqlalchemy import SQLAlchemy
from flask_mail import Mail, Message
from apscheduler.schedulers.background import BackgroundScheduler
from flask_login import LoginManager, UserMixin, login_user, login_required, logout_user, current_user
from werkzeug.security import generate_password_hash, check_password_hash

app = Flask(__name__)
app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///landsat_app.db'
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
db = SQLAlchemy(app)

with app.app_context():
    db.create_all()

app.config['MAIL_SERVER'] = 'smtp.example.com'  # Replace with your SMTP server
app.config['MAIL_PORT'] = 587
app.config['MAIL_USE_TLS'] = True
app.config['MAIL_USERNAME'] = 'your_email@example.com'  # Replace with your email
app.config['MAIL_PASSWORD'] = 'your_password'  # Replace with your password

mail = Mail(app)

login_manager = LoginManager()
login_manager.init_app(app)
login_manager.login_view = 'login'


@app.route('/')
def index():
    return render_template('index.html')

class User(UserMixin, db.Model):
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(80), unique=True, nullable=False)
    email = db.Column(db.String(120), unique=True, nullable=False)
    password_hash = db.Column(db.String(128))

    def set_password(self, password):
        self.password_hash = generate_password_hash(password)

    def check_password(self, password):
        return check_password_hash(self.password_hash, password)

class Location(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), nullable=False)
    latitude = db.Column(db.Float, nullable=False)
    longitude = db.Column(db.Float, nullable=False)
    email = db.Column(db.String(120), nullable=False)
    notify = db.Column(db.Boolean, default=True)
    created_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    user = db.relationship('User', backref=db.backref('locations', lazy=True))

    def to_dict(self):
        return {
            'id': self.id,
            'name': self.name,
            'latitude': self.latitude,
            'longitude': self.longitude,
            'email': self.email,
            'notify': self.notify,
            'created_at': self.created_at.isoformat()
        }

@login_manager.user_loader
def load_user(user_id):
    return User.query.get(int(user_id))


# Add these new routes for user authentication
@app.route('/register', methods=['GET', 'POST'])
def register():
    if request.method == 'POST':
        username = request.form.get('username')
        email = request.form.get('email')
        password = request.form.get('password')
        
        user = User.query.filter_by(username=username).first()
        if user:
            return jsonify({'error': 'Username already exists'}), 400
        
        new_user = User(username=username, email=email)
        new_user.set_password(password)
        db.session.add(new_user)
        db.session.commit()
        
        login_user(new_user)
        return jsonify({'message': 'Registered successfully'})
    
    return render_template('register.html')

@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        username = request.form.get('username')
        password = request.form.get('password')
        
        user = User.query.filter_by(username=username).first()
        if user and user.check_password(password):
            login_user(user)
            return jsonify({'message': 'Logged in successfully'})
        
        return jsonify({'error': 'Invalid username or password'}), 401
    
    return render_template('login.html')

@app.route('/logout')
@login_required
def logout():
    logout_user()
    return jsonify({'message': 'Logged out successfully'})

def get_landsat_overpasses(latitude, longitude):
    # USGS Landsat Acquisition Tool API endpoint
    url = "https://landsat.usgs.gov/landsat_acquisition_api/v1/acqs"
    
    # Calculate date range (next 16 days)
    start_date = datetime.now().strftime("%Y-%m-%d")
    end_date = (datetime.now() + timedelta(days=16)).strftime("%Y-%m-%d")
    
    # Prepare request parameters
    params = {
        "start_date": start_date,
        "end_date": end_date,
        "lat": latitude,
        "lng": longitude,
        "satellite": "landsat_8_9"
    }
    
    try:
        response = requests.get(url, params=params)
        response.raise_for_status()  # Raise an exception for bad status codes
        data = response.json()
        
        # Process and format the overpass times
        overpasses = []
        for acq in data['results']:
            overpass_time = datetime.fromisoformat(acq['acquisition_date'].replace('Z', '+00:00'))
            overpasses.append(overpass_time.strftime("%Y-%m-%d %H:%M:%S"))
        
        return overpasses
    except requests.RequestException as e:
        print(f"API request failed: {e}")
        return []


@app.route('/get_locations', methods=['GET'])
@login_required
def get_locations():
    locations = Location.query.filter_by(user=current_user).order_by(Location.created_at.desc()).all()
    return jsonify([location.to_dict() for location in locations])


def check_and_notify():
    with app.app_context():
        locations = Location.query.filter_by(notify=True).all()
        for location in locations:
            overpasses = get_landsat_overpasses(location.latitude, location.longitude)
            if overpasses:
                next_pass = overpasses[0]
                message = Message("Upcoming Landsat Pass",
                                  sender="your_email@example.com",
                                  recipients=[location.email])
                message.body = f"Hello,\n\nThere is an upcoming Landsat pass for your location '{location.name}' at {next_pass}.\n\nBest regards,\nLandsat Notification System"
                mail.send(message)

# Set up the scheduler
scheduler = BackgroundScheduler()
scheduler.add_job(func=check_and_notify, trigger="interval", hours=24)
scheduler.start()

# Modify the submit_location function to include email
@app.route('/submit_location', methods=['POST'])
@login_required
def submit_location():
    data = request.json
    latitude = data.get('latitude')
    longitude = data.get('longitude')
    name = data.get('name', f"Location at {latitude}, {longitude}")
    
    new_location = Location(name=name, latitude=latitude, longitude=longitude, user=current_user)
    db.session.add(new_location)
    db.session.commit()
    
    overpasses = get_landsat_overpasses(latitude, longitude)
    
    return jsonify({
        'message': f'Saved location: {name}',
        'location': new_location.to_dict(),
        'overpasses': overpasses
    })

@app.teardown_appcontext
def shutdown_scheduler(error=None):
    if scheduler.running:
        scheduler.shutdown()

if __name__ == '__main__':
    app.run(debug=False)
