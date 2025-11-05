from flask import Flask, request, jsonify, render_template, session, redirect, url_for, abort
from flask_sqlalchemy import SQLAlchemy
from werkzeug.security import generate_password_hash, check_password_hash
import os
from dotenv import load_dotenv
from datetime import datetime, timezone
from flask_socketio import SocketIO, emit, join_room, leave_room
from sqlalchemy import func # <-- IMPORTADO
from sqlalchemy.exc import IntegrityError # <-- IMPORTADO

load_dotenv()

app = Flask(__name__)

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
    comuna = db.Column(db.String(100))
    horario = db.Column(db.String(255))
    atiende_urgencias = db.Column(db.Boolean, default=False)
    
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
    comentario = db.Column(db.Text, nullable=True) # <-- CAMPO NUEVO

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


# --- RUTAS DE PÁGINAS ---

@app.route('/')
def index():
    return render_template('index.html')

@app.route('/login')
def login_page():
    if 'user_id' in session:
        return redirect(url_for('dashboard'))
    return render_template('login.html')

@app.route('/registro/usuario')
def registro_usuario_page():
    if 'user_id' in session:
        return redirect(url_for('dashboard'))
    return render_template('registro_usuario.html')

@app.route('/registro/proveedor')
def registro_proveedor_page():
    if 'user_id' in session:
        return redirect(url_for('dashboard'))
    return render_template('registro_proveedor.html')

@app.route('/dashboard')
def dashboard():
    if 'user_id' not in session:
        return redirect(url_for('login_page'))

    user_type = session.get('user_type')

    if user_type == 'usuario':
        return render_template('dashboard_usuario.html')
    elif user_type == 'proveedor':
        return render_template('dashboard_proveedor.html')
    else:
        return redirect(url_for('api_logout'))

# --- RUTAS DE AUTENTICACIÓN Y PERFIL ---

@app.route('/api/login', methods=['POST'])
def api_login():
    datos = request.json
    email = datos.get('email')
    password = datos.get('password')
    usuario = Usuario.query.filter_by(email=email).first()
    if usuario and usuario.check_password(password):
        session['user_id'] = usuario.id
        session['user_type'] = 'usuario'
        return jsonify({"mensaje": "Inicio de sesión exitoso"}), 200

    proveedor = Proveedor.query.filter_by(email=email).first()
    if proveedor and proveedor.check_password(password):
        session['user_id'] = proveedor.id
        session['user_type'] = 'proveedor'
        return jsonify({"mensaje": "Inicio de sesión exitoso"}), 200

    return jsonify({"mensaje": "Email o contraseña incorrectos"}), 401

@app.route('/api/logout')
def api_logout():
    session.pop('user_id', None)
    session.pop('user_type', None)
    return redirect(url_for('login_page'))

@app.route('/api/get_profile')
def get_profile():
    if 'user_id' not in session:
        return jsonify({"error": "No autorizado"}), 401
    
    user_id = session['user_id']
    user_type = session['user_type']
    
    if user_type == 'usuario':
        user = Usuario.query.get(user_id)
        profile_data = {
            "id": user.id, # <-- ID AÑADIDO
            "nombre": user.nombre_completo,
            "email": user.email,
            "tipo": user_type
        }
    else:
        user = Proveedor.query.get(user_id)
        profile_data = {
            "id": user.id, # <-- ID AÑADIDO
            "nombre": user.nombre_completo,
            "email": user.email,
            "tipo": user_type,
            "oficio": user.oficio
        }
        
    return jsonify(profile_data)

@app.route('/registrar/usuario', methods=['POST'])
def registrar_usuario():
    datos = request.json
    if Usuario.query.filter_by(email=datos['email']).first():
        return jsonify({"mensaje": "El email ya está registrado"}), 400

    nuevo_usuario = Usuario(
        nombre_completo=datos['nombre_completo'],
        email=datos['email'],
        telefono=datos.get('telefono')
    )
    nuevo_usuario.set_password(datos['password'])
    db.session.add(nuevo_usuario)
    db.session.commit()
    session['user_id'] = nuevo_usuario.id
    session['user_type'] = 'usuario'
    
    return jsonify({"mensaje": "Usuario cliente registrado con éxito"}), 201

