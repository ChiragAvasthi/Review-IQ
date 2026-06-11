// --- DOM Elements ---
const views = document.querySelectorAll('.view');
const navBtns = document.querySelectorAll('.nav-btn');
const importModal = document.getElementById('import-modal');
const toastContainer = document.getElementById('toast-container');
const statusText = document.getElementById('status-text');
const statusIndicator = document.querySelector('.status-indicator');
const statusDate = document.getElementById('status-date');
const alertsContainer = document.getElementById('alerts-container');

// --- State ---
let currentDaysFilter = '30';
let activeProduct = 'All Products';
let compareProduct = null;
let metadataSchema = {};
let themeChartInstance = null;
let sentimentChartInstance = null;
let currentReviewsPage = 1;
const REVIEWS_PER_PAGE = 50;

const API_BASE = '/api';

// --- Initialization ---
async function init() {
  setupNavigation();
  setupImportModal();
  setupFilters();
  setupSettings();
  setupExplorer();
  setupPdfExport();
  await setupProductFilter();

  // Load Initial Data
  await loadDashboard();
  await loadSettings();
  await checkTrends();

  // Setup Progress Polling
  setInterval(pollProgress, 2000);
}

// --- API Helpers ---
async function fetchAPI(endpoint, method = 'GET', body = null, skipProductInjection = false) {
  const options = { method, headers: {} };
  if (body) {
    options.headers['Content-Type'] = 'application/json';
    options.body = JSON.stringify(body);
  }
  
  let finalEndpoint = endpoint;
  if (method === 'GET' && activeProduct && activeProduct !== 'All Products' && !skipProductInjection && !endpoint.includes('product=')) {
    const sep = endpoint.includes('?') ? '&' : '?';
    finalEndpoint += `${sep}product=${encodeURIComponent(activeProduct)}`;
  }
  
  const res = await fetch(`${API_BASE}${finalEndpoint}`, options);
  if (!res.ok) {
    const err = await res.json().catch(() => ({}));
    throw new Error(err.error || `API error: ${res.status}`);
  }
  return await res.json();
}

async function pollProgress() {
  try {
    const data = await fetchAPI('/progress');
    if (data.task !== 'None') {
      updateProgress(data);
    }
  } catch (err) {
    console.error('Progress poll failed', err);
  }
}

// --- Navigation ---
function setupNavigation() {
  navBtns.forEach(btn => {
    btn.addEventListener('click', () => {
      if (btn.id === 'btn-import-sidebar') return;
      switchView(btn.dataset.target);
    });
  });
  document.getElementById('btn-import-sidebar').addEventListener('click', showImportModal);
}

async function setupProductFilter() {
  const select = document.getElementById('global-product-filter');
  if (!select) return;
  
  try {
    const products = await fetchAPI('/products');
    const select1 = document.getElementById('global-product-filter');
    const select2 = document.getElementById('global-product-filter-2');
    const compareToggle = document.getElementById('compare-mode-toggle');
    const compareContainer = document.getElementById('compare-selector-container');
    
    select1.innerHTML = '<option value="All Products">All Products</option>';
    select2.innerHTML = '<option value="">Select Product B...</option>';
    
    products.forEach(p => {
      select1.innerHTML += `<option value="${p}">${p}</option>`;
      select2.innerHTML += `<option value="${p}">${p}</option>`;
    });
    
    compareToggle.addEventListener('change', (e) => {
      compareContainer.style.display = e.target.checked ? 'block' : 'none';
      compareProduct = e.target.checked ? select2.value : null;
      loadDashboard();
    });
    
    select1.addEventListener('change', async (e) => {
      activeProduct = e.target.value;
      await loadMetadataSchema();
      loadDashboard();
      if (document.getElementById('view-explorer').classList.contains('active')) {
        loadExplorer();
      }
    });
    
    select2.addEventListener('change', (e) => {
      compareProduct = e.target.value;
      if (compareToggle.checked) loadDashboard();
    });
    
    // Initial load of schema
    await loadMetadataSchema();
  } catch (err) {
    console.error('Failed to load products', err);
  }
}

