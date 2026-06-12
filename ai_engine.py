import concurrent.futures
import json
import uuid
import datetime
import re
import nltk
from nltk.sentiment.vader import SentimentIntensityAnalyzer
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.decomposition import LatentDirichletAllocation
from sklearn.ensemble import IsolationForest
import database

executor = None
sentiment_model = None

def load_models():
    global sentiment_model
    if not sentiment_model:
        update_progress('init', 'Loading VADER Sentiment Model...', 0)
        try:
            sentiment_model = SentimentIntensityAnalyzer()
        except Exception as e:
            print(f"Failed to load VADER sentiment model: {e}")
            try:
                nltk.download('vader_lexicon', quiet=True)
                sentiment_model = SentimentIntensityAnalyzer()
            except:
                pass

def get_progress():
    settings = database.get_settings()
    prog_str = settings.get('progress_json')
    if prog_str:
        return json.loads(prog_str)
    return {'task': 'None', 'message': 'Idle', 'percent': 0, 'busy': False}

_last_progress = None
def update_progress(task, message, percent, busy=True):
    global _last_progress
    prog = {'task': task, 'message': message, 'percent': percent, 'busy': busy}
    if prog != _last_progress:
        database.save_settings({'progress_json': json.dumps(prog)})
        _last_progress = prog

def process_sentiment():
    update_progress('sentiment', 'Initializing...', 0)
    load_models()
    
    conn = database.get_connection()
    c = conn.cursor()
    c.execute('SELECT id, text FROM reviews WHERE id NOT IN (SELECT review_id FROM analysis)')
    reviews = c.fetchall()
    
    if not reviews:
        update_progress('sentiment', 'No new reviews to analyze', 100, False)
        conn.close()
        return

    settings = database.get_settings()
    neutral_threshold = float(settings.get('neutral_threshold', 0.65))
    
    total = len(reviews)
    batch_size = 100
    processed = 0
    
    c.execute('SELECT DISTINCT name FROM themes')
    candidate_themes = [row['name'] for row in c.fetchall()]
    if not candidate_themes:
        candidate_themes = ["Product Quality", "Customer Service", "Pricing", "Delivery", "Ease of Use"]

    for i in range(0, total, batch_size):
        batch = reviews[i:i+batch_size]
        
        for idx, r in enumerate(batch):
            text = r['text'] if r['text'] else ''
            if not text.strip():
                continue
                
            res = sentiment_model.polarity_scores(text)
            compound = res['compound']
            
            # Map [-1, 1] to [0, 1] for our score
            score = (compound + 1.0) / 2.0
            
            if compound > 0.05:
                label = 'POSITIVE'
            elif compound < -0.05:
                label = 'NEGATIVE'
            else:
                label = 'NEUTRAL'
                
            rev_id = r['id']
            c.execute('''
                INSERT OR REPLACE INTO analysis (id, review_id, sentiment_label, sentiment_score, processed_at)
                VALUES (?, ?, ?, ?, ?)
            ''', (
                str(uuid.uuid4()), rev_id, label, score, datetime.datetime.utcnow().isoformat()
            ))
            
            # Simple Aspect-Based Sentiment Analysis using VADER & Keyword Matching
            sentences = [s.strip() for s in re.split(r'(?<=[.!?]) +', text) if len(s.strip()) > 10][:3]
            for sentence in sentences:
                sent_res = sentiment_model.polarity_scores(sentence)
                s_comp = sent_res['compound']
                
                s_label = 'NEUTRAL'
                if s_comp > 0.05: s_label = 'POSITIVE'
                elif s_comp < -0.05: s_label = 'NEGATIVE'
                s_score = (s_comp + 1.0) / 2.0
                
                matched_theme = None
                sentence_lower = sentence.lower()
                for theme in candidate_themes:
                    theme_words = theme.lower().split()
                    if any(tw in sentence_lower for tw in theme_words if len(tw) > 3):
                        matched_theme = theme
                        break
                        
                if matched_theme and s_label != 'NEUTRAL':
                    c.execute('''
                        INSERT INTO review_aspects (id, review_id, aspect_name, sentiment_label, sentiment_score)
                        VALUES (?, ?, ?, ?, ?)
                    ''', (str(uuid.uuid4()), rev_id, matched_theme, s_label, s_score))
                            
        conn.commit()
        processed += len(batch)
        update_progress('sentiment', 'Analyzing sentiment & aspects...', int((processed/total)*100))
        
    conn.close()
    update_progress('sentiment', 'Sentiment Analysis Complete', 100, False)

def extract_keywords_lda(texts, k):
    if not texts or len(texts) < 2:
        return []
    
    # Use n-grams (1 to 3) for more meaningful phrases instead of single words
    vectorizer = TfidfVectorizer(stop_words='english', max_features=1000, ngram_range=(1, 3))
    try:
        X = vectorizer.fit_transform(texts)
    except ValueError:
        return [] # vocabulary empty
        
    feature_names = vectorizer.get_feature_names_out()
    
    lda = LatentDirichletAllocation(n_components=k, random_state=42, max_iter=5)
    doc_topics = lda.fit_transform(X)
    
    clusters_keywords = []
    for topic_idx, topic in enumerate(lda.components_):
        top_words_idx = topic.argsort()[:-6:-1]
        top_words = [feature_names[i] for i in top_words_idx]
        clusters_keywords.append(top_words)
        
    labels = doc_topics.argmax(axis=1)
    
    closest_indices = []
    for i in range(k):
        sorted_idx = doc_topics[:, i].argsort()[::-1][:5]
        closest_indices.append(sorted_idx.tolist())
        
    return clusters_keywords, labels, closest_indices