@app.route('/registrar/proveedor', methods=['POST'])
def registrar_proveedor():
    datos = request.json
    if Proveedor.query.filter_by(email=datos['email']).first():
        return jsonify({"mensaje": "El email ya está registrado"}), 400
    if 'oficio' not in datos or not datos['oficio']:
         return jsonify({"mensaje": "El campo 'oficio' es obligatorio"}), 400

    nuevo_proveedor = Proveedor(
        nombre_completo=datos['nombre_completo'],
        email=datos['email'],
        telefono=datos['telefono'],
        oficio=datos['oficio'],
        descripcion=datos.get('descripcion'),
        comuna=datos.get('comuna'),
        horario=datos.get('horario'),
        atiende_urgencias=datos.get('atiende_urgencias', False)
    )
    nuevo_proveedor.set_password(datos['password'])
    db.session.add(nuevo_proveedor)
    db.session.commit()
    session['user_id'] = nuevo_proveedor.id
    session['user_type'] = 'proveedor'
    
    return jsonify({"mensaje": "Proveedor registrado con éxito"}), 201

# --- FUNCIONES HELPER PARA BÚSQUEDA ---

def _get_base_query_proveedores_con_calif():
    """
    Crea la consulta base de Proveedor unida (outerjoin)
    a la subconsulta de calificaciones (promedio y total).
    """
    calif_subquery = db.session.query(
        Calificacion.proveedor_id,
        func.avg(Calificacion.puntuacion).label('calif_promedio'),
        func.count(Calificacion.id).label('calif_total')
    ).group_by(Calificacion.proveedor_id).subquery()

    return db.session.query(
        Proveedor, 
        calif_subquery.c.calif_promedio, 
        calif_subquery.c.calif_total
    ).outerjoin(
        calif_subquery, Proveedor.id == calif_subquery.c.proveedor_id
    )

def _serializar_proveedores_con_calif(resultados_query):
    """
    Toma los resultados de la consulta (Proveedor, promedio, total) 
    y los convierte en una lista de diccionarios JSON.
    """
    lista_proveedores = []
    for p, promedio, total in resultados_query:
        lista_proveedores.append({
            "proveedor_id": p.id,
            "nombre": p.nombre_completo,
            "oficio": p.oficio,
            "descripcion": p.descripcion,
            "telefono": p.telefono,
            "comuna": p.comuna,
            "horario": p.horario,
            "atiende_urgencias": p.atiende_urgencias,
            "calif_promedio": round(float(promedio), 1) if promedio else 0,
            "calif_total": int(total) if total else 0
        })
    return lista_proveedores

# --- RUTAS DE BÚSQUEDA DE PROVEEDORES ---

@app.route('/api/proveedores/cercanos')
def api_proveedores_cercanos():
    if 'user_id' not in session or session['user_type'] != 'usuario':
        return jsonify({"error": "No autorizado"}), 401

    try:
        base_query = _get_base_query_proveedores_con_calif()
        proveedores_con_calif = base_query.limit(10).all()
        lista_proveedores = _serializar_proveedores_con_calif(proveedores_con_calif)

        return jsonify(lista_proveedores)

    except Exception as e:
        # --- LÍNEA DE DEPURACIÓN AÑADIDA ---
        print(f"!!! ERROR en /api/proveedores/cercanos: {e}") 
        return jsonify({"error": str(e)}), 500


@app.route('/api/buscar')
def api_buscar():
    if 'user_id' not in session or session['user_type'] != 'usuario':
        return jsonify({"error": "No autorizado"}), 401

    query = request.args.get('q', '')
    comuna = request.args.get('comuna', '')
    
    try:
        base_query = _get_base_query_proveedores_con_calif() 
        
        if query:
            termino_busqueda = f"%{query}%"
            base_query = base_query.filter(
                (Proveedor.oficio.ilike(termino_busqueda)) |
                (Proveedor.descripcion.ilike(termino_busqueda))
            )

        if comuna and comuna.lower() != 'todas':
            comuna_busqueda = f"%{comuna}%" 
            base_query = base_query.filter(Proveedor.comuna.ilike(comuna_busqueda))

        proveedores_con_calif = base_query.all()
        lista_proveedores = _serializar_proveedores_con_calif(proveedores_con_calif)
            
        return jsonify(lista_proveedores)
    
    except Exception as e:
        print(f"!!! ERROR en /api/buscar: {e}") # <-- Línea de depuración
        return jsonify({"error": str(e)}), 500

# --- RUTAS DE CHAT Y MENSAJERÍA ---
    
