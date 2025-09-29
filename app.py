from flask import Flask, render_template, request, redirect, url_for, session, jsonify
from flask_sqlalchemy import SQLAlchemy
from flask_bcrypt import Bcrypt
from datetime import datetime, date
import requests
import os

app = Flask(__name__)
app.secret_key = 'mi_clave_secreta'
app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///usuarios.db'
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False

db = SQLAlchemy(app)
bcrypt = Bcrypt(app)

# =========================
# Modelos
# =========================

class User(db.Model):
    __tablename__ = "user"

    id = db.Column(db.Integer, primary_key=True)
    nombre = db.Column(db.String(150), nullable=False)
    fecha_nacimiento = db.Column(db.Date, nullable=False)
    sexo = db.Column(db.String(10), nullable=False)
    objetivo = db.Column(db.String(200), nullable=True)
    actividad = db.Column(db.String(50), nullable=False, default="Sedentario")  # 👈 Nuevo campo

    # Autenticación
    correo = db.Column(db.String(150), nullable=False, unique=True)
    password = db.Column(db.String(150), nullable=False)

    # Relaciones
    registros_imc = db.relationship('RegistroIMC', backref='usuario', lazy=True, cascade="all, delete-orphan")
    alimentos = db.relationship('Alimento', backref='usuario', lazy=True, cascade="all, delete-orphan")
    consumos = db.relationship('Consumo', backref='usuario', lazy=True, cascade="all, delete-orphan")


class RegistroIMC(db.Model):
    __tablename__ = "registro_imc"

    id = db.Column(db.Integer, primary_key=True)
    altura = db.Column(db.Float, nullable=False)
    peso = db.Column(db.Float, nullable=False)
    imc = db.Column(db.Float, nullable=False)
    clasificacion = db.Column(db.String(50), nullable=False)  # Ej: "Normal", "Sobrepeso"
    calorias = db.Column(db.Integer, nullable=True)           # 🔹 Nueva columna

    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)


class Alimento(db.Model):
    __tablename__ = "alimento"

    id = db.Column(db.Integer, primary_key=True)
    nombre = db.Column(db.String(100), nullable=False)
    calorias = db.Column(db.Float)
    proteinas = db.Column(db.Float)
    grasas = db.Column(db.Float)
    carbohidratos = db.Column(db.Float)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    

class Consumo(db.Model):
    __tablename__ = "consumo"

    id = db.Column(db.Integer, primary_key=True)
    fecha_hora = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)
    porcion = db.Column(db.String(50), nullable=True, default="100 g")

    # Snapshot de los datos del alimento en el momento del consumo
    nombre = db.Column(db.String(100), nullable=False)
    calorias = db.Column(db.Float)
    proteinas = db.Column(db.Float)
    grasas = db.Column(db.Float)
    carbohidratos = db.Column(db.Float)

    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)


# =========================
# Helpers
# =========================

def clasificar_imc(imc):
    if imc < 18.5:
        return "Bajo peso"
    elif 18.5 <= imc < 25:
        return "Peso normal"
    elif 25 <= imc < 30:
        return "Sobrepeso"
    else:
        return "Obesidad"

def login_required(view_func):
    # Decorador simple para rutas protegidas
    from functools import wraps
    @wraps(view_func)
    def wrapped(*args, **kwargs):
        if 'user_id' not in session:
            return redirect(url_for('login'))
        return view_func(*args, **kwargs)
    return wrapped

def calcular_calorias(user, edad, peso, altura_m):
    """
    Calcula calorías diarias recomendadas con Mifflin-St Jeor,
    ajustadas por nivel de actividad y objetivo del usuario.

    :param user: instancia User con atributos sexo, actividad, objetivo
    :param edad: edad en años (int)
    :param peso: peso en kg (float)
    :param altura_m: altura en metros (float)
    :return: calorías recomendadas (int)
    """
    # 1) TMB (Mifflin-St Jeor)
    altura_cm = altura_m * 100
    sexo = (user.sexo or "").strip().lower()
    if sexo == "masculino" or sexo == "m":
        tmb = 10 * peso + 6.25 * altura_cm - 5 * edad + 5
    else:
        tmb = 10 * peso + 6.25 * altura_cm - 5 * edad - 161

    # 2) Factores de actividad (según opciones en register.html)
    factores = {
        "sedentario": 1.2,
        "ligero": 1.375,
        "moderado": 1.55,
        "intenso": 1.725,
        "muy intenso": 1.9
    }
    actividad_key = (user.actividad or "sedentario").strip().lower()
    factor = factores.get(actividad_key, 1.2)

    mantenimiento = tmb * factor

    # 3) Ajuste por objetivo
    objetivo = (user.objetivo or "").strip().lower()
    if objetivo == "ganar peso":
        objetivo_kcal = round(mantenimiento + 500)
    elif objetivo == "perder peso":
        objetivo_kcal = round(mantenimiento - 500)
    else:  # Mantener peso
        objetivo_kcal = round(mantenimiento)

    return objetivo_kcal



