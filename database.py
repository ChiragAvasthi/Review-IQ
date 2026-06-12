import sqlite3
import uuid
import datetime
import hashlib
import json
from werkzeug.security import generate_password_hash

DB_PATH = 'reviewiq.db'

def get_connection():
    conn = sqlite3.connect(DB_PATH, timeout=20.0)
    conn.row_factory = sqlite3.Row
    conn.execute('PRAGMA journal_mode=WAL;')
    conn.execute('PRAGMA synchronous=NORMAL;')
    conn.execute('PRAGMA cache_size=-64000;')
    return conn

def init_db():
    conn = get_connection()
    c = conn.cursor()
    c.executescript('''
        CREATE TABLE IF NOT EXISTS reviews (
            id TEXT PRIMARY KEY,
            source TEXT,
            author TEXT,
            rating INTEGER,
            text TEXT,
            date TEXT,
            imported_at TEXT,
            hash TEXT UNIQUE,
            product TEXT DEFAULT 'Global',
            metadata TEXT DEFAULT '{}'
        );

        CREATE VIRTUAL TABLE IF NOT EXISTS reviews_fts USING fts5(
            text, author, source, content='reviews', content_rowid='rowid'
        );

        CREATE TRIGGER IF NOT EXISTS reviews_ai AFTER INSERT ON reviews BEGIN
            INSERT INTO reviews_fts(rowid, text, author, source) VALUES (new.rowid, new.text, new.author, new.source);
        END;
        
        CREATE TRIGGER IF NOT EXISTS reviews_ad AFTER DELETE ON reviews BEGIN
            INSERT INTO reviews_fts(reviews_fts, rowid, text, author, source) VALUES('delete', old.rowid, old.text, old.author, old.source);
        END;

        CREATE TABLE IF NOT EXISTS analysis (
            id TEXT PRIMARY KEY,
            review_id TEXT UNIQUE,
            sentiment_label TEXT,
            sentiment_score REAL,
            processed_at TEXT,
            FOREIGN KEY(review_id) REFERENCES reviews(id) ON DELETE CASCADE
        );

        CREATE TABLE IF NOT EXISTS themes (
            id TEXT PRIMARY KEY,
            name TEXT,
            keywords TEXT,
            color TEXT,
            product TEXT DEFAULT 'Global',
            summary TEXT
        );

        CREATE TABLE IF NOT EXISTS review_themes (
            id TEXT PRIMARY KEY,
            review_id TEXT,
            theme_id TEXT,
            relevance_score REAL,
            FOREIGN KEY(review_id) REFERENCES reviews(id) ON DELETE CASCADE,
            FOREIGN KEY(theme_id) REFERENCES themes(id) ON DELETE CASCADE
        );

        CREATE TABLE IF NOT EXISTS review_aspects (
            id TEXT PRIMARY KEY,
            review_id TEXT,
            aspect_name TEXT,
            sentiment_label TEXT,
            sentiment_score REAL,
            FOREIGN KEY(review_id) REFERENCES reviews(id) ON DELETE CASCADE
        );

        CREATE TABLE IF NOT EXISTS weekly_snapshots (
            id TEXT PRIMARY KEY,
            week_start TEXT,
            product TEXT DEFAULT 'Global',
            avg_sentiment REAL,
            pos_pct REAL,
            neg_pct REAL,
            top_theme TEXT,
            total_reviews INTEGER,
            UNIQUE(week_start, product)
        );

        CREATE TABLE IF NOT EXISTS anomaly_insights (
            id TEXT PRIMARY KEY,
            week_start TEXT,
            product TEXT,
            alert_message TEXT,
            root_cause_keywords TEXT
        );

        CREATE TABLE IF NOT EXISTS settings (
            key TEXT PRIMARY KEY,
            value TEXT
        );
        
        CREATE TABLE IF NOT EXISTS users (
            id TEXT PRIMARY KEY,
            username TEXT UNIQUE,
            password_hash TEXT,
            role TEXT
        );
    ''')
    
    # Safe migrations for existing databases
    for table, col in [('reviews', 'product'), ('themes', 'product'), ('weekly_snapshots', 'product'), ('reviews', 'metadata'), ('themes', 'summary'), ('analysis', 'is_anomaly')]:
        try:
            default_val = '"{}"' if col == 'metadata' else ('"Global"' if col == 'product' else ('0' if col == 'is_anomaly' else 'NULL'))
            c.execute(f'ALTER TABLE {table} ADD COLUMN {col} TEXT DEFAULT {default_val}')
        except sqlite3.OperationalError:
            pass
    
    # Seed default settings
    defaults = {
        'business_name': 'My Business',
        'date_range': '30',
        'theme_count': '6',
        'neutral_threshold': '0.65'
    }
    for key, value in defaults.items():
        c.execute('INSERT OR IGNORE INTO settings (key, value) VALUES (?, ?)', (key, value))
        
    # Seed default admin user
    c.execute('SELECT * FROM users WHERE username = ?', ('admin',))
    if not c.fetchone():
        pwd_hash = generate_password_hash('admin')
        c.execute('INSERT INTO users (id, username, password_hash, role) VALUES (?, ?, ?, ?)',
                  (str(uuid.uuid4()), 'admin', pwd_hash, 'ADMIN'))
        
    conn.commit()
    conn.close()

