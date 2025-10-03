import eventlet
eventlet.monkey_patch()
from flask import Flask, render_template, request, redirect, url_for, session, jsonify, json
from flask_sqlalchemy import SQLAlchemy
import psycopg2
import os
import razorpay
from flask_socketio import SocketIO, emit
from werkzeug.security import generate_password_hash, check_password_hash
from werkzeug.utils import secure_filename
import qrcode
import uuid
import io, base64
import encodings
from reportlab.pdfgen import canvas
from reportlab.lib.pagesizes import A4
from datetime import datetime, timedelta

app = Flask(__name__, template_folder="templates")
print("Templates folder absolute path:", os.path.abspath(os.path.join(os.getcwd(), "templates")))
app.secret_key = "my_dream_project_of_2006"
socketio = SocketIO(app)

DATABASE_URL = "postgresql://oddz_7d2m_user:XchteBlGGUaBLNnTqBUM55Hw1ap0LRNw@dpg-d3f1mo15pdvs73ccof50-a/oddz_7d2m"
conn = psycopg2.connect(DATABASE_URL)
cur = conn.cursor()

def init_db():
    cur = conn.cursor()
    cur.execute("ALTER DATABASE oddz_7d2m Set timezone = 'Asia/Kolkata';")
    conn.commit()


    cur.execute("""

        CREATE TABLE IF NOT EXISTS admins(
            id serial primary key,
            fullname varchar(100),
            email varchar(255),
            password text
        );
        CREATE TABLE IF NOT EXISTS restaurants(
            id serial primary key,
            admin_id int not null references admins(id) on delete cascade,
            restaurant_name varchar(100),
            address text,
            phone numeric,
            logo bytea,
            category varchar(50)
            );
        CREATE TABLE IF NOT EXISTS menu(
            id serial primary key,
            restaurants_id int not null references restaurants(id) on delete cascade,
            admins_id int not null references admins(id) on delete cascade,
            item_name varchar(255),
            price numeric,
            category varchar(100),
            about varchar(255)
            );

        CREATE TABLE IF NOT EXISTS team(
            id serial primary key,
            restaurants_id int not null references restaurants(id) on delete cascade,
            name varchar(100),
            role varchar(50),
            phone numeric
            );
        CREATE TABLE IF NOT EXISTS orders(
            order_id serial primary key,
            restaurant_id int not null references restaurants(id) on delete cascade,
            table_number int,
            total_amount numeric(10,2),
            status varchar(25),
            order_time timestamp default current_timestamp,
            txn_id varchar(255)
        );

        CREATE TABLE IF NOT EXISTS order_items(
            item_id serial primary key,
            order_id int not null references orders(order_id) on delete cascade,
            menu_item_id int not null references menu(id) on delete cascade,
            quantity int,
            price numeric(10,2)
            );

        CREATE TABLE IF NOT EXISTS qr_token(
            id serial primary key,
            token uuid,
            admin_id int not null references admins(id) on delete cascade,
            restaurant_id int not null references restaurants(id) on delete cascade,
            table_number INTEGER NOT NULL,
            UNIQUE (restaurant_id, table_number),
            created_at timestamp default current_timestamp
            );

        CREATE TABLE IF NOT EXISTS payment_credentials(
            id serial primary key,
            admin_id int not null references admins(id) on delete cascade,
            upi_id varchar(100),
            created_at timestamp default current_timestamp,
            updated_at timestamp default current_timestamp
            );

        CREATE TABLE IF NOT EXISTS subscriptions(
            id serial primary key,
            restaurant_name text,
            restaurant_id int,
            email text,
            contact numeric,
            plan_name text,
            plan_amount real,
            validity text,
            subscription_id text,
            status text,
            admin_id int,
            active text,
            start_at timestamp default current_timestamp,
            end_at timestamp default current_timestamp
            );
        """)
    conn.commit()
    print("worked well")

with app.app_context():
    init_db()

# app = Flask("__main__")

client = razorpay.Client(auth=(os.getenv("RAZORPAY_KEY_ID"), os.getenv("RAZORPAY_KEY_SECRET")))

app.config['SQLALCHEMY_DATABASE_URI'] = 'postgresql://postgres:2006@localhost:5432/oddz'
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False



@app.route('/')
def landing():
    return render_template("landing.html")

@app.route('/logout')
def logout():
    session.clear()
    return redirect(url_for('landing'))

@app.route('/privacy')
def privacy():
    return render_template('privacy.html')

@app.route('/terms')
def terms():
    return render_template('terms.html')

@app.route('/contact')
def contact():
    return render_template('contact.html')

