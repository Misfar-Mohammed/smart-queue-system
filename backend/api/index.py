import sys
import os
import io
import jwt
import datetime
from functools import wraps
from flask import Flask, request, jsonify, send_file
from flask_cors import CORS
from werkzeug.security import generate_password_hash, check_password_hash
import qrcode
import pandas as pd

# Add parent directory of index.py to sys.path to resolve imports cleanly
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# Dynamically read and load the .env file from the project root if present
root_dir = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
env_path = os.path.join(root_dir, ".env")
if os.path.exists(env_path):
    with open(env_path, "r") as env_file:
        for line in env_file:
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                key, value = line.split("=", 1)
                os.environ[key.strip()] = value.strip().strip("'").strip('"')

# Import our database service
from services.supabase_service import SupabaseService

app = Flask(__name__)
CORS(app, resources={r"/api/*": {"origins": "*"}})

# Lazy database connection — only created on first request to avoid startup crashes
_db = None
def get_db():
    global _db
    if _db is None:
        _db = SupabaseService()
    return _db

JWT_SECRET = os.environ.get("JWT_SECRET", "smart-queue-secret-key-2026")

# Health check — visiting http://localhost:5000 shows this confirmation message
@app.route("/", methods=["GET"])
def health_check():
    return jsonify({"status": "Smart Queue API is running!", "version": "1.0"}), 200

# Global error handlers — always return JSON, never HTML error pages
@app.errorhandler(404)
def not_found(e):
    return jsonify({"message": "Route not found", "error": str(e)}), 404

@app.errorhandler(500)
def internal_error(e):
    return jsonify({"message": "Internal server error", "error": str(e)}), 500

@app.errorhandler(Exception)
def handle_exception(e):
    import traceback
    return jsonify({
        "message": "Server error - check Flask terminal for details",
        "error": str(e),
        "type": type(e).__name__
    }), 500

