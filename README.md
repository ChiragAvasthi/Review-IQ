# ReviewIQ - Comprehensive Application Architecture & Feature Overview

ReviewIQ is a robust, dynamic, AI-powered customer sentiment and analytics platform. Below is a detailed breakdown of everything we have built to date.

---

## 1. Application Architecture

The application follows a modern decoupled architecture:
*   **Backend:** A lightweight API server built with **Python (Flask)**.
*   **Database:** **SQLite3** for high-performance embedded storage, augmented with **FTS5 (Full-Text Search)** for lightning-fast querying.
*   **AI Engine:** Uses Hugging Face's `transformers` library (specifically `distilbert-base-uncased-finetuned-sst-2-english`) for sentiment analysis, and `scikit-learn` for TF-IDF keyword extraction and K-Means clustering. 
*   **Frontend:** A responsive Single Page Application (SPA) built purely with **HTML, CSS, and Vanilla JavaScript**.

---

## 2. Core Features

### A. Intelligent Data Ingestion
*   **Multi-Format Uploads:** Users can upload raw CSV files or paste text directly.
*   **Heuristic Mapping:** The CSV parser intelligently maps recognized columns (like "Date", "Author", "Rating", "Source", "Product").
*   **Dynamic Metadata Engine:** Unlike rigid systems, any unrecognized columns (e.g., "App Version", "User Location", "Subscription Tier") are not thrown away. They are seamlessly bundled into a dynamic JSON `metadata` payload and stored in the database.
*   **Deduplication:** A secure hashing algorithm (`SHA-256`) ensures that exact duplicate reviews are never imported twice.   

### B. AI-Powered Analytics
When data is imported, it is sent to a background thread to prevent UI freezing. The AI pipeline performs two major tasks:
1.  **Sentiment Analysis:** Uses a pre-trained BERT model (truncated to 250 characters for extreme speed optimization) to classify every review as POSITIVE, NEGATIVE, or NEUTRAL.
2.  **Recursive K-Means Clustering:** 
    *   The engine extracts keywords using `TF-IDF` and clusters reviews using `K-Means`.
    *   It first runs this globally across your entire dataset to find **Global Themes**.
    *   It then automatically splits your dataset by `product` and recursively runs K-Means on *each individual product*, finding hyper-specific themes (e.g., "Streaming Quality" for Netflix vs "Shipping Speed" for a physical item).

### C. Dynamic Frontend Dashboard
*   **Interactive Visualizations:** Uses `Chart.js` for dynamic doughnut charts (sentiment) and bar charts (theme volume).
*   **Multi-Product Context Switching:** A global "Active Product" dropdown allows the user to switch context. Switching products instantly morphs the entire dashboard, charts, trends, and explorer to only show data for that specific product.
*   **Smart Alerts & Trend Tracking:** The system generates weekly snapshots of your data and calculates week-over-week trends. If negative sentiment spikes by more than 20% compared to last week, a critical alert banner is displayed.

### D. The Review Explorer
*   **Dynamic Columns:** The data table dynamically adapts to the uploaded dataset. If your CSV has a "Device Type" column, the table will automatically generate a new "Device Type" column to display it.
*   **Magical Filters:** The backend constantly scans the dataset schema. The UI intercepts this schema and automatically generates dropdown filters for every custom metadata field it finds.
*   **Full-Text Search:** Users can instantly search through thousands of reviews utilizing SQLite's native FTS5 indexing engine.

---

## 3. Database Schema

The database (`reviewiq.db`) relies on the following structure:

*   **`reviews`**: The core table. Stores `id`, `text`, `rating`, `date`, `author`, `source`, `product`, and the dynamic `metadata` JSON blob.
*   **`reviews_fts`**: A virtual table synced via SQLite triggers. Provides instant search capabilities over review text.
*   **`analysis`**: Stores the output of the BERT sentiment model (`sentiment_label`, `sentiment_score`) linked to the review ID.
*   **`themes`**: Stores the output of the K-Means clustering (Theme Name, Keywords, Assigned Color, and the Associated Product).
*   **`review_themes`**: A mapping table linking individual reviews to their respective AI-generated themes.
*   **`weekly_snapshots`**: Stores week-by-week aggregated metrics to power the trend analysis engine.
*   **`settings`**: A key-value store for app configuration (Business Name, Theme Count, Date Ranges).

---

## 4. UI/UX Aesthetics

*   **Dark-Mode Native:** The interface utilizes a sleek, modern dark mode palette (`var(--bg-dark)`) with high-contrast text and vibrant, dynamic chart colors.
*   **Glassmorphism Effects:** Soft shadows and rounded corners (`border-radius: 12px`) create a premium feel.
*   **Responsive:** Navigation sidebar, flexible grid layouts, and horizontal scrolling containers for ultra-wide dynamic datasets. 

---

## Summary
What started as a generic review dashboard is now a highly scalable, dynamic intelligence platform capable of adapting to any arbitrary business dataset, running robust machine learning models locally without relying on paid APIs, and presenting insights through a dynamic, responsive UI.