@app.route('/refund')
def refund():
    return render_template('refund.html')

@app.route('/payment')
def payment():
    return render_template("payment.html")

@app.route('/shipping')
def shipping():
    return render_template('/shipping.html')

@app.route('/Analytics')
def Analytics():
    subscription_check = check_admin()
    if subscription_check is not None:
        return subscription_check

    cur = conn.cursor()
    restaurants_id = session.get('restaurants_id')
    admin_id = session.get('admin_id')
    if not restaurants_id:
        return redirect(url_for('signin'))
    cur.execute("SELECT plan_name, status from subscriptions where admin_id=%s",(admin_id,))
    rows = cur.fetchall()
    row = rows[0]
    plan_name = row[0]
    status = row[1]
    menu = show_menu(restaurants_id)
    team = show_team(restaurants_id)
    orders_week = order_section(restaurants_id)
    money = revenue(restaurants_id)
    deletemenu = delete_menu()
    restaurant_name = session.get('restaurant_name')
    result = res(restaurants_id)
    return render_template("Analytics.html", money=money, orders_week=orders_week, menu = menu,team=team, deletemenu = deletemenu, restaurant_name = restaurant_name, chart_data=result, plan_name=plan_name, status=status)

def res(restaurant_id):
    if not restaurant_id:
        return "Restaurant is not regestered! Please contact to the devloper"
    cur = conn.cursor()
    today = datetime.today().date()
    start_date = today - timedelta(days=6)

    cur.execute("""
        SELECT DATE(order_time) AS date,
               COUNT(order_id) AS orders,
               SUM(total_amount) AS sales
        FROM orders
        WHERE DATE(order_time) BETWEEN %s AND %s 
              AND restaurant_id = %s
        GROUP BY DATE(order_time)
        ORDER BY DATE(order_time);
    """, (start_date, today, restaurant_id))

    data = cur.fetchall()
    cur.close()

    result = []
    for i in range(7):
        day = start_date + timedelta(days=i)
        found = next((x for x in data if x[0] == day), None)
        if found:
            result.append({
                "date": day.strftime("%Y-%m-%d"),
                "orders": found[1],
                "sales": float(found[2])
            })
        else:
            result.append({
                "date": day.strftime("%Y-%m-%d"),
                "orders": 0,
                "sales": 0.0
            })
    return result


@app.route('/api/chart_data', methods=['GET','POST'])
def get_chart_data():
    restaurants_id = session.get('restaurants_id')
    if not restaurants_id:
        return "doosra tareeka"
    cur = conn.cursor()
    
    today = datetime.today().date()
    start_date = today - timedelta(days=6)
    cur.execute("""SELECT
    DATE(order_time) AS date,
    COUNT(order_id) AS orders,
    SUM(total_amount) AS sales
    FROM orders
    WHERE
        DATE(order_time) BETWEEN %s AND %s AND restaurant_id = %s
    GROUP BY
        DATE(order_time)
    ORDER BY
        DATE(order_time);
    """, (start_date, today, restaurants_id))
    
    data = cur.fetchall()
    cur.close()

    result = []
    for i in range(7):
        day = start_date + timedelta(days=i)
        found = next((x for x in data if x[0] == day), None)
        if found:
            result.append({
                "date": day.strftime("%Y-%m-%d"), 
                "orders": found[1], 
                "sales": float(found[2]) 
            })
        else:
            result.append({
                "date": day.strftime("%Y-%m-%d"), 
                "orders": 0, 
                "sales": 0.0
            })
    return jsonify(result)


def order_section(restaurant_id):
    cur = conn.cursor()
    if restaurant_id:
        cur.execute("""SELECT
                    TO_CHAR(order_time, 'month') as Month_name,
                    COUNT(order_id) AS total_order
                    from orders
                    where restaurant_id = %s
                    GROUP by Month_name
                    order by Month_name;""", (restaurant_id,))
        
        orders_week = cur.fetchall()
        return orders_week
    return redirect(url_for('signin'))

def revenue(restaurant_id):
    cur = conn.cursor()
    if restaurant_id:
        cur.execute("""SELECT
                    DATE_TRUNC('month',order_time) AS Month,
                    SUM(total_amount) as total_amount
                    from orders
                    where restaurant_id = %s
                    GROUP BY Month
                    ORDER BY Month;""", (restaurant_id,))
        
        money = cur.fetchall()
        return money

def show_menu(restaurants_id):
    if restaurants_id:
        cur = conn.cursor()
        cur.execute("select * from menu where restaurants_id = %s", (restaurants_id,))
        menu = cur.fetchall()
        conn.commit()
        return menu
    return render_template('login')