def generate_hash(text):
    return hashlib.sha256(text.encode('utf-8')).hexdigest()

def get_user_by_username(username):
    conn = get_connection()
    c = conn.cursor()
    c.execute('SELECT * FROM users WHERE username = ?', (username,))
    user = c.fetchone()
    conn.close()
    return dict(user) if user else None

def import_reviews(reviews_list, skip_duplicates=True):
    conn = get_connection()
    c = conn.cursor()
    imported = 0
    duplicates = 0
    
    for r in reviews_list:
        text = r.get('text', '')
        author = r.get('author', '')
        date = r.get('date', '')
        row_id = str(uuid.uuid4())
        
        product = r.get('product', 'Global')
        metadata_json = json.dumps(r.get('metadata', {}))
        hash_input = f"{text}|{author}|{date}|{product}"
        if not skip_duplicates:
            # Append unique ID so the hash is never flagged as a duplicate by SQLite
            hash_input += f"|{row_id}"
            
        r_hash = generate_hash(hash_input)
        
        try:
            c.execute('''
                INSERT INTO reviews (id, source, author, rating, text, date, imported_at, hash, product, metadata)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ''', (
                row_id,
                r.get('source', 'Other'),
                author or 'Anonymous',
                int(r.get('rating', 3)),
                text,
                date or datetime.date.today().isoformat(),
                datetime.datetime.utcnow().isoformat(),
                r_hash,
                product,
                metadata_json
            ))
            imported += 1
        except sqlite3.IntegrityError:
            duplicates += 1
            
    conn.commit()
    conn.close()
    return imported, duplicates

def get_settings():
    conn = get_connection()
    c = conn.cursor()
    c.execute('SELECT key, value FROM settings')
    settings = {row['key']: row['value'] for row in c.fetchall()}
    conn.close()
    return settings

def save_settings(settings_dict):
    conn = get_connection()
    c = conn.cursor()
    for key, value in settings_dict.items():
        c.execute('INSERT OR REPLACE INTO settings (key, value) VALUES (?, ?)', (key, str(value)))
    conn.commit()
    conn.close()
    return get_settings()

def get_stats(product=None):
    conn = get_connection()
    c = conn.cursor()
    
    where_clause = ""
    params = ()
    if product and product != "All Products":
        where_clause = "WHERE r.product = ?"
        params = (product,)
        
    c.execute(f'SELECT COUNT(*) as count FROM reviews r {where_clause}', params)
    total = c.fetchone()['count']
    
    c.execute(f'''
        SELECT a.sentiment_label 
        FROM analysis a
        JOIN reviews r ON a.review_id = r.id
        {where_clause}
    ''', params)
    analysis_rows = c.fetchall()
    
    pos = neg = neu = 0
    for row in analysis_rows:
        label = row['sentiment_label']
        if label == 'POSITIVE': pos += 1
        elif label == 'NEGATIVE': neg += 1
        else: neu += 1
        
    analyzed = len(analysis_rows)
    avg_sentiment = int((pos / analyzed) * 100) if analyzed > 0 else 0
    
    c.execute(f'''
        SELECT COUNT(*) as count FROM reviews r
        JOIN analysis a ON r.id = a.review_id
        WHERE a.sentiment_label = 'NEGATIVE' AND r.rating <= 2
        {f"AND r.product = ?" if where_clause else ""}
    ''', params)
    critical = c.fetchone()['count']
    
    conn.close()
    return {
        'total': total,
        'avgSentiment': avg_sentiment,
        'pos': pos,
        'neg': neg,
        'neu': neu,
        'criticalCount': critical,
        'analyzed': analyzed
    }

