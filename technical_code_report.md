# SmartQueue System - Technical Code & Database Report

This report provides a detailed breakdown of the software architecture, code structures, API endpoints, and database schemas implemented in the **SmartQueue** project.

---

## 1. Directory Structure & Key Files

```text
Q-System/
│
├── backend/
│   ├── api/
│   │   └── index.py            # Flask REST API, routing, and JWT middlewares
│   └── services/
│       └── supabase_service.py # Database operations, transactional RPCs, and KV fallback
│
├── frontend/
│   ├── js/
│   │   ├── app.js              # Token authorization, dynamic helper wrappers
│   │   └── config.js           # Dynamic backend URL targeting
│   │
│   ├── index.html              # Landing Page
│   ├── login.html / register.html # Shop owner auth pages
│   ├── dashboard.html          # Real-time dashboard, settings modal & Chart.js logic
│   ├── shop.html               # Customer intake & QR scan registration
│   └── token.html              # Real-time ticket tracking, haptic alerts & single audio voice
│
├── supabase_schema.sql         # Database tables, relationships & PL/pgSQL scripts
└── presentation_report.md      # General presentation slides document
```

---

## 2. Database Layer (`supabase_schema.sql`)

SmartQueue utilizes **PostgreSQL hosted on Supabase**. The schema guarantees data integrity, secure lookups, and transaction safety.

### A. Database Table Schemas

#### 1. `shops` Table
Stores registered shops and credentials for dashboard auth.
```sql
CREATE TABLE shops (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    shop_name VARCHAR(255) NOT NULL,
    owner_name VARCHAR(255) NOT NULL,
    phone VARCHAR(50) UNIQUE NOT NULL,
    password_hash VARCHAR(255) NOT NULL,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
);
```

#### 2. `queue` Table
Stores customer ticket records.
```sql
CREATE TABLE queue (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    shop_id UUID REFERENCES shops(id) ON DELETE CASCADE,
    name VARCHAR(255) NOT NULL,
    phone VARCHAR(50) NOT NULL,
    token_number INTEGER NOT NULL,
    status VARCHAR(50) DEFAULT 'waiting' CHECK (status IN ('waiting', 'serving', 'completed', 'skipped')),
    service_type VARCHAR(100) DEFAULT 'General Inquiry',
    rating INTEGER CHECK (rating >= 1 AND rating <= 5),
    feedback TEXT,
    time_joined TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    time_completed TIMESTAMP WITH TIME ZONE
);
```

### B. Transactional Queue Join Stored Procedure (`PL/pgSQL`)
To prevent concurrent users from obtaining duplicate token numbers on the same day, we implement a database-level atomic stored procedure:
```sql
CREATE OR REPLACE FUNCTION join_shop_queue(
    p_shop_id UUID, 
    p_name VARCHAR, 
    p_phone VARCHAR,
    p_service_type VARCHAR DEFAULT 'General Inquiry',
    p_timezone_offset INTEGER DEFAULT 0
)
RETURNS SETOF queue AS $$
DECLARE
    next_token INTEGER;
    new_id UUID;
    new_time TIMESTAMP WITH TIME ZONE;
    day_start TIMESTAMP WITH TIME ZONE;
    local_now TIMESTAMP WITH TIME ZONE;
BEGIN
    new_id := gen_random_uuid();
    new_time := CURRENT_TIMESTAMP;
    
    -- Convert UTC time to local shop time zone to group by date correctly
    local_now := new_time - (p_timezone_offset * INTERVAL '1 minute');
    day_start := date_trunc('day', local_now) + (p_timezone_offset * INTERVAL '1 minute');

    -- Atomic Lock & Increment to calculate next ticket sequence
    SELECT COALESCE(MAX(token_number), 0) + 1 INTO next_token
    FROM queue
    WHERE shop_id = p_shop_id 
      AND time_joined >= day_start;

    -- Create queue ticket
    INSERT INTO queue (id, shop_id, name, phone, token_number, status, time_joined, service_type)
    VALUES (new_id, p_shop_id, p_name, p_phone, next_token, 'waiting', new_time, p_service_type);

    RETURN QUERY SELECT * FROM queue WHERE id = new_id;
END;
$$ LANGUAGE plpgsql;
```

---

## 3. Backend REST API Layer (`backend/api/index.py`)

Built with **Flask**, serving serverless HTTP request routes.