def show_team(restaurants_id):
    if restaurants_id:
        cur = conn.cursor()
        cur.execute("select * from team where restaurants_id = %s", (restaurants_id,))
        team = cur.fetchall()
        conn.commit()
        return team
    return render_template('login')

@app.route('/delete_menu', methods=['GET','POST'])
def delete_menu():
    cur = conn.cursor()
    if request.method == 'POST':
        restaurants_id = session.get('restaurants_id')
        if not restaurants_id:
            return redirect(url_for('login'))
        
        item_name = request.form.get('name')
        price = request.form.get('price')
        cur.execute("DELETE from menu where restaurants_id = %s and item_name = %s and price = %s", (restaurants_id, item_name, price))
        conn.commit()
        return "Menu Has been Successfully deleted"
    return redirect(url_for('Analytics'))
    
@app.route('/delete_staff', methods=['GET','POST'])
def delete_staff():
    cur = conn.cursor()
    if request.method == 'POST':
        restaurants_id = session.get('restaurants_id')
        if not restaurants_id:
            return redirect(url_for('login'))
        
        name = request.form.get('name')
        role = request.form.get('role')
        cur.execute("DELETE from team where restaurants_id = %s and name = %s and role = %s", (restaurants_id, name, role))
        conn.commit()
        return "That staff details Has been Successfully deleted"
    return redirect(url_for('Analytics'))
    


@app.route('/Admin', methods=['GET', 'POST'])
def home():
    if request.method == 'POST':
        username = request.form['username']
        email = request.form['email']
        password = request.form['password']
        cpassword = request.form['confirm_password']
        admin_id = None
        hashed_password = generate_password_hash(password)
        if password == cpassword:
            cur.execute("INSERT INTO Admins (FullName, email, password) VALUES (%s, %s, %s)",(username, email, hashed_password))
            conn.commit()
            cur.execute("SELECT id FROM Admins WHERE email = %s", (email,))
            admin_id = cur.fetchone()[0]
            session['admin_id'] = admin_id
            return redirect(url_for('dashboard'))
        
        else:
            return "Passwords do not match. Please try again."
    return render_template('Admin.html')

@app.route('/details', methods=['GET','POST'])
def dashboard():
    admin_id = session.get('admin_id')
    if not admin_id:
        return redirect(url_for('signin'))
    if request.method == 'POST':
        Restaurant = request.form['restaurant_name']
        address = request.form['address']
        phone = request.form['phone']
        category = request.form['category']
        image = request.files['logo']
        image_path = None
        if image and image.filename != '':
            filename = secure_filename(image.filename)
            image_path = os.path.join('static/images', filename)
            image.save(image_path)
        
        cur.execute("INSERT INTO restaurants (admin_id, restaurant_name, address, phone, logo, category) values (%s, %s, %s, %s, %s, %s)", (admin_id, Restaurant, address, phone, image_path, category))
        conn.commit()

        cur.execute("SELECT id from restaurants where admin_id =%s",(admin_id,))
        restaurants_id = cur.fetchone()[0]
        session['restaurants_id'] = restaurants_id
        cur.execute("SELECT restaurant_name FROM restaurants WHERE admin_id = %s", (admin_id,))
        row = cur.fetchone()
        start_at = datetime.now()
        end_at = start_at + timedelta(days=30)
        cur.execute("insert into subscriptions(start_at, end_at, plan_name, status, active, admin_id)values(%s, %s, %s, %s, %s, %s) returning start_at",(start_at, end_at, 'trail', 'active', 'True', admin_id))
        conn.commit()
        session['restaurant_name'] = row[0] if row else "Unknown"
        return redirect(url_for('Analytics'))
    return render_template('details.html')

@app.route('/login',methods=['GET','POST'])
def signin():
    if request.method == 'POST':
        username = request.form['username']
        password = request.form['password']
        cur.execute("select password from admins where email=%s",(username,))
        result = cur.fetchone()
    
        if result and check_password_hash(result[0], password):
            cur.execute("SELECT id FROM Admins WHERE email = %s", (username,))
            admin_id = cur.fetchone()[0]
            session['admin_id'] = admin_id
            subscription_check = check_admin()
            if subscription_check is not None:
                return subscription_check
            cur.execute('SELECT id FROM restaurants WHERE admin_id = %s', (admin_id,))
            res_id = cur.fetchone()
            session['restaurants_id'] = res_id[0]
            cur.execute("SELECT restaurant_name FROM restaurants WHERE admin_id = %s", (admin_id,))
            row = cur.fetchone()
            session['restaurant_name'] = row[0] if row else "Unknown"
            subscription_check = check_admin()
            if subscription_check is not None:
                return subscription_check
            return redirect(url_for('Analytics'))
        else:
            return "Invalid credentials. Please try again."
    return render_template('signin.html')

