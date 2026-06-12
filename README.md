# ReviewIQ - Comprehensive Application Architecture & Feature Overview

ReviewIQ is a robust, dynamic, locally-powered customer sentiment and analytics platform. Below is a detailed breakdown of everything we have built to date.

---

## 1. Application Architecture

The application follows a modern decoupled architecture:
*   **Backend:** A lightweight API server built with **Python (Flask)**.
*   **Database:** **SQLite3** for high-performance embedded storage, augmented with **FTS5 (Full-Text Search)** for lightning-fast querying and optimized with `WAL` mode for high concurrency.
*   **AI Engine:** Uses **Classical Machine Learning**. It relies on `NLTK (VADER)` for extremely fast lexicon-based sentiment analysis, `scikit-learn` for TF-IDF keyword extraction and Latent Dirchlet Allocation (LDA) topic modeling, and `IsolationForest` for anomaly detection. This ensures zero network requests and no heavy model downloads.
*   **Frontend:** A responsive Single Page Application (SPA) built purely with **HTML, CSS, and Vanilla JavaScript**, featuring IndexedDB caching and Virtualized Infinite Scrolling.

---

## 2. Core Features

### A. Intelligent Data Ingestion
*   **Multi-Format Uploads:** Users can upload raw CSV files or paste text directly.
*   **Heuristic Mapping:** The CSV parser intelligently maps recognized columns (like "Date", "Author", "Rating", "Source", "Product").
*   **Dynamic Metadata Engine:** Unlike rigid systems, any unrecognized columns (e.g., "App Version", "User Location", "Subscription Tier") are not thrown away. They are seamlessly bundled into a dynamic JSON `metadata` payload and stored in the database.
*   **Deduplication:** A secure hashing algorithm (`SHA-256`) ensures that exact duplicate reviews are never imported twice.   

### B. AI-Powered Analytics
When data is imported, it is sent to a background Process Pool to prevent UI freezing. The ML pipeline performs:
1.  **Sentiment Analysis:** Uses NLTK VADER to classify every review as POSITIVE, NEGATIVE, or NEUTRAL instantly without a GPU.
2.  **Advanced Topic Modeling (LDA):** Extracts keywords using `TF-IDF` (n-grams) and clusters reviews using Latent Dirichlet Allocation (LDA) to find Global and Product-Specific Themes.
3.  **Anomaly Detection:** Uses an `IsolationForest` to identify statistical outliers in review text (anomalies/spam/trolls) and automatically alerts you.

### C. Enterprise Security & Readiness
*   **Local JWT Authentication:** Fully offline JWT-based authentication system (`PyJWT`).
*   **Role-Based Access Control (RBAC):** Admin-only protection for mutating endpoints (imports, data deletion, settings changes). Read-only endpoints use standard tokens.
*   **In-Memory Rate Limiting:** Built-in endpoint protection against brute force attacks and spam using `Flask-Limiter`.

### D. Dynamic Frontend Dashboard
*   **Interactive Visualizations:** Uses `Chart.js` for dynamic doughnut charts and bar charts.
*   **Multi-Product Comparison:** Compare metrics across two different product lines side-by-side dynamically.
*   **Smart Alerts & Trend Tracking:** The system generates weekly snapshots of your data and calculates week-over-week trends, alerting on anomalies or severe sentiment drops.
*   **IndexedDB Caching:** Instant load times by caching all Dashboard API requests locally using IndexedDB.
*   **Infinite Scrolling Explorer:** Seamlessly explore 10,000+ reviews without pagination buttons, utilizing an `IntersectionObserver` sentinel for local data virtualization.

---

## 3. Database Schema

The database (`reviewiq.db`) relies on the following structure:

*   **`users`**: Stores `username`, hashed `password_hash`, and `role` for JWT authentication.
*   **`reviews`**: The core table. Stores `id`, `text`, `rating`, `date`, `author`, `source`, `product`, and dynamic `metadata`.
*   **`reviews_fts`**: A virtual table synced via SQLite triggers. Provides instant search capabilities over review text.
*   **`analysis`**: Stores `sentiment_label`, `sentiment_score`, and `is_anomaly` flags.
*   **`themes`**: Stores Topic Modeling outputs (Name, Keywords, Assigned Color, Product).
*   **`review_themes`**: A mapping table linking reviews to themes.
*   **`weekly_snapshots`**: Stores week-by-week aggregated metrics to power trend analysis.
*   **`anomaly_insights`**: Stores specific alerts triggered by the AI engine.
*   **`settings`**: A key-value store for app configuration.

---

## 4. UI/UX Aesthetics

*   **Dark-Mode Native:** Sleek, modern dark mode palette (`var(--bg-dark)`) with high-contrast text.
*   **Glassmorphism Effects:** Soft shadows and rounded corners (`border-radius: 12px`).
*   **Responsive:** Navigation sidebar, flexible grid layouts, and smooth CSS transitions.

---

## Summary
ReviewIQ is a highly scalable, dynamic intelligence platform capable of adapting to any arbitrary business dataset. It runs robust classical machine learning models fully locally (zero external APIs), is secured by enterprise-grade offline authentication, and presents insights through an instantly-loading, virtualized frontend UI.
