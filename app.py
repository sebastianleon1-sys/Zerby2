from flask import Flask
from flask_sqlalchemy import SQLAlchemy
from werkzeug.security import generate_password_hash, check_password_hash
import os
from dotenv import load_dotenv
from datetime import datetime, timezone
from flask_socketio import SocketIO

load_dotenv()

app = Flask(__name__)

UPLOAD_FOLDER = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'static/uploads')
app.config['UPLOAD_FOLDER'] = UPLOAD_FOLDER

# Creamos la carpeta si no existe automáticamente
os.makedirs(UPLOAD_FOLDER, exist_ok=True)

# Límite de tamaño (opcional, ej: 16MB)
app.config['MAX_CONTENT_LENGTH'] = 16 * 1024 * 1024

# --- CONFIGURACIÓN ---
DATABASE_URL = os.getenv("DATABASE_URL")
if not DATABASE_URL or not DATABASE_URL.startswith("postgresql://"):
    raise RuntimeError("DATABASE_URL no está configurada o invalida. Debe apuntar a Neon.")

app.config['SQLALCHEMY_DATABASE_URI'] = DATABASE_URL
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
app.config['SECRET_KEY'] = os.getenv("SECRET_KEY")
app.config.setdefault("SQLALCHEMY_ENGINE_OPTIONS", {"pool_pre_ping": True}) 

db = SQLAlchemy(app)

socketio = SocketIO(
    app,
    cors_allowed_origins="*",
    logger=True,
    engineio_logger=True
)

# --- MODELOS ---

class Usuario(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    nombre_completo = db.Column(db.String(100), nullable=False)
    email = db.Column(db.String(100), unique=True, nullable=False)
    password_hash = db.Column(db.Text, nullable=False)
    telefono = db.Column(db.String(15))
    direccion = db.Column(db.String(255)) 
    lat = db.Column(db.Float)
    lon = db.Column(db.Float)

    def set_password(self, password):
        self.password_hash = generate_password_hash(password)

    def check_password(self, password):
        return check_password_hash(self.password_hash, password)

class Proveedor(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    nombre_completo = db.Column(db.String(100), nullable=False)
    email = db.Column(db.String(100), unique=True, nullable=False)
    password_hash = db.Column(db.Text, nullable=False)
    telefono = db.Column(db.String(15), nullable=False)
    oficio = db.Column(db.String(50), nullable=False) 
    descripcion = db.Column(db.Text)
    direccion = db.Column(db.String(255)) 
    horario = db.Column(db.String(255))
    atiende_urgencias = db.Column(db.Boolean, default=False)
    lat = db.Column(db.Float)
    lon = db.Column(db.Float)
    
    def set_password(self, password):
        self.password_hash = generate_password_hash(password)

    def check_password(self, password):
        return check_password_hash(self.password_hash, password)

class Conversacion(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    usuario_id = db.Column(db.Integer, db.ForeignKey('usuario.id'), nullable=False)
    proveedor_id = db.Column(db.Integer, db.ForeignKey('proveedor.id'), nullable=False)
    mensajes = db.relationship('Mensaje', backref='conversacion', lazy=True, cascade="all, delete-orphan")
    usuario = db.relationship('Usuario', backref='conversaciones')
    proveedor = db.relationship('Proveedor', backref='conversaciones')

class Mensaje(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    conversacion_id = db.Column(db.Integer, db.ForeignKey('conversacion.id'), nullable=False)
    remitente_id = db.Column(db.Integer, nullable=False)
    remitente_tipo = db.Column(db.String(20), nullable=False)
    contenido = db.Column(db.Text, nullable=False)
    timestamp = db.Column(db.DateTime, nullable=False, default=lambda: datetime.now(timezone.utc))

class Calificacion(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    puntuacion = db.Column(db.Integer, nullable=False)
    usuario_id = db.Column(db.Integer, db.ForeignKey('usuario.id'), nullable=False)
    proveedor_id = db.Column(db.Integer, db.ForeignKey('proveedor.id'), nullable=False)
    timestamp = db.Column(db.DateTime, nullable=False, default=lambda: datetime.now(timezone.utc))
    comentario = db.Column(db.Text, nullable=True)

    __table_args__ = (
        db.UniqueConstraint('usuario_id', 'proveedor_id', name='uq_usuario_proveedor_calificacion'),
        db.CheckConstraint('puntuacion >= 1 AND puntuacion <= 7', name='check_puntuacion_range')
    )

class Portafolio(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    proveedor_id = db.Column(db.Integer, db.ForeignKey('proveedor.id'), nullable=False)
    imagen_url = db.Column(db.Text, nullable=False) 
    descripcion = db.Column(db.Text, nullable=True) 
    timestamp = db.Column(db.DateTime, nullable=False, default=lambda: datetime.now(timezone.utc))
    proveedor = db.relationship('Proveedor', backref=db.backref('portafolios', lazy=True, cascade="all, delete-orphan"))

# --- EJECUCIÓN ---

if __name__ == "__main__":
    # Importante: Importar las rutas AQUÍ, justo antes de correr la app
    # para asegurar que los modelos y la app ya existan.
    from routes import * 
    socketio.run(app, host="127.0.0.1", port=5000, debug=True, use_reloader=False)