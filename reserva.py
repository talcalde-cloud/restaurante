import os
import sqlite3
from flask import Flask, render_template, request, jsonify

app = Flask(__name__)
DB_NAME = "database.db"

def get_db():
    conn = sqlite3.connect(DB_NAME)
    conn.row_factory = sqlite3.Row
    return conn

def init_db():
    conn = get_db()
    cursor = conn.cursor()
    
    # Tabla de Usuarios / Roles
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS usuarios (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            nombre TEXT NOT NULL,
            email TEXT UNIQUE NOT NULL,
            rol TEXT NOT NULL -- 'admin', 'camarero', 'cocina', 'cliente'
        )
    ''')

    # Tabla de Mesas
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS mesas (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            numero INTEGER UNIQUE NOT NULL,
            capacidad INTEGER NOT NULL,
            estado TEXT DEFAULT 'Disponible' -- 'Disponible', 'Ocupada', 'Reservada'
        )
    ''')

    # Tabla de Menú / Platos
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS platos (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            nombre TEXT NOT NULL,
            categoria TEXT NOT NULL,
            precio REAL NOT NULL,
            disponible INTEGER DEFAULT 1
        )
    ''')

    # Tabla de Inventario / Insumos
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS inventario (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            ingrediente TEXT UNIQUE NOT NULL,
            cantidad REAL NOT NULL,
            unidad TEXT NOT NULL,
            stock_minimo REAL NOT NULL
        )
    ''')

    # Tabla de Reservas
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS reservas (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            nombre_cliente TEXT NOT NULL,
            telefono TEXT NOT NULL,
            mesa_id INTEGER,
            fecha_hora TEXT NOT NULL,
            comensales INTEGER NOT NULL,
            estado TEXT DEFAULT 'Confirmada'
        )
    ''')

    # Tabla de Pedidos
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS pedidos (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            mesa_id INTEGER NOT NULL,
            camarero TEXT NOT NULL,
            estado TEXT DEFAULT 'Pendiente', -- 'Pendiente', 'En Preparación', 'Listo', 'Pagado'
            total REAL DEFAULT 0.0,
            fecha_hora TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    ''')

    # Tabla Detalle de Pedidos
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS detalle_pedidos (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            pedido_id INTEGER NOT NULL,
            plato_id INTEGER NOT NULL,
            cantidad INTEGER NOT NULL,
            precio_unitario REAL NOT NULL,
            FOREIGN KEY (pedido_id) REFERENCES pedidos (id),
            FOREIGN KEY (plato_id) REFERENCES platos (id)
        )
    ''')

    # Insertar datos de prueba iniciales si la base de datos está vacía
    cursor.execute("SELECT COUNT(*) FROM mesas")
    if cursor.fetchone()[0] == 0:
        cursor.executemany("INSERT INTO mesas (numero, capacidad) VALUES (?, ?)", [
            (1, 2), (2, 4), (3, 4), (4, 6), (5, 8), (6, 2)
        ])
        
        cursor.executemany("INSERT INTO platos (nombre, categoria, precio) VALUES (?, ?, ?)", [
            ('Hamburguesa Gourmet', 'Platos Fuertes', 12.50),
            ('Pizza Margarita', 'Platos Fuertes', 10.00),
            ('Tacos al Pastor', 'Platos Fuertes', 9.00),
            ('Ensalada César', 'Entradas', 7.50),
            ('Cerveza Artesanal', 'Bebidas', 4.00),
            ('Jugo Natural', 'Bebidas', 3.00),
            ('Tiramisú', 'Postres', 5.00)
        ])

        cursor.executemany("INSERT INTO inventario (ingrediente, cantidad, unidad, stock_minimo) VALUES (?, ?, ?, ?)", [
            ('Carne de Res', 15.0, 'kg', 5.0),
            ('Queso Mozzarella', 2.0, 'kg', 3.0),  # Generará alerta de stock bajo
            ('Pan de Hamburguesa', 30.0, 'unidades', 10.0),
            ('Cerveza', 8.0, 'unidades', 12.0),     # Generará alerta de stock bajo
            ('Tomates', 10.0, 'kg', 4.0)
        ])

    conn.commit()
    conn.close()

# --- RUTAS DE LA APLICACIÓN ---

@app.route('/')
def index():
    return render_template('index.html')

# API: Obtener datos iniciales y estado general
@app.route('/api/estado_general', methods=['GET'])
def estado_general():
    conn = get_db()
    cursor = conn.cursor()
    
    mesas = [dict(row) for row in cursor.execute("SELECT * FROM mesas").fetchall()]
    platos = [dict(row) for row in cursor.execute("SELECT * FROM platos").fetchall()]
    inventario = [dict(row) for row in cursor.execute("SELECT * FROM inventario").fetchall()]
    pedidos = [dict(row) for row in cursor.execute("SELECT * FROM pedidos WHERE estado != 'Pagado'").fetchall()]
    reservas = [dict(row) for row in cursor.execute("SELECT * FROM reservas").fetchall()]
    
    # Detalle de cada pedido para la vista de cocina
    for p in pedidos:
        detalles = cursor.execute('''
            SELECT dp.cantidad, pl.nombre 
            FROM detalle_pedidos dp 
            JOIN platos pl ON dp.plato_id = pl.id 
            WHERE dp.pedido_id = ?
        ''', (p['id'],)).fetchall()
        p['detalles'] = [dict(d) for d in detalles]

    # --- SITEMA DE ALERTAS PYTHON ---
    alertas = []
    
    # 1. Alerta de Stock Bajo
    for item in inventario:
        if item['cantidad'] <= item['stock_minimo']:
            alertas.append({
                'tipo': 'danger',
                'titulo': '⚠️ ALERTA DE INVENTARIO CRÍTICO',
                'mensaje': f"El ingrediente '{item['ingrediente']}' está bajo ({item['cantidad']} {item['unidad']}). Mínimo requerido: {item['stock_minimo']} {item['unidad']}."
            })
            
    # 2. Alerta de Pedidos Retrasados/Pendientes en Cocina
    pedidos_pendientes = [p for p in pedidos if p['estado'] == 'Pendiente']
    if len(pedidos_pendientes) >= 3:
        alertas.append({
            'tipo': 'warning',
            'titulo': '🔥 ALERTA DE SOBRECARGA EN COCINA',
            'mensaje': f"Hay {len(pedidos_pendientes)} pedidos pendientes acumulados en cocina."
        })

    conn.close()
    return jsonify({
        'mesas': mesas,
        'platos': platos,
        'inventario': inventario,
        'pedidos': pedidos,
        'reservas': reservas,
        'alertas': alertas
    })

# API: Crear nueva reserva
@app.route('/api/reservas', methods=['POST'])
def crear_reserva():
    data = request.json
    conn = get_db()
    cursor = conn.cursor()
    
    cursor.execute('''
        INSERT INTO reservas (nombre_cliente, telefono, mesa_id, fecha_hora, comensales)
        VALUES (?, ?, ?, ?, ?)
    ''', (data['nombre'], data['telefono'], data['mesa_id'], data['fecha_hora'], data['comensales']))
    
    # Marcar mesa como reservada
    cursor.execute("UPDATE mesas SET estado = 'Reservada' WHERE id = ?", (data['mesa_id'],))
    
    conn.commit()
    conn.close()
    return jsonify({'status': 'ok', 'mensaje': 'Reserva creada exitosamente con confirmación automática.'})

# API: Crear nuevo pedido (Camarero/POS)
@app.route('/api/pedidos', methods=['POST'])
def crear_pedido():
    data = request.json
    conn = get_db()
    cursor = conn.cursor()
    
    cursor.execute('''
        INSERT INTO pedidos (mesa_id, camarero, total, estado)
        VALUES (?, ?, ?, 'Pendiente')
    ''', (data['mesa_id'], data['camarero'], data['total']))
    
    pedido_id = cursor.lastrowid
    
    for item in data['items']:
        cursor.execute('''
            INSERT INTO detalle_pedidos (pedido_id, plato_id, cantidad, precio_unitario)
            VALUES (?, ?, ?, ?)
        ''', (pedido_id, item['plato_id'], item['cantidad'], item['precio']))
        
    cursor.execute("UPDATE mesas SET estado = 'Ocupada' WHERE id = ?", (data['mesa_id'],))
    
    conn.commit()
    conn.close()
    return jsonify({'status': 'ok', 'mensaje': f'Pedido #{pedido_id} enviado a Cocina con alerta sonora.'})

# API: Cambiar estado de pedido (Cocina KDS)
@app.route('/api/pedidos/<int:pedido_id>/estado', methods=['PUT'])
def cambiar_estado_pedido(pedido_id):
    nuevo_estado = request.json.get('estado')
    conn = get_db()
    cursor = conn.cursor()
    
    cursor.execute("UPDATE pedidos SET estado = ? WHERE id = ?", (nuevo_estado, pedido_id))
    
    conn.commit()
    conn.close()
    return jsonify({'status': 'ok'})

# API: Cobrar y Cerrar Mesa
@app.route('/api/pedidos/<int:pedido_id>/cerrar', methods=['POST'])
def cerrar_pedido(pedido_id):
    conn = get_db()
    cursor = conn.cursor()
    
    mesa_id = cursor.execute("SELECT mesa_id FROM pedidos WHERE id = ?", (pedido_id,)).fetchone()[0]
    
    cursor.execute("UPDATE pedidos SET estado = 'Pagado' WHERE id = ?", (pedido_id,))
    cursor.execute("UPDATE mesas SET estado = 'Disponible' WHERE id = ?", (mesa_id,))
    
    conn.commit()
    conn.close()
    return jsonify({'status': 'ok', 'mensaje': 'Mesa cobrada correctamente. Liberada para nuevos clientes.'})

if __name__ == '__main__':
    init_db()
    print("Servidor iniciado en http://127.0.0.1:5000")
    app.run(debug=True, port=5000)