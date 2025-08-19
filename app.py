from flask import Flask, render_template, request, redirect, url_for
from flask_sqlalchemy import SQLAlchemy
from flask_migrate import Migrate
from datetime import datetime
import requests
import threading

app = Flask(__name__)
app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///app.db' # Drei Schrägstriche für den relativen Pfad, vier wären absolut
db = SQLAlchemy(app)
migrate = Migrate(app, db)
 
class Home(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String, nullable=False)
    rooms = db.relationship('Room', backref='home', cascade="all, delete-orphan") # Cascade und delete-orphan sagt SQLAlchemy, dass alle untergeordneten Objekte (?) bei Löschen auch entfernt werden sollen

class Room(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String, nullable=False)
    home_id = db.Column(db.Integer, db.ForeignKey('home.id'), nullable=False)
    sensors = db.relationship('Sensor', backref='room', cascade="all, delete-orphan")

class Sensor(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String, nullable=False)
    url = db.Column(db.String, nullable=False)
    room_id = db.Column(db.Integer, db.ForeignKey('room.id'), nullable=False)
    measurements = db.relationship('Measurement', backref='sensor', cascade="all, delete-orphan")

class Measurement(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    sensor_id = db.Column(db.Integer, db.ForeignKey('sensor.id'), nullable=False)
    timestamp = db.Column(db.DateTime, default=datetime.now, nullable=False) # Bei Aufruf wird automatisch die aktuelle Zeit gesetzt, fälschlicherweise habe ich zuerst datetime.now() gebraucht, was nur bei Programmstart gesetzt wird
    values = db.relationship('MeasurementValue', backref='measurement', cascade="all, delete-orphan")

class MeasurementType(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String, nullable=False)
    unit = db.Column(db.String, nullable=False)
    values = db.relationship('MeasurementValue', backref='measurement_type', cascade="all, delete-orphan")

class MeasurementValue(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    value = db.Column(db.Float, nullable=False)
    measurement_id = db.Column(db.Integer, db.ForeignKey('measurement.id'), nullable=False)
    measurement_type_id = db.Column(db.Integer, db.ForeignKey('measurement_type.id'), nullable=False)


def background_task(interval_seconds=60):
    with app.app_context(): # Wird gebraucht, damit der Thread Zugriff auf die Flask-App und die Datenbank hat
        while True:
            get_measurements()
            threading.Event().wait(interval_seconds)  # Wartet 60 Sekunden vor dem nächsten Durchlaufen

def get_measurement(sensor_id):
    sensor = Sensor.query.get(sensor_id)
    if not sensor:
        print(f"Sensor {sensor_id} not found")
        return
    response = requests.get(sensor.url)
    if response.status_code != 200:
        print(f"Failed to get sensor data: {response.status_code}")
        return
    data = response.json()
    
    measurement = Measurement(sensor_id=sensor.id)
    db.session.add(measurement)
    db.session.flush()  # Stellt sicher, dass "measurement" eine gültigen ID hat, bevor wir MeasurementValue hinzufügen
    for type_name, value in data.items():
        if isinstance(value, (int, float)):
            measurement_type = MeasurementType.query.filter_by(name=type_name).first()
            if not measurement_type:
                measurement_type = MeasurementType(name=type_name, unit='unit') # Standard als Platzhalter, kann später angepasst werden
                db.session.add(measurement_type)
                db.session.flush()  # Stellt sicher, dass "measurement_type" eine gültigen ID hat
            measurement_value = MeasurementValue(value=value, measurement_id=measurement.id, measurement_type_id=measurement_type.id)
            db.session.add(measurement_value)
        else:
            print(f"Invalid data type for {type_name}: {value}")
    db.session.commit()
    return measurement

def get_measurements():
    for sensor in Sensor.query.all():
        measurement = get_measurement(sensor.id)
        if measurement:
            print(f"Sensor: {sensor.name}, Measurement: {measurement.timestamp}, Values: {[value.value for value in measurement.values]}")


@app.route('/')
def index():
    homes = Home.query.all()
    return render_template('index.html', homes=homes)

@app.route('/home/add', methods=['GET', 'POST'])
def add_home():
    if request.method == 'POST':
        name = request.form['name']
        db.session.add(Home(name=name))
        db.session.commit()
        return redirect(url_for('index'))
    return render_template('add_home.html')

@app.route('/room/add/<int:home_id>', methods=['GET', 'POST'])
def add_room(home_id):
    if request.method == 'POST':
        name = request.form['name']
        db.session.add(Room(name=name, home_id=home_id))
        db.session.commit()
        return redirect(url_for('index'))
    return render_template('add_room.html', home_id=home_id)

@app.route('/sensor/add/<int:room_id>', methods=['GET', 'POST'])
def add_sensor(room_id):
    if request.method == 'POST':
        name = request.form['name']
        url = request.form['url']
        db.session.add(Sensor(name=name, url=url, room_id=room_id))
        db.session.commit()
        return redirect(url_for('index'))
    return render_template('add_sensor.html', room_id=room_id)

@app.route('/sensor/<int:sensor_id>')
def sensor_detail(sensor_id):
    sensor = Sensor.query.get_or_404(sensor_id)# Holt den Sensor oder sendet 404 fehler wenn der sensor nicht findet
    
    property_name = request.args.get('property', 'temperature') # Temperatur als Standardwert falls kein Parameter angegeben wird
    
    measurements = [] 
    values = [] 
    for m in sensor.measurements:
        mv = next((v for v in m.values if v.measurement_type.name == property_name), None) # Sucht nach dem ersten MeasurementValue dass dem property_name entspricht
        if mv: # mv steht für MeasurementValue, m ist Measurement
            measurements.append(m.timestamp.strftime('%Y-%m-%d %H:%M:%S')) # Formatiert Datum und Urzeit
            values.append(mv.value) 
    
    return render_template('sensor_detail.html', sensor=sensor, measurements=measurements, values=values, property_name=property_name)


if __name__ == '__main__':
    thread = threading.Thread(target=background_task, args=(60,), daemon=True)  # Daemon-Thread, damit er im Hintergrund läuft und die App nicht blockiert, schliesst automatisch wenn die App geschlossen wird
    thread.start()  # Startet den Hintergrund-Thread
    app.run(debug=True)
