from flask import Flask, request, jsonify, render_template, Response, g
import time
import json
import datetime
from flask_cors import CORS
import jwt
from functools import wraps
from flask_limiter import Limiter
from flask_limiter.util import get_remote_address
from werkzeug.security import check_password_hash

import database
import ai_engine

app = Flask(__name__, static_folder='static', template_folder='templates')
CORS(app)

app.config['SECRET_KEY'] = 'super-secret-local-key'

limiter = Limiter(
    get_remote_address,
    app=app,
    default_limits=["200 per day", "50 per hour"],
    storage_uri="memory://"
)

def token_required(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        token = None
        if 'Authorization' in request.headers:
            parts = request.headers['Authorization'].split()
            if len(parts) == 2 and parts[0] == 'Bearer':
                token = parts[1]
                
        if not token:
            return jsonify({'error': 'Token is missing'}), 401
            
        try:
            data = jwt.decode(token, app.config['SECRET_KEY'], algorithms=["HS256"])
            current_user = database.get_user_by_username(data['username'])
            if not current_user:
                return jsonify({'error': 'User not found'}), 401
            g.user = current_user
        except:
            return jsonify({'error': 'Token is invalid'}), 401
            
        return f(*args, **kwargs)
    return decorated

def admin_required(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        if not hasattr(g, 'user') or g.user['role'] != 'ADMIN':
            return jsonify({'error': 'Admin privilege required'}), 403
        return f(*args, **kwargs)
    return decorated

@app.route('/')
def index():
    return render_template('index.html')

@app.route('/api/login', methods=['POST'])
@limiter.limit("10 per minute")
def login():
    data = request.json
    if not data or not data.get('username') or not data.get('password'):
        return jsonify({'error': 'Missing credentials'}), 401
        
    user = database.get_user_by_username(data.get('username'))
    if user and check_password_hash(user['password_hash'], data.get('password')):
        token = jwt.encode({
            'username': user['username'],
            'role': user['role'],
            'exp': datetime.datetime.utcnow() + datetime.timedelta(hours=24)
        }, app.config['SECRET_KEY'], algorithm="HS256")
        
        return jsonify({'token': token, 'role': user['role']})
        
    return jsonify({'error': 'Invalid credentials'}), 401

@app.route('/api/import', methods=['POST'])
@token_required
@admin_required
def import_data():
    try:
        payload = request.json
        reviews = payload.get('reviews', [])
        skip_duplicates = payload.get('skipDuplicates', True)
        
        if not isinstance(reviews, list) or len(reviews) == 0:
            return jsonify({'error': 'Invalid payload, expected non-empty list of reviews'}), 400
            
        imported, duplicates = database.import_reviews(reviews, skip_duplicates)
        
        ai_engine.trigger_analysis()
        
        return jsonify({'imported': imported, 'duplicates': duplicates})
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/api/stats', methods=['GET'])
@token_required
def get_stats():
    product = request.args.get('product')
    return jsonify(database.get_stats(product))

@app.route('/api/themes', methods=['GET'])
@token_required
def get_themes():
    product = request.args.get('product')
    return jsonify(database.get_themes(product))

@app.route('/api/sources', methods=['GET'])
@token_required
def get_sources():
    product = request.args.get('product')
    return jsonify(database.get_source_counts(product))

@app.route('/api/reviews', methods=['GET'])
@token_required
def get_reviews():
    try:
        page = int(request.args.get('page', 1))
        limit = int(request.args.get('limit', 50))
        search = request.args.get('search', '')
        product = request.args.get('product')
        
        filters = {}
        if request.args.get('sentiment'): filters['sentiment'] = request.args.get('sentiment')
        if request.args.get('rating'): filters['rating'] = request.args.get('rating')
        if request.args.get('source'): filters['source'] = request.args.get('source')
        
        import re
        meta_filters = {}
        for key, val in request.args.items():
            if key.startswith('meta_') and val:
                meta_filters[key[5:]] = val

        if search:
            pattern = r'(\w+):(?:([^" \n]+)|"([^"\n]+)")'
            matches = re.finditer(pattern, search)
            for match in matches:
                key = match.group(1).lower()
                val = match.group(2) or match.group(3)
                
                if key in ['rating', 'sentiment', 'source']:
                    filters[key] = val
                else:
                    meta_filters[key] = val
                    
            search = re.sub(pattern, '', search).strip()
            
        if meta_filters:
            filters['metadata'] = meta_filters

        if search:
            reviews = database.search_reviews(search, filters, page, limit, product)
        else:
            reviews = database.get_reviews(filters, page, limit, product)
            
        return jsonify(reviews)
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/api/trends', methods=['GET'])
@token_required
def get_trends():
    product = request.args.get('product')
    return jsonify(database.get_trends(product))

@app.route('/api/products', methods=['GET'])
@token_required
def get_products():
    return jsonify(database.get_products())

@app.route('/api/metadata_schema', methods=['GET'])
@token_required
def get_metadata_schema():
    product = request.args.get('product')
    return jsonify(database.get_metadata_schema(product))

@app.route('/api/settings', methods=['GET', 'POST'])
@token_required
def handle_settings():
    if request.method == 'POST':
        # Need admin to change settings
        if g.user['role'] != 'ADMIN':
            return jsonify({'error': 'Admin privilege required'}), 403
            
        settings = request.json
        updated = database.save_settings(settings)
        return jsonify(updated)
    else:
        return jsonify(database.get_settings())

@app.route('/api/clear', methods=['POST'])
@token_required
@admin_required
def clear_data():
    database.clear_data()
    return jsonify({'success': True})

@app.route('/api/progress', methods=['GET'])
def get_progress():
    return jsonify(ai_engine.get_progress())

@app.route('/api/stream_progress')
def stream_progress():
    def event_stream():
        last_state = None
        while True:
            current_state = ai_engine.get_progress()
            if current_state != last_state:
                yield f"data: {json.dumps(current_state)}\n\n"
                last_state = current_state.copy()
            time.sleep(1)
    return Response(event_stream(), mimetype="text/event-stream")

@app.route('/api/rerun_ai', methods=['POST'])
@token_required
@admin_required
def rerun_ai():
    settings = database.get_settings()
    theme_count = int(settings.get('theme_count', 6))
    
    database.get_connection().execute('DELETE FROM analysis')
    database.get_connection().commit()
    
    ai_engine.trigger_analysis()
    return jsonify({'success': True})

if __name__ == '__main__':
    app.run(debug=True, port=5000)
