## Ejecutar: 
```
pip install -r requirements.txt
py reset_db.py
```
Luego:

```
py create_schema.py
```
Y para correr aplicación:
```
py app.py
```
**(03/12) SE ACTUALIZÓ LA MAIN BRANCH** 
===============
## Cambios: 

1. En general, la UI se embelleció en las vistas
2. Sistema de pago, por tarjeta y efectivo
  * Cliente empieza chat con proveedor
  * Proveedor crea una cotización
  * El cliente elige metodo de pago, y efectua el pago
  * El proveedor acusa recibo
  * El usuario puede dejar reseña (ahora son 5 estrellas)

3. Sistema de comunas eliminado, ahora se implementó totalmente el sistema de localización por direccion escrita
  * Proveedor y usuario pueden actualizar su dirección
    
**Falta:**
Creo que está todo. Plis testear

**(02/12) HAY NUEVA ACTUALIZACION EN LA BRANCH new-branch.** 
===============
## Cambios: 

1. El archivo app.py se separó en:
  * app.py -> para iniciar la aplicacion y generar el modelo de la base de datos
  * routes.py -> maneja las rutas, endpoints, API

2. Sistema de comunas eliminado (falta eliminarlo de los formularios de registro)
3. El usuario puede cambiar su direccion (falta hacer eso para los proveedores)

4. Los proveedores ahora pueden subir archivos y no URL para las imagenes

**Falta:**

1. Actualizar formulario de registro, ya no se usan comunas (sistema antiguo)

2. Sistema de pago

3. Que los proveedores puedan cambiar su direccion

**(05/11) HAY NUEVA ACTUALIZACION EN LA BRANCH address-update.** 
===============

Se agregaron nuevos logos y sistema de geolocalizacion:

__*logo_zerby_white*__:
<img width="918" height="198" alt="logo_zerby_white" src="https://github.com/user-attachments/assets/f8323138-1e78-4afd-95cd-b436206ab192" />

__*logo_zerby_inverted*__:
<img width="918" height="198" alt="logo_zerby_inverted" src="https://github.com/user-attachments/assets/699dd33a-efdb-48e7-8ea6-fdf14cdbdc2a" />

__*logo_zerby_black*__:
<img width="918" height="198" alt="logo_zerby_black" src="https://github.com/user-attachments/assets/ee3d92e0-ec1b-46e2-8bc8-571328574b8c" />

__*logo_zerby*__ (DEFAULT):
<img width="918" height="198" alt="logo_zerby" src="https://github.com/user-attachments/assets/7bc5e344-1d05-4733-bc6d-a85c9dcf2965" />
