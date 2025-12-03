from flask import request, jsonify, render_template, session, redirect, url_for, abort
from sqlalchemy import func
from datetime import datetime, timezone
from flask_socketio import emit, join_room
import os
import time
from werkzeug.utils import secure_filename

# --- IMPORTACIONES NUEVAS PARA GEOLOCALIZACIÓN ---
from geopy.geocoders import Nominatim
from haversine import haversine, Unit

# Importamos la instancia de app, db, socketio y los modelos
from app import app, db, socketio, Usuario, Proveedor, Conversacion, Mensaje, Calificacion, Portafolio, Trabajo

# --- FUNCIONES HELPER ---

def obtener_coordenadas(direccion):
    """
    Recibe una dirección en texto, la consulta en OpenStreetMap
    y retorna (latitud, longitud). Si falla, retorna (None, None).
    """
    if not direccion:
        return None, None
    
    # Es importante poner un user_agent único para no ser bloqueado por Nominatim
    geolocator = Nominatim(user_agent="zerby_app_v2_client")
    try:
        # Añadimos ", Chile" para acotar la búsqueda
        location = geolocator.geocode(direccion + ", Chile", timeout=10)
        if location:
            return location.latitude, location.longitude
    except Exception as e:
        print(f"Error obteniendo coordenadas: {e}")
    
    return None, None

def _get_base_query_proveedores_con_calif():
    """Consulta base para obtener proveedores con su promedio de notas."""
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

def _serializar_proveedor(p, promedio, total, distancia_km=None):
    """Convierte objeto Proveedor a JSON, incluyendo distancia si existe."""
    data = {
        "proveedor_id": p.id,
        "nombre": p.nombre_completo,
        "oficio": p.oficio,
        "descripcion": p.descripcion,
        "telefono": p.telefono,
        "direccion": p.direccion, # Usamos direccion, no comuna
        "horario": p.horario,
        "atiende_urgencias": p.atiende_urgencias,
        "calif_promedio": round(float(promedio), 1) if promedio else 0,
        "calif_total": int(total) if total else 0,
        "lat": p.lat,
        "lon": p.lon
    }
    if distancia_km is not None:
        data["distancia_km"] = round(distancia_km, 2)
    return data

# --- RUTAS DE PÁGINAS ---

@app.route('/')
def index():
    return render_template('index.html')

@app.route('/login')
def login_page():
    if 'user_id' in session: return redirect(url_for('dashboard'))
    return render_template('login.html')

@app.route('/registro/usuario')
def registro_usuario_page():
    if 'user_id' in session: return redirect(url_for('dashboard'))
    return render_template('registro_usuario.html')

@app.route('/registro/proveedor')
def registro_proveedor_page():
    if 'user_id' in session: return redirect(url_for('dashboard'))
    return render_template('registro_proveedor.html')

@app.route('/dashboard')
def dashboard():
    if 'user_id' not in session: return redirect(url_for('login_page'))
    user_type = session.get('user_type')
    if user_type == 'usuario': return render_template('dashboard_usuario.html')
    elif user_type == 'proveedor': return render_template('dashboard_proveedor.html')
    else: return redirect(url_for('api_logout'))

# --- RUTAS DE AUTENTICACIÓN Y PERFIL ---

@app.route('/api/login', methods=['POST'])
def api_login():
    datos = request.json
    usuario = Usuario.query.filter_by(email=datos.get('email')).first()
    if usuario and usuario.check_password(datos.get('password')):
        session['user_id'] = usuario.id
        session['user_type'] = 'usuario'
        return jsonify({"mensaje": "Inicio de sesión exitoso"}), 200

    proveedor = Proveedor.query.filter_by(email=datos.get('email')).first()
    if proveedor and proveedor.check_password(datos.get('password')):
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
    if 'user_id' not in session: return jsonify({"error": "No autorizado"}), 401
    
    user_id = session['user_id']
    user_type = session['user_type']
    
    if user_type == 'usuario':
        user = Usuario.query.get(user_id)
        # Devolvemos direccion, lat y lon
        profile_data = {
            "id": user.id,
            "nombre": user.nombre_completo,
            "email": user.email,
            "tipo": user_type,
            "direccion": user.direccion,
            "lat": user.lat,
            "lon": user.lon
        }
    else:
        user = Proveedor.query.get(user_id)
        profile_data = {
            "id": user.id,
            "nombre": user.nombre_completo,
            "email": user.email,
            "tipo": user_type,
            "oficio": user.oficio,
            "direccion": user.direccion
        }
        
    return jsonify(profile_data)