@app.route('/api/iniciar_chat/<int:proveedor_id>', methods=['POST'])
def api_iniciar_chat(proveedor_id):
    if 'user_id' not in session or session['user_type'] != 'usuario':
        return jsonify({"error": "No autorizado"}), 401

    cliente_id = session['user_id']

    conversacion_existente = Conversacion.query.filter_by(
        usuario_id=cliente_id,
        proveedor_id=proveedor_id
    ).first()

    if conversacion_existente:
        return jsonify({"mensaje": "Conversación existente", "conversacion_id": conversacion_existente.id}), 200
    else:
        try:
            nueva_conversacion = Conversacion(
                usuario_id=cliente_id,
                proveedor_id=proveedor_id
            )
            db.session.add(nueva_conversacion)
            db.session.commit()
            return jsonify({"mensaje": "Conversación iniciada", "conversacion_id": nueva_conversacion.id}), 201
        except Exception as e:
            db.session.rollback()
            return jsonify({"error": str(e)}), 500

@app.route('/bandeja_entrada')
def bandeja_entrada():
    if 'user_id' not in session:
        return redirect(url_for('login_page'))
    return render_template('bandeja_entrada.html')

@app.route('/conversacion/<int:conv_id>')
def vista_conversacion(conv_id):
    if 'user_id' not in session:
        return redirect(url_for('login_page'))
    
    conv = Conversacion.query.get_or_404(conv_id)
    user_id = session['user_id']
    user_type = session['user_type']

    if (user_type == 'usuario' and conv.usuario_id != user_id) or \
       (user_type == 'proveedor' and conv.proveedor_id != user_id):
        return abort(403) 

    return render_template('conversacion.html', 
                           conv_id=conv_id, 
                           user_tipo_actual=user_type)

@app.route('/api/conversaciones')
def api_get_conversaciones():
    if 'user_id' not in session:
        return jsonify({"error": "No autorizado"}), 401
    
    user_id = session['user_id']
    user_type = session['user_type']
    lista_convos = []
    
    if user_type == 'usuario':
        conversaciones = db.session.query(Conversacion, Proveedor.nombre_completo, Proveedor.oficio)\
            .join(Proveedor, Conversacion.proveedor_id == Proveedor.id)\
            .filter(Conversacion.usuario_id == user_id).all()
        
        for conv, nombre, oficio in conversaciones:
            lista_convos.append({
                "id": conv.id,
                "otro_participante": nombre,
                "detalle": oficio
            })
    else: # user_type == 'proveedor'
        conversaciones = db.session.query(Conversacion, Usuario.nombre_completo)\
            .join(Usuario, Conversacion.usuario_id == Usuario.id)\
            .filter(Conversacion.proveedor_id == user_id).all()

        for conv, nombre in conversaciones:
             lista_convos.append({
                "id": conv.id,
                "otro_participante": nombre,
                "detalle": "Cliente"
            })
    
    return jsonify(lista_convos)

@app.route('/api/conversacion/<int:conv_id>/detalles')
def api_get_detalles_conv(conv_id):
    if 'user_id' not in session: return jsonify({"error": "No autorizado"}), 401
    
    conv = Conversacion.query.get_or_404(conv_id)
    user_id = session['user_id']
    user_type = session['user_type']
    
    if (user_type == 'usuario' and conv.usuario_id != user_id) or \
       (user_type == 'proveedor' and conv.proveedor_id != user_id):
        return jsonify({"error": "No autorizado"}), 403

    otro_nombre = conv.proveedor.nombre_completo if user_type == 'usuario' else conv.usuario.nombre_completo
    mensajes_db = Mensaje.query.filter_by(conversacion_id=conv_id).order_by(Mensaje.timestamp.asc()).all()
    mensajes_json = []
    for msg in mensajes_db:
        mensajes_json.append({
            "contenido": msg.contenido,
            "remitente_tipo": msg.remitente_tipo,
            "timestamp": msg.timestamp.strftime("%d/%m %H:%M") 
        })
    
    return jsonify({
        "otro_nombre": otro_nombre,
        "mensajes": mensajes_json,
        # --- LÍNEA CORREGIDA (la que faltaba) ---
        "proveedor_id": conv.proveedor_id if user_type == 'usuario' else None
    })

