from flask import Flask, request, jsonify, render_template, Response
import time
import json
from flask_cors import CORS
import database
import ai_engine

app = Flask(__name__, static_folder='static', template_folder='templates')
CORS(app)

@app.route('/')
def index():
    return render_template('index.html')

@app.route('/api/import', methods=['POST'])
def import_data():
    try:
        payload = request.json
        reviews = payload.get('reviews', [])
        skip_duplicates = payload.get('skipDuplicates', True)
        
        if not isinstance(reviews, list) or len(reviews) == 0:
            return jsonify({'error': 'Invalid payload, expected non-empty list of reviews'}), 400
            
        imported, duplicates = database.import_reviews(reviews, skip_duplicates)
        
        # Trigger background analysis
        ai_engine.trigger_analysis()
        
        return jsonify({'imported': imported, 'duplicates': duplicates})
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/api/stats', methods=['GET'])
def get_stats():
    product = request.args.get('product')
    return jsonify(database.get_stats(product))

@app.route('/api/themes', methods=['GET'])
def get_themes():
    product = request.args.get('product')
    return jsonify(database.get_themes(product))

@app.route('/api/sources', methods=['GET'])
def get_sources():
    product = request.args.get('product')
    return jsonify(database.get_source_counts(product))

@app.route('/api/reviews', methods=['GET'])
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
        # Extract dynamic metadata filters from query params
        meta_filters = {}
        for key, val in request.args.items():
            if key.startswith('meta_') and val:
                meta_filters[key[5:]] = val

        # Advanced Regex Parser for Search String Filters (e.g. rating:5 source:"App Store" battery)
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
                    
            # Strip the extracted filters from the search string
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
def get_trends():
    product = request.args.get('product')
    return jsonify(database.get_trends(product))

@app.route('/api/products', methods=['GET'])
def get_products():
    return jsonify(database.get_products())

@app.route('/api/metadata_schema', methods=['GET'])
def get_metadata_schema():
    product = request.args.get('product')
    return jsonify(database.get_metadata_schema(product))

@app.route('/api/settings', methods=['GET', 'POST'])
def handle_settings():
    if request.method == 'POST':
        settings = request.json
        updated = database.save_settings(settings)
        return jsonify(updated)
    else:
        return jsonify(database.get_settings())

@app.route('/api/clear', methods=['POST'])
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
def rerun_ai():
    settings = database.get_settings()
    theme_count = int(settings.get('theme_count', 6))
    
    database.get_connection().execute('DELETE FROM analysis')
    database.get_connection().commit()
    
    ai_engine.trigger_analysis()
    return jsonify({'success': True})

if __name__ == '__main__':
    app.run(debug=True, port=5000)