# =========================
# Rutas
# =========================

@app.route('/')
def home():
    return render_template('home.html')


@app.route('/login', methods=['GET', 'POST'])
def login():
    error = None
    if request.method == 'POST':
        correo = request.form.get('correo', '').strip().lower()
        password = request.form.get('password', '')

        user = User.query.filter_by(correo=correo).first()
        if user and bcrypt.check_password_hash(user.password, password):
            session['user_id'] = user.id
            return redirect(url_for('dashboard'))
        else:
            error = 'Correo o contraseña incorrectos.'
    return render_template('login.html', error=error)


@app.route('/register', methods=['GET', 'POST'])
def register():
    error = None
    if request.method == 'POST':
        try:
            nombre = request.form.get('nombre', '').strip()
            fecha_nacimiento_str = request.form.get('fecha_nacimiento', '').strip()
            sexo = request.form.get('sexo', '').strip()
            objetivo = request.form.get('objetivo', '').strip() or None
            actividad = request.form.get('actividad', '').strip()   # 👈 nuevo
            correo = request.form.get('correo', '').strip().lower()
            password = request.form.get('password', '')

            if not all([nombre, fecha_nacimiento_str, sexo, correo, password, actividad]):
                error = 'Completa todos los campos obligatorios.'
                return render_template('register.html', error=error)

            if User.query.filter_by(correo=correo).first():
                error = 'Ya existe una cuenta con ese correo.'
                return render_template('register.html', error=error)

            fecha_nacimiento = datetime.strptime(fecha_nacimiento_str, '%Y-%m-%d').date()

            hashed = bcrypt.generate_password_hash(password).decode('utf-8')
            user = User(
                nombre=nombre,
                fecha_nacimiento=fecha_nacimiento,
                sexo=sexo,
                objetivo=objetivo,
                actividad=actividad,  # 👈 Guardamos
                correo=correo,
                password=hashed
            )
            db.session.add(user)
            db.session.commit()
            return redirect(url_for('login'))
        except ValueError:
            error = 'Formato de fecha inválido. Usa AAAA-MM-DD.'
        except Exception as e:
            error = f'Ocurrió un error creando la cuenta: {str(e)}'
    return render_template('register.html', error=error)



@app.route('/calculadora', methods=['GET', 'POST'])
@login_required
def calculadora():
    user = User.query.get(session['user_id'])
    resultado = None

    # 🔹 Calcular edad (para perfil y fórmula)
    hoy = date.today()
    edad = hoy.year - user.fecha_nacimiento.year - (
        (hoy.month, hoy.day) < (user.fecha_nacimiento.month, user.fecha_nacimiento.day)
    )

    if request.method == 'POST':
        try:
            # ✅ Cambio de peso y altura (calcular IMC y calorías)
            if 'altura' in request.form and 'peso' in request.form:
                altura = float(request.form['altura'])
                peso = float(request.form['peso'])
                imc = round(peso / (altura ** 2), 2)

                clasificacion = clasificar_imc(imc)

                # ✅ Usamos la función que toma actividad y objetivo
                calorias = calcular_calorias(user, edad, peso, altura)

                resultado = {"imc": imc, "clasificacion": clasificacion, "calorias": calorias}

                # Guardar en DB
                registro = RegistroIMC(
                    altura=altura,
                    peso=peso,
                    imc=imc,
                    clasificacion=clasificacion,
                    calorias=calorias,
                    user_id=user.id
                )
                db.session.add(registro)
                db.session.commit()

            # ✅ Cambio de objetivo
            elif 'objetivo' in request.form:
                nuevo_objetivo = request.form.get('objetivo')
                if nuevo_objetivo:
                    user.objetivo = nuevo_objetivo
                    db.session.commit()

            # ✅ Cambio de actividad física
            elif 'actividad' in request.form:
                nueva_actividad = request.form.get('actividad')
                if nueva_actividad:
                    user.actividad = nueva_actividad
                    db.session.commit()

        except Exception as e:
            resultado = {"error": f"Error al calcular IMC: {e}"}

    else:
        # 🔹 Si ya tiene registros previos
        ultimo_registro = RegistroIMC.query.filter_by(user_id=user.id).order_by(RegistroIMC.id.desc()).first()
        if ultimo_registro:
            resultado = {
                "imc": ultimo_registro.imc,
                "clasificacion": ultimo_registro.clasificacion,
                "calorias": ultimo_registro.calorias
            }

    return render_template('calculadora.html', user=user, resultado=resultado, edad=edad)

