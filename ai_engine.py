import threading
import queue
import uuid
import datetime
import re           
# pyrefly: ignore [missing-import]
from transformers import pipeline
from sklearn.cluster import KMeans
from sklearn.feature_extraction.text import TfidfVectorizer
import database

# Task queue and progress state
task_queue = queue.Queue()
progress_state = {
    'task': 'None',
    'message': 'Idle',
    'percent': 0,
    'busy': False
}

sentiment_model = None
absa_model = None
summarizer_model = None

def load_models():
    global sentiment_model, absa_model, summarizer_model
    if not sentiment_model:
        progress_state['message'] = 'Loading Sentiment Model...'
        try:
            sentiment_model = pipeline('sentiment-analysis', model='distilbert-base-uncased-finetuned-sst-2-english')
        except Exception as e:
            print(f"Failed to load sentiment model: {e}")
    if not absa_model:
        progress_state['message'] = 'Loading ABSA Model...'
        try:
            absa_model = pipeline('zero-shot-classification', model='cross-encoder/nli-distilroberta-base')
        except Exception as e:
            print(f"Failed to load ABSA model: {e}")
            absa_model = None
    if not summarizer_model:
        progress_state['message'] = 'Loading Summarizer...'
        try:
            summarizer_model = pipeline('summarization', model='sshleifer/distilbart-cnn-12-6')
        except Exception as e:
            print(f"Failed to load Summarizer model: {e}")
            summarizer_model = None

def get_progress():
    return progress_state

def update_progress(task, message, percent, busy=True):
    progress_state['task'] = task
    progress_state['message'] = message
    progress_state['percent'] = percent
    progress_state['busy'] = busy

def process_sentiment():
    update_progress('sentiment', 'Initializing...', 0)
    load_models()
    
    conn = database.get_connection()
    c = conn.cursor()
    c.execute('SELECT id, text FROM reviews WHERE id NOT IN (SELECT review_id FROM analysis)')
    reviews = c.fetchall()
    
    if not reviews:
        update_progress('sentiment', 'No new reviews to analyze', 100, False)
        return

    settings = database.get_settings()
    neutral_threshold = float(settings.get('neutral_threshold', 0.65))
    
    total = len(reviews)
    batch_size = 32
    processed = 0
    
    c.execute('SELECT DISTINCT name FROM themes')
    candidate_themes = [row['name'] for row in c.fetchall()]
    if not candidate_themes:
        candidate_themes = ["Product Quality", "Customer Service", "Pricing", "Delivery", "Ease of Use"]

    for i in range(0, total, batch_size):
        batch = reviews[i:i+batch_size]
        texts = [r['text'] if r['text'] else '' for r in batch]
        
        # Aggressive truncation for massive speedup on CPU. 
        texts_trunc = [t[:250] for t in texts]
        results = sentiment_model(texts_trunc)
        
        for idx, res in enumerate(results):
            label = res['label']
            score = res['score']
            if score < neutral_threshold:
                label = 'NEUTRAL'
                
            rev_id = batch[idx]['id']
            c.execute('''
                INSERT OR REPLACE INTO analysis (id, review_id, sentiment_label, sentiment_score, processed_at)
                VALUES (?, ?, ?, ?, ?)
            ''', (
                str(uuid.uuid4()), rev_id, label, score, datetime.datetime.utcnow().isoformat()
            ))
            
            # Aspect-Based Sentiment Analysis (ABSA)
            if absa_model:
                raw_text = batch[idx]['text']
                if raw_text:
                    sentences = [s.strip() for s in re.split(r'(?<=[.!?]) +', raw_text) if len(s.strip()) > 10][:3]
                    for sentence in sentences:
                        try:
                            absa_res = absa_model(sentence, candidate_labels=candidate_themes)
                            top_aspect = absa_res['labels'][0]
                            top_aspect_score = absa_res['scores'][0]
                            if top_aspect_score > 0.4:
                                sent_res = sentiment_model(sentence[:250])[0]
                                s_label = sent_res['label']
                                s_score = sent_res['score']
                                if s_score < neutral_threshold: s_label = 'NEUTRAL'
                                
                                c.execute('''
                                    INSERT INTO review_aspects (id, review_id, aspect_name, sentiment_label, sentiment_score)
                                    VALUES (?, ?, ?, ?, ?)
                                ''', (str(uuid.uuid4()), rev_id, top_aspect, s_label, s_score))
                        except Exception as e:
                            pass
                            
        conn.commit()
        processed += len(batch)
        update_progress('sentiment', 'Analyzing sentiment & aspects...', int((processed/total)*100))
        
    conn.close()
    update_progress('sentiment', 'AI Analysis Complete', 100, False)