def get_themes(product=None):
    conn = get_connection()
    c = conn.cursor()
    
    where_clause = ""
    params = ()
    if product and product != "All Products":
        where_clause = "WHERE t.product = ?"
        params = (product,)
    else:
        where_clause = "WHERE t.product = 'Global'"
        
    c.execute(f'''
        SELECT t.*, COUNT(rt.review_id) as volume 
        FROM themes t
        LEFT JOIN review_themes rt ON t.id = rt.theme_id
        {where_clause}
        GROUP BY t.id
        ORDER BY volume DESC
    ''', params)
    themes = [dict(row) for row in c.fetchall()]
    conn.close()
    return themes

def get_source_counts(product=None):
    conn = get_connection()
    c = conn.cursor()
    
    where_clause = ""
    params = ()
    if product and product != "All Products":
        where_clause = "WHERE product = ?"
        params = (product,)
        
    c.execute(f'SELECT source, COUNT(*) as count FROM reviews {where_clause} GROUP BY source ORDER BY count DESC', params)
    sources = [dict(row) for row in c.fetchall()]
    conn.close()
    return sources

def get_reviews(filters=None, page=1, limit=50, product=None):
    if filters is None: filters = {}
    conn = get_connection()
    c = conn.cursor()
    
    query = '''
        SELECT r.*, a.sentiment_label, a.sentiment_score, group_concat(t.name) as themes
        FROM reviews r
        LEFT JOIN analysis a ON r.id = a.review_id
        LEFT JOIN review_themes rt ON r.id = rt.review_id
        LEFT JOIN themes t ON rt.theme_id = t.id
    '''
    where = []
    params = []
    
    if product and product != "All Products":
        where.append('r.product = ?')
        params.append(product)
        
    if filters.get('source'):
        where.append('r.source = ?')
        params.append(filters['source'])
    if filters.get('rating'):
        where.append('r.rating = ?')
        params.append(int(filters['rating']))
    if filters.get('sentiment'):
        where.append('a.sentiment_label = ?')
        params.append(filters['sentiment'])
        
    meta_filters = filters.get('metadata', {})
    for key, val in meta_filters.items():
        where.append(f"json_extract(r.metadata, '$.{key}') = ?")
        params.append(val)
        
    if where:
        query += ' WHERE ' + ' AND '.join(where)
        
    query += ' GROUP BY r.id ORDER BY r.date DESC LIMIT ? OFFSET ?'
    params.extend([limit, (page - 1) * limit])
    
    c.execute(query, params)
    reviews = [dict(row) for row in c.fetchall()]
    conn.close()
    return reviews

def search_reviews(search_term, filters=None, page=1, limit=50, product=None):
    if not filters: filters = {}
    if not search_term: return get_reviews(filters, page, limit, product)
    conn = get_connection()
    c = conn.cursor()
    
    query = '''
        SELECT r.*, a.sentiment_label, a.sentiment_score, group_concat(t.name) as themes
        FROM reviews_fts fts
        JOIN reviews r ON fts.rowid = r.rowid
        LEFT JOIN analysis a ON r.id = a.review_id
        LEFT JOIN review_themes rt ON r.id = rt.review_id
        LEFT JOIN themes t ON rt.theme_id = t.id
        WHERE reviews_fts MATCH ?
    '''
    params = [search_term]
    
    if product and product != "All Products":
        query += ' AND r.product = ?'
        params.append(product)
        
    if filters.get('source'):
        query += ' AND r.source = ?'
        params.append(filters['source'])
    if filters.get('rating'):
        query += ' AND r.rating = ?'
        params.append(int(filters['rating']))
    if filters.get('sentiment'):
        query += ' AND a.sentiment_label = ?'
        params.append(filters['sentiment'])
        
    meta_filters = filters.get('metadata', {})
    for key, val in meta_filters.items():
        query += f" AND json_extract(r.metadata, '$.{key}') = ?"
        params.append(val)
        
    query += ' GROUP BY r.id ORDER BY r.date DESC LIMIT ? OFFSET ?'
    params.extend([limit, (page - 1) * limit])
    
    c.execute(query, params)
    reviews = [dict(row) for row in c.fetchall()]
    conn.close()
    return reviews