async function loadMetadataSchema() {
  try {
    metadataSchema = await fetchAPI('/metadata_schema');
    
    // Update dynamic filters
    const container = document.getElementById('dynamic-filters-container');
    if (container) {
      container.innerHTML = '';
      Object.keys(metadataSchema).forEach(key => {
        const select = document.createElement('select');
        select.className = 'input-field dynamic-filter';
        select.dataset.key = key;
        select.innerHTML = `<option value="">All ${key}</option>`;
        metadataSchema[key].forEach(val => {
          select.innerHTML += `<option value="${val}">${val}</option>`;
        });
        select.addEventListener('change', () => { currentReviewsPage = 1; loadExplorer(); });
        container.appendChild(select);
      });
    }

    // Update dynamic table headers
    const headerRow = document.getElementById('reviews-table-header');
    if (headerRow) {
      // Keep first 6 static columns
      while (headerRow.children.length > 6) headerRow.removeChild(headerRow.lastChild);
      Object.keys(metadataSchema).forEach(key => {
        const th = document.createElement('th');
        th.innerText = key;
        headerRow.appendChild(th);
      });
    }
  } catch (err) { console.error('Failed to load metadata schema', err); }
}

function switchView(targetId) {
  navBtns.forEach(btn => btn.classList.remove('active'));
  document.querySelector(`.nav-btn[data-target="${targetId}"]`)?.classList.add('active');
  
  views.forEach(view => view.classList.remove('active'));
  document.getElementById(`view-${targetId}`).classList.add('active');

  if (targetId === 'dashboard') loadDashboard();
  if (targetId === 'explorer') loadExplorer();
}

// --- Data Loading & Dashboard ---
async function loadDashboard() {
  try {
    const settings = await fetchAPI('/settings');
    const trends = await fetchAPI('/trends');
    
    // Fetch Data for Product A
    let urlA = `/stats`;
    let themesUrlA = `/themes`;
    if (activeProduct && activeProduct !== 'All Products') {
        urlA += `?product=${encodeURIComponent(activeProduct)}`;
        themesUrlA += `?product=${encodeURIComponent(activeProduct)}`;
    }
    const statsA = await fetchAPI(urlA, 'GET', null, true);
    const themesA = await fetchAPI(themesUrlA, 'GET', null, true);
    
    let statsB = null;
    let themesB = null;
    
    if (compareProduct) {
        let urlB = `/stats?product=${encodeURIComponent(compareProduct)}`;
        let themesUrlB = `/themes?product=${encodeURIComponent(compareProduct)}`;
        statsB = await fetchAPI(urlB, 'GET', null, true);
        themesB = await fetchAPI(themesUrlB, 'GET', null, true);
    }
    
    if (compareProduct) {
      document.getElementById('db-business-name').innerText = `${activeProduct} vs ${compareProduct}`;
    } else {
      document.getElementById('db-business-name').innerText = activeProduct === 'All Products' ? (settings.business_name || 'ReviewIQ Dashboard') : `${activeProduct} Dashboard`;
    }
    
    // Handle Alerts
    const alertBanner = document.getElementById('anomaly-alert-banner');
    const alertText = document.getElementById('anomaly-alert-text');
    if (trends && trends.alerts && trends.alerts.length > 0) {
      alertText.innerText = trends.alerts[0].message;
      alertBanner.style.display = 'flex';
    } else {
      alertBanner.style.display = 'none';
    }
    
    document.getElementById('stat-total').innerText = statsA.total.toLocaleString() + (statsB ? ` / ${statsB.total.toLocaleString()}` : '');
    document.getElementById('stat-avg').innerText = statsA.avgSentiment + '%' + (statsB ? ` / ${statsB.avgSentiment}%` : '');
    document.getElementById('stat-critical').innerText = statsA.criticalCount.toLocaleString() + (statsB ? ` / ${statsB.criticalCount.toLocaleString()}` : '');
    document.getElementById('stat-top-theme').innerText = themesA.length > 0 ? themesA[0].name : '-';
    
    if (statsA.analyzed > 0) {
      statusDate.innerText = `Last analyzed: ${new Date().toLocaleDateString()}`;
    }

    renderCharts(statsA, themesA, statsB, themesB);
    renderInsights(statsA, themesA);
    renderSources();
    renderSampleReviews();
  } catch (err) {
    console.error(err);
    showToast('Failed to load dashboard data', 'error');
  }
}