@app.route('/main_dashboard', methods=['GET', 'POST'])
def main_dashboard():
    subscription_check = check_admin()
    if subscription_check is not None:
        return subscription_check
    cur = conn.cursor()
    admin_id = session.get('admin_id')
    restaurants_id = session.get('restaurants_id')
    if not admin_id:
        return redirect(url_for('signin'))
    restaurant_name = session.get('restaurant_name')
    return render_template('main_dashboard.html', restaurant_name=restaurant_name)

def check_admin():
    cur = conn.cursor()
    admin_id = session.get('admin_id')
    cur.execute("select start_at, end_at, status, active from subscriptions where admin_id=%s", (admin_id,))
    rows = cur.fetchall()
    if not rows:
        return "Please take a subscription plan." 
        
    row = rows[0] 
    start_at = row[0]
    end_at = row[1]
    status = row[2]
    active = row[3]
    # session_end = start_at + timedelta(hours=5, minutes=54)
    is_expired = datetime.now() > end_at
    # is_expired = datetime.now() > session_end
    
    if is_expired or status != 'active' or active != 'True':
        cur.execute("update subscriptions set status=%s, active=%s where admin_id=%s", ('expired', 'False', admin_id))
        conn.commit()
        return redirect(url_for('payment'))
    else:
        return None
    
@app.route('/add_menu')
def add_menu():
    if request.method == 'POST':
        pass

@app.route('/add_multiple_menu', methods=['GET', 'POST'])
def add_multiple_menu():
    if request.method == 'POST':
        cur = conn.cursor()
        item_count = 0
        while f'name_{item_count}' in request.form:
            item_count += 1
        for i in range(item_count):
            item_name = request.form.get(f'name_{i}')
            about = request.form.get(f'about_{i}')
            price = request.form.get(f'price_{i}')
            category = request.form.get(f'category_{i}')
            admin_id = session.get('admin_id')
            restaurants_id = session.get('restaurants_id')
            cur.execute(
                "INSERT INTO menu (restaurants_id, admins_id, item_name, about, price, category) VALUES (%s, %s, %s, %s, %s, %s)",(restaurants_id, admin_id, item_name, about, price, category)
            )
        conn.commit()
        return jsonify({"message": "Menu items added successfully!"})
    return render_template('menu.html')

@app.route('/menu', methods=['GET', 'POST'])
def menu():
    subscription_check = check_admin()
    if subscription_check is not None:
        return subscription_check
    admin_id = session.get('admin_id')
    if not admin_id:
        return redirect(url_for('signin'))
    restaurant_name = session.get('restaurant_name')
    return render_template('menu.html', restaurant_name = restaurant_name)

@app.route('/team', methods=['GET', 'POST'])
def team():
    subscription_check = check_admin()
    if subscription_check is not None:
        return subscription_check
    admin_id = session.get('admin_id')
    if not admin_id:
        return redirect(url_for('signin'))
    restaurant_name = session.get('restaurant_name')
    return render_template('team.html', restaurant_name = restaurant_name)

@app.route('/add_multiple_team', methods=['GET', 'POST'])
def add_multiple_team():
    if request.method == 'POST':
        cur = conn.cursor()
        i = 0
        member_count = 0
        while f'name_{member_count}' in request.form:
            member_count += 1
        for i in range(member_count):
            name = request.form.get(f'name_{i}')
            role = request.form.get(f'role_{i}')
            contact = request.form.get(f'contact_{i}')
            restaurants_id = session.get('restaurants_id')
            admin_id = session.get('admin_id')
            cur.execute(
                "INSERT INTO team (restaurants_id, name, role, phone) VALUES (%s, %s, %s, %s)",(restaurants_id, name, role, contact)
            )
        conn.commit()
        cur.close()
        return jsonify({"message":"Team members added successfully!"})

    return redirect(url_for('team'))