# --- RUTAS DE REGISTRO CON GEOCODING ---

@app.route('/registrar/usuario', methods=['POST'])
def registrar_usuario():
    datos = request.json
    if Usuario.query.filter_by(email=datos['email']).first():
        return jsonify({"mensaje": "El email ya está registrado"}), 400

    # 1. Calcular Coordenadas
    lat, lon = None, None
    if 'direccion' in datos and datos['direccion']:
        lat, lon = obtener_coordenadas(datos['direccion'])

    nuevo_usuario = Usuario(
        nombre_completo=datos['nombre_completo'],
        email=datos['email'],
        telefono=datos.get('telefono'),
        direccion=datos.get('direccion'), # Guardamos dirección
        lat=lat, # Guardamos Lat
        lon=lon  # Guardamos Lon
    )
    nuevo_usuario.set_password(datos['password'])
    db.session.add(nuevo_usuario)
    db.session.commit()
    session['user_id'] = nuevo_usuario.id
    session['user_type'] = 'usuario'
    
    return jsonify({"mensaje": "Usuario registrado"}), 201

@app.route('/registrar/proveedor', methods=['POST'])
def registrar_proveedor():
    datos = request.json
    if Proveedor.query.filter_by(email=datos['email']).first():
        return jsonify({"mensaje": "El email ya está registrado"}), 400

    # 1. Calcular Coordenadas
    lat, lon = None, None
    if 'direccion' in datos and datos['direccion']:
        lat, lon = obtener_coordenadas(datos['direccion'])

    nuevo_proveedor = Proveedor(
        nombre_completo=datos['nombre_completo'],
        email=datos['email'],
        telefono=datos['telefono'],
        oficio=datos['oficio'],
        descripcion=datos.get('descripcion'),
        direccion=datos.get('direccion'), # Usamos direccion en vez de comuna
        horario=datos.get('horario'),
        atiende_urgencias=datos.get('atiende_urgencias', False),
        lat=lat,
        lon=lon
    )
    nuevo_proveedor.set_password(datos['password'])
    db.session.add(nuevo_proveedor)
    db.session.commit()
    session['user_id'] = nuevo_proveedor.id
    session['user_type'] = 'proveedor'
    
    return jsonify({"mensaje": "Proveedor registrado con éxito"}), 201

@app.route('/api/proveedor/actualizar_perfil', methods=['POST'])
def api_actualizar_proveedor():
    """Permite al proveedor actualizar su dirección y teléfono."""
    if 'user_id' not in session or session['user_type'] != 'proveedor':
        return jsonify({"error": "No autorizado"}), 401
    
    proveedor = Proveedor.query.get(session['user_id'])
    datos = request.json
    
    try:
        if 'telefono' in datos:
            proveedor.telefono = datos['telefono']
    
        if 'direccion' in datos:
            nueva_direccion = datos['direccion']
            if nueva_direccion != proveedor.direccion: # Solo si cambió
                lat, lon = obtener_coordenadas(nueva_direccion)
                proveedor.direccion = nueva_direccion
                proveedor.lat = lat
                proveedor.lon = lon
            
        db.session.commit()
        return jsonify({"mensaje": "Perfil actualizado correctamente"}), 200

    except Exception as e:
        db.session.rollback()
        return jsonify({"error": "Error al actualizar: " + str(e)}), 500

@app.route('/api/usuario/actualizar_perfil', methods=['POST'])
def api_actualizar_usuario():
    if 'user_id' not in session or session['user_type'] != 'usuario':
        return jsonify({"error": "No autorizado"}), 401
    
    user_id = session['user_id']
    usuario = Usuario.query.get(user_id)
    datos = request.json
    
    try:
        if 'telefono' in datos:
            usuario.telefono = datos['telefono']
        
        # Lógica de geolocalización al actualizar
        if 'direccion' in datos:
            nueva_direccion = datos['direccion']
            # Solo llamamos a la API de mapas si la dirección cambió
            if nueva_direccion != usuario.direccion:
                lat, lon = obtener_coordenadas(nueva_direccion)
                usuario.direccion = nueva_direccion
                usuario.lat = lat
                usuario.lon = lon
            
        db.session.commit()
        return jsonify({"mensaje": "Perfil actualizado correctamente"}), 200

    except Exception as e:
        db.session.rollback()
        return jsonify({"error": "Error al actualizar: " + str(e)}), 500