function renderCharts(statsA, themesA, statsB, themesB) {
  if (!window.Chart) return;
  Chart.defaults.color = getComputedStyle(document.body).getPropertyValue('--text-muted').trim() || '#6c757d';
  Chart.defaults.font.family = getComputedStyle(document.body).fontFamily || 'sans-serif';

  // --- Theme Chart ---
  const themeCtx = document.getElementById('themeChart').getContext('2d');
  
  let themeLabels = [];
  let datasets = [];
  
  if (statsB) {
      // Grouped bar chart
      const allThemeNames = new Set([...themesA.map(t => t.name), ...themesB.map(t => t.name)]);
      themeLabels = Array.from(allThemeNames);
      
      const dataA = themeLabels.map(label => {
          const t = themesA.find(x => x.name === label);
          return t ? t.volume : 0;
      });
      const dataB = themeLabels.map(label => {
          const t = themesB.find(x => x.name === label);
          return t ? t.volume : 0;
      });
      
      datasets = [
          { label: activeProduct, data: dataA, backgroundColor: '#4A90E2', borderRadius: 4 },
          { label: compareProduct, data: dataB, backgroundColor: '#D0021B', borderRadius: 4 }
      ];
  } else {
      themeLabels = themesA.map(t => t.name);
      datasets = [{
        label: 'Review Volume',
        data: themesA.map(t => t.volume),
        backgroundColor: themesA.map(t => t.color),
        borderRadius: 4
      }];
  }

  if (themeChartInstance) themeChartInstance.destroy();
  themeChartInstance = new Chart(themeCtx, {
    type: 'bar',
    data: { labels: themeLabels, datasets: datasets },
    options: {
      indexAxis: 'y',
      responsive: true,
      maintainAspectRatio: false,
      scales: {
        x: { grid: { color: 'rgba(255, 255, 255, 0.05)' } },
        y: { grid: { color: 'rgba(255, 255, 255, 0.05)' } }
      },
      plugins: { legend: { display: !!statsB } },
      onClick: (e, elements) => {
        if (elements.length > 0) switchView('explorer');
      }
    }
  });

  // --- Sentiment Chart ---
  const sentCtx = document.getElementById('sentimentChart').getContext('2d');
  
  let sentData = {};
  if (statsB) {
      sentData = {
          labels: ['Positive', 'Neutral', 'Negative'],
          datasets: [
              { label: activeProduct, data: [statsA.pos, statsA.neu, statsA.neg], backgroundColor: ['#00e676', '#78716c', '#ff1744'], borderWidth: 0, hoverOffset: 4 },
              { label: compareProduct, data: [statsB.pos, statsB.neu, statsB.neg], backgroundColor: ['#00b259', '#57524e', '#d31539'], borderWidth: 0, hoverOffset: 4 }
          ]
      };
  } else {
      sentData = {
          labels: ['Positive', 'Neutral', 'Negative'],
          datasets: [{
            data: [statsA.pos, statsA.neu, statsA.neg],
            backgroundColor: ['#00e676', '#78716c', '#ff1744'],
            borderWidth: 0,
            hoverOffset: 4
          }]
      };
  }
  
  if (sentimentChartInstance) sentimentChartInstance.destroy();
  sentimentChartInstance = new Chart(sentCtx, {
    type: 'doughnut',
    data: sentData,
    options: {
      responsive: true,
      maintainAspectRatio: false,
      cutout: statsB ? '40%' : '70%',
      plugins: { legend: { position: 'bottom' } }
    }
  });
}

function renderInsights(stats, themes) {
  const i1 = document.getElementById('insight-1');
  const i2 = document.getElementById('insight-2');
  const i3 = document.getElementById('insight-3');

  if (stats.total === 0) {
    i1.innerText = "Import data to generate insights.";
    i2.innerText = "";
    i3.innerText = "";
    return;
  }

  i1.innerHTML = `<strong>Overall Health:</strong> Sentiment is ${stats.avgSentiment > 50 ? 'leaning positive' : 'leaning negative'} at ${stats.avgSentiment}%.`;
  i2.innerHTML = themes.length > 0 ? `<strong>Top Driver:</strong> "${themes[0].name}" is the most frequently mentioned theme.` : '';
  i3.innerHTML = stats.criticalCount > 0 ? `<strong>Action Needed:</strong> There are ${stats.criticalCount} critical negative reviews requiring attention.` : 'No critical issues detected.';
}

async function renderSources() {
  try {
    const sources = await fetchAPI('/sources');
    const list = document.getElementById('sources-list');
    list.innerHTML = '';
    for (const s of sources) {
      list.innerHTML += `<li><span>${s.source}</span> <strong>${s.count}</strong></li>`;
    }
  } catch (err) { console.error('Failed to load sources:', err); }
}

