<<<<<<< HEAD
from app import app, db

with app.app_context():
    db.create_all()
=======
from app import app, db

with app.app_context():
    db.create_all()
>>>>>>> aaafc6b04224a148da2d641bf606b0c747bdc61b
    print("tablas creadas correctamente")