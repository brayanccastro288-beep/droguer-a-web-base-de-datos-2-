from flask import Flask, render_template, request, redirect, url_for, session, flash
import mysql.connector
import hashlib

app = Flask(__name__)
app.secret_key = "cambia_esta_clave"

# ---------- CONEXIÓN A LA BASE DE DATOS ----------
def conectar():
    return mysql.connector.connect(
        host="localhost",
        user="root",
        password="d123456",      # <-- la de tu MySQL
        database="drogueria_salud_vida"
    )

def consultar(sql, params=(), uno=False):
    con = conectar()
    cur = con.cursor(dictionary=True)
    cur.execute(sql, params)
    datos = cur.fetchone() if uno else cur.fetchall()
    cur.close()
    con.close()
    return datos

def ejecutar(sql, params=()):
    con = conectar()
    cur = con.cursor()
    cur.execute(sql, params)
    con.commit()
    cur.close()
    con.close()

def es_admin():
    return session.get("rol", "").lower() == "administrador"

# ---------- LOGIN ----------
@app.route("/", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        usuario = request.form["usuario"]
        # la clave se guarda como SHA-256 (64 caracteres), igual que en la BD
        clave_hash = hashlib.sha256(request.form["clave"].encode()).hexdigest()
        user = consultar(
            """SELECT u.nombre_usuario, r.nombre_rol
               FROM usuario u JOIN rol r ON u.id_rol = r.id_rol
               WHERE u.nombre_usuario = %s AND u.clave_hash = %s AND u.activo = 1""",
            (usuario, clave_hash), uno=True)
        if user:
            session["usuario"] = user["nombre_usuario"]
            session["rol"] = user["nombre_rol"]
            return redirect(url_for("productos"))
        flash("Usuario o contraseña incorrectos")
    return render_template("login.html")

@app.route("/logout")
def logout():
    session.clear()
    return redirect(url_for("login"))

# ---------- VER Y BUSCAR PRODUCTOS ----------
@app.route("/productos")
def productos():
    if "usuario" not in session:
        return redirect(url_for("login"))

    texto = request.args.get("texto", "")        # busca en nombre o código
    categoria = request.args.get("categoria", "")
    proveedor = request.args.get("proveedor", "")

    sql = """SELECT p.id_producto, p.codigo, p.nombre, p.precio_compra, p.precio_venta,
                    p.stock, p.stock_minimo, p.fecha_vencimiento,
                    c.nombre_categoria, pr.razon_social
             FROM producto p
             JOIN categoria c ON p.id_categoria = c.id_categoria
             JOIN proveedor pr ON p.id_proveedor = pr.id_proveedor
             WHERE (p.nombre LIKE %s OR p.codigo LIKE %s)
               AND c.nombre_categoria LIKE %s
               AND pr.razon_social LIKE %s
             ORDER BY p.nombre"""
    lista = consultar(sql, (f"%{texto}%", f"%{texto}%", f"%{categoria}%", f"%{proveedor}%"))
    return render_template("productos.html", productos=lista)

# ---------- INSERTAR ----------
@app.route("/productos/nuevo", methods=["GET", "POST"])
def nuevo():
    if not es_admin():
        return redirect(url_for("productos"))
    if request.method == "POST":
        try:
            ejecutar("""INSERT INTO producto (codigo, nombre, id_categoria, id_proveedor,
                        precio_compra, precio_venta, stock, stock_minimo, fecha_vencimiento)
                        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)""",
                     (request.form["codigo"], request.form["nombre"],
                      request.form["id_categoria"], request.form["id_proveedor"],
                      request.form["precio_compra"], request.form["precio_venta"],
                      request.form["stock"], request.form["stock_minimo"],
                      request.form["fecha_vencimiento"] or None))
            return redirect(url_for("productos"))
        except mysql.connector.Error as e:
            flash(f"No se pudo guardar: {e.msg}")
    return render_template("formulario.html", producto=None,
                           categorias=consultar("SELECT * FROM categoria"),
                           proveedores=consultar("SELECT * FROM proveedor"))

# ---------- ACTUALIZAR ----------
@app.route("/productos/editar/<int:id>", methods=["GET", "POST"])
def editar(id):
    if not es_admin():
        return redirect(url_for("productos"))
    if request.method == "POST":
        try:
            ejecutar("""UPDATE producto SET codigo=%s, nombre=%s, id_categoria=%s, id_proveedor=%s,
                        precio_compra=%s, precio_venta=%s, stock=%s, stock_minimo=%s,
                        fecha_vencimiento=%s WHERE id_producto=%s""",
                     (request.form["codigo"], request.form["nombre"],
                      request.form["id_categoria"], request.form["id_proveedor"],
                      request.form["precio_compra"], request.form["precio_venta"],
                      request.form["stock"], request.form["stock_minimo"],
                      request.form["fecha_vencimiento"] or None, id))
            return redirect(url_for("productos"))
        except mysql.connector.Error as e:
            flash(f"No se pudo actualizar: {e.msg}")
    producto = consultar("SELECT * FROM producto WHERE id_producto=%s", (id,), uno=True)
    return render_template("formulario.html", producto=producto,
                           categorias=consultar("SELECT * FROM categoria"),
                           proveedores=consultar("SELECT * FROM proveedor"))

# ---------- ELIMINAR ----------
@app.route("/productos/eliminar/<int:id>")
def eliminar(id):
    if not es_admin():
        return redirect(url_for("productos"))
    try:
        ejecutar("DELETE FROM producto WHERE id_producto=%s", (id,))
    except mysql.connector.Error:
        flash("No se puede eliminar: el producto tiene ventas o compras asociadas")
    return redirect(url_for("productos"))

# ---------- EXTRACCIÓN Y ANÁLISIS ----------
@app.route("/reportes")
def reportes():
    if "usuario" not in session:
        return redirect(url_for("login"))

    mas_vendidos = consultar("""
        SELECT p.nombre, SUM(dv.cantidad) AS total_vendido
        FROM detalle_venta dv JOIN producto p ON dv.id_producto = p.id_producto
        GROUP BY p.nombre ORDER BY total_vendido DESC LIMIT 5""")

    stock_bajo = consultar("""
        SELECT nombre, stock, stock_minimo FROM producto
        WHERE stock <= stock_minimo ORDER BY stock""")

    por_vencer = consultar("""
        SELECT nombre, fecha_vencimiento FROM producto
        WHERE fecha_vencimiento IS NOT NULL
          AND fecha_vencimiento <= DATE_ADD(CURDATE(), INTERVAL 90 DAY)
        ORDER BY fecha_vencimiento""")

    por_categoria = consultar("""
        SELECT c.nombre_categoria, COUNT(*) AS cantidad_productos
        FROM producto p JOIN categoria c ON p.id_categoria = c.id_categoria
        GROUP BY c.nombre_categoria""")

    ventas_mes = consultar("""
        SELECT DATE_FORMAT(fecha, '%Y-%m') AS mes, SUM(total) AS total_vendido
        FROM venta GROUP BY mes ORDER BY mes DESC LIMIT 6""")

    return render_template("reportes.html", mas_vendidos=mas_vendidos, stock_bajo=stock_bajo,
                           por_vencer=por_vencer, por_categoria=por_categoria,
                           ventas_mes=ventas_mes)

if __name__ == "__main__":
    app.run(debug=True)