@app.route("/generate_qrs_json", methods=['POST'])
def generate_qrs_json():
    cur = conn.cursor()
    admin_id = session.get('admin_id')
    restaurants_id = session.get('restaurants_id')
    data = request.get_json() 
    table_Count = int(data.get('tableCount', 0)) 
    
    if not admin_id or not restaurants_id:
        return jsonify({"error": "Admin or Restaurant ID missing from session."}), 401
    
    if table_Count <= 0:
        return jsonify({"error": "Invalid table count received."}), 400
    
    cur.execute("SELECT plan_name, status from subscriptions where admin_id=%s",(admin_id,))
    rows = cur.fetchall()
    for row in rows:
        plan_name = row[0]
        status = row[1]

    if plan_name == 'trail' or table_Count <= 10:
        qr_data = []
        for i in range(1, table_Count + 1):
            unique_token = str(uuid.uuid4())

            cur.execute("""INSERT INTO qr_token (token, admin_id, restaurant_id, table_number)
                        VALUES (%s, %s, %s, %s)
                        ON CONFLICT (restaurant_id, table_number) DO UPDATE SET token = EXCLUDED.token;""", (unique_token, admin_id, restaurants_id, i))
            
            conn.commit()
            link = url_for(
                'orderpage',
                token=unique_token,
                _external=True
            )

            qr = qrcode.make(link)
            filename = f'qr_{restaurants_id}_{i}.png'
                

            buffer = io.BytesIO()
            qr.save(buffer, format="PNG")
            buffer.seek(0)

            qr_base64 = base64.b64encode(buffer.read()).decode("utf-8")
            img_data = f"data:image/png;base64,{qr_base64}"

            qr_data.append({"path": filename,"link": link, "image":img_data})
            
        return jsonify({"message": "QR Codes Generated", "qrs":qr_data})
    
    elif plan_name == 'basic' and table_Count <= 5:
    
        qr_data = []
        for i in range(1, table_Count + 1):
            unique_token = str(uuid.uuid4())

            cur.execute("""INSERT INTO qr_token (token, admin_id, restaurant_id, table_number)
                        VALUES (%s, %s, %s, %s)
                        ON CONFLICT (restaurant_id, table_number) DO UPDATE SET token = EXCLUDED.token;""", (unique_token, admin_id, restaurants_id, i))
            
            conn.commit()
            link = url_for(
                'orderpage',
                token=unique_token,
                _external=True
            )

            qr = qrcode.make(link)
            filename = f'qr_{restaurants_id}_{i}.png'
                

            buffer = io.BytesIO()
            qr.save(buffer, format="PNG")
            buffer.seek(0)

            qr_base64 = base64.b64encode(buffer.read()).decode("utf-8")
            img_data = f"data:image/png;base64,{qr_base64}"

            qr_data.append({"path": filename,"link": link, "image":img_data})
            
        return jsonify({"message": "QR Codes Generated", "qrs":qr_data})
        

    elif plan_name == 'moderate' and table_Count<=10:
        qr_data = []
        for i in range(1, table_Count + 1):
            unique_token = str(uuid.uuid4())

            cur.execute("""INSERT INTO qr_token (token, admin_id, restaurant_id, table_number)
                        VALUES (%s, %s, %s, %s)
                        ON CONFLICT (restaurant_id, table_number) DO UPDATE SET token = EXCLUDED.token;""", (unique_token, admin_id, restaurants_id, i))
            
            conn.commit()
            link = url_for(
                'orderpage',
                token=unique_token,
                _external=True
            )
            qr = qrcode.make(link)
            filename = f'qr_{restaurants_id}_{i}.png'
                

            buffer = io.BytesIO()
            qr.save(buffer, format="PNG")
            buffer.seek(0)

            qr_base64 = base64.b64encode(buffer.read()).decode("utf-8")
            img_data = f"data:image/png;base64,{qr_base64}"

            qr_data.append({"path": filename,"link": link, "image":img_data})
            
        return jsonify({"message": "QR Codes Generated", "qrs":qr_data})

    elif plan_name == 'standard':
        qr_data = []
        for i in range(1, table_Count + 1):
            unique_token = str(uuid.uuid4())

            cur.execute("""INSERT INTO qr_token (token, admin_id, restaurant_id, table_number)
                        VALUES (%s, %s, %s, %s)
                        ON CONFLICT (restaurant_id, table_number) DO UPDATE SET token = EXCLUDED.token;""", (unique_token, admin_id, restaurants_id, i))
            
            conn.commit()
            link = url_for(
                'orderpage',
                token=unique_token,
                _external=True
            )

            qr = qrcode.make(link)
            filename = f'qr_{restaurants_id}_{i}.png'
                

            buffer = io.BytesIO()
            qr.save(buffer, format="PNG")
            buffer.seek(0)

            qr_base64 = base64.b64encode(buffer.read()).decode("utf-8")
            img_data = f"data:image/png;base64,{qr_base64}"

            qr_data.append({"path": filename,"link": link, "image":img_data})
            
        return jsonify({"message": "QR Codes Generated", "qrs":qr_data})
    
    else:
        return jsonify({'error':"You Are Accsseding the QR generation Limit."})


    # qr_data = []
    # for i in range(1, table_Count + 1):
    #     link = url_for(
    #         'orderpage',
    #         admin_id=admin_id,
    #         restaurant_id=restaurants_id,
    #         table_number=i,
    #         _external=True
    #     )
        
    #     qr = qrcode.make(link)
    #     filename = f'qr_{restaurants_id}_{i}.png'
        

    #     buffer = io.BytesIO()
    #     qr.save(buffer, format="PNG")
    #     buffer.seek(0)

    #     qr_base64 = base64.b64encode(buffer.read()).decode("utf-8")
    #     img_data = f"data:image/png;base64,{qr_base64}"

    #     qr_data.append({"path": filename,"link": link, "image":img_data})
    
    # return jsonify({"message": "QR Codes Generated", "qrs":qr_data})


