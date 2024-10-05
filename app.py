from flask import Flask, render_template, request, jsonify, redirect, url_for
from flask_mail import Mail, Message
from apscheduler.schedulers.background import BackgroundScheduler
from flask_login import LoginManager, UserMixin, login_user, login_required, logout_user, current_user
from werkzeug.security import generate_password_hash, check_password_hash
import requests
from datetime import datetime, timedelta
import os
import pymysql
from pymysql.cursors import DictCursor
import logging

# Configure logging
logging.basicConfig(level=logging.DEBUG)

class Location:
    def __init__(self, id, name, latitude, longitude, notify, notification_lead_time, cloud_coverage_threshold, created_at, user_id):
        self.id = id
        self.name = name
        self.latitude = latitude
        self.longitude = longitude
        self.notify = notify
        self.notification_lead_time = notification_lead_time
        self.cloud_coverage_threshold = cloud_coverage_threshold
        self.created_at = created_at
        self.user_id = user_id

    def to_dict(self):
        return {
            'id': self.id,
            'name': self.name,
            'latitude': self.latitude,
            'longitude': self.longitude,
            'notify': self.notify,
            'notification_lead_time': self.notification_lead_time,
            'cloud_coverage_threshold': self.cloud_coverage_threshold,
            'created_at': self.created_at.isoformat() if self.created_at else None,
            'user_id': self.user_id
        }

app = Flask(__name__)
app.config['SECRET_KEY'] = os.environ.get('SECRET_KEY', 'fallback_secret_key')

# Database configuration
db_config = {
    'host': os.environ.get('DB_HOST', 'localhost'),
    'user': os.environ.get('DB_USER', 'root'),
    'password': os.environ.get('DB_PASSWORD', '12345'),
    'db': os.environ.get('DB_NAME', 'abintest'),
    'charset': 'utf8mb4',
    'cursorclass': DictCursor
}

# Email configuration
app.config['MAIL_SERVER'] = os.environ.get('MAIL_SERVER', 'smtp.gmail.com')
app.config['MAIL_PORT'] = int(os.environ.get('MAIL_PORT', 587))
app.config['MAIL_USE_TLS'] = os.environ.get('MAIL_USE_TLS', 'True').lower() == 'true'
app.config['MAIL_USERNAME'] = os.environ.get('MAIL_USERNAME', 'abinr.csa2226@saintgits.org')
app.config['MAIL_PASSWORD'] = os.environ.get('MAIL_PASSWORD', 'abin@saintgits')

mail = Mail(app)

login_manager = LoginManager()
login_manager.init_app(app)
login_manager.login_view = 'login'

class User(UserMixin):
    def __init__(self, id, username, email, password_hash):
        self.id = id
        self.username = username
        self.email = email
        self.password_hash = password_hash

    def check_password(self, password):
        return check_password_hash(self.password_hash, password)

@login_manager.user_loader
def load_user(user_id):
    with get_db_connection() as conn:
        with conn.cursor() as cursor:
            cursor.execute("SELECT * FROM users WHERE id = %s", (user_id,))
            user = cursor.fetchone()
            if user:
                return User(user['id'], user['username'], user['email'], user['password_hash'])
    return None

def get_db_connection():
    return pymysql.connect(**db_config)

@app.route('/')
def login_page():
    return render_template('login.html')

@app.route('/register', methods=['GET', 'POST'])
def register():
    if request.method == 'POST':
        username = request.form.get('username')
        email = request.form.get('email')
        password = request.form.get('password')
        
        with get_db_connection() as conn:
            with conn.cursor() as cursor:
                cursor.execute("SELECT * FROM users WHERE username = %s", (username,))
                if cursor.fetchone():
                    return jsonify({'error': 'Username already exists'}), 400

                password_hash = generate_password_hash(password)
                cursor.execute("INSERT INTO users (username, email, password_hash) VALUES (%s, %s, %s)",
                                   (username, email, password_hash))
                conn.commit()
                    
                cursor.execute("SELECT * FROM users WHERE username = %s", (username,))
                user = cursor.fetchone()
                    
        new_user = User(user['id'], user['username'], user['email'], user['password_hash'])
        login_user(new_user)
        return jsonify({'message': 'Registered successfully'})
    
    return render_template('register.html')


@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        username = request.form.get('username')
        password = request.form.get('password')
        
        with get_db_connection() as conn:
            with conn.cursor() as cursor:
                cursor.execute("SELECT * FROM users WHERE username = %s", (username,))
                user = cursor.fetchone()
                
                # Log the fetched user data for debugging
                logging.debug(f"Fetched user: {user}")

        if user and check_password_hash(user['password_hash'], password):
            user_obj = User(user['id'], user['username'], user['email'], user['password_hash'])
            login_user(user_obj)
            return jsonify({'message': 'Logged in successfully'})
        
        logging.warning(f"Login failed for user: {username}")
        return jsonify({'error': 'Invalid username or password'}), 401
    
    return render_template('login.html')

@app.route('/index')
@login_required
def index():
    return render_template('index.html')

@app.route('/logout')
@login_required
def logout():
    logout_user()
    return jsonify({'message': 'Logged out successfully'})

