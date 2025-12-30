-- Workers master table
CREATE TABLE IF NOT EXISTS workers (
    worker_id TEXT PRIMARY KEY,
    name TEXT,
    phone TEXT,
    email TEXT,
    joined_at TEXT,
    current_status TEXT,
    notes TEXT
);

-- Orders table (many orders per worker)
CREATE TABLE IF NOT EXISTS orders (
    order_id TEXT PRIMARY KEY,
    worker_id TEXT,
    order_date TEXT,
    distance_km REAL,
    duration_min INTEGER,
    payout_amount REAL,
    status TEXT,
    flags TEXT,
    payment_compliant INTEGER DEFAULT 1,   -- 1 = payout as per norms, 0 = reduced/not compliant
    reduction_reason TEXT,                -- nullable: reason why payout was reduced
    FOREIGN KEY (worker_id) REFERENCES workers(worker_id)
);

-- Termination status table (one row per worker for quick lookup)
CREATE TABLE IF NOT EXISTS termination_status (
    worker_id TEXT PRIMARY KEY,
    is_terminated INTEGER DEFAULT 0,
    terminated_at TEXT,
    termination_reason_code TEXT,
    termination_reason_text TEXT,
    appeal_allowed INTEGER,
    appeal_deadline TEXT,
    FOREIGN KEY (worker_id) REFERENCES workers(worker_id)
);

-- Termination logs table (history of termination-related events / reasons)
CREATE TABLE IF NOT EXISTS termination_logs (
    log_id INTEGER PRIMARY KEY AUTOINCREMENT,
    worker_id TEXT,
    logged_at TEXT,
    reason_code TEXT,
    reason_text TEXT,
    related_order_id TEXT,
    evidence TEXT,
    severity INTEGER DEFAULT 0,
    action_taken TEXT,
    recorded_by TEXT,
    FOREIGN KEY (worker_id) REFERENCES workers(worker_id),
    FOREIGN KEY (related_order_id) REFERENCES orders(order_id)
);

-- Review counts table (one row per worker)
CREATE TABLE IF NOT EXISTS review_counts (
    worker_id TEXT PRIMARY KEY,
    count_5 INTEGER DEFAULT 0,
    count_4 INTEGER DEFAULT 0,
    count_3 INTEGER DEFAULT 0,
    count_2 INTEGER DEFAULT 0,
    count_1 INTEGER DEFAULT 0,
    total_reviews INTEGER DEFAULT 0,
    FOREIGN KEY (worker_id) REFERENCES workers(worker_id)
);