@app.route("/qr")
def qr_generation_page():
    subscription_check = check_admin()
    if subscription_check is not None:
        return subscription_check
    admin_id = session.get('admin_id')
    if not admin_id:
        return redirect(url_for('signin'))
    
    restaurant_name = session.get('restaurant_name')
    return render_template("qrgeneration.html", restaurant_name=restaurant_name)

@app.route("/order/<string:token>", methods=['GET','POST'])
def orderpage(token):
    cur = conn.cursor()
    cur.execute("""SELECT q.admin_id, r.id, q.table_number, r.restaurant_name 
                FROM qr_token q 
                JOIN restaurants r ON r.id=q.restaurant_id 
                WHERE q.token = %s""", (token,))
    rows = cur.fetchone()
    
    if not rows:
        return "Invalid QR Code or Token not found.", 404
    row = rows    
    admin_id = row[0]
    restaurant_id = row[1]
    table_number = row[2]
    restaurant_name = row[3]
    session['table_number']=table_number
    session['restaurant_name']=restaurant_name
    session['restaurants_id']=restaurant_id
    session['admin_id']=admin_id

    if not restaurant_id:
        return "didnt get admin_id"
    menu = fetch_menu(restaurant_id)
    cur.execute("SELECT restaurant_name from restaurants where id = %s and admin_id = %s", (restaurant_id, admin_id))
    naam = cur.fetchone()
    branch = naam[0]
    return render_template('orderpage.html', menu=json.dumps(menu), restaurant_name = branch, restaurant_id=restaurant_id, table_number=table_number)

def fetch_menu(restaurant_id):
    cur = conn.cursor()
    cur.execute("SELECT id, item_name, about, price, category FROM menu WHERE restaurants_id = %s group by menu.id, menu.category", (restaurant_id,))
    rows = cur.fetchall()
    data = []
    for row in rows:
        data.append({ 
            "id" : row[0],
            "item_name" : row[1],
            "about" : row[2],
            "price" : float(row[3]),
            "category" : (row[4]).capitalize()
         })
    cur.close()
    return data

#     cur.execute("SELECT restaurant_name FROM admins WHERE id = %s", (restaurant_id,))
#     restaurant = cur.fetchone()
#     cur.close()
#     restaurant_name = restaurant[0] if restaurant else ""
#     return render_template("orderpage.html", menu=menu, restaurant_name=restaurant_name)

@app.route("/kitchen_dashboard")
def kitchen_dashboard():
    subscription_check = check_admin()
    if subscription_check is not None:
        return subscription_check 
    restaurant_name = session.get('restaurant_name')
    return render_template("kitchen_dashboard.html", restaurant_name = restaurant_name)

@app.route("/place_order", methods=['GET','POST'])
def place_order():
    restaurant_name = session.get('restaurant_name')
    if request.method == 'POST':
        if not restaurant_name:
            print("restaurant_name", restaurant_name)
            return "try another way"
        table_number = session.get('table_number')
        if not table_number:
            return "table_number not found in request"
        data = request.get_json()
        restaurants_id = session.get('restaurants_id')
        items = data.get('items')
        txn_id = data.get('txn_id')
        #--- item_content = json.dumps(item_name) ---#
        # total_amount = sum(float(i['price']) for i in items)
        total_amount = data.get('total_amount')
        cur = conn.cursor()
        cur.execute(
            "INSERT into Orders (restaurant_id, table_number, total_amount, txn_id) Values (%s, %s, %s, %s) RETURNING order_id", (restaurants_id, table_number, total_amount, txn_id)
        )
        order_id = cur.fetchone()[0]
        conn.commit()
        order_time = datetime.now()
        cur.execute("select status from orders where order_id = %s and table_number = %s",(order_id,table_number))
        sta = cur.fetchone()
        status = sta[0] if sta else 0
        for item in items:
            menu_item_id = item.get('id')
            price = item.get('price')
            quantity = item.get('quantity')

            cur.execute('INSERT INTO order_items(order_id, menu_item_id, quantity, price) values (%s, %s, %s, %s)', (order_id, menu_item_id, quantity, price))
            conn.commit()
        socketio.emit("new_order", {"message": "order placed"})
        pdf_base64 = generate_slip(restaurant_name, order_id, table_number, items, total_amount, txn_id)
        return jsonify({"message": "Thank You for the Order.","order_id": order_id, "status": status, "pdf_data": pdf_base64})