# --- RUTAS DE BÚSQUEDA GEOGRÁFICA (SISTEMA NUEVO) ---

@app.route('/api/proveedores/cercanos')
def api_proveedores_cercanos():
    """
    Algoritmo:
    1. Obtener lat/lon del usuario actual.
    2. Obtener todos los proveedores.
    3. Calcular distancia Haversine con cada uno.
    4. Ordenar y devolver los más cercanos.
    """
    if 'user_id' not in session or session['user_type'] != 'usuario':
        return jsonify({"error": "No autorizado"}), 401

    try:
        usuario = Usuario.query.get(session['user_id'])
        
        # Caso A: El usuario no tiene ubicación
        if not usuario.lat or not usuario.lon:
            # Devolvemos lista simple sin orden geográfico
            base_query = _get_base_query_proveedores_con_calif().limit(10).all()
            resultados = []
            for p, prom, total in base_query:
                resultados.append(_serializar_proveedor(p, prom, total, distancia_km=None))
            return jsonify(resultados)

        # Caso B: Usuario con ubicación -> Calcular distancias
        user_coords = (usuario.lat, usuario.lon)
        todos_proveedores = _get_base_query_proveedores_con_calif().all()
        
        lista_con_distancia = []
        for p, prom, total in todos_proveedores:
            # Solo calculamos si el proveedor también tiene coordenadas
            if p.lat and p.lon:
                prov_coords = (p.lat, p.lon)
                distancia = haversine(user_coords, prov_coords) # Devuelve KM por defecto
                lista_con_distancia.append({
                    "obj": p, "prom": prom, "total": total, "dist": distancia
                })
        
        # Ordenamos por distancia (menor a mayor)
        lista_con_distancia.sort(key=lambda x: x['dist'])
        
        # Tomamos los 20 más cercanos
        top_cercanos = lista_con_distancia[:20]
        
        json_response = []
        for item in top_cercanos:
            json_response.append(_serializar_proveedor(
                item['obj'], item['prom'], item['total'], item['dist']
            ))
            
        return jsonify(json_response)

    except Exception as e:
        print(f"!!! ERROR en /api/proveedores/cercanos: {e}") 
        return jsonify({"error": str(e)}), 500


@app.route('/api/buscar')
def api_buscar():
    if 'user_id' not in session or session['user_type'] != 'usuario':
        return jsonify({"error": "No autorizado"}), 401

    query = request.args.get('q', '')
    
    try:
        base_query = _get_base_query_proveedores_con_calif() 
        
        if query:
            termino_busqueda = f"%{query}%"
            # Buscamos en Oficio, Descripción y ahora DIRECCIÓN
            base_query = base_query.filter(
                (Proveedor.oficio.ilike(termino_busqueda)) |
                (Proveedor.descripcion.ilike(termino_busqueda)) |
                (Proveedor.direccion.ilike(termino_busqueda))
            )

        proveedores_con_calif = base_query.all()
        
        # Serializamos (en este endpoint de búsqueda por texto no calculamos distancia obligatoriamente)
        lista_proveedores = []
        for p, prom, total in proveedores_con_calif:
            lista_proveedores.append(_serializar_proveedor(p, prom, total))
            
        return jsonify(lista_proveedores)
    
    except Exception as e:
        print(f"!!! ERROR en /api/buscar: {e}") 
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
    if 'user_id' not in session: return redirect(url_for('login_page'))
    return render_template('bandeja_entrada.html')

@app.route('/conversacion/<int:conv_id>')
def vista_conversacion(conv_id):
    if 'user_id' not in session: return redirect(url_for('login_page'))
    conv = Conversacion.query.get_or_404(conv_id)
    user_id = session['user_id']
    user_type = session['user_type']
    if (user_type == 'usuario' and conv.usuario_id != user_id) or \
       (user_type == 'proveedor' and conv.proveedor_id != user_id):
        return abort(403) 
    return render_template('conversacion.html', conv_id=conv_id, user_tipo_actual=user_type)