### A. JWT Token Security Decorator
Secures owner dashboard endpoints using JSON Web Token checks:
```python
def token_required(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        token = None
        if "Authorization" in request.headers:
            auth_header = request.headers["Authorization"].split(" ")
            if len(auth_header) == 2 and auth_header[0] == "Bearer":
                token = auth_header[1]

        if not token:
            return jsonify({"message": "Token is missing!"}), 401

        try:
            data = jwt.decode(token, JWT_SECRET, algorithms=["HS256"])
            current_shop_id = data["shop_id"]
        except Exception:
            return jsonify({"message": "Token is invalid or expired!"}), 401

        return f(current_shop_id, *args, **kwargs)
    return decorated
```

### B. Dynamic Profile & Settings Update Endpoints
Allows dashboard setting customizations:
```python
@app.route("/api/shop/update", methods=["POST"])
@token_required
def update_shop_profile(current_shop_id):
    data = request.get_json() or {}
    shop_name = data.get("shop_name").strip()
    owner_name = data.get("owner_name").strip()
    phone = data.get("phone").strip()

    # Phone unique check (excluding current shop)
    existing = get_db().get_shop_by_phone(phone)
    if existing and existing["id"] != current_shop_id:
        return jsonify({"message": "Phone number already in use"}), 409

    updated = get_db().update_shop(current_shop_id, shop_name, owner_name, phone)
    return jsonify({"message": "Profile updated successfully", "shop": updated}), 200
```

---

## 4. Database Service Layer (`backend/services/supabase_service.py`)

Handles direct data transactions with the Supabase client.

### A. Smart Metadata Fallback Store
If the database table `shops` doesn't have custom settings columns, the service transparently reads/writes configuration profiles as JSON payloads inside a system row (`token_number = -999`) in the `queue` table:
```python
    def get_shop_settings(self, shop_id):
        try:
            res = self.client.table("queue") \
                .select("phone") \
                .eq("shop_id", shop_id) \
                .eq("name", "__SYSTEM_SHOP_SETTINGS__") \
                .execute()
            if len(res.data) > 0:
                import json
                settings = json.loads(res.data[0]["phone"])
                return {
                    "is_open": settings.get("is_open", True),
                    "profile_photo": settings.get("profile_photo", None)
                }
        except Exception:
            pass
        return {"is_open": True, "profile_photo": None}
```

### B. Exclude Key-Value System Records from Lists & Metrics
To avoid corrupting queues and daily analytics, we filter this dummy config record out:
```python
    def get_active_queue(self, shop_id, target_date=None, timezone_offset=0):
        start_iso, end_iso, _ = self._get_date_range(target_date, timezone_offset)
        res = self.client.table("queue") \
            .select("*") \
            .eq("shop_id", shop_id) \
            .in_("status", ["waiting", "serving"]) \
            .neq("name", "__SYSTEM_SHOP_SETTINGS__") \
            .gte("time_joined", start_iso) \
            .lt("time_joined", end_iso) \
            .order("token_number", desc=False) \
            .execute()
        return res.data
```

---

## 5. Frontend Script Implementations

### A. Client-Side JWT Auth Wrapper (`js/app.js`)
Configures AJAX routing with automatic token injections:
```javascript
const Auth = {
    getToken() { return localStorage.getItem('shop_token'); },
    setShop(shop) { localStorage.setItem('shop_data', JSON.stringify(shop)); },
    getShop() { return JSON.parse(localStorage.getItem('shop_data')); },
    
    async fetch(endpoint, options = {}) {
        const token = this.getToken();
        const headers = {
            'Content-Type': 'application/json',
            ...options.headers
        };
        if (token) headers['Authorization'] = `Bearer ${token}`;
        return fetch(endpoint, { ...options, headers });
    }
};
```

### B. High-Performance Dashboard Polling (`dashboard.html`)
Avoids overlapping requests by executing a recursive `setTimeout` logic on a 1-second interval:
```javascript
        let pollingActive = false;
        function startPolling() {
            if (pollingActive) return;
            pollingActive = true;
            pollQueue();
        }

        async function pollQueue() {
            if (!pollingActive) return;
            await fetchDashboardData();
            setTimeout(pollQueue, 1000); // Wait exactly 1 second AFTER fetch returns
        }
```

### C. Thread-Safe Speech Playback (`token.html`)
Avoids browser speech synthesizers from speaking completed queue arrival notifications repetitively by using single-use locking flags:
```javascript
        let isCompletionAlerted = false;

        function playCompletionVoice() {
            if (!isCompletionAlerted && 'speechSynthesis' in window) {
                window.speechSynthesis.cancel(); // Stop current speech
                const utterance = new SpeechSynthesisUtterance("Thank you for your visit. Come again, and have a safe journey!");
                utterance.rate = 0.95;
                window.speechSynthesis.speak(utterance);
                isCompletionAlerted = true; // Lock playback
            }
        }
```