def generate_slip(restaurant_name, order_id, table_number, items, total_amount, txn_id):
    buffer = io.BytesIO()
    c = canvas.Canvas(buffer, pagesize=A4)

    c.setFont("Helvetica-Bold", 16)
    c.drawString(250, 800,f"{restaurant_name}")

    c.setFont("Helvetica", 12)
    c.drawString(50, 770, f"Order Id: {order_id}")
    c.drawString(50, 750, f"Table Number: {table_number}")
    c.drawString(50, 730, f"Payment Type/ID: {txn_id}")
    c.drawString(50, 710, f"Date: {datetime.now().strftime('%d-%m-%Y %H:%M:%S')}")

    y = 680
    cur = conn.cursor()
    for item in items:
        # c.drawString(50, y, str(item.get('id')))
        cur.execute("SELECT item_name from menu where id = %s",(item.get('id'),))
        nm = cur.fetchone()
        name = nm[0] if nm else 0
        c.drawString(50, y, str(name))
        c.drawString(300, y, str(item.get('price')))
        c.drawString(200, y, str(item.get('quantity')))
        y -= 20

    c.setFont("Helvetica-Bold", 12)
    c.drawString(50, y - 20, f"Total:{total_amount}")

    c.showPage()
    c.save()
    buffer.seek(0)

    pdf_base64 = base64.b64encode(buffer.getvalue()).decode("utf-8")
    return pdf_base64

@app.route("/get_orders")
def get_orders():
    conn = psycopg2.connect(DATABASE_URL)
    cur = conn.cursor()
    restaurant_id = session.get('restaurants_id')
    cur.execute("""
            SELECT 
                o.order_id AS order_id,
                o.table_number,
                o.total_amount,
                o.status,
                To_char(o.order_time, 'HH12:MI:SS AM') AS order_time,
                json_agg(json_build_object(
                    'item_name', m.item_name,
                    'price', oi.price,
                    'quantity', oi.quantity
                )) AS items
            FROM orders o
            JOIN order_items oi ON o.order_id = oi.order_id
            JOIN menu m ON oi.menu_item_id = m.id
            where restaurants_id = %s
            and o.order_time >= NOW() - interval '24 hours'
            GROUP BY o.order_id, o.table_number, o.total_amount
            ORDER BY o.order_id DESC;
        """,(restaurant_id,))
    rows = cur.fetchall()
    orders = []
    for r in rows:
        orders.append({
            "order_id": r[0],
            "table_number": r[1],
            "total_amount": float(r[2]),
            "status":r[3],
            "order_time": r[4],
            "items": r[5]
        })

    conn.close()
    return jsonify(orders)
    

@app.route('/update_status',methods=['GET','POST'])
def update_status():
    cur = conn.cursor()
    if request.method == "POST":
        data = request.json
        order_id = data.get("order_id")
        status = data.get("status")
        if not order_id or not status:
            print("order_id",order_id)
            print("status",status)
            return jsonify({"error":"Invalid request"}), 100
        try:
            cur.execute("UPDATE orders SET status = %s where order_id = %s RETURNING status", (status, order_id))
            conn.commit()
            status = cur.fetchone()
            updated_status = status[0] if status else 0
            cur.close()
            if updated_status:
                socketio.emit("status_update", {"order_id": order_id, "status": updated_status})
                return jsonify({"success": True, "status": updated_status})
            else:
                return jsonify({"success": False, "error":"Order not found"})
        except Exception as e:
            conn.rollback()
            return jsonify({"success":False, "error": str(e)}), 500
        


@app.route('/get_upi', methods=['GET','POST'])
def get_upi():
    admin_id = session.get('admin_id')
    if request.method == 'POST':
        if not admin_id:
            return redirect(url_for('signin'))
        cur = conn.cursor()
        upi_id = request.form.get('upi_id')

        cur.execute("INSERT INTO payment_credentials (admin_id, upi_id) values(%s, %s)",(admin_id, upi_id))
        conn.commit()
        return "All Set To Recive Payments"
    return redirect(url_for('settings'))