async function renderSampleReviews() {
  try {
    const pos = await fetchAPI('/reviews?sentiment=POSITIVE&limit=1');
    const neg = await fetchAPI('/reviews?sentiment=NEGATIVE&limit=1');
    if (pos.length) document.getElementById('sample-pos-text').innerText = `"${pos[0].text}" - ${pos[0].author}`;
    if (neg.length) document.getElementById('sample-neg-text').innerText = `"${neg[0].text}" - ${neg[0].author}`;
  } catch (e) { console.error(e); }
}

async function checkTrends() {
  try {
    const data = await fetchAPI('/trends');
    alertsContainer.innerHTML = '';
    if (data.alerts && data.alerts.length > 0) {
      data.alerts.forEach(alert => {
        alertsContainer.innerHTML += `
          <div class="alert-banner">
            <div>${alert.message}</div>
            <button class="alert-close" onclick="this.parentElement.remove()">×</button>
          </div>
        `;
      });
    }
  } catch (err) { console.error(err); }
}

// --- Import Logic ---
function setupImportModal() {
  const cancelBtn = document.getElementById('btn-cancel-import');
  const confirmBtn = document.getElementById('btn-confirm-import');

  cancelBtn.addEventListener('click', hideImportModal);
  
  confirmBtn.addEventListener('click', async () => {
    let type = document.getElementById('import-type').value;
    const fileInput = document.getElementById('import-file');
    let content = document.getElementById('import-content').value;
    
    if (fileInput.files.length > 0) {
      const file = fileInput.files[0];
      content = await file.text();
      if (file.name.toLowerCase().endsWith('.csv')) type = 'csv';
      else type = 'text';
    }
    
    if (!content.trim()) {
      showToast('Please upload a file or paste some content.', 'error');
      return;
    }

    try {
      document.getElementById('import-progress').classList.remove('hidden');
      confirmBtn.disabled = true;
      cancelBtn.disabled = true;
      
      updateProgress({ message: 'Parsing...', percent: 10, busy: true });
      let parsed = [];
      
      if (type === 'csv') {
        const results = Papa.parse(content, { header: true, skipEmptyLines: true });
        parsed = results.data.map(row => {
          let textStr = '';
          let maxLen = 0;
          let ratingVal = 3;
          let dateVal = new Date().toISOString().split('T')[0];
          let authorVal = 'Anonymous';
          let sourceVal = 'CSV Import';
          let productVal = 'Global';
          let foundExplicitText = false;
          let metadataObj = {};

          for (const [key, val] of Object.entries(row)) {
            if (!val) continue;
            const k = key.toLowerCase().trim();
            const v = String(val).trim();
            
            // Check for explicit text column
            if (!foundExplicitText && (k.includes('text') || k.includes('review') || k.includes('content') || k.includes('comment') || k.includes('feedback') || k.includes('message') || k.includes('body'))) {
              textStr = v;
              foundExplicitText = true;
            } 
            // Fallback: if no explicit header found, always keep the longest string
            else if (!foundExplicitText && v.length > maxLen && isNaN(v)) {
              textStr = v;
              maxLen = v.length;
            }
            
            if (k.includes('rating') || k.includes('score') || k.includes('star') || k.includes('grade')) {
              const num = parseFloat(v);
              if (!isNaN(num) && num > 0 && num <= 100) ratingVal = num > 5 ? (num/20) : num;
            }
            else if (k.includes('date') || k.includes('time') || k.includes('submitted')) dateVal = v;
            else if (k.includes('author') || k.includes('user') || k.includes('name') || k.includes('reviewer')) authorVal = v;
            else if (k.includes('source') || k.includes('platform')) sourceVal = v;
            else if (k.includes('product') || k.includes('item') || k.includes('movie') || k.includes('sku') || k.includes('asin')) productVal = v;
            else {
              // Unrecognized column -> bundle into metadata
              metadataObj[key] = v;
            }
          }
          
          return {
            text: textStr.replace(/<[^>]*>?/gm, '').trim(),
            rating: ratingVal,
            date: dateVal,
            author: authorVal,
            source: sourceVal,
            product: productVal,
            metadata: metadataObj
          };
        }).filter(r => r.text.length > 0);
      } else {
        const blocks = content.split(/\n\s*\n|\n/);
        parsed = blocks.map(block => ({
          text: block.replace(/<[^>]*>?/gm, '').trim(),
          rating: 3,
          date: new Date().toISOString().split('T')[0],
          author: 'Anonymous',
          source: 'Text Import'
        })).filter(r => r.text.length > 0);
      }
      
      if (parsed.length === 0) throw new Error("No valid reviews found.");
      
      const skipDuplicates = document.getElementById('import-skip-duplicates').checked;
      
      updateProgress({ message: 'Sending to Server...', percent: 20, busy: true });
      
      const result = await fetchAPI('/import', 'POST', { 
        reviews: parsed,
        skipDuplicates: skipDuplicates
      });
      
      showToast(`Imported ${result.imported} reviews. Skipped ${result.duplicates} duplicates.`, 'success');
      
      document.getElementById('import-content').value = '';
      fileInput.value = '';
      hideImportModal();
      document.getElementById('import-progress').classList.add('hidden');
      confirmBtn.disabled = false;
      cancelBtn.disabled = false;
      await setupProductFilter(); // Refresh dropdown
      loadDashboard();
      
    } catch (err) {
      showToast(err.message || 'Import failed', 'error');
    } finally {
      document.getElementById('import-progress').classList.add('hidden');
      confirmBtn.disabled = false;
      cancelBtn.disabled = false;
    }
  });
}

