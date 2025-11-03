from flask import Flask, request, jsonify, render_template, session, redirect, url_for
from flask_sqlalchemy import SQLAlchemy
from werkzeug.security import generate_password_hash, check_password_hash
import os
from datetime import datetime, timezone
from flask import Flask, request, jsonify, render_template, session, redirect, url_for, abort

app = Flask(__name__)
basedir = os.path.abspath(os.path.dirname(__file__))
app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///' + os.path.join(basedir, 'database.db')
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
app.config['SECRET_KEY'] = 'mi-clave-secreta-12345' 

db = SQLAlchemy(app)


class Usuario(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    nombre_completo = db.Column(db.String(100), nullable=False)
    email = db.Column(db.String(100), unique=True, nullable=False)
    password_hash = db.Column(db.String(128), nullable=False)
    telefono = db.Column(db.String(15))

    def set_password(self, password):
        self.password_hash = generate_password_hash(password)

    def check_password(self, password):
        return check_password_hash(self.password_hash, password)

class Proveedor(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    nombre_completo = db.Column(db.String(100), nullable=False)
    email = db.Column(db.String(100), unique=True, nullable=False)
    password_hash = db.Column(db.String(128), nullable=False)
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
    else:
        user = Proveedor.query.get(user_id)
        
    return jsonify({
        "nombre": user.nombre_completo,
        "email": user.email,
        "tipo": user_type
    })


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

@app.route('/api/proveedores/cercanos')
def api_proveedores_cercanos():
    if 'user_id' not in session or session['user_type'] != 'usuario':
        return jsonify({"error": "No autorizado"}), 401

    try:
        proveedores = Proveedor.query.limit(10).all()
        lista_proveedores = []
        for p in proveedores:
            lista_proveedores.append({
                "proveedor_id": p.id,
                "nombre": p.nombre_completo,
                "oficio": p.oficio,
                "descripcion": p.descripcion,
                "telefono": p.telefono,
                "comuna": p.comuna,
                "horario": p.horario,
                "atiende_urgencias": p.atiende_urgencias
            })

        return jsonify(lista_proveedores)

    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route('/api/buscar')
def api_buscar():
    if 'user_id' not in session or session['user_type'] != 'usuario':
        return jsonify({"error": "No autorizado"}), 401

    query = request.args.get('q', '')
    comuna = request.args.get('comuna', '')
    
    try:
        base_query = Proveedor.query
        if query:
            termino_busqueda = f"%{query}%"
            base_query = base_query.filter(
                (Proveedor.oficio.ilike(termino_busqueda)) |
                (Proveedor.descripcion.ilike(termino_busqueda))
            )

        if comuna and comuna.lower() != 'todas':
            comuna_busqueda = f"%{comuna}%" 
            base_query = base_query.filter(Proveedor.comuna.ilike(comuna_busqueda))

        proveedores = base_query.all()
        lista_proveedores = []
        for p in proveedores:
            lista_proveedores.append({
                "proveedor_id": p.id,
                "nombre": p.nombre_completo,
                "oficio": p.oficio,
                "descripcion": p.descripcion,
                "telefono": p.telefono,
                "comuna": p.comuna,
                "horario": p.horario,
                "atiende_urgencias": p.atiende_urgencias
            })
            
        return jsonify(lista_proveedores)
    
    except Exception as e:
        return jsonify({"error": str(e)}), 500
    
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
        
# --- 5. Rutas de PÁGINAS (Mensajería) ---

@app.route('/bandeja_entrada')
def bandeja_entrada():
    if 'user_id' not in session:
        return redirect(url_for('login_page'))
    # Esta página cargará los chats usando JavaScript
    return render_template('bandeja_entrada.html')

@app.route('/conversacion/<int:conv_id>')
def vista_conversacion(conv_id):
    if 'user_id' not in session:
        return redirect(url_for('login_page'))
    
    # 1. Verificar que el chat existe
    conv = Conversacion.query.get_or_404(conv_id)
    user_id = session['user_id']
    user_type = session['user_type']

    # 2. Verificar que el usuario actual es parte de este chat
    if (user_type == 'usuario' and conv.usuario_id != user_id) or \
       (user_type == 'proveedor' and conv.proveedor_id != user_id):
        return abort(403) # Error 403: Prohibido

    # 3. Enviar a la plantilla el ID del chat y el tipo de usuario
    return render_template('conversacion.html', 
                           conv_id=conv_id, 
                           user_tipo_actual=user_type)


# --- 6. Rutas de API (Mensajería) ---

@app.route('/api/conversaciones')
def api_get_conversaciones():
    if 'user_id' not in session:
        return jsonify({"error": "No autorizado"}), 401
    
    user_id = session['user_id']
    user_type = session['user_type']
    lista_convos = []
    
    if user_type == 'usuario':
        # Cliente: Busca sus chats y el nombre del PROVEEDOR
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
        # Proveedor: Busca sus chats y el nombre del CLIENTE
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
            # Formateamos la hora para que sea legible
            "timestamp": msg.timestamp.strftime("%d/%m %H:%M") 
        })
    
    return jsonify({
        "otro_nombre": otro_nombre,
        "mensajes": mensajes_json
    })

@app.route('/api/conversacion/<int:conv_id>/enviar', methods=['POST'])
def api_enviar_mensaje(conv_id):
    if 'user_id' not in session: return jsonify({"error": "No autorizado"}), 401
    
    conv = Conversacion.query.get_or_404(conv_id)
    user_id = session['user_id']
    user_type = session['user_type']
    datos = request.json

    # Seguridad
    if (user_type == 'usuario' and conv.usuario_id != user_id) or \
       (user_type == 'proveedor' and conv.proveedor_id != user_id):
        return jsonify({"error": "No autorizado"}), 403
    
    if 'contenido' not in datos or not datos['contenido']:
        return jsonify({"error": "Mensaje vacío"}), 400

    try:
        nuevo_mensaje = Mensaje(
            conversacion_id=conv_id,
            remitente_id=user_id,
            remitente_tipo=user_type,
            contenido=datos['contenido']
        )
        db.session.add(nuevo_mensaje)
        db.session.commit()
        return jsonify({"mensaje": "Enviado"}), 201
    except Exception as e:
        db.session.rollback()
        return jsonify({"error": str(e)}), 500

if __name__ == '__main__':
    with app.app_context():
        db.create_all()
    app.run(debug=True)