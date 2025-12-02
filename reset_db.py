import sys
from app import app, db

def reset_tables():
    """
    Borra TODAS las tablas y las vuelve a crear.
    ¡ADVERTENCIA: ESTO ELIMINA TODOS LOS DATOS!
    """
    with app.app_context():
        print("Conectando a la base de datos...")

        try:
            # 1. Borrar todas las tablas
            print("Borrando todas las tablas existentes (db.drop_all())...")
            db.drop_all()
            print("Tablas borradas.")

            # 2. Crear todas las tablas de nuevo (con los modelos actualizados)
            print("Creando nuevas tablas (db.create_all())...")
            db.create_all()
            print("¡Tablas creadas exitosamente!")

            print("\nBase de datos reseteada. El esquema está actualizado.")

        except Exception as e:
            print(f"\nOcurrió un error: {e}")

if __name__ == "__main__":
    # Pedimos confirmación para evitar desastres
    print("--- SCRIPT DE RESETEO DE BASE DE DATOS ---")
    print("¡ADVERTENCIA! Esto borrará TODOS los datos de tu base de datos.")

    # Hacemos que el usuario escriba "RESET" para confirmar
    confirm = input("Escribe 'RESET' para confirmar y continuar: ")

    if confirm == "RESET":
        reset_tables()
    else:
        print("Confirmación incorrecta. No se ha hecho nada.")
        sys.exit(0)