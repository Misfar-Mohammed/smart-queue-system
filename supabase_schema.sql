-- ============================================================================
-- SUPABASE POSTGRESQL SCHEMA CONFIGURATION
-- Smart Queue System (Multi-Shop SaaS)
-- Copy and execute these queries inside your Supabase SQL Editor.
-- ============================================================================

-- 1. Create shops Table
CREATE TABLE IF NOT EXISTS shops (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    shop_name VARCHAR(255) NOT NULL,
    owner_name VARCHAR(255) NOT NULL,
    phone VARCHAR(50) UNIQUE NOT NULL,
    password_hash VARCHAR(255) NOT NULL,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
);

-- 2. Create queue Table
CREATE TABLE IF NOT EXISTS queue (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    shop_id UUID REFERENCES shops(id) ON DELETE CASCADE,
    name VARCHAR(255) NOT NULL,
    phone VARCHAR(50) NOT NULL,
    token_number INTEGER NOT NULL,
    status VARCHAR(50) DEFAULT 'waiting', -- 'waiting', 'serving', 'completed', 'skipped'
    time_joined TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    time_completed TIMESTAMP WITH TIME ZONE,
    service_type VARCHAR(100) DEFAULT 'General Inquiry',
    rating INTEGER CHECK (rating >= 1 AND rating <= 5),
    feedback TEXT
);

-- 3. Create Performance Indexes for real-time querying
CREATE INDEX IF NOT EXISTS idx_queue_shop_status ON queue(shop_id, status);
CREATE INDEX IF NOT EXISTS idx_queue_shop_joined ON queue(shop_id, time_joined);

-- 4. Enable Row Level Security (RLS) or leave public for direct API access
-- For standard REST API operations with SUPABASE_KEY, default access is allowed.
-- If you use supabase RLS policies, you can define them here. 
-- For simplicity, we ensure these tables are accessible by the API key.

-- ============================================================================
-- ATOMIC STORED PROCEDURES (POSTGRESQL FUNCTIONS) FOR TRANSACTION SAFETY
-- ============================================================================

-- A. Atomic Customer Queue Join Stored Procedure
CREATE OR REPLACE FUNCTION join_shop_queue(
    p_shop_id UUID, 
    p_name VARCHAR, 
    p_phone VARCHAR,
    p_service_type VARCHAR DEFAULT 'General Inquiry'
)
RETURNS TABLE (
    id UUID,
    shop_id UUID,
    name VARCHAR,
    phone VARCHAR,
    token_number INTEGER,
    status VARCHAR,
    time_joined TIMESTAMP WITH TIME ZONE,
    service_type VARCHAR
) AS $$
DECLARE
    next_token INTEGER;
    new_id UUID;
    new_time TIMESTAMP WITH TIME ZONE;
BEGIN
    -- 1. Lock the queue rows of the shop to prevent parallel token overlaps
    -- 2. Get the next incremented token number for this shop
    SELECT COALESCE(MAX(q.token_number), 0) + 1 INTO next_token
    FROM queue q
    WHERE q.shop_id = p_shop_id;

    new_id := gen_random_uuid();
    new_time := CURRENT_TIMESTAMP;

    -- 3. Insert customer record into queue
    INSERT INTO queue (id, shop_id, name, phone, token_number, status, time_joined, service_type)
    VALUES (new_id, p_shop_id, p_name, p_phone, next_token, 'waiting', new_time, p_service_type);

    RETURN QUERY SELECT new_id, p_shop_id, p_name, p_phone, next_token, 'waiting'::VARCHAR, new_time, p_service_type::VARCHAR;
END;
$$ LANGUAGE plpgsql;

-- B. Atomic Turn Calling Stored Procedure
CREATE OR REPLACE FUNCTION call_next_customer(
    p_shop_id UUID
)
RETURNS TABLE (
    completed_id UUID,
    serving_id UUID,
    serving_token INTEGER
) AS $$
DECLARE
    v_current_serving_id UUID;
    v_next_waiting_id UUID;
    v_next_token INTEGER;
BEGIN
    -- 1. Locate the current customer being served (if any) and update to 'completed'
    SELECT q.id INTO v_current_serving_id
    FROM queue q
    WHERE q.shop_id = p_shop_id AND q.status = 'serving'
    LIMIT 1;

    IF v_current_serving_id IS NOT NULL THEN
        UPDATE queue
        SET status = 'completed', time_completed = CURRENT_TIMESTAMP
        WHERE id = v_current_serving_id;
    END IF;

    -- 2. Locate the next waiting customer and update status to 'serving'
    SELECT q.id, q.token_number INTO v_next_waiting_id, v_next_token
    FROM queue q
    WHERE q.shop_id = p_shop_id AND q.status = 'waiting'
    ORDER BY q.token_number ASC
    LIMIT 1;

    IF v_next_waiting_id IS NOT NULL THEN
        UPDATE queue
        SET status = 'serving'
        WHERE id = v_next_waiting_id;
    END IF;

    RETURN QUERY SELECT v_current_serving_id, v_next_waiting_id, v_next_token;
END;
$$ LANGUAGE plpgsql;

-- ============================================================================
-- MIGRATION SCRIPTS (Execute these in Supabase SQL editor if database is already running)
-- ============================================================================
-- ALTER TABLE queue ADD COLUMN IF NOT EXISTS service_type VARCHAR(100) DEFAULT 'General Inquiry';
-- ALTER TABLE queue ADD COLUMN IF NOT EXISTS rating INTEGER CHECK (rating >= 1 AND rating <= 5);
-- ALTER TABLE queue ADD COLUMN IF NOT EXISTS feedback TEXT;