@app.route('/api/conversaciones')
def api_get_conversaciones():
    if 'user_id' not in session: return jsonify({"error": "No autorizado"}), 401
    user_id = session['user_id']
    user_type = session['user_type']
    lista_convos = []
    if user_type == 'usuario':
        conversaciones = db.session.query(Conversacion, Proveedor.nombre_completo, Proveedor.oficio)\
            .join(Proveedor, Conversacion.proveedor_id == Proveedor.id)\
            .filter(Conversacion.usuario_id == user_id).all()
        for conv, nombre, oficio in conversaciones:
            lista_convos.append({"id": conv.id, "otro_participante": nombre, "detalle": oficio})
    else:
        conversaciones = db.session.query(Conversacion, Usuario.nombre_completo)\
            .join(Usuario, Conversacion.usuario_id == Usuario.id)\
            .filter(Conversacion.proveedor_id == user_id).all()
        for conv, nombre in conversaciones:
             lista_convos.append({"id": conv.id, "otro_participante": nombre, "detalle": "Cliente"})
    return jsonify(lista_convos)

# En routes.py

@app.route('/api/conversacion/<int:conv_id>/detalles')
def api_get_detalles_conv(conv_id):
    if 'user_id' not in session: return jsonify({"error": "No autorizado"}), 401
    
    conv = Conversacion.query.get_or_404(conv_id)
    user_id = session['user_id']
    user_type = session['user_type']
    
    # Verificación de seguridad
    if (user_type == 'usuario' and conv.usuario_id != user_id) or \
       (user_type == 'proveedor' and conv.proveedor_id != user_id):
        return jsonify({"error": "No autorizado"}), 403

    otro_nombre = conv.proveedor.nombre_completo if user_type == 'usuario' else conv.usuario.nombre_completo
    
    lista_historial = []

    # 1. Obtener MENSAJES de texto
    mensajes_db = Mensaje.query.filter_by(conversacion_id=conv_id).all()
    for msg in mensajes_db:
        lista_historial.append({
            "tipo": "mensaje",
            "contenido": msg.contenido,
            "remitente_tipo": msg.remitente_tipo,
            "timestamp_dt": msg.timestamp,
            "timestamp": msg.timestamp.strftime("%d/%m %H:%M") 
        })

    # 2. Obtener TRABAJOS (Cotizaciones) - AQUÍ ESTABA EL ERROR
    trabajos_db = Trabajo.query.filter_by(conversacion_id=conv_id).all()
    
    for job in trabajos_db:
        # Definimos el subtipo para que el JS sepa qué color usar
        subtipo = "cotizacion"
        if job.estado == 'PAGADO': subtipo = "pago_confirmado"
        elif job.estado == 'FINALIZADO': subtipo = "trabajo_finalizado"

        lista_historial.append({
            "tipo": "sistema_trabajo",
            "trabajo_id": job.id,
            "estado": job.estado,
            "subtipo": subtipo,
            # --- DATOS CLAVE QUE FALTABAN ---
            "monto": job.monto,          
            "descripcion": job.descripcion,
            "mensaje": job.descripcion, # Fallback
            # -------------------------------
            "timestamp_dt": job.timestamp_creacion,
            "timestamp": job.timestamp_creacion.strftime("%d/%m %H:%M")
        })

    # 3. Ordenar por fecha (mezclando mensajes y trabajos)
    lista_historial.sort(key=lambda x: x['timestamp_dt'])

    # 4. Limpieza final (borrar el objeto datetime que no es serializable)
    for item in lista_historial:
        del item['timestamp_dt']
    
    return jsonify({
        "otro_nombre": otro_nombre,
        "historial": lista_historial,
        "proveedor_id": conv.proveedor_id if user_type == 'usuario' else None
    })