@app.route('/api/conversacion/<int:conv_id>/enviar', methods=['POST'])
def api_enviar_mensaje(conv_id):
    if 'user_id' not in session:
        return jsonify({"error": "No autorizado"}), 401
    
    conv = Conversacion.query.get_or_404(conv_id)
    user_id = session['user_id']
    user_type = session['user_type']
    datos = request.json

    autorizado = (user_type == 'usuario' and conv.usuario_id == user_id) or \
                 (user_type == 'proveedor' and conv.proveedor_id == user_id)
    if not autorizado:
        return jsonify({"error": "No autorizado"}), 403
    
    contenido = datos.get('contenido', '').strip()
    if not contenido:
        return jsonify({"error": "Mensaje vacío"}), 400

    try:
        nuevo_mensaje = Mensaje(
            conversacion_id=conv_id,
            remitente_id=user_id,
            remitente_tipo=user_type,
            contenido=contenido
        )
        db.session.add(nuevo_mensaje)
        db.session.commit()

        payload = {
            "contenido": nuevo_mensaje.contenido,
            "remitente_tipo": nuevo_mensaje.remitente_tipo,
            "timestamp": nuevo_mensaje.timestamp.strftime("%d/%m %H:%M")
        }
        room = f"chat_{conv_id}"
        print(f"[EMIT] room={room} payload={payload}")
        socketio.emit("receive_message", payload, room=room)

        return jsonify({"mensaje": "Enviado"}), 201

    except Exception as e:
        db.session.rollback()
        return jsonify({"error": str(e)}), 500

# --- RUTAS DE CALIFICACIÓN Y PERFIL PÚBLICO ---

@app.route('/api/calificar/<int:proveedor_id>', methods=['POST'])
def api_calificar(proveedor_id):
    if 'user_id' not in session or session['user_type'] != 'usuario':
        return jsonify({"error": "No autorizado"}), 401

    datos = request.json
    puntuacion = datos.get('puntuacion')
    comentario = datos.get('comentario', '').strip() # <-- CAMPO NUEVO
    usuario_id = session['user_id']

    if not isinstance(puntuacion, int) or not (1 <= puntuacion <= 7):
        return jsonify({"error": "Puntuación debe ser un número entero entre 1 y 7"}), 400

    proveedor = Proveedor.query.get(proveedor_id)
    if not proveedor:
        return jsonify({"error": "Proveedor no encontrado"}), 404

    calificacion_existente = Calificacion.query.filter_by(
        usuario_id=usuario_id, 
        proveedor_id=proveedor_id
    ).first()

    try:
        if calificacion_existente:
            calificacion_existente.puntuacion = puntuacion
            calificacion_existente.comentario = comentario # <-- ACTUALIZADO
            calificacion_existente.timestamp = datetime.now(timezone.utc)
            db.session.commit()
            return jsonify({"mensaje": "Calificación actualizada"}), 200
        else:
            nueva_calificacion = Calificacion(
                usuario_id=usuario_id,
                proveedor_id=proveedor_id,
                puntuacion=puntuacion,
                comentario=comentario # <-- ACTUALIZADO
            )
            db.session.add(nueva_calificacion)
            db.session.commit()
            return jsonify({"mensaje": "Calificación enviada"}), 201
            
    except Exception as e:
        db.session.rollback()
        return jsonify({"error": str(e)}), 500

@app.route('/perfil/proveedor/<int:proveedor_id>')
def perfil_proveedor(proveedor_id):
    """Ruta que renderiza la PÁGINA de perfil (vacía)."""
    proveedor = Proveedor.query.get_or_404(proveedor_id)
    return render_template('perfil_proveedor.html', 
                             proveedor_id=proveedor.id, 
                             proveedor_nombre=proveedor.nombre_completo)