function showImportModal() { importModal.classList.remove('hidden'); }
function hideImportModal() { importModal.classList.add('hidden'); }

// --- AI Progress ---
let lastPercent = -1;
function updateProgress(data) {
  const bar = document.querySelector('.progress-bar-fill');
  const text = document.querySelector('.progress-text');
  if (bar && text && data.percent !== lastPercent) {
    bar.style.width = `${data.percent}%`;
    text.innerText = data.message;
    lastPercent = data.percent;
  }
  setStatus(data.message, data.busy);
  
  if (data.percent === 100 && data.message.includes('Complete')) {
    setTimeout(loadDashboard, 1000);
  }
}

function setStatus(msg, isBusy) {
  statusText.innerText = msg;
  if (isBusy) statusIndicator.classList.add('busy');
  else statusIndicator.classList.remove('busy');
}

// --- Explorer ---
function setupExplorer() {
  document.getElementById('btn-prev-page').addEventListener('click', () => {
    if (currentReviewsPage > 1) { currentReviewsPage--; loadExplorer(); }
  });
  document.getElementById('btn-next-page').addEventListener('click', () => {
    currentReviewsPage++; loadExplorer();
  });

  const triggerSearch = debounce(() => { currentReviewsPage = 1; loadExplorer(); }, 300);
  document.getElementById('search-input').addEventListener('input', triggerSearch);
  document.getElementById('filter-sentiment').addEventListener('change', triggerSearch);
  document.getElementById('filter-rating').addEventListener('change', triggerSearch);
}

async function loadExplorer() {
  const search = document.getElementById('search-input').value;
  const sentiment = document.getElementById('filter-sentiment').value;
  const rating = document.getElementById('filter-rating').value;

  const params = new URLSearchParams({ page: currentReviewsPage, limit: REVIEWS_PER_PAGE });
  if (search) params.append('search', search);
  if (sentiment) params.append('sentiment', sentiment);
  if (rating) params.append('rating', rating);
  
  document.querySelectorAll('.dynamic-filter').forEach(select => {
    if (select.value) params.append(`meta_${select.dataset.key}`, select.value);
  });

  try {
    const reviews = await fetchAPI(`/reviews?${params.toString()}`);
    
    const tbody = document.getElementById('reviews-table-body');
    tbody.innerHTML = '';
    
    reviews.forEach(r => {
      let badgeClass = r.sentiment_label === 'POSITIVE' ? 'pos' : (r.sentiment_label === 'NEGATIVE' ? 'neg' : 'neu');
      let tr = document.createElement('tr');
      
      let dynamicCells = '';
      let metaObj = {};
      try { if (r.metadata) metaObj = JSON.parse(r.metadata); } catch(e){}
      
      Object.keys(metadataSchema).forEach(key => {
        const val = metaObj[key] !== undefined ? metaObj[key] : '-';
        dynamicCells += `<td>${val}</td>`;
      });
      
      tr.innerHTML = `
        <td style="white-space: nowrap">${r.date}</td>
        <td>${r.source}</td>
        <td>${'★'.repeat(r.rating)}${'☆'.repeat(5-r.rating)}</td>
        <td><span class="badge ${badgeClass}">${r.sentiment_label || 'UNANALYZED'}</span></td>
        <td>${r.themes || '-'}</td>
        <td style="max-width:300px; overflow:hidden; text-overflow:ellipsis; white-space:nowrap;" title="${r.text}">${r.text}</td>
        ${dynamicCells}
      `;
      tbody.appendChild(tr);
    });

    document.getElementById('page-indicator').innerText = `Page ${currentReviewsPage}`;
  } catch (err) {
    showToast('Failed to load reviews', 'error');
  }
}