@app.route('/api/conversacion/<int:conv_id>/enviar', methods=['POST'])
def api_enviar_mensaje(conv_id):
    if 'user_id' not in session: return jsonify({"error": "No autorizado"}), 401
    conv = Conversacion.query.get_or_404(conv_id)
    user_id = session['user_id']
    user_type = session['user_type']
    datos = request.json
    autorizado = (user_type == 'usuario' and conv.usuario_id == user_id) or \
                 (user_type == 'proveedor' and conv.proveedor_id == user_id)
    if not autorizado: return jsonify({"error": "No autorizado"}), 403
    contenido = datos.get('contenido', '').strip()
    if not contenido: return jsonify({"error": "Mensaje vacío"}), 400
    try:
        nuevo_mensaje = Mensaje(conversacion_id=conv_id, remitente_id=user_id, remitente_tipo=user_type, contenido=contenido)
        db.session.add(nuevo_mensaje)
        db.session.commit()
        payload = {
            "contenido": nuevo_mensaje.contenido,
            "remitente_tipo": nuevo_mensaje.remitente_tipo,
            "timestamp": nuevo_mensaje.timestamp.strftime("%d/%m %H:%M")
        }
        room = f"chat_{conv_id}"
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
    comentario = datos.get('comentario', '').strip() 
    usuario_id = session['user_id']

    # CORRECCIÓN: Cambiado de 7 a 5
    if not isinstance(puntuacion, int) or not (1 <= puntuacion <= 5):
        return jsonify({"error": "Puntuación debe ser un número entero entre 1 y 5"}), 400
    proveedor = Proveedor.query.get(proveedor_id)
    if not proveedor: return jsonify({"error": "Proveedor no encontrado"}), 404
    calificacion_existente = Calificacion.query.filter_by(usuario_id=usuario_id, proveedor_id=proveedor_id).first()
    try:
        if calificacion_existente:
            calificacion_existente.puntuacion = puntuacion
            calificacion_existente.comentario = comentario
            calificacion_existente.timestamp = datetime.now(timezone.utc)
            db.session.commit()
            return jsonify({"mensaje": "Calificación actualizada"}), 200
        else:
            nueva_calificacion = Calificacion(usuario_id=usuario_id, proveedor_id=proveedor_id, puntuacion=puntuacion, comentario=comentario)
            db.session.add(nueva_calificacion)
            db.session.commit()
            return jsonify({"mensaje": "Calificación enviada"}), 201
    except Exception as e:
        db.session.rollback()
        return jsonify({"error": str(e)}), 500

@app.route('/perfil/usuario/<int:user_id>')
def perfil_usuario(user_id):
    usuario = Usuario.query.get_or_404(user_id)
    if 'user_id' not in session or session['user_id'] != user_id:
         pass 
    return render_template('perfil_usuario.html', usuario=usuario)



@app.route('/perfil/proveedor/<int:proveedor_id>')
def perfil_proveedor(proveedor_id):
    proveedor = Proveedor.query.get_or_404(proveedor_id)
    return render_template('perfil_proveedor.html', proveedor_id=proveedor.id, proveedor_nombre=proveedor.nombre_completo)

@app.route('/api/perfil/proveedor/<int:proveedor_id>')
def api_get_perfil_proveedor(proveedor_id):
    proveedor = Proveedor.query.get_or_404(proveedor_id)
    calificaciones_db = db.session.query(Calificacion, Usuario.nombre_completo)\
        .join(Usuario, Calificacion.usuario_id == Usuario.id)\
        .filter(Calificacion.proveedor_id == proveedor_id).order_by(Calificacion.timestamp.desc()).all()
    calificaciones_json = [{
        "puntuacion": c.puntuacion,
        "comentario": c.comentario,
        "nombre_usuario": u_nombre,
        "timestamp": c.timestamp.strftime("%d/%m/%Y")
    } for c, u_nombre in calificaciones_db]
    portafolio_db = Portafolio.query.filter_by(proveedor_id=proveedor_id).order_by(Portafolio.timestamp.desc()).all()
    portafolio_json = [{"id": i.id, "imagen_url": i.imagen_url, "descripcion": i.descripcion} for i in portafolio_db]
    stats = db.session.query(func.avg(Calificacion.puntuacion).label('promedio'), func.count(Calificacion.id).label('total'))\
        .filter(Calificacion.proveedor_id == proveedor_id).first()
    perfil_data = {
        "nombre": proveedor.nombre_completo,
        "oficio": proveedor.oficio,
        "descripcion": proveedor.descripcion,
        "direccion": proveedor.direccion, # Usamos direccion
        "horario": proveedor.horario,
        "atiende_urgencias": proveedor.atiende_urgencias,
        "calif_promedio": round(float(stats.promedio), 1) if stats.promedio else 0,
        "calif_total": int(stats.total) if stats.total else 0,
        "calificaciones": calificaciones_json,
        "portafolio": portafolio_json,
        "telefono": proveedor.telefono
    }
    return jsonify(perfil_data)