def clear_data():
    conn = get_connection()
    c = conn.cursor()
    c.executescript('''
        DELETE FROM review_themes;
        DELETE FROM themes;
        DELETE FROM analysis;
        DELETE FROM reviews;
        DELETE FROM weekly_snapshots;
    ''')
    conn.commit()
    conn.close()

def get_week_start(date_str=None):
    if not date_str:
        d = datetime.date.today()
    else:
        d = datetime.date.fromisoformat(date_str)
    start = d - datetime.timedelta(days=d.weekday())
    return start.isoformat()

def generate_snapshot(week_start, product=None):
    conn = get_connection()
    c = conn.cursor()
    end_of_week = (datetime.date.fromisoformat(week_start) + datetime.timedelta(days=7)).isoformat()
    
    where_clause = "r.date >= ? AND r.date < ?"
    params = [week_start, end_of_week]
    
    if product and product != "All Products":
        where_clause += " AND r.product = ?"
        params.append(product)
    
    c.execute(f'''
        SELECT 
            COUNT(r.id) as total,
            SUM(CASE WHEN a.sentiment_label = 'POSITIVE' THEN 1 ELSE 0 END) as pos,
            SUM(CASE WHEN a.sentiment_label = 'NEGATIVE' THEN 1 ELSE 0 END) as neg
        FROM reviews r
        LEFT JOIN analysis a ON r.id = a.review_id
        WHERE {where_clause}
    ''', tuple(params))
    stats = c.fetchone()
    
    total = stats['total'] or 0
    if total == 0:
        conn.close()
        return None
        
    pos_pct = (stats['pos'] / total) * 100 if stats['pos'] else 0
    neg_pct = (stats['neg'] / total) * 100 if stats['neg'] else 0
    avg_sentiment = pos_pct
    
    c.execute(f'''
        SELECT t.name, COUNT(rt.review_id) as vol
        FROM reviews r
        JOIN review_themes rt ON r.id = rt.review_id
        JOIN themes t ON rt.theme_id = t.id
        WHERE {where_clause}
        GROUP BY t.id
        ORDER BY vol DESC LIMIT 1
    ''', tuple(params))
    top_theme_row = c.fetchone()
    top_theme = top_theme_row['name'] if top_theme_row else 'None'
    
    conn.close()
    return {
        'id': str(uuid.uuid4()),
        'week_start': week_start,
        'avg_sentiment': avg_sentiment,
        'pos_pct': pos_pct,
        'neg_pct': neg_pct,
        'top_theme': top_theme,
        'total_reviews': total,
        'product': product or 'Global'
    }