@app.route('/alimentos', methods=['GET', 'POST'])
@login_required
def alimentos():
    info = None
    if request.method == 'POST':
        nombre = request.form.get('nombre', '').strip()
        if nombre:
            try:
                response = requests.get(
                    "https://world.openfoodfacts.org/cgi/search.pl",
                    params={"search_terms": nombre, "search_simple": 1, "json": 1},
                    timeout=15
                )
                data = response.json() if response.ok else {}
                if data.get('products'):
                    producto = data['products'][0]
                    nutr = producto.get('nutriments', {}) or {}
                    calorias = nutr.get('energy-kcal_100g', 0) or 0
                    proteinas = nutr.get('proteins_100g', 0) or 0
                    grasas = nutr.get('fat_100g', 0) or 0
                    carbos = nutr.get('carbohydrates_100g', 0) or 0

                    info = {
                        'nombre': producto.get('product_name', nombre) or nombre,
                        'calorias': calorias,
                        'proteinas': proteinas,
                        'grasas': grasas,
                        'carbohidratos': carbos,
                        'imagen': producto.get('image_url')
                    }
                    nuevo = Alimento(
                        nombre=info['nombre'],
                        calorias=calorias,
                        proteinas=proteinas,
                        grasas=grasas,
                        carbohidratos=carbos,
                        user_id=session['user_id']
                    )
                    db.session.add(nuevo)
                    db.session.commit()
                else:
                    info = {'error': 'No se encontró información para ese alimento.'}
            except Exception:
                info = {'error': 'No se pudo consultar OpenFoodFacts. Intenta más tarde.'}

    historial = Alimento.query.filter_by(user_id=session['user_id']).order_by(Alimento.id.desc()).limit(10).all()
    return render_template('alimentos.html', info=info, historial=historial)

@app.route("/eliminar_consumo/<int:consumo_id>", methods=["POST"])
def eliminar_consumo(consumo_id):
    consumo = Consumo.query.filter_by(id=consumo_id, user_id=session["user_id"]).first()
    if not consumo:
        # Redirige aunque no exista, para no romper la vista
        return redirect(url_for("agregar_alimentos"))

    db.session.delete(consumo)
    db.session.commit()

    # Redirige a la página de alimentos consumidos después de eliminar
    return redirect(url_for("agregar_alimentos"))

@app.route('/alimentos-consumidos', methods=['GET'])
@login_required
def agregar_alimentos():
    user_id = session['user_id']

    # 🔹 Traer alimentos consumidos del usuario
    consumos = Consumo.query.filter_by(user_id=user_id) \
                            .order_by(Consumo.fecha_hora.desc()).all()

    # 🔹 Últimas calorías recomendadas (de la calculadora/IMC)
    calorias_recomendadas = None
    ultimo_registro = RegistroIMC.query.filter_by(user_id=user_id) \
                                       .order_by(RegistroIMC.id.desc()).first()
    if ultimo_registro:
        calorias_recomendadas = ultimo_registro.calorias

    # 🔹 Calorías consumidas HOY
    hoy = datetime.utcnow().date()
    calorias_consumidas = db.session.query(db.func.sum(Consumo.calorias)) \
        .filter(Consumo.user_id == user_id) \
        .filter(db.func.date(Consumo.fecha_hora) == hoy) \
        .scalar() or 0

    return render_template(
        'agregar_alimentos.html',
        consumos=consumos,
        calorias_recomendadas=calorias_recomendadas,
        calorias_consumidas=calorias_consumidas
    )


# ---------------------------
# Agregar un nuevo consumo
# ---------------------------
@app.route('/consumos/agregar', methods=['POST'])
@login_required
def agregar_consumo():
    alimento_id = request.form.get('alimento_id', type=int)
    porcion = request.form.get('porcion') or '100 g'

    if not alimento_id:
        return jsonify({"success": False, "message": "No se seleccionó alimento"}), 400

    alimento = Alimento.query.filter_by(id=alimento_id, user_id=session['user_id']).first()
    if not alimento:
        return jsonify({"success": False, "message": "Alimento no encontrado"}), 404

    c = Consumo(
        nombre=alimento.nombre,
        calorias=alimento.calorias,
        proteinas=alimento.proteinas,
        grasas=alimento.grasas,
        carbohidratos=alimento.carbohidratos,
        porcion=porcion,
        user_id=session['user_id'],
        fecha_hora=datetime.utcnow()
    )
    db.session.add(c)
    db.session.commit()


    return jsonify({
        "success": True,
        "message": f"{alimento.nombre} agregado con éxito",
        "consumo": {
            "nombre": alimento.nombre,
            "calorias": alimento.calorias,
            "porcion": porcion
        }
    })



@app.route('/dashboard')
@login_required
def dashboard():
    user = User.query.get(session['user_id'])
    registro = RegistroIMC.query.filter_by(user_id=user.id).order_by(RegistroIMC.id.desc()).first()
    return render_template('dashboard.html', user=user, registro=registro)


@app.route('/logout')
def logout():
    session.pop('user_id', None)
    return redirect(url_for('login'))


# =========================
# Main
# =========================
if __name__ == '__main__':
    with app.app_context():
        db.create_all()
    app.run(debug=True)