# --- RUTAS DE PORTAFOLIO (CON UPLOAD DE IMAGEN) ---

def allowed_file(filename):
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in {'png', 'jpg', 'jpeg', 'gif'}

@app.route('/api/trabajo/crear', methods=['POST'])
def api_crear_trabajo():
    """El PROVEEDOR crea una cotización."""
    if 'user_id' not in session or session['user_type'] != 'proveedor':
        return jsonify({"error": "No autorizado"}), 401
    
    datos = request.json
    conv_id = datos.get('conversacion_id')
    monto = datos.get('monto')
    descripcion = datos.get('descripcion')

    if not conv_id or not monto or not descripcion:
        return jsonify({"error": "Faltan datos"}), 400

    # Verificamos que la conversación sea de este proveedor
    conv = Conversacion.query.get_or_404(conv_id)
    if conv.proveedor_id != session['user_id']:
        return jsonify({"error": "No autorizado"}), 403

    try:
        nuevo_trabajo = Trabajo(
            conversacion_id=conv_id,
            proveedor_id=session['user_id'],
            usuario_id=conv.usuario_id,
            monto=monto,
            descripcion=descripcion,
            estado='COTIZADO'
        )
        db.session.add(nuevo_trabajo)
        db.session.commit()

        # Notificar al chat en tiempo real
        payload = {
            "tipo": "sistema_trabajo",
            "subtipo": "cotizacion",
            "trabajo_id": nuevo_trabajo.id,
            "monto": monto,
            "descripcion": descripcion,
            "estado": "COTIZADO",
            "mensaje": f"Se ha generado una cotización por ${monto}"
        }
        socketio.emit("receive_message", payload, room=f"chat_{conv_id}")

        return jsonify({"mensaje": "Cotización enviada", "trabajo_id": nuevo_trabajo.id}), 201

    except Exception as e:
        db.session.rollback()
        return jsonify({"error": str(e)}), 500


@app.route('/pago/<int:trabajo_id>')
def pagina_pago(trabajo_id):
    """Renderiza la vista de pago falso."""
    if 'user_id' not in session: return redirect(url_for('login_page'))
    
    trabajo = Trabajo.query.get_or_404(trabajo_id)
    
    # Seguridad: Solo el dueño del trabajo (cliente) puede ver la pagina de pago
    if session['user_type'] == 'usuario' and trabajo.usuario_id != session['user_id']:
         return abort(403)

    return render_template('pago.html', trabajo=trabajo)


@app.route('/api/trabajo/pagar/<int:trabajo_id>', methods=['POST'])
def api_pagar_trabajo(trabajo_id):
    """El CLIENTE paga la cotización (cambia estado a PAGADO)."""
    if 'user_id' not in session or session['user_type'] != 'usuario':
        return jsonify({"error": "No autorizado"}), 401

    trabajo = Trabajo.query.get_or_404(trabajo_id)
    
    if trabajo.usuario_id != session['user_id']:
        return jsonify({"error": "No autorizado"}), 403

    if trabajo.estado != 'COTIZADO':
        return jsonify({"error": "Este trabajo ya fue pagado o finalizado"}), 400

    try:
        trabajo.estado = 'PAGADO'
        trabajo.timestamp_pago = datetime.now(timezone.utc)
        db.session.commit()

        # CORRECCIÓN: Enviamos monto y descripción para que el frontend no muestre $0
        payload = {
            "tipo": "sistema_trabajo",
            "subtipo": "pago_confirmado",
            "trabajo_id": trabajo.id,
            "monto": trabajo.monto,            # <--- AGREGADO
            "descripcion": trabajo.descripcion, # <--- AGREGADO
            "estado": "PAGADO",
            "mensaje": "¡Pago confirmado! El proveedor puede comenzar el trabajo."
        }
        socketio.emit("receive_message", payload, room=f"chat_{trabajo.conversacion_id}")

        return jsonify({"mensaje": "Pago exitoso"}), 200

    except Exception as e:
        db.session.rollback()
        return jsonify({"error": str(e)}), 500