@app.route('/submit_location', methods=['POST'])
@login_required
def submit_location():
    try:
        data = request.json
        latitude = data.get('latitude')
        longitude = data.get('longitude')
        name = data.get('name', f"Location at {latitude}, {longitude}")
        notification_lead_time = data.get('notification_lead_time', 24)
        cloud_coverage_threshold = data.get('cloud_coverage_threshold', 15.0)
        
        if not latitude or not longitude:
            return jsonify({'error': 'Latitude and longitude are required'}), 400
        
        with get_db_connection() as conn:
            with conn.cursor() as cursor:
                cursor.execute("""
                    INSERT INTO locations (name, latitude, longitude, user_id, notification_lead_time, cloud_coverage_threshold)
                    VALUES (%s, %s, %s, %s, %s, %s)
                """, (name, float(latitude), float(longitude), current_user.id, int(notification_lead_time), float(cloud_coverage_threshold)))
                conn.commit()
                
                cursor.execute("SELECT * FROM locations WHERE id = LAST_INSERT_ID()")
                new_location_data = cursor.fetchone()
                
                new_location = Location(
                    id=new_location_data['id'],
                    name=new_location_data['name'],
                    latitude=new_location_data['latitude'],
                    longitude=new_location_data['longitude'],
                    notify=new_location_data['notify'],
                    notification_lead_time=new_location_data['notification_lead_time'],
                    cloud_coverage_threshold=new_location_data['cloud_coverage_threshold'],
                    created_at=new_location_data['created_at'],
                    user_id=new_location_data['user_id']
                )
        
        # Fetch Landsat data (implement this function)
        landsat_data = get_landsat_data(latitude, longitude)
        
        return jsonify({
            'message': f'Saved location: {name}',
            'location': new_location.to_dict(),
            'landsat_data': landsat_data
        })
    except Exception as e:
        app.logger.error(f"Error in submit_location: {str(e)}")
        return jsonify({'error': 'An error occurred while submitting the location'}), 500

def check_and_notify():
    with app.app_context():
        with get_db_connection() as conn:
            with conn.cursor() as cursor:
                cursor.execute("SELECT * FROM locations WHERE notify = TRUE")
                locations_data = cursor.fetchall()
                
        for location_data in locations_data:
            location = Location(
                id=location_data['id'],
                name=location_data['name'],
                latitude=location_data['latitude'],
                longitude=location_data['longitude'],
                notify=location_data['notify'],
                notification_lead_time=location_data['notification_lead_time'],
                cloud_coverage_threshold=location_data['cloud_coverage_threshold'],
                created_at=location_data['created_at'],
                user_id=location_data['user_id']
            )
            
            start_date = datetime.now() + timedelta(hours=location.notification_lead_time)
            end_date = start_date + timedelta(days=1)
            overpasses = get_landsat_overpasses(location.latitude, location.longitude, start_date, end_date)
            if overpasses:
                next_pass = overpasses[0]
                with get_db_connection() as conn:
                    with conn.cursor() as cursor:
                        cursor.execute("SELECT email FROM users WHERE id = %s", (location.user_id,))
                        user = cursor.fetchone()
                if user:
                    message = Message("Upcoming Landsat Pass",
                                      sender=app.config['MAIL_USERNAME'],
                                      recipients=[user['email']])
                    message.body = f"Hello,\n\nThere is an upcoming Landsat pass for your location '{location.name}' at {next_pass}.\n\nBest regards,\nLandsat Notification System"
                    mail.send(message)
scheduler = BackgroundScheduler()
scheduler.add_job(func=check_and_notify, trigger="interval", hours=24)
scheduler.start()

@app.teardown_appcontext
def shutdown_scheduler(error=None):
    if scheduler.running:
        scheduler.shutdown()


def get_landsat_sr_data(latitude, longitude, date):
    url = f"https://landsatlook.usgs.gov/data/v1/sr?lat={latitude}&lon={longitude}&date={date}"

    try:
        response = requests.get(url)
        response.raise_for_status()
        data = response.json()
        return data
    except requests.RequestException as e:
        print(f"Error fetching Landsat SR data: {e}")
        return None
    
app.route('/get_landsat_data', methods=['POST'])
def get_landsat_data():
    data = request.json
    latitude = data.get('latitude')
    longitude = data.get('longitude')
    cloud_coverage_threshold = data.get('cloud_coverage_threshold')

    # Replace with actual Landsat API URL and parameters
    # For now, we'll simulate it with a placeholder API endpoint
    landsat_api_url = f"https://api.landsat-imaginary.com/get-data?lat={latitude}&lon={longitude}&cloud_cover={cloud_coverage_threshold}"
    
    try:
        response = requests.get(landsat_api_url)
        landsat_data = response.json()

        # Filter the results based on the cloud coverage threshold
        filtered_data = [
            scene for scene in landsat_data['scenes']
            if scene['cloud_coverage'] <= cloud_coverage_threshold
        ]

        if filtered_data:
            return jsonify({
                'message': 'Landsat data fetched successfully.',
                'data': filtered_data
            })
        else:
            return jsonify({
                'message': 'No Landsat scenes found for the given parameters.',
                'data': []
            })

    except Exception as e:
        return jsonify({'error': str(e)}), 500
    

def get_landsat_overpasses(latitude, longitude, start_date, end_date):
    url = "https://landsat.usgs.gov/landsat_acquisition_api/v1/acqs"
    
    params = {
        "start_date": start_date.strftime("%Y-%m-%d"),
        "end_date": end_date.strftime("%Y-%m-%d"),
        "lat": latitude,
        "lng": longitude,
        "satellite": "landsat_8_9"
    }
    
    try:
        response = requests.get(url, params=params)
        response.raise_for_status()
        data = response.json()
        
        overpasses = []
        for acq in data['results']:
            overpass_time = datetime.fromisoformat(acq['acquisition_date'].replace('Z', '+00:00'))
            overpasses.append(overpass_time.strftime("%Y-%m-%d %H:%M:%S"))
        
        return overpasses
    except requests.RequestException as e:
        print(f"Error fetching Landsat overpass data: {e}")
        return []

if __name__ == '__main__':
    app.run(debug=False)
