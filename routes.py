from flask import request, jsonify, render_template, session, redirect, url_for, abort
from sqlalchemy import func
from datetime import datetime, timezone
from flask_socketio import emit, join_room
import os
import time
from werkzeug.utils import secure_filename
import random

# --- IMPORTACIONES NUEVAS PARA GEOLOCALIZACIÓN ---
from geopy.geocoders import Nominatim
from haversine import haversine, Unit

geolocator = Nominatim(user_agent="zerby_app_v2_client_autocomplete")

# Importamos la instancia de app, db, socketio y los modelos
from app import app, db, socketio, Usuario, Proveedor, Conversacion, Mensaje, Calificacion, Portafolio, SolicitudServicio


def get_or_create_conversacion(usuario_id, proveedor_id):
    """
    Devuelve una conversación existente entre usuario y proveedor,
    o la crea si no existe.
    """
    conv = Conversacion.query.filter_by(
        usuario_id=usuario_id,
        proveedor_id=proveedor_id
    ).first()

    if conv:
        return conv

    conv = Conversacion(
        usuario_id=usuario_id,
        proveedor_id=proveedor_id
    )
    db.session.add(conv)
    db.session.commit()
    return conv


# --- FUNCIONES HELPER ---

def obtener_coordenadas(direccion):
    """
    Recibe una dirección en texto, la consulta en OpenStreetMap
    y retorna (latitud, longitud). Si falla, retorna (None, None).
    """
    if not direccion:
        return None, None
    
    # Es importante poner un user_agent único para no ser bloqueado por Nominatim
    try:
        # Añadimos ", Chile" para acotar la búsqueda
        location = geolocator.geocode(direccion + ", Chile", timeout=10)
        if location:
            return location.latitude, location.longitude
    except Exception as e:
        print(f"Error obteniendo coordenadas: {e}")
    
    return None, None