def assign_theme_name(keywords):
    k_str = ' '.join(keywords).lower()
    if any(w in k_str for w in ['delivery', 'shipping', 'late', 'arrive', 'tracking']): return "Delivery & shipping"
    if any(w in k_str for w in ['quality', 'material', 'broke', 'sturdy', 'cheap']): return "Product quality"
    if any(w in k_str for w in ['service', 'staff', 'helpful', 'support', 'rude']): return "Customer service"
    if any(w in k_str for w in ['price', 'value', 'expensive', 'worth', 'cost']): return "Price & value"
    if any(w in k_str for w in ['packaging', 'box', 'damaged', 'wrapped']): return "Packaging"
    return ", ".join([w.capitalize() for w in keywords[:3]])

THEME_COLORS = ['#185FA5', '#F5A623', '#7ED321', '#D0021B', '#9013FE', '#4A90E2', '#F8E71C', '#BD10E0', '#50E3C2', '#B8E986']

def process_clustering(k):
    update_progress('cluster', 'Initializing clustering...', 0)
    
    conn = database.get_connection()
    c = conn.cursor()
    c.execute('SELECT id, text, product FROM reviews')
    reviews_raw = c.fetchall()
    
    if not reviews_raw:
        update_progress('cluster', 'No reviews to cluster', 100, False)
        conn.close()
        return
        
    groups = {'Global': reviews_raw}
    for r in reviews_raw:
        prod = r['product'] or 'Global'
        if prod != 'Global':
            if prod not in groups:
                groups[prod] = []
            groups[prod].append(r)
            
    conn.close() 
    
    total_groups = len(groups)
    current_group = 0
    
    all_themes_to_insert = []
    all_review_themes_to_insert = []
    
    for prod_name, reviews in groups.items():
        if len(reviews) < 3: 
            current_group += 1
            continue
            
        texts = [r['text'] if r['text'] else '' for r in reviews]
        update_progress('cluster', f'Extracting keywords for {prod_name}...', int((current_group/total_groups)*100))
        
        result = extract_keywords_lda(texts, min(k, len(texts)))
        if not result:
            current_group += 1
            continue
            
        clusters_keywords, labels, closest_indices = result
        
        themes = []
        for i in range(len(clusters_keywords)):
            keywords = clusters_keywords[i]
            
            # Simple Extractive Summary (take the first 150 chars of the most representative review)
            summary_text = ""
            if i < len(closest_indices):
                top_idx = closest_indices[i]
                if top_idx and top_idx[0] < len(texts):
                    summary_text = texts[top_idx[0]][:150] + "..."
                        
            themes.append({
                'id': str(uuid.uuid4()),
                'name': assign_theme_name(keywords),
                'keywords': ", ".join(keywords),
                'color': THEME_COLORS[i % len(THEME_COLORS)],
                'review_ids': [reviews[idx]['id'] for idx, label in enumerate(labels) if label == i],
                'product': prod_name,
                'summary': summary_text
            })
            
        for t in themes:
            if t['review_ids']:
                all_themes_to_insert.append((t['id'], t['name'], t['keywords'], t['color'], t['product'], t['summary']))
                for rid in t['review_ids']:
                    all_review_themes_to_insert.append((str(uuid.uuid4()), rid, t['id'], 1.0))
                              
        current_group += 1
                              
    conn = database.get_connection()
    c = conn.cursor()
    c.executescript('DELETE FROM review_themes; DELETE FROM themes;')
    
    c.executemany('INSERT INTO themes (id, name, keywords, color, product, summary) VALUES (?, ?, ?, ?, ?, ?)', all_themes_to_insert)
    c.executemany('INSERT INTO review_themes (id, review_id, theme_id, relevance_score) VALUES (?, ?, ?, ?)', all_review_themes_to_insert)
    
    conn.commit()
    conn.close()
    update_progress('cluster', 'Clustering Complete', 100, False)

def process_anomalies():
    update_progress('anomaly', 'Detecting anomalies...', 0)
    conn = database.get_connection()
    c = conn.cursor()
    c.execute('SELECT id, text FROM reviews')
    reviews_raw = c.fetchall()
    
    if len(reviews_raw) > 5:
        texts = [r['text'] if r['text'] else '' for r in reviews_raw]
        vectorizer = TfidfVectorizer(stop_words='english', max_features=500)
        try:
            X = vectorizer.fit_transform(texts)
            iso_forest = IsolationForest(contamination=0.05, random_state=42)
            anomaly_labels = iso_forest.fit_predict(X)
            
            anomalous_ids = [(reviews_raw[i]['id'],) for i, label in enumerate(anomaly_labels) if label == -1]
            
            if anomalous_ids:
                c.executemany('UPDATE analysis SET is_anomaly = 1 WHERE review_id = ?', anomalous_ids)
                conn.commit()
        except ValueError:
            pass
            
    conn.close()
    update_progress('anomaly', 'Anomaly Detection Complete', 100, False)

def run_pipeline(k):
    try:
        process_clustering(k)
        process_sentiment()
        process_anomalies()
        update_progress('done', 'AI Analysis Complete', 100, False)
    except Exception as e:
        import traceback
        print(f"Error in background process: {e}\n{traceback.format_exc()}")
        update_progress('error', f'Error: {str(e)}', 0, False)

def trigger_analysis():
    global executor
    if executor is None:
        executor = concurrent.futures.ProcessPoolExecutor(max_workers=1)
    
    settings = database.get_settings()
    theme_count = int(settings.get('theme_count', 6))
    executor.submit(run_pipeline, theme_count)