def get_trends(product=None):
    conn = get_connection()
    c = conn.cursor()
    
    today = datetime.date.today()
    current_week_start = get_week_start(today.isoformat())
    last_week_start = get_week_start((today - datetime.timedelta(days=7)).isoformat())
    
    prod_val = product if product and product != "All Products" else 'Global'
    
    for ws in [current_week_start, last_week_start]:
        c.execute('SELECT * FROM weekly_snapshots WHERE week_start = ? AND product = ?', (ws, prod_val))
        if not c.fetchone():
            snap = generate_snapshot(ws, product)
            if snap:
                c.execute('''
                    INSERT OR REPLACE INTO weekly_snapshots 
                    (id, week_start, product, avg_sentiment, pos_pct, neg_pct, top_theme, total_reviews)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                ''', (snap['id'], snap['week_start'], snap['product'], snap['avg_sentiment'], snap['pos_pct'], snap['neg_pct'], snap['top_theme'], snap['total_reviews']))
                
    c.execute('''
        SELECT * FROM weekly_snapshots 
        WHERE product = ?
        ORDER BY week_start ASC LIMIT 12
    ''', (prod_val,))
    snapshots = [dict(row) for row in c.fetchall()]
    
    alerts = []
    curr_snap = next((s for s in snapshots if s['week_start'] == current_week_start), None)
    last_snap = next((s for s in snapshots if s['week_start'] == last_week_start), None)
    
    if curr_snap and last_snap and (curr_snap['neg_pct'] - last_snap['neg_pct']) > 20:
        c.execute('SELECT alert_message, root_cause_keywords FROM anomaly_insights WHERE week_start = ? AND product = ?', (current_week_start, prod_val))
        anomaly = c.fetchone()
        
        if not anomaly:
            # Calculate anomaly
            from sklearn.feature_extraction.text import TfidfVectorizer
            def get_neg_texts(week_start):
                query = '''
                    SELECT r.text FROM reviews r
                    JOIN analysis a ON r.id = a.review_id
                    WHERE a.sentiment_label = 'NEGATIVE'
                    AND r.date >= ? AND r.date < date(?, '+7 days')
                '''
                params = [week_start, week_start]
                if prod_val != 'Global':
                    query += ' AND r.product = ?'
                    params.append(prod_val)
                c.execute(query, params)
                return [row['text'] for row in c.fetchall() if row['text']]
                
            curr_texts = get_neg_texts(current_week_start)
            last_texts = get_neg_texts(last_week_start)
            
            if curr_texts:
                try:
                    vectorizer = TfidfVectorizer(stop_words='english', max_features=500)
                    vectorizer.fit(curr_texts + last_texts)
                    curr_vec = vectorizer.transform([" ".join(curr_texts)]).toarray()[0]
                    last_vec = vectorizer.transform([" ".join(last_texts)]).toarray()[0] if last_texts else [0]*len(curr_vec)
                    
                    delta = curr_vec - last_vec
                    feature_names = vectorizer.get_feature_names_out()
                    top_indices = delta.argsort()[-3:][::-1]
                    top_keywords = [feature_names[i] for i in top_indices if delta[i] > 0]
                    
                    if top_keywords:
                        msg = f"Alert: Negative sentiment spiked by >20% this week, heavily correlated with terms: {top_keywords}"
                        c.execute('INSERT INTO anomaly_insights (id, week_start, product, alert_message, root_cause_keywords) VALUES (?, ?, ?, ?, ?)',
                                  (str(uuid.uuid4()), current_week_start, prod_val, msg, json.dumps(top_keywords)))
                        conn.commit()
                        alerts.append({'type': 'warning', 'message': msg})
                except ValueError:
                    pass
        else:
            alerts.append({'type': 'warning', 'message': anomaly['alert_message']})
        
        if not alerts: # fallback if TF-IDF failed
            alerts.append({
                'type': 'warning',
                'message': 'Alert: Overall negative sentiment spiked by >20% this week!'
            })
        
    conn.close()
    return {
        'snapshots': snapshots,
        'alerts': alerts
    }

def get_products():
    conn = get_connection()
    c = conn.cursor()
    c.execute('SELECT DISTINCT product FROM reviews ORDER BY product ASC')
    products = [row['product'] for row in c.fetchall() if row['product']]
    conn.close()
    return products

def get_metadata_schema(product=None):
    conn = get_connection()
    c = conn.cursor()
    
    where_clause = ""
    params = ()
    if product and product != "All Products":
        where_clause = "WHERE product = ?"
        params = (product,)
        
    c.execute(f'SELECT metadata FROM reviews {where_clause}', params)
    rows = c.fetchall()
    conn.close()
    
    schema = {}
    for row in rows:
        if not row['metadata']: continue
        try:
            meta = json.loads(row['metadata'])
            for key, val in meta.items():
                if val is None or str(val).strip() == '': continue
                if key not in schema:
                    schema[key] = set()
                schema[key].add(str(val).strip())
        except:
            pass
            
    # Convert sets to sorted lists, limited to 50 unique values per key
    return {k: sorted(list(v))[:50] for k, v in schema.items()}

# Ensure initialized
init_db()