# Decorator to protect endpoints that require shop authorization
def token_required(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        token = None
        # Extract JWT token from header
        if "Authorization" in request.headers:
            auth_header = request.headers["Authorization"]
            if auth_header.startswith("Bearer "):
                token = auth_header.split(" ")[1]
        
        if not token:
            return jsonify({"message": "Token is missing!"}), 401
        
        try:
            data = jwt.decode(token, JWT_SECRET, algorithms=["HS256"])
            current_shop_id = data["shop_id"]
        except jwt.ExpiredSignatureError:
            return jsonify({"message": "Token has expired!"}), 401
        except jwt.InvalidTokenError:
            return jsonify({"message": "Token is invalid!"}), 401
            
        return f(current_shop_id, *args, **kwargs)
    return decorated

# ----------------- AUTH ENDPOINTS -----------------

@app.route("/api/auth/register", methods=["POST"])
def register():
    data = request.get_json() or {}
    shop_name = data.get("shop_name")
    owner_name = data.get("owner_name")
    phone = data.get("phone")
    password = data.get("password")

    if not all([shop_name, owner_name, phone, password]):
        return jsonify({"message": "Missing required fields"}), 400

    # Clean input
    phone = phone.strip()
    
    # Check if shop already exists
    existing_shop = get_db().get_shop_by_phone(phone)
    if existing_shop:
        return jsonify({"message": "A shop with this phone number already exists"}), 409

    # Hash the password
    password_hash = generate_password_hash(password)
    
    # Create the shop in database
    new_shop = get_db().create_shop(shop_name, owner_name, phone, password_hash)
    if not new_shop:
        return jsonify({"message": "Failed to register shop"}), 500

    # Generate JWT token
    token = jwt.encode(
        {"shop_id": new_shop["id"], "exp": datetime.datetime.now(datetime.timezone.utc) + datetime.timedelta(days=7)},
        JWT_SECRET,
        algorithm="HS256"
    )

    return jsonify({
        "message": "Registration successful",
        "token": token,
        "shop": {
            "id": new_shop["id"],
            "shop_name": new_shop["shop_name"],
            "owner_name": new_shop["owner_name"],
            "phone": new_shop["phone"]
        }
    }), 201

@app.route("/api/auth/login", methods=["POST"])
def login():
    data = request.get_json() or {}
    phone = data.get("phone")
    password = data.get("password")

    if not phone or not password:
        return jsonify({"message": "Phone and password are required"}), 400

    phone = phone.strip()
    shop = get_db().get_shop_by_phone(phone)
    if not shop:
        return jsonify({"message": "Invalid phone number or password"}), 401

    if not check_password_hash(shop["password_hash"], password):
        return jsonify({"message": "Invalid phone number or password"}), 401

    # Generate JWT token
    token = jwt.encode(
        {"shop_id": shop["id"], "exp": datetime.datetime.now(datetime.timezone.utc) + datetime.timedelta(days=7)},
        JWT_SECRET,
        algorithm="HS256"
    )

    return jsonify({
        "message": "Login successful",
        "token": token,
        "shop": {
            "id": shop["id"],
            "shop_name": shop["shop_name"],
            "owner_name": shop["owner_name"],
            "phone": shop["phone"]
        }
    }), 200

@app.route("/api/auth/me", methods=["GET"])
@token_required
def get_current_user(current_shop_id):
    shop = get_db().get_shop_by_id(current_shop_id)
    if not shop:
        return jsonify({"message": "Shop not found"}), 404
        
    return jsonify({
        "id": shop["id"],
        "shop_name": shop["shop_name"],
        "owner_name": shop["owner_name"],
        "phone": shop["phone"]
    }), 200

# ----------------- SHOP PUBLIC ENDPOINTS -----------------

@app.route("/api/shop/<shop_id>", methods=["GET"])
def get_shop_info(shop_id):
    shop = get_db().get_shop_by_id(shop_id)
    if not shop:
        return jsonify({"message": "Shop not found"}), 404
    return jsonify({
        "id": shop["id"],
        "shop_name": shop["shop_name"],
        "owner_name": shop["owner_name"]
    }), 200

@app.route("/api/shop/<shop_id>/qr", methods=["GET"])
def get_shop_qr(shop_id):
    shop = get_db().get_shop_by_id(shop_id)
    if not shop:
        return jsonify({"message": "Shop not found"}), 404

    # Determine front-end host URL
    frontend_url = os.environ.get("FRONTEND_URL")
    if not frontend_url:
        # Fallback for local testing
        frontend_url = request.host_url.replace("/api/", "")
        if "127.0.0.1" in frontend_url or "localhost" in frontend_url:
            # Assume local static server runs on 5500 (standard Live Server) or 3000
            frontend_url = "http://localhost:5500" if "5500" in request.headers.get("Referer", "") else "http://localhost:3000"
        else:
            # Production fallback targeting your Netlify frontend
            frontend_url = "https://smart-q-misfar.netlify.app"

    # Clean the URL representation
    frontend_url = frontend_url.rstrip("/")
    target_url = f"{frontend_url}/shop.html?id={shop_id}"

    # Generate QR Code image
    qr = qrcode.QRCode(
        version=1,
        error_correction=qrcode.constants.ERROR_CORRECT_L,
        box_size=10,
        border=4,
    )
    qr.add_data(target_url)
    qr.make(fit=True)

    img = qr.make_image(fill_color="black", back_color="white")
    
    # Save image to bytes IO stream
    img_io = io.BytesIO()
    img.save(img_io, 'PNG')
    img_io.seek(0)
    
    return send_file(img_io, mimetype='image/png', as_attachment=False, download_name=f"shop_{shop_id}_qr.png")

# ----------------- CUSTOMER QUEUE ENDPOINTS -----------------

@app.route("/api/shop/<shop_id>/join", methods=["POST"])
def join_shop_queue(shop_id):
    # Verify shop exists first
    shop = get_db().get_shop_by_id(shop_id)
    if not shop:
        return jsonify({"message": "Shop not found"}), 404

    data = request.get_json() or {}
    name = data.get("name")
    phone = data.get("phone")
    service_type = data.get("service_type", "General Inquiry")

    if not name or not phone:
        return jsonify({"message": "Name and phone are required to join the queue"}), 400

    name = name.strip()
    phone = phone.strip()
    if service_type:
        service_type = service_type.strip()

    # Enter into database
    queue_record = get_db().join_queue(shop_id, name, phone, service_type)
    if not queue_record:
        return jsonify({"message": "Failed to join queue"}), 500

    return jsonify({
        "message": "Successfully joined the queue",
        "ticket": queue_record
    }), 201

@app.route("/api/queue/<token_id>", methods=["GET"])
def get_token_details(token_id):
    member = get_db().get_queue_member(token_id)
    if not member:
        return jsonify({"message": "Token not found"}), 404
    return jsonify(member), 200

@app.route("/api/queue/<token_id>/feedback", methods=["POST"])
def submit_feedback(token_id):
    data = request.get_json() or {}
    rating = data.get("rating")
    feedback_text = data.get("feedback", "")

    if rating is None or not (1 <= int(rating) <= 5):
        return jsonify({"message": "Valid rating (1-5) is required"}), 400

    updated_record = get_db().submit_feedback(token_id, int(rating), feedback_text)
    if not updated_record:
        return jsonify({"message": "Token not found or failed to submit feedback"}), 404

    return jsonify({
        "message": "Feedback submitted successfully",
        "ticket": updated_record
    }), 200

# ----------------- OWNER DASHBOARD ENDPOINTS (PROTECTED) -----------------

@app.route("/api/shop/support", methods=["GET"])
@token_required
def get_support_contact(current_shop_id):
    return jsonify({
        "whatsapp_number": "+94 703759561",
        "whatsapp_url": "https://wa.me/94703759561?text=Hello%20Support,%20I%20am%20a%20registered%20owner%20of%20a%20Q-System%20shop."
    }), 200

@app.route("/api/shop/dashboard-data", methods=["GET"])
@token_required
def get_dashboard_data(current_shop_id):
    # Fetch analytics
    analytics = get_db().get_dashboard_analytics(current_shop_id)
    
    # Fetch active queue
    active_queue = get_db().get_active_queue(current_shop_id)
    
    # Fetch completed/skipped history
    history = get_db().get_queue_history(current_shop_id)

    return jsonify({
        "analytics": analytics,
        "active_queue": active_queue,
        "history": history
    }), 200

@app.route("/api/shop/queue/next", methods=["POST"])
@token_required
def call_next_customer(current_shop_id):
    result = get_db().call_next(current_shop_id)
    if not result:
        return jsonify({"message": "Queue is empty"}), 200
        
    # Simulate sending SMS/WhatsApp notification in the backend log
    serving_id = result.get("serving_id")
    if serving_id:
        member = get_db().get_queue_member(serving_id)
        if member:
            print("\n" + "="*80)
            print(f"[SMS/WhatsApp Notification Dispatcher]")
            print(f"To: {member['phone']} ({member['name']})")
            print(f"Message: Hi {member['name']}, your turn has arrived at {member['shop_name']}! "
                  f"Your token number is #{member['token_number']}. Please proceed to the counter.")
            print("="*80 + "\n")
            sys.stdout.flush()
        
    return jsonify({
        "message": "Called next customer successfully",
        "status": result
    }), 200

@app.route("/api/shop/queue/skip/<token_id>", methods=["POST"])
@token_required
def skip_customer(current_shop_id, token_id):
    # Ensure it belongs to the shop owner
    skipped_record = get_db().skip_customer(current_shop_id, token_id)
    if not skipped_record:
        return jsonify({"message": "Customer token not found or doesn't belong to this shop"}), 404

    return jsonify({
        "message": "Customer skipped successfully",
        "ticket": skipped_record
    }), 200

@app.route("/api/shop/queue/reset", methods=["POST"])
@token_required
def reset_shop_queue(current_shop_id):
    get_db().reset_queue(current_shop_id)
    return jsonify({"message": "Queue reset successfully"}), 200

# ----------------- EXPORT ENDPOINT (PROTECTED) -----------------

@app.route("/api/shop/export", methods=["GET"])
@token_required
def export_excel(current_shop_id):
    shop = get_db().get_shop_by_id(current_shop_id)
    if not shop:
        return jsonify({"message": "Shop not found"}), 404
        
    raw_data = get_db().get_export_data(current_shop_id)
    
    # Check if empty
    if not raw_data:
        # Create an empty excel sheets structure
        df = pd.DataFrame(columns=["Shop Name", "Customer Name", "Phone", "Token Number", "Status", "Time Joined"])
    else:
        # Formulate pandas DataFrame
        records = []
        for row in raw_data:
            joined_dt = datetime.datetime.fromisoformat(row["time_joined"].replace('Z', '+00:00'))
            # Format time beautifully
            joined_str = joined_dt.strftime("%Y-%m-%d %I:%M %p UTC")
            
            records.append({
                "Shop Name": shop["shop_name"],
                "Customer Name": row["name"],
                "Phone": row["phone"],
                "Token Number": row["token_number"],
                "Status": row["status"].capitalize(),
                "Time Joined": joined_str
            })
        df = pd.DataFrame(records)

    # Output to excel in memory
    excel_io = io.BytesIO()
    with pd.ExcelWriter(excel_io, engine="openpyxl") as writer:
        df.to_excel(writer, index=False, sheet_name="Queue History")
    
    excel_io.seek(0)
    
    # Prepare secure download filename
    safe_name = shop["shop_name"].lower().replace(" ", "_")
    filename = f"{safe_name}_queue_report.xlsx"

    return send_file(
        excel_io,
        mimetype="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        as_attachment=True,
        download_name=filename
    )

# Required by Vercel Serverless
if __name__ == "__main__":
    app.run(debug=True, port=int(os.environ.get("PORT", 5000)))
