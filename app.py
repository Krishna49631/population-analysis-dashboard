import os
import mysql.connector
import sqlite3
import traceback
import pandas as pd
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import seaborn as sns
import io
import base64
from flask import Flask, render_template, request, jsonify, url_for, session, flash, redirect
from flask_cors import CORS
from werkzeug.security import generate_password_hash, check_password_hash
from dotenv import load_dotenv


ADMIN_USERNAME = os.getenv("ADMIN_USERNAME", "admin")  # Default "admin" agar nahi mile to

load_dotenv()

app = Flask(__name__)
CORS(app)
app.secret_key = os.getenv("FLASK_SECRET_KEY", "dev_secret")

# -------------------------------
# MySQL Database Configuration
# -------------------------------
def get_db():
    # Production (Render) mein SQLite use karein
    if os.environ.get('RENDER'):
        import sqlite3
        # SQLite database create karein
        conn = sqlite3.connect('/tmp/population_analysis.db')
        return conn
    else:
        # Local development mein MySQL use karein
        return mysql.connector.connect(
            host=os.getenv("DB_HOST", "localhost"),
            user=os.getenv("DB_USER", "root"),
            password=os.getenv("DB_PASSWORD", ""),
            database=os.getenv("DB_NAME", "population_analysis")
        )

def init_db():
    db = get_db()
    cursor = db.cursor()
    
    # SQLite compatible table creation
    if os.environ.get('RENDER'):
        # Users table
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS users (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                username TEXT UNIQUE NOT NULL,
                password_hash TEXT NOT NULL,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)
        # Feedback table - SQLite version
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS feedback (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                username TEXT NOT NULL,
                email TEXT,
                message TEXT NOT NULL,
                rating INTEGER,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)
    else:
        # MySQL tables
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS users (
                id INT AUTO_INCREMENT PRIMARY KEY,
                username VARCHAR(50) UNIQUE NOT NULL,
                password_hash VARCHAR(255) NOT NULL,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS feedback (
                id INT AUTO_INCREMENT PRIMARY KEY,
                username VARCHAR(50) NOT NULL,
                email VARCHAR(100),
                message TEXT NOT NULL,
                rating INT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)
    
    db.commit()
    cursor.close()
    db.close()

init_db()

# -------------------------------
# Load Dataset Once, Globally
# -------------------------------
DATASET_PATH = "Dataset.csv"
if not os.path.exists(DATASET_PATH):
    raise FileNotFoundError("Dataset file not found: 'dataset.csv'")

df = pd.read_csv(DATASET_PATH)
df.columns = df.columns.str.strip()
df["state_name"] = df["state_name"].str.strip().str.upper()

# For literacy analysis (filter columns)
literacy_columns = [
    'name_of_city', 'state_name', 'population_total',
    'effective_literacy_rate_total', 'effective_literacy_rate_male',
    'effective_literacy_rate_female'
]
df_literacy = df[literacy_columns].dropna()

# -------------------------------
# Authentication Routes
# -------------------------------
@app.route("/", methods=["GET", "POST"])
def login():
    if "user" in session:
        return redirect(url_for("dashboard"))
    
    if request.method == "POST":
        username = request.form["username"]
        password = request.form["password"]

        db = get_db()
        
        # SQLite compatible cursor
        if os.environ.get('RENDER'):
            cursor = db.cursor()
            cursor.row_factory = sqlite3.Row
        else:
            cursor = db.cursor(dictionary=True)
            
        cursor.execute("SELECT * FROM users WHERE username=?", (username,))
        user = cursor.fetchone()
        cursor.close()
        db.close()

        # SQLite compatible data access
        if user:
            if os.environ.get('RENDER'):
                # SQLite: user[0]=id, user[1]=username, user[2]=password_hash
                password_hash = user[2]
            else:
                # MySQL: user["password_hash"]
                password_hash = user["password_hash"]
            
            if check_password_hash(password_hash, password):
                session["user"] = username
                flash("Login successful!", "success")
                return redirect(url_for("dashboard"))

        flash("Invalid credentials", "danger")
        return redirect(url_for("login"))

    return render_template("login.html")

@app.route("/register", methods=["GET", "POST"])
def register():
    if "user" in session:
        return redirect(url_for("dashboard"))
    
    if request.method == "POST":
        username = request.form["username"]
        password = request.form["password"]
        password2 = request.form["password2"]

        if password != password2:
            flash("Passwords do not match", "danger")
            return redirect(url_for("register"))

        password_hash = generate_password_hash(password)

        try:
            db = get_db()
            cursor = db.cursor()
            
            # SQLite compatible query
            if os.environ.get('RENDER'):
                cursor.execute("INSERT INTO users (username, password_hash) VALUES (?, ?)", 
                              (username, password_hash))
            else:
                cursor.execute("INSERT INTO users (username, password_hash) VALUES (%s, %s)", 
                              (username, password_hash))
                              
            db.commit()
            cursor.close()
            db.close()
        except Exception as e:
            flash(f"Registration error: {str(e)}", "danger")
            return redirect(url_for("register"))

        flash("Registration successful. Please login.", "success")
        return redirect(url_for("login"))

    return render_template("register.html")

@app.route("/dashboard")
def dashboard():
    if "user" not in session:
        flash("Please login first", "warning")
        return redirect(url_for("login"))
    return render_template("dashboard.html", user=session["user"])

@app.route("/logout")
def logout():
    session.pop("user", None)
    flash("Logged out", "info")
    return redirect(url_for("login"))
# -------------------------------
# Protected Analysis Routes
# -------------------------------
@app.route('/literacy')
def literacy_rate():
    if "user" not in session:
        flash("Please login first", "warning")
        return redirect(url_for("login"))
    return render_template('literacy_rate.html')

@app.route('/comparison')
def comparison():
    if "user" not in session:
        flash("Please login first", "warning")
        return redirect(url_for("login"))
    return render_template('comparison.html')

@app.route('/employment')
def employment():
    if "user" not in session:
        flash("Please login first", "warning")
        return redirect(url_for("login"))
    return render_template('EMPLOYMENT.html')

@app.route('/unemployment')
def unemployment():
    if "user" not in session:
        flash("Please login first", "warning")
        return redirect(url_for("login"))
    return render_template('unployment.html')

# ---- B) Analyze Literacy (Histogram)
@app.route('/analyze', methods=['POST'])
def analyze():
    """
    Creates a histogram of the state's literacy rates 
    and returns it as base64-encoded PNG.
    """
    try:
        data = request.json
        state_name = data.get('state_name', '').strip().upper()
        if not state_name:
            return jsonify({'error': "State name is required"}), 400

        # Filter the dataset for the given state
        df_state = df_literacy[df_literacy['state_name'].str.contains(state_name, case=False, na=False)]
        if df_state.empty:
            return jsonify({'error': f"No data available for {state_name}"}), 404

        # Plot: Literacy Rate Distribution
        plt.figure(figsize=(10, 5))
        sns.histplot(df_state['effective_literacy_rate_total'], bins=30, kde=True)
        plt.xlabel("Total Literacy Rate (%)")
        plt.ylabel("Frequency")
        plt.title(f"Literacy Rate Distribution in {state_name}")

        # Convert the figure to base64
        img = io.BytesIO()
        plt.savefig(img, format='png')
        img.seek(0)
        graph_url = base64.b64encode(img.getvalue()).decode()
        plt.close()

        return jsonify({
            'graph': f"data:image/png;base64,{graph_url}",
            'state': state_name
        })
    except Exception as e:
        return jsonify({'error': str(e)}), 500

# ---- C) Compare Two States (Population, Literacy, etc.)
def generate_comparison_graph(state1, state2, df):
    """
    Compare two states on:
      - population_total
      - effective_literacy_rate_total
      - sex_ratio
      - total_graduates
    """
    statewise_data = df.groupby("state_name").agg({
        "population_total": "sum",
        "effective_literacy_rate_total": "mean",
        "sex_ratio": "mean",
        "total_graduates": "sum"
    }).reset_index()

    selected_states = statewise_data[statewise_data["state_name"].isin([state1, state2])]
    if selected_states.empty or len(selected_states) < 2:
        return None

    states = selected_states["state_name"].values
    metrics = ["Population", "Literacy Rate", "Sex Ratio", "Total Graduates"]
    values = [
        selected_states["population_total"].values,
        selected_states["effective_literacy_rate_total"].values,
        selected_states["sex_ratio"].values,
        selected_states["total_graduates"].values
    ]

    fig, axes = plt.subplots(2, 2, figsize=(12, 10))
    palettes = ["viridis", "coolwarm", "magma", "cubehelix"]

    for i, ax in enumerate(axes.flat):
        sns.barplot(x=states, y=values[i], ax=ax, palette=palettes[i])
        ax.set_title(f"{metrics[i]} Comparison")
        ax.set_ylabel(metrics[i])

    plt.tight_layout()
    img = io.BytesIO()
    plt.savefig(img, format='png')
    img.seek(0)
    graph_url = base64.b64encode(img.getvalue()).decode()
    plt.close()
    return f"data:image/png;base64,{graph_url}"


@app.route('/compare_states', methods=['POST'])
def compare_states():
    """
    Compare two states on various metrics 
    (population, literacy, etc.)
    """
    try:
        data = request.json
        state1 = data.get("state1", "").strip().upper()
        state2 = data.get("state2", "").strip().upper()

        if not state1 or not state2:
            return jsonify({"error": "Both states must be provided"}), 400

        valid_states = set(df["state_name"].unique())
        if state1 not in valid_states or state2 not in valid_states:
            return jsonify({"error": "Invalid state names"}), 400

        graph_url = generate_comparison_graph(state1, state2, df)
        if graph_url is None:
            return jsonify({"error": "Insufficient data"}), 404

        return jsonify({"graph": graph_url})
    except Exception as e:
        return jsonify({"error": str(e)}), 500

# ---- D) Top States (e.g. Unemployment Rate)
@app.route('/top_states', methods=['GET'])
def top_states():
    """
    Example route to show top states by 
    'Estimated Unemployment Rate (%)'.
    """
    try:
        if "Estimated Unemployment Rate (%)" not in df.columns:
            return jsonify({"error": "Estimated Unemployment Rate (%) column not found"}), 400

        top_states = (
            df.groupby("state_name")["Estimated Unemployment Rate (%)"]
            .mean().sort_values(ascending=False)
            .head(10)
        )
        return jsonify(top_states.to_dict())
    except Exception as e:
        return jsonify({"error": str(e)}), 500

# ---- E) Analyze a Single State's Unemployment
@app.route('/analyze_state', methods=['POST'])
def analyze_state():
    """
    Example route for analyzing unemployment data 
    (Estimated Employed, Region, etc.)
    """
    try:
        data = request.json
        state_name = data.get("state_name", "").strip().upper()

        if not state_name:
            return jsonify({"error": "State name is required"}), 400

        df_state = df[df["state_name"] == state_name]
        if df_state.empty:
            return jsonify({"error": "No data available for the entered state."}), 404

        # Example: Sort by 'Estimated Unemployment Rate (%)'
        # then plot a bar chart of 'Estimated Employed' by Region
        if "Estimated Unemployment Rate (%)" not in df.columns or "Region" not in df.columns:
            return jsonify({"error": "Required columns not found"}), 400

        df_sorted = df_state.sort_values(by="Estimated Unemployment Rate (%)", ascending=False).head(10)
        if "Estimated Employed" not in df.columns:
            return jsonify({"error": "No 'Estimated Employed' column found"}), 400

        img = io.BytesIO()
        plt.figure(figsize=(10,5))
        sns.barplot(x="Region", y="Estimated Employed", data=df_sorted, color="blue", alpha=0.7)
        plt.xlabel("Region")
        plt.ylabel("Estimated Employed")
        plt.title(f"Employment in {state_name}")
        plt.xticks(rotation=45)
        plt.tight_layout()
        plt.savefig(img, format='png')
        img.seek(0)
        graph_url = base64.b64encode(img.getvalue()).decode()
        plt.close()

        return jsonify({"graph": f"data:image/png;base64,{graph_url}"})
    except Exception as e:
        return jsonify({"error": str(e)}), 500

# ---- F) Another Example Route for 4-plot Employment Analysis
@app.route('/analyze_employment', methods=['POST'])
def analyze_employment():
    try:
        data = request.json
        region_name = data.get("region_name", "").strip()
        if not region_name:
            return jsonify({"error": "Please provide a region name"}), 400

        # Debug: Check available columns
        print("Available columns:", df.columns.tolist())
        
        # Find region-like columns
        region_columns = [col for col in df.columns if 'region' in col.lower() or 'state' in col.lower() or 'area' in col.lower()]
        
        if not region_columns:
            return jsonify({"error": "No region/state columns found in dataset. Available columns: " + str(df.columns.tolist())}), 400

        # Use first available region column
        region_col = region_columns[0]
        state_data = df[df[region_col].astype(str).str.lower() == region_name.lower()]
        
        if state_data.empty:
            available_regions = df[region_col].astype(str).unique().tolist()
            return jsonify({
                "error": f"No data found for: {region_name}. Available {region_col}s: {available_regions}"
            }), 404

        # Find employment-related column
        employed_cols = [col for col in df.columns if 'employed' in col.lower() or 'employment' in col.lower()]
        if not employed_cols:
            return jsonify({"error": "No employment-related columns found. Available columns: " + str(df.columns.tolist())}), 400
        
        employed_col = employed_cols[0]

        # Create simple plot instead of 4-subplot
        plt.figure(figsize=(10, 6))
        sns.histplot(state_data[employed_col], bins=10, kde=True)
        plt.title(f"Employment Distribution in {region_name}")
        plt.xlabel(employed_col)
        plt.ylabel("Frequency")

        # Convert the figure to base64
        img = io.BytesIO()
        plt.savefig(img, format='png')
        img.seek(0)
        graph_b64 = base64.b64encode(img.getvalue()).decode()
        plt.close()

        return jsonify({
            "message": "Success",
            "region": region_name,
            "graph": f"data:image/png;base64,{graph_b64}",
            "used_column": employed_col
        })
        
    except Exception as e:
        return jsonify({"error": str(e), "traceback": str(traceback.format_exc())}), 500
    
# -------------------------------
# Feedback Routes
# -------------------------------
@app.route("/feedback", methods=["GET", "POST"])
def feedback():
    if "user" not in session:
        flash("Please login first to submit feedback", "warning")
        return redirect(url_for("login"))
    
    if session["user"] != ADMIN_USERNAME:
        flash("⛔ Access denied. Admin only feature.", "danger")
        return redirect(url_for("dashboard"))
    
    if request.method == "POST":
        email = request.form.get("email", "")
        message = request.form.get("message", "")
        rating = request.form.get("rating", 5)
        
        if not message:
            flash("Please enter your feedback message", "danger")
            return redirect(url_for("feedback"))
        
        try:
            db = get_db()
            cursor = db.cursor()
            
            # SQLite compatible query
            if os.environ.get('RENDER'):
                cursor.execute(
                    "INSERT INTO feedback (username, email, message, rating) VALUES (?, ?, ?, ?)",
                    (session["user"], email, message, rating)
                )
            else:
                cursor.execute(
                    "INSERT INTO feedback (username, email, message, rating) VALUES (%s, %s, %s, %s)",
                    (session["user"], email, message, rating)
                )
                
            db.commit()
            cursor.close()
            db.close()
            
            flash("Thank you for your feedback! 💖", "success")
            return redirect(url_for("dashboard"))
            
        except Exception as e:
            flash(f"Error submitting feedback: {str(e)}", "danger")
            return redirect(url_for("feedback"))
    
    return render_template("feedback.html", user=session["user"])

# -------------------------------
# Feedback Routes
# -------------------------------
@app.route("/view_feedback")
def view_feedback():
    if "user" not in session:
        flash("Please login first", "warning")
        return redirect(url_for("login"))
    
    if session["user"] != ADMIN_USERNAME:
        flash("⛔ Access denied. Admin only feature.", "danger")
        return redirect(url_for("dashboard"))
    
    try:
        db = get_db()
        
        # SQLite compatible cursor
        if os.environ.get('RENDER'):
            cursor = db.cursor()
            cursor.row_factory = sqlite3.Row  # ← Yahaan fix karein
        else:
            cursor = db.cursor(dictionary=True)
            
        cursor.execute("SELECT * FROM feedback ORDER BY created_at DESC")
        feedback_list = cursor.fetchall()
        cursor.close()
        db.close()
        
        # SQLite Row objects to dictionaries convert karein
        if os.environ.get('RENDER'):
            feedback_list = [dict(row) for row in feedback_list]
        
        return render_template("view_feedback.html", 
                             feedback=feedback_list, 
                             user=session["user"])
    except Exception as e:
        flash(f"Error loading feedback: {str(e)}", "danger")
        return redirect(url_for("dashboard"))

# -------------------------------
# Finally, run the app
# -------------------------------
if __name__ == '__main__':
    port = int(os.environ.get("PORT", 5000))
    app.run(host='0.0.0.0', port=port, debug=False)
    