@app.route('/api/geocode/search')
def api_geocode_search():
    """
    Devuelve sugerencias de direcciones usando Nominatim (OpenStreetMap).
    Recibe: ?q=texto
    Responde: lista de { display_name, lat, lon }
    """
    query = request.args.get('q', '').strip()
    if not query:
        return jsonify([])

    try:
        # limit=5 para no abusar del servicio
        locations = geolocator.geocode(
            query + ", Chile",
            exactly_one=False,
            limit=5,
            addressdetails=True,
            timeout=10
        )
    except Exception as e:
        print(f"Error en api_geocode_search: {e}")
        return jsonify([])

    results = []
    if locations:
        for loc in locations:
            results.append({
                "display_name": loc.address,
                "lat": loc.latitude,
                "lon": loc.longitude
            })

    return jsonify(results)


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
    """Convierte objeto Proveedor a JSON, incluyendo distancia e imagen de portada si existe."""

    imagen_portada = None
    try:
        # p.portafolios es la relación definida en el modelo Portafolio
        # Nos aseguramos de que exista y tenga al menos un elemento
        if hasattr(p, "portafolios"):
            lista = list(p.portafolios)  # forzamos a lista por si es InstrumentedList
            if lista:
                # Puedes elegir: primero o más reciente
                # 1) Primero:
                # imagen_portada = lista[0].imagen_url

                # 2) Más reciente por timestamp (recomendado):
                ultimo_trabajo = max(
                    lista,
                    key=lambda x: x.timestamp or datetime.min
                )
                imagen_portada = ultimo_trabajo.imagen_url

    except Exception as e:
        print(f"[WARN] Error calculando imagen_portada para proveedor {p.id}: {e}")
        imagen_portada = None

    data = {
        "proveedor_id": p.id,
        "nombre": p.nombre_completo,
        "oficio": p.oficio,
        "descripcion": p.descripcion,
        "telefono": p.telefono,
        "direccion": p.direccion,  # Usamos direccion, no comuna
        "horario": p.horario,
        "atiende_urgencias": p.atiende_urgencias,
        "calif_promedio": round(float(promedio), 1) if promedio else 0,
        "calif_total": int(total) if total else 0,
        "lat": p.lat,
        "lon": p.lon,
        "imagen_portada": imagen_portada,
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

    # Si el front envía lat/lon, las usamos directamente
    lat_str = datos.get('lat')
    lon_str = datos.get('lon')

    if lat_str and lon_str:
        try:
            lat = float(lat_str)
            lon = float(lon_str)
        except ValueError:
            lat, lon = None, None

    # Si no llegaron o son inválidas, usamos geocodificación por dirección como antes
    if (lat is None or lon is None) and datos.get('direccion'):
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

    # Si el front envía lat/lon (desde el autocomplete), las usamos directo
    lat_str = datos.get('lat')
    lon_str = datos.get('lon')

    if lat_str and lon_str:
        try:
            lat = float(lat_str)
            lon = float(lon_str)
        except ValueError:
            lat, lon = None, None

    # Si no llegaron o son inválidas, usamos geocodificación por dirección como antes
    if (lat is None or lon is None) and datos.get('direccion'):
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
    Si algo falla, devolvemos igualmente una lista simple de proveedores sin distancia.
    """
    if 'user_id' not in session or session['user_type'] != 'usuario':
        return jsonify({"error": "No autorizado"}), 401

    try:
        usuario = Usuario.query.get(session['user_id'])
        if not usuario:
            raise ValueError("Usuario no encontrado en la base de datos")

        # === CASO A: Usuario SIN coordenadas -> devolvemos lista simple ===
        if usuario.lat is None or usuario.lon is None:
            print("[INFO] Usuario sin lat/lon, devolviendo lista simple de proveedores.")
            base_query = _get_base_query_proveedores_con_calif().limit(20).all()
            resultados = [
                _serializar_proveedor(p, prom, total, distancia_km=None)
                for p, prom, total in base_query
            ]
            return jsonify(resultados), 200

        # === CASO B: Usuario CON coordenadas -> calculamos distancias ===
        try:
            user_coords = (float(usuario.lat), float(usuario.lon))
        except Exception as e:
            print(f"[WARN] Lat/Lon de usuario inválidas: {usuario.lat}, {usuario.lon} -> {e}")
            # fallback a lista simple
            base_query = _get_base_query_proveedores_con_calif().limit(20).all()
            resultados = [
                _serializar_proveedor(p, prom, total, distancia_km=None)
                for p, prom, total in base_query
            ]
            return jsonify(resultados), 200

        todos_proveedores = _get_base_query_proveedores_con_calif().all()

        lista_con_distancia = []
        for p, prom, total in todos_proveedores:
            try:
                if p.lat is None or p.lon is None:
                    continue
                prov_coords = (float(p.lat), float(p.lon))
                distancia = haversine(user_coords, prov_coords)  # KM por defecto
                lista_con_distancia.append({
                    "obj": p,
                    "prom": prom,
                    "total": total,
                    "dist": distancia
                })
            except Exception as e:
                print(f"[WARN] Error calculando distancia para proveedor {p.id}: {e}")
                # Lo saltamos, pero no rompemos todo el endpoint
                continue

        # Ordenamos por distancia
        lista_con_distancia.sort(key=lambda x: x['dist'])

        # Tomamos los 20 más cercanos
        top_cercanos = lista_con_distancia[:20]

        json_response = [
            _serializar_proveedor(item['obj'], item['prom'], item['total'], item['dist'])
            for item in top_cercanos
        ]
        return jsonify(json_response), 200

    except Exception as e:
        # FALLBACK GLOBAL: si algo muy raro pasa, igual devolvemos proveedores sin distancia
        print(f"!!! ERROR en /api/proveedores/cercanos (usando fallback): {e}")
        try:
            base_query = _get_base_query_proveedores_con_calif().limit(20).all()
            resultados = [
                _serializar_proveedor(p, prom, total, distancia_km=None)
                for p, prom, total in base_query
            ]
            return jsonify(resultados), 200
        except Exception as e2:
            print(f"!!! ERROR también en fallback de /api/proveedores/cercanos: {e2}")
            return jsonify({"error": "Error interno al obtener proveedores"}), 500


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

    # ✅ Verificar que haya al menos una solicitud aceptada/pagada/completada
    estados_permitidos = ("aceptada", "pagado", "completado")

    tiene_solicitud_valida = SolicitudServicio.query.filter(
        SolicitudServicio.usuario_id == cliente_id,
        SolicitudServicio.proveedor_id == proveedor_id,
        SolicitudServicio.estado.in_(estados_permitidos)
    ).first()

    if not tiene_solicitud_valida:
        return jsonify({
            "error": "El chat solo se habilita cuando el proveedor acepta tu solicitud."
        }), 403

    try:
        conv = get_or_create_conversacion(cliente_id, proveedor_id)
        return jsonify({
            "mensaje": "Conversación habilitada",
            "conversacion_id": conv.id
        }), 200
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
    mensajes_json = [{
        "contenido": msg.contenido,
        "remitente_tipo": msg.remitente_tipo,
        "timestamp": msg.timestamp.strftime("%d/%m %H:%M") 
    } for msg in mensajes_db]
    return jsonify({
        "otro_nombre": otro_nombre,
        "mensajes": mensajes_json,
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
    if not isinstance(puntuacion, int) or not (1 <= puntuacion <= 7):
        return jsonify({"error": "Puntuación debe ser un número entero entre 1 y 7"}), 400
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

@app.route('/api/proveedores/<int:proveedor_id>/solicitudes', methods=['POST'])
def api_crear_solicitud(proveedor_id):
    # Solo usuarios tipo "usuario" pueden enviar solicitudes
    if 'user_id' not in session or session.get('user_type') != 'usuario':
        return jsonify({"error": "No autorizado"}), 401
    
    datos = request.json or {}
    usuario_id = session['user_id']

    try:
        fecha_str = datos.get('fecha')
        hora_ini_str = datos.get('hora_inicio')
        hora_fin_str = datos.get('hora_fin')
        descripcion = datos.get('descripcion', '').strip()

        if not (fecha_str and hora_ini_str and hora_fin_str):
            return jsonify({"error": "Faltan campos obligatorios"}), 400
        
        fecha = datetime.strptime(fecha_str, "%Y-%m-%d").date()
        hora_inicio = datetime.strptime(hora_ini_str, "%H:%M").time()
        hora_fin = datetime.strptime(hora_fin_str, "%H:%M").time()

        if hora_fin <= hora_inicio:
            return jsonify({"error": "La hora de término debe ser mayor a la de inicio"}), 400

        proveedor = Proveedor.query.get(proveedor_id)
        if not proveedor:
            return jsonify({"error": "Proveedor no encontrado"}), 404

        # 1) Crear solicitud (queda en estado "pendiente")
        solicitud = SolicitudServicio(
            usuario_id=usuario_id,
            proveedor_id=proveedor_id,
            fecha=fecha,
            hora_inicio=hora_inicio,
            hora_fin=hora_fin,
            descripcion=descripcion,
            estado="pendiente"
        )
        db.session.add(solicitud)
        db.session.commit()

        # ❌ YA NO CREAMOS CONVERSACIÓN AQUÍ
        return jsonify({
            "mensaje": "Solicitud enviada",
            "solicitud_id": solicitud.id
        }), 201

    except Exception as e:
        db.session.rollback()
        print("Error creando solicitud:", e)
        return jsonify({"error": "Error al crear la solicitud"}), 500

@app.route('/api/solicitudes/proveedor')
def api_solicitudes_proveedor():
    if 'user_id' not in session or session.get('user_type') != 'proveedor':
        return jsonify({"error": "No autorizado"}), 401
    
    proveedor_id = session['user_id']

    # Traemos solicitudes ordenadas por fecha de creación (más nuevas primero)
    solicitudes = (db.session.query(SolicitudServicio, Usuario.nombre_completo)
                   .join(Usuario, SolicitudServicio.usuario_id == Usuario.id)
                   .filter(SolicitudServicio.proveedor_id == proveedor_id)
                   .order_by(SolicitudServicio.creado_en.desc())
                   .limit(5)
                   .all())

    results = []
    for s, nombre_usuario in solicitudes:
        results.append({
            "id": s.id,
            "cliente": nombre_usuario,
            "fecha": s.fecha.isoformat(),
            "hora_inicio": s.hora_inicio.strftime("%H:%M"),
            "hora_fin": s.hora_fin.strftime("%H:%M"),
            "descripcion": s.descripcion,
            "estado": s.estado,
            "creado_en": s.creado_en.strftime("%Y-%m-%d %H:%M"),
            "pin_codigo": s.pin_codigo  # <- NUEVO
        })
    
    return jsonify(results)


@app.route('/api/solicitudes/<int:solicitud_id>/estado', methods=['POST'])
def api_actualizar_estado_solicitud(solicitud_id):
    if 'user_id' not in session or session.get('user_type') != 'proveedor':
        return jsonify({"error": "No autorizado"}), 401
    
    proveedor_id = session['user_id']
    datos = request.json or {}
    nuevo_estado = datos.get('estado')

    if nuevo_estado not in ("aceptada", "rechazada"):
        return jsonify({"error": "Estado inválido"}), 400

    sol = SolicitudServicio.query.get_or_404(solicitud_id)
    if sol.proveedor_id != proveedor_id:
        return jsonify({"error": "No autorizado"}), 403
    
    try:
        sol.estado = nuevo_estado
        db.session.commit()

        respuesta = {"mensaje": "Estado actualizado"}

        # 👇 solo si se acepta, creamos/recuperamos el chat
        if nuevo_estado == "aceptada":
            conv = get_or_create_conversacion(sol.usuario_id, sol.proveedor_id)
            respuesta["conversacion_id"] = conv.id

        return jsonify(respuesta), 200

    except Exception as e:
        db.session.rollback()
        print("Error actualizando estado:", e)
        return jsonify({"error": "Error al actualizar la solicitud"}), 500



@app.route('/api/solicitudes/<int:solicitud_id>/confirmar_pin', methods=['POST'])
def api_confirmar_pin(solicitud_id):
    if 'user_id' not in session or session.get('user_type') != 'proveedor':
        return jsonify({"error": "No autorizado"}), 401

    proveedor_id = session['user_id']
    datos = request.json or {}
    pin_enviado = str(datos.get('pin', '')).strip()

    sol = SolicitudServicio.query.get_or_404(solicitud_id)

    if sol.proveedor_id != proveedor_id:
        return jsonify({"error": "No autorizado"}), 403

    if sol.estado != "pagado":
        return jsonify({"error": "La solicitud no está en estado pagado"}), 400

    if not sol.pin_codigo:
        return jsonify({"error": "La solicitud no tiene PIN asociado"}), 400

    if pin_enviado != sol.pin_codigo:
        return jsonify({"error": "PIN incorrecto"}), 400

    try:
        sol.estado = "completado"
        sol.confirmado_en = datetime.now(timezone.utc)
        db.session.commit()
        return jsonify({"mensaje": "Servicio confirmado correctamente"}), 200
    except Exception as e:
        db.session.rollback()
        print("Error confirmando PIN:", e)
        return jsonify({"error": "Error al confirmar el servicio"}), 500


@app.route('/api/solicitudes/<int:solicitud_id>/confirmar_servicio', methods=['POST'])
def api_confirmar_servicio(solicitud_id):
    if 'user_id' not in session or session.get('user_type') != 'proveedor':
        return jsonify({"error": "No autorizado"}), 401

    proveedor_id = session['user_id']
    datos = request.json or {}
    pin = (datos.get("pin") or "").strip()

    sol = SolicitudServicio.query.get_or_404(solicitud_id)

    if sol.proveedor_id != proveedor_id:
        return jsonify({"error": "No autorizado"}), 403

    if sol.estado != "pagado":
        return jsonify({"error": "La solicitud no está pagada"}), 400

    if not sol.pin_codigo:
        return jsonify({"error": "Esta solicitud no tiene PIN asignado"}), 400

    if pin != sol.pin_codigo:
        return jsonify({"error": "Código incorrecto"}), 400

    try:
        sol.estado = "completado"
        sol.confirmado_en = datetime.now(timezone.utc)
        db.session.commit()
        return jsonify({"mensaje": "Servicio confirmado"}), 200
    except Exception as e:
        db.session.rollback()
        print("Error al confirmar servicio:", e)
        return jsonify({"error": "Error al confirmar servicio"}), 500


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
    

@app.route('/solicitudes')
def vista_solicitudes_proveedor():
    if 'user_id' not in session or session.get('user_type') != 'proveedor':
        return redirect(url_for('login_page'))
    return render_template('solicitudes_proveedor.html')


@app.route('/pago/<int:solicitud_id>')
def vista_pago(solicitud_id):
    if 'user_id' not in session or session.get('user_type') != 'usuario':
        return redirect(url_for('login_page'))

    solicitud = SolicitudServicio.query.get_or_404(solicitud_id)

    # Verificar propiedad
    if solicitud.usuario_id != session['user_id']:
        return abort(403)

    # Solo solicitudes aceptadas pueden pagarse
    if solicitud.estado != "aceptada":
        return abort(403)

    return render_template("pago.html", solicitud=solicitud)

@app.route('/api/pago/<int:solicitud_id>', methods=['POST'])
def api_pago_realizado(solicitud_id):
    if 'user_id' not in session or session.get('user_type') != 'usuario':
        return jsonify({"error": "No autorizado"}), 401

    solicitud = SolicitudServicio.query.get_or_404(solicitud_id)

    if solicitud.usuario_id != session['user_id']:
        return jsonify({"error": "No autorizado"}), 403

    if solicitud.estado != "aceptada":
        return jsonify({"error": "La solicitud no está en estado aceptada"}), 400

    try:
        # marcar como pagado
        solicitud.estado = "pagado"

        # generar PIN de 6 dígitos si no existe
        if not solicitud.pin_codigo:
            solicitud.pin_codigo = f"{random.randint(0, 999999):06d}"

        db.session.commit()
        return jsonify({
            "mensaje": "Pago confirmado",
            "pin": solicitud.pin_codigo
        }), 200

    except Exception as e:
        db.session.rollback()
        print("Error al registrar pago:", e)
        return jsonify({"error": "Error al registrar pago"}), 500


@app.route('/api/solicitudes/usuario')
def api_solicitudes_usuario():
    if 'user_id' not in session or session.get('user_type') != 'usuario':
        return jsonify({"error": "No autorizado"}), 401
    
    usuario_id = session['user_id']

    solicitudes = (
        db.session.query(SolicitudServicio, Proveedor.nombre_completo)
        .join(Proveedor, SolicitudServicio.proveedor_id == Proveedor.id)
        .filter(SolicitudServicio.usuario_id == usuario_id)
        .order_by(SolicitudServicio.creado_en.desc())
        .all()
    )

    results = []
    for s, proveedor_nombre in solicitudes:
        results.append({
            "id": s.id,
            "proveedor": proveedor_nombre,
            "proveedor_id": s.proveedor_id,   # 👈 NUEVO
            "fecha": s.fecha.isoformat(),
            "hora_inicio": s.hora_inicio.strftime("%H:%M"),
            "hora_fin": s.hora_fin.strftime("%H:%M"),
            "descripcion": s.descripcion,
            "estado": s.estado,
            "creado_en": s.creado_en.strftime("%Y-%m-%d %H:%M"),
            "pin_codigo": s.pin_codigo
        })
    
    return jsonify(results), 200




@app.route('/mis_solicitudes')
def mis_solicitudes():
    if 'user_id' not in session or session.get('user_type') != 'usuario':
        return redirect(url_for('login_page'))
    
    return render_template('solicitudes_usuario.html')


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