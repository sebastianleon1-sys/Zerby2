
"""
Iniciar test automatico:
* pip install pytest pytest-flask
* pytest test_app.py -v
"""
import pytest
from app import app, db, Usuario, Proveedor, Conversacion, Mensaje

@pytest.fixture
def client():
    app.config['TESTING'] = True
    app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///:memory:'
    app.config['SECRET_KEY'] = 'test-secret-key'

    with app.test_client() as client:
        with app.app_context():
            db.create_all()
        yield client
        with app.app_context():
            db.drop_all()

@pytest.fixture
def init_db():
    with app.app_context():
        db.create_all()
        yield db
        db.drop_all()

# --- PRUEBAS UNITARIAS ---
def test_password_hashing():
    user = Usuario(nombre_completo="Test", email="test@example.com")
    user.set_password("mipassword")
    assert user.check_password("mipassword") == True
    assert user.check_password("otro") == False

# --- PRUEBAS DE REGISTRO ---
def test_registro_usuario(client):
    response = client.post('/registrar/usuario', json={
        "nombre_completo": "Juan Pérez",
        "email": "juan@example.com",
        "password": "123456",
        "telefono": "987654321"
    })
    assert response.status_code == 201
    assert response.json['mensaje'] == "Usuario cliente registrado con éxito"

    # No permite duplicado
    response2 = client.post('/registrar/usuario', json={
        "nombre_completo": "Juan",
        "email": "juan@example.com",
        "password": "123"
    })
    assert response2.status_code == 400

def test_registro_proveedor(client):
    response = client.post('/registrar/proveedor', json={
        "nombre_completo": "Carlos Gómez",
        "email": "carlos@proveedor.com",
        "password": "123456",
        "telefono": "987654321",
        "oficio": "Plomero"
    })
    assert response.status_code == 201

    # Falla si falta oficio
    response2 = client.post('/registrar/proveedor', json={
        "nombre_completo": "Ana",
        "email": "ana@example.com",
        "password": "123",
        "telefono": "123"
    })
    assert response2.status_code == 400

# --- PRUEBAS DE LOGIN ---
def test_login_usuario(client):
    # Registrar primero
    client.post('/registrar/usuario', json={
        "nombre_completo": "Ana", "email": "ana@test.com", "password": "123456"
    })

    # Login exitoso
    response = client.post('/api/login', json={
        "email": "ana@test.com", "password": "123456"
    })
    assert response.status_code == 200
    assert 'user_id' in client.application.view_functions['api_login'].__globals__['session']

    # Login fallido
    response2 = client.post('/api/login', json={
        "email": "ana@test.com", "password": "wrong"
    })
    assert response2.status_code == 401

# --- PRUEBAS DE AUTORIZACIÓN ---
def test_dashboard_sin_login(client):
    response = client.get('/dashboard')
    assert response.status_code == 302  # redirige a login

def test_api_protected_sin_login(client):
    response = client.get('/api/proveedores/cercanos')
    assert response.status_code == 401

# --- PRUEBAS DE MENSAJERÍA ---
def test_iniciar_chat_y_enviar_mensaje(client):
    # Registrar usuario y proveedor
    client.post('/registrar/usuario', json={
        "nombre_completo": "Luis", "email": "luis@cliente.com", "password": "123"
    })
    prov = client.post('/registrar/proveedor', json={
        "nombre_completo": "Mario", "email": "mario@prov.com", "password": "123",
        "telefono": "123", "oficio": "Electricista"
    })

    # Login como usuario
    client.post('/api/login', json={"email": "luis@cliente.com", "password": "123"})

    # Obtener proveedor ID (simulado)
    proveedor = Proveedor.query.filter_by(email="mario@prov.com").first()

    # Iniciar chat
    response = client.post(f'/api/iniciar_chat/{proveedor.id}')
    assert response.status_code == 201
    conv_id = response.json['conversacion_id']

    # Enviar mensaje
    response = client.post(f'/api/conversacion/{conv_id}/enviar', json={
        "contenido": "Hola, necesito ayuda"
    })
    assert response.status_code == 201

    # Ver mensajes
    response = client.get(f'/api/conversacion/{conv_id}/detalles')
    assert response.status_code == 200
    assert len(response.json['mensajes']) == 1
    assert response.json['mensajes'][0]['contenido'] == "Hola, necesito ayuda"