def extract_keywords(texts, k):
    if not texts:
        return []
    vectorizer = TfidfVectorizer(stop_words='english', max_features=1000)
    X = vectorizer.fit_transform(texts)
    feature_names = vectorizer.get_feature_names_out()
    
    kmeans = KMeans(n_clusters=k, random_state=42, n_init='auto')
    kmeans.fit(X)
    
    order_centroids = kmeans.cluster_centers_.argsort()[:, ::-1]
    clusters_keywords = []
    
    distances = kmeans.transform(X)
    closest_indices = []
    
    for i in range(k):
        top_words = [feature_names[ind] for ind in order_centroids[i, :5]]
        clusters_keywords.append(top_words)
        sorted_idx = distances[:, i].argsort()[:5]
        closest_indices.append(sorted_idx.tolist())
        
    return clusters_keywords, kmeans.labels_, closest_indices

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
    load_models()
    
    conn = database.get_connection()
    c = conn.cursor()
    c.execute('SELECT id, text, product FROM reviews')
    reviews_raw = c.fetchall()
    
    if not reviews_raw:
        update_progress('cluster', 'No reviews to cluster', 100, False)
        return
        
    # Group by product and create a Global group
    groups = {'Global': reviews_raw}
    for r in reviews_raw:
        prod = r['product'] or 'Global'
        if prod != 'Global':
            if prod not in groups:
                groups[prod] = []
            groups[prod].append(r)
            
    c.executescript('DELETE FROM review_themes; DELETE FROM themes;')
    
    total_groups = len(groups)
    current_group = 0
    
    for prod_name, reviews in groups.items():
        if len(reviews) < 3: 
            continue # Skip clustering for extremely sparse products
            
        texts = [r['text'] if r['text'] else '' for r in reviews]
        update_progress('cluster', f'Extracting keywords for {prod_name}...', int((current_group/total_groups)*100))
        
        clusters_keywords, labels, closest_indices = extract_keywords(texts, min(k, len(texts)))
        
        themes = []
        for i in range(len(clusters_keywords)):
            keywords = clusters_keywords[i]
            
            # Generate summary from top 5 closest reviews
            summary_text = ""
            if summarizer_model and i < len(closest_indices):
                top_5_idx = closest_indices[i]
                combined_text = " ".join([texts[idx] for idx in top_5_idx if idx < len(texts)])
                trunc = combined_text[:800]
                if len(trunc) > 50:
                    try:
                        summ = summarizer_model(trunc, max_length=40, min_length=10, do_sample=False)
                        summary_text = summ[0]['summary_text'].strip()
                    except:
                        pass
                        
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
                c.execute('INSERT INTO themes (id, name, keywords, color, product, summary) VALUES (?, ?, ?, ?, ?, ?)', 
                          (t['id'], t['name'], t['keywords'], t['color'], t['product'], t['summary']))
                for rid in t['review_ids']:
                    # Only map review to theme if it's the Global run OR the specific product run
                    c.execute('INSERT INTO review_themes (id, review_id, theme_id, relevance_score) VALUES (?, ?, ?, ?)',
                              (str(uuid.uuid4()), rid, t['id'], 1.0))
                              
        current_group += 1
                              
    conn.commit()
    conn.close()
    update_progress('cluster', 'Clustering Complete', 100, False)
    
    # Automatically trigger sentiment after clustering
    task_queue.put({'type': 'sentiment'})

def worker_loop():
    while True:
        task = task_queue.get()
        if task is None:
            break
        try:
            if task['type'] == 'sentiment':
                process_sentiment()
            elif task['type'] == 'cluster':
                process_clustering(task['k'])
        except Exception as e:
            print(f"Error in background task: {e}")
            update_progress('error', f'Error: {str(e)}', 0, False)
        finally:
            task_queue.task_done()

# Start background thread
worker_thread = threading.Thread(target=worker_loop, daemon=True)
worker_thread.start()

def trigger_analysis():
    settings = database.get_settings()
    theme_count = int(settings.get('theme_count', 6))
    task_queue.put({'type': 'cluster', 'k': theme_count})