def get_admin_upi(admin_id):
    cur = conn.cursor()
    cur.execute("SELECT upi_id from payment_credentials where admin_id = %s", (admin_id,))
    row = cur.fetchone()
    return row if row else None

@app.route('/checkout', methods=['GET','POST'])
def checkout():
    data = request.json
    admin_id = session.get('admin_id')
    total_amount = data.get('total_amount')
    upi_id = get_admin_upi(admin_id)
    if not upi_id:
        return jsonify({"error":"Upi id not found for this admin"})
    
    deeplink = f"upi://pay?pa={upi_id}&pn=Restaurant&am={total_amount}&cu=INR&tn=Food%2Order"

    return jsonify({"deeplink":deeplink})

@app.route('/change_password' , methods=['GET', 'POST'])
def change_password():
    if request.method == 'POST':
        cur = conn.cursor()
        admin_id = session.get('admin_id')
        if not admin_id:
            return redirect(url_for('signin'))
        currentpassword = request.form.get('currentpassword')
        newpassword = request.form.get('newpassword')
        confirmpassword = request.form.get('confirmpassword')

        cur.execute("select password from admins where id = %s" , (admin_id,))
        result = cur.fetchone()

        if not result:
            return "User not found"
        current_hashed_password = result[0]

        if not check_password_hash(current_hashed_password, currentpassword):
            return "Incorrect password"
        
        if newpassword != confirmpassword:
            return "Password do not match"
        
        hashed_password = generate_password_hash(newpassword)

        cur.execute("update admins set password = %s where id = %s", (hashed_password, admin_id))
        conn.commit()
        cur.close()

        return "Password updated successfully!"
    return redirect(url_for('settings'))

@app.route('/update_upi', methods=['GET','POST'])
def update_upi():
    if request.method == 'POST':
        cur = conn.cursor()
        upi_id = request.form.get('upi_id')
        admin_id = session.get('admin_id')
        cur.execute("Update payment_credentials SET upi_id=%s where admin_id=%s", (upi_id, admin_id))
        conn.commit()
        cur.close()
        return "UPI has been updated successfully."

@app.route('/settings', methods=["GET","POST"])
def settings():
    subscription_check = check_admin()
    if subscription_check is not None:
        return subscription_check
    cur = conn.cursor()
    restaurant_name = session.get('restaurant_name')
    admin_id = session.get('admin_id')
    restaurants_id = session.get('restaurants_id')
    if not admin_id:
        return redirect(url_for('signin'))
    if request.method == 'POST':
        if admin_id :
            cur.execute('delete from team where restaurants_id = %s',(restaurants_id,))
            conn.commit()
            cur.execute('delete from menu where restaurants_id = %s',(restaurants_id,))
            conn.commit()
            cur.execute('delete from restaurants where admin_id = %s',(admin_id,))
            conn.commit()
            cur.execute('delete from admins where id = %s',(admin_id,))
            conn.commit()
            cur.close()
            session.clear()
            return "Your account has been deleted successfully."
        return render_template("Admin.html")
    return render_template('settings.html', restaurant_name = restaurant_name, admin_id = admin_id, restaurant_id = restaurants_id)

@app.route('/staff_login', methods=['GET','POST'])
def staff_login():
    cur = conn.cursor()
    if request.method == 'POST':
        name = request.form.get('name')
        role = request.form.get('role')
        phone = request.form.get('contact')
        cur.execute("SELECT name , restaurants_id FROM team WHERE name=%s AND role=%s AND phone=%s", (name, role, phone))
        rows = cur.fetchall()
        for row in rows:
            result = row[0]
            restaurant_id = row[1]

        session['restaurants_id'] = restaurant_id
        if result:
            db_name = result
            if db_name.lower() == name.lower():
                return redirect(url_for('kitchen_dashboard', restaurant_id=restaurant_id))
        
        return "You have entered wrong details!"
    
    return render_template("staff_login.html")



@app.after_request
def add_header(response):
    response.headers['Cache-Control'] = 'no-store, no-cache, must-revalidate, post-check=0, pre-check=0, max-age=0'
    response.headers['Pragma'] = 'no-cache'
    response.headers['Expires'] = '-1'
    return response

if __name__ == "__main__":
    import os
    port = int(os.environ.get("PORT", 10000))
    socketio.run(app, host="0.0.0.0", port=port)