@app.route('/api/perfil/proveedor/<int:proveedor_id>')
def api_get_perfil_proveedor(proveedor_id):
    """API que entrega los DATOS del perfil (info, portafolio, ratings)."""
    proveedor = Proveedor.query.get_or_404(proveedor_id)
    
    calificaciones_db = db.session.query(
        Calificacion, Usuario.nombre_completo
    ).join(
        Usuario, Calificacion.usuario_id == Usuario.id
    ).filter(
        Calificacion.proveedor_id == proveedor_id
    ).order_by(
        Calificacion.timestamp.desc()
    ).all()

    calificaciones_json = []
    for calif, nombre_usuario in calificaciones_db:
        calificaciones_json.append({
            "puntuacion": calif.puntuacion,
            "comentario": calif.comentario,
            "nombre_usuario": nombre_usuario,
            "timestamp": calif.timestamp.strftime("%d/%m/%Y")
        })

    portafolio_db = Portafolio.query.filter_by(
        proveedor_id=proveedor_id
    ).order_by(Portafolio.timestamp.desc()).all()
    
    portafolio_json = [{
        "id": item.id,
        "imagen_url": item.imagen_url,
        "descripcion": item.descripcion
    } for item in portafolio_db]

    stats = db.session.query(
        func.avg(Calificacion.puntuacion).label('promedio'),
        func.count(Calificacion.id).label('total')
    ).filter(Calificacion.proveedor_id == proveedor_id).first()
    
    promedio = round(float(stats.promedio), 1) if stats.promedio else 0
    total = int(stats.total) if stats.total else 0
    
    perfil_data = {
        "nombre": proveedor.nombre_completo,
        "oficio": proveedor.oficio,
        "descripcion": proveedor.descripcion,
        "comuna": proveedor.comuna,
        "horario": proveedor.horario,
        "atiende_urgencias": proveedor.atiende_urgencias,
        "calif_promedio": promedio,
        "calif_total": total,
        "calificaciones": calificaciones_json,
        "portafolio": portafolio_json,
        "telefono": proveedor.telefono # Añadido teléfono al perfil
    }
    return jsonify(perfil_data)

@app.route('/api/portafolio/add', methods=['POST'])
def api_add_portafolio():
    """API para que el proveedor añada un item a su portafolio."""
    if 'user_id' not in session or session['user_type'] != 'proveedor':
        return jsonify({"error": "No autorizado"}), 401
    
    proveedor_id = session['user_id']
    datos = request.json
    imagen_url = datos.get('imagen_url')
    descripcion = datos.get('descripcion')

    if not imagen_url:
        return jsonify({"error": "La URL de la imagen es obligatoria"}), 400
    
    try:
        nuevo_item = Portafolio(
            proveedor_id=proveedor_id,
            imagen_url=imagen_url,
            descripcion=descripcion
        )
        db.session.add(nuevo_item)
        db.session.commit()
        return jsonify({
            "mensaje": "Trabajo añadido", 
            "item": {
                "id": nuevo_item.id,
                "imagen_url": nuevo_item.imagen_url,
                "descripcion": nuevo_item.descripcion
            }
        }), 201
    except Exception as e:
        db.session.rollback()
        return jsonify({"error": str(e)}), 500

@app.route('/api/portafolio/delete/<int:item_id>', methods=['DELETE'])
def api_delete_portafolio(item_id):
    """API para que el proveedor elimine un item de su portafolio."""
    if 'user_id' not in session or session['user_type'] != 'proveedor':
        return jsonify({"error": "No autorizado"}), 401
    
    proveedor_id = session['user_id']
    item = Portafolio.query.get_or_404(item_id)
    
    if item.proveedor_id != proveedor_id:
        return jsonify({"error": "No autorizado"}), 403
        
    try:
        db.session.delete(item)
        db.session.commit()
        return jsonify({"mensaje": "Trabajo eliminado"}), 200
    except Exception as e:
        db.session.rollback()
        return jsonify({"error": str(e)}), 500

# --- SOCKET.IO ---

@socketio.on("join")
def handle_join(data):
    conv_id = data.get("conv_id")
    if not conv_id:
        return emit("error", {"message": "conv_id requerido"})

    if 'user_id' not in session:
        return emit("error", {"message": "No autorizado"})

    conv = Conversacion.query.get(conv_id)
    if not conv:
        return emit("error", {"message": "Conversación no existe"})

    user_id = session['user_id']
    user_type = session['user_type']
    autorizado = (user_type == 'usuario' and conv.usuario_id == user_id) or \
                 (user_type == 'proveedor' and conv.proveedor_id == user_id)
    if not autorizado:
        return emit("error", {"message": "No autorizado"})

    room = f"chat_{conv_id}"
    join_room(room)
    print(f"[JOIN] user={user_id} tipo={user_type} -> room={room}")
    emit("joined", {"conv_id": conv_id})

@socketio.on("connect")
def on_connect():
    print("Usuario conectado al socket:", request.sid)

@socketio.on("disconnect")
def on_disconnect():
    print("Usuario desconectado del socket:", request.sid)

if __name__ == "__main__":
    socketio.run(app, host="127.0.0.1", port=5000, debug=True, use_reloader=False)