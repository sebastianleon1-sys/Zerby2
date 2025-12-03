### Esta rama es de respaldo. 03/12 00:45
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
2. Sistema de pago, por tarjeta y efectivo:
  > 1. Cliente empieza chat con proveedor
> 
  > 2. Proveedor crea una cotización
> 
  > 3. El cliente elige metodo de pago, y efectua el pago
> 
  > 4. El proveedor acusa recibo
> 
  > 5. El usuario puede dejar reseña (ahora son 5 estrellas)
> 

3. Sistema de comunas eliminado, ahora se implementó totalmente el sistema de localización por direccion escrita
  * Proveedor y usuario pueden actualizar su dirección
    
**Falta:**

Creo que está todo. Plis testear