@app.route('/api/trabajo/terminar/<int:trabajo_id>', methods=['POST'])
def api_terminar_trabajo(trabajo_id):
    """El PROVEEDOR marca el trabajo como finalizado."""
    if 'user_id' not in session or session['user_type'] != 'proveedor':
        return jsonify({"error": "No autorizado"}), 401

    trabajo = Trabajo.query.get_or_404(trabajo_id)
    
    if trabajo.proveedor_id != session['user_id']:
        return jsonify({"error": "No autorizado"}), 403

    if trabajo.estado != 'PAGADO':
         return jsonify({"error": "El trabajo debe estar pagado para finalizarlo"}), 400

    try:
        trabajo.estado = 'FINALIZADO'
        trabajo.timestamp_fin = datetime.now(timezone.utc)
        db.session.commit()

        # CORRECCIÓN: Enviamos monto y descripción
        payload = {
            "tipo": "sistema_trabajo",
            "subtipo": "trabajo_finalizado",
            "trabajo_id": trabajo.id,
            "monto": trabajo.monto,            # <--- AGREGADO
            "descripcion": trabajo.descripcion, # <--- AGREGADO
            "estado": "FINALIZADO",
            "mensaje": "Trabajo finalizado. ¡Por favor califica el servicio!"
        }
        socketio.emit("receive_message", payload, room=f"chat_{trabajo.conversacion_id}")

        return jsonify({"mensaje": "Trabajo finalizado"}), 200

    except Exception as e:
        db.session.rollback()
        return jsonify({"error": str(e)}), 500
    
@app.route('/api/portafolio/add', methods=['POST'])
def api_add_portafolio():
    if 'user_id' not in session or session['user_type'] != 'proveedor':
        return jsonify({"error": "No autorizado"}), 401
    
    if 'imagen' not in request.files:
        return jsonify({"error": "No se encontró el archivo de imagen"}), 400
    
    file = request.files['imagen']
    descripcion = request.form.get('descripcion', '') 

    if file.filename == '':
        return jsonify({"error": "Nombre de archivo vacío"}), 400

    if file and allowed_file(file.filename):
        try:
            filename = secure_filename(file.filename)
            unique_filename = f"{int(time.time())}_{filename}"
            filepath = os.path.join(app.config['UPLOAD_FOLDER'], unique_filename)
            file.save(filepath)
            
            imagen_url = url_for('static', filename=f'uploads/{unique_filename}')
            proveedor_id = session['user_id']
            nuevo_item = Portafolio(proveedor_id=proveedor_id, imagen_url=imagen_url, descripcion=descripcion)
            db.session.add(nuevo_item)
            db.session.commit()

            return jsonify({
                "mensaje": "Trabajo subido con éxito", 
                "item": {"id": nuevo_item.id, "imagen_url": nuevo_item.imagen_url, "descripcion": nuevo_item.descripcion}
            }), 201

        except Exception as e:
            db.session.rollback()
            print(f"Error subiendo imagen: {e}")
            return jsonify({"error": "Error al guardar la imagen"}), 500
    else:
        return jsonify({"error": "Tipo de archivo no permitido"}), 400

@app.route('/api/portafolio/delete/<int:item_id>', methods=['DELETE'])
def api_delete_portafolio(item_id):
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

# --- SOCKET.IO HANDLERS ---

@socketio.on("join")
def handle_join(data):
    conv_id = data.get("conv_id")
    if not conv_id: return emit("error", {"message": "conv_id requerido"})
    if 'user_id' not in session: return emit("error", {"message": "No autorizado"})
    conv = Conversacion.query.get(conv_id)
    if not conv: return emit("error", {"message": "Conversación no existe"})
    user_id = session['user_id']
    user_type = session['user_type']
    autorizado = (user_type == 'usuario' and conv.usuario_id == user_id) or \
                 (user_type == 'proveedor' and conv.proveedor_id == user_id)
    if not autorizado: return emit("error", {"message": "No autorizado"})
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