// --- Settings ---
function setupSettings() {
  document.getElementById('btn-save-settings').addEventListener('click', async () => {
    const settings = {
      business_name: document.getElementById('set-biz-name').value,
      date_range: document.getElementById('set-date-range').value,
      theme_count: document.getElementById('set-theme-count').value,
      neutral_threshold: document.getElementById('set-neutral-thresh').value
    };
    await fetchAPI('/settings', 'POST', settings);
    showToast('Settings saved successfully', 'success');
    loadSettings();
  });

  document.getElementById('btn-rerun-ai').addEventListener('click', async () => {
    if (confirm("This will re-process all reviews. It may take some time. Proceed?")) {
      await fetchAPI('/rerun_ai', 'POST');
      showToast('AI Pipeline Started', 'success');
    }
  });

  document.getElementById('btn-clear-data').addEventListener('click', async () => {
    if (confirm("WARNING: This will permanently delete all reviews and analysis. Are you sure?")) {
      await fetchAPI('/clear', 'POST');
      showToast('Data cleared.', 'success');
      loadDashboard();
    }
  });
}

async function loadSettings() {
  try {
    const settings = await fetchAPI('/settings');
    if (settings.business_name) {
      document.getElementById('set-biz-name').value = settings.business_name;
    }
    if (settings.date_range) {
      document.getElementById('set-date-range').value = settings.date_range;
      document.getElementById('db-date-range-text').innerText = `Last ${settings.date_range} Days`;
    }
    if (settings.theme_count) {
      document.getElementById('set-theme-count').value = settings.theme_count;
      document.getElementById('theme-val').innerText = settings.theme_count;
    }
    if (settings.neutral_threshold) {
      document.getElementById('set-neutral-thresh').value = settings.neutral_threshold;
      document.getElementById('thresh-val').innerText = settings.neutral_threshold;
    }
  } catch(e) { console.error('Failed to load settings', e); }
}

// --- PDF Export ---
function setupPdfExport() {
  document.getElementById('btn-export-pdf').addEventListener('click', exportPDF);
}

async function exportPDF() {
  const reportContainer = document.getElementById('report-container');
  showToast('Generating PDF...', 'info');
  
  try {
    const canvas = await window.html2canvas(reportContainer, { scale: 2, useCORS: true, logging: false });
    const imgData = canvas.toDataURL('image/png');
    const pdf = new window.jspdf.jsPDF('p', 'mm', 'a4');
    const pdfWidth = pdf.internal.pageSize.getWidth();
    const pdfHeight = (canvas.height * pdfWidth) / canvas.width;
    
    pdf.addImage(imgData, 'PNG', 0, 0, pdfWidth, pdfHeight);
    pdf.save('ReviewIQ_Report.pdf');
    showToast('PDF Exported successfully', 'success');
  } catch (err) {
    showToast('PDF Export failed: ' + err.message, 'error');
  }
}

// --- Utils ---
function setupFilters() {
  document.querySelectorAll('.filter-btn').forEach(btn => {
    btn.addEventListener('click', () => {
      document.querySelectorAll('.filter-btn').forEach(b => b.classList.remove('active'));
      btn.classList.add('active');
      currentDaysFilter = btn.dataset.days;
      document.getElementById('db-date-range-text').innerText = btn.innerText;
    });
  });
}

function showToast(message, type = 'info') {
  const el = document.createElement('div');
  el.className = `toast ${type}`;
  el.innerText = message;
  toastContainer.appendChild(el);
  setTimeout(() => el.remove(), 4000);
}

function debounce(func, wait) {
  let timeout;
  return function(...args) {
    clearTimeout(timeout);
    timeout = setTimeout(() => func.apply(this, args), wait);
  };
}

// Run
window.addEventListener('DOMContentLoaded', init);
