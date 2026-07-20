let predictionData = [];
let riskChart;
let signalChart;
let labelMapping = { high_risk: 'high_risk', low_risk: 'low_risk' };

async function loadDashboard() {
    try {
        const role = document.getElementById('roleSelect').value;
        const apiKey = localStorage.getItem('show_ai_model_key') || '';
        const [summaryRes, predictionRes, chartsRes, insightsRes, aiRes, brandingRes] = await Promise.all([
            fetch('/api/summary'),
            fetch('/api/predictions'),
            fetch('/api/charts'),
            fetch(`/api/insights?role=${role}`),
            fetch(`/api/ai-insights?model_key=${encodeURIComponent(apiKey)}`),
            fetch('/api/branding')
        ]);

        const summaryData = await summaryRes.json();
        const predictionsPayload = await predictionRes.json();
        const chartsData = await chartsRes.json();
        const insightsData = await insightsRes.json();
        const aiData = await aiRes.json();
        const brandingData = await brandingRes.json();

        predictionData = predictionsPayload.predictions || [];
        labelMapping = brandingData.label_mapping || { high_risk: 'high_risk', low_risk: 'low_risk' };

        const riskFilter = document.getElementById('riskFilter');
        if (riskFilter) {
            const currentVal = riskFilter.value;
            const highLabel = labelMapping.high_risk.replace('_', ' ').replace(/\b\w/g, l => l.toUpperCase());
            const lowLabel = labelMapping.low_risk.replace('_', ' ').replace(/\b\w/g, l => l.toUpperCase());
            riskFilter.innerHTML = `
                <option value="all">All risks</option>
                <option value="${labelMapping.high_risk}">${highLabel}</option>
                <option value="${labelMapping.low_risk}">${lowLabel}</option>
            `;
            if (currentVal && (currentVal === 'all' || currentVal === labelMapping.high_risk || currentVal === labelMapping.low_risk)) {
                riskFilter.value = currentVal;
            } else {
                riskFilter.value = 'all';
            }
        }

        const company = document.getElementById('companyNameInput').value || brandingData.company_name || 'RetentionIQ Analytics';
        document.getElementById('brandTitle').textContent = company;

        renderSourceMeta();
        renderRows();
        renderCharts(chartsData);
        renderInsights(insightsData);
        renderExecutiveSummary(insightsData);
        renderAiPanel(aiData);
        
        // NotebookLM sidebars refresh
        await fetchSources();
        await fetchNotes();
        await loadBusinessAnalytics();
    } catch (error) {
        console.error('Dashboard load failed', error);
    }
}

function renderSourceMeta() {
    const total = predictionData.length;
    const highRisk = predictionData.filter(item => item.prediction_label === labelMapping.high_risk).length;
    const fields = Array.from(new Set(predictionData.flatMap(item => Object.keys(item)))).sort();

    document.getElementById('metaTotal').textContent = total;
    document.getElementById('metaHigh').textContent = highRisk;
    document.getElementById('metaLow').textContent = total - highRisk;
    document.getElementById('metaFields').textContent = fields.length || '—';
}

function renderAiPanel(aiData) {
    document.getElementById('aiHeadline').textContent = aiData.headline || 'Awaiting analysis';
    document.getElementById('aiNarrative').textContent = aiData.narrative || '';
    const segments = aiData.segments || [];
    document.getElementById('aiSegments').innerHTML = segments.length
        ? segments.map(s => `<div class="aiSegment"><h4>${s.title}</h4><p>${s.detail}</p></div>`).join('')
        : '';
}

const INTERNAL_COLUMNS = new Set(['predicted_probability', 'prediction_label', 'created_at', 'churned']);

function dynamicColumns() {
    const idCol = predictionData.some(r => r.customer_id !== undefined && r.customer_id !== null)
        ? 'customer_id'
        : (predictionData.some(r => r.id !== undefined) ? 'id' : null);

    const extra = [];
    if (predictionData.length) {
        for (const key of Object.keys(predictionData[0])) {
            if (key === idCol || INTERNAL_COLUMNS.has(key)) continue;
            const vals = predictionData.slice(0, 50).map(r => r[key]);
            const nonEmpty = vals.filter(v => v !== null && v !== undefined && v !== '');
            if (!nonEmpty.length) continue;
            extra.push(key);
            if (extra.length >= 7) break;
        }
    }
    return { idCol, extra };
}

function renderRows() {
    const filterValue = document.getElementById('riskFilter').value;
    const table = document.getElementById('predictionTable');
    const rows = document.getElementById('predictionRows');
    if (!table || !rows) return;

    const { idCol, extra } = dynamicColumns();
    const headers = ['Customer', 'Risk', 'Probability', ...extra.map(c => c.replace(/_/g, ' ').replace(/\b\w/g, l => l.toUpperCase()))];

    let thead = table.querySelector('thead');
    if (!thead) {
        thead = document.createElement('thead');
        table.appendChild(thead);
    }
    thead.innerHTML = `<tr>${headers.map(h => `<th>${h}</th>`).join('')}</tr>`;
    rows.innerHTML = '';

    const filtered = filterValue === 'all'
        ? predictionData
        : predictionData.filter(item => item.prediction_label === filterValue);

    if (!filtered.length) {
        rows.innerHTML = `<tr><td colspan="${headers.length}" class="empty">No records to display yet. Upload a file to begin.</td></tr>`;
        return;
    }

    const cell = (value) => value === null || value === undefined || value === '' ? 'n/a' : value;
    filtered.forEach(item => {
        const probability = Number(item.predicted_probability || 0).toFixed(3);
        const labelClass = item.prediction_label === labelMapping.high_risk ? 'high' : 'low';
        const idVal = idCol ? cell(item[idCol]) : cell(item.customer_id);

        const tds = [`<td>${idVal}</td>`,
            `<td><span class="badge ${labelClass}">${item.prediction_label.replace('_', ' ')}</span></td>`,
            `<td>${probability}</td>`,
            ...extra.map(c => `<td>${cell(item[c])}</td>`)].join('');

        const row = document.createElement('tr');
        row.innerHTML = tds;
        rows.appendChild(row);
    });
}

function renderCharts(chartPayload) {
    const riskLabels = (chartPayload.charts || []).map(item => item.label);
    const riskValues = (chartPayload.charts || []).map(item => item.value);
    const signalLabels = (chartPayload.signals || []).map(item => item.label);
    const signalValues = (chartPayload.signals || []).map(item => item.value);

    if (riskChart) riskChart.destroy();
    if (signalChart) signalChart.destroy();

    const bodyStyles = getComputedStyle(document.body);
    const labelColor = bodyStyles.getPropertyValue('--muted').trim() || '#475467';
    const gridColor = bodyStyles.getPropertyValue('--border').trim() || 'rgba(16, 24, 40, 0.08)';

    riskChart = new Chart(document.getElementById('riskChart'), {
        type: 'doughnut',
        data: {
            labels: riskLabels.length ? riskLabels : ['No data'],
            datasets: [{ data: riskValues.length ? riskValues : [1], backgroundColor: ['#ff5d5d', '#37d39b', '#4f8cff'] }]
        },
        options: { responsive: true, maintainAspectRatio: false, cutout: '62%', plugins: { legend: { labels: { color: labelColor } } } }
    });

    signalChart = new Chart(document.getElementById('signalChart'), {
        type: 'bar',
        data: {
            labels: signalLabels.length ? signalLabels : ['No retention signals'],
            datasets: [{ label: 'Customers', data: signalValues.length ? signalValues : [0], backgroundColor: ['#6ea8ff', '#37d39b', '#ffb454', '#ff5d5d'] }]
        },
        options: {
            responsive: true, maintainAspectRatio: false,
            plugins: { legend: { display: false } },
            scales: {
                y: { beginAtZero: true, ticks: { color: labelColor }, grid: { color: gridColor } },
                x: { ticks: { color: labelColor }, grid: { color: gridColor } }
            }
        }
    });
}

function renderExecutiveSummary(insightsData) {
    const highRisk = predictionData.filter(item => item.prediction_label === labelMapping.high_risk).length;
    const lowRisk = predictionData.length - highRisk;
    const avgProbability = predictionData.length
        ? (predictionData.reduce((acc, item) => acc + Number(item.predicted_probability || 0), 0) / predictionData.length).toFixed(3)
        : '0.000';
    const actions = (insightsData.recommendations || []).length;

    document.getElementById('executiveSummary').innerHTML = `
        <div><strong>Risk mix</strong><p>${highRisk} high / ${lowRisk} low</p></div>
        <div><strong>Avg churn probability</strong><p>${avgProbability}</p></div>
        <div><strong>AI recommendations</strong><p>${actions} prioritized actions</p></div>
    `;
}

function renderInsights(insightsData) {
    const panel = document.getElementById('insightPanel');
    const recommendations = insightsData.recommendations || [];
    panel.innerHTML = recommendations.length
        ? recommendations.map(item => `<p>${item}</p>`).join('')
        : '<p>No insights available yet.</p>';
}

async function uploadFile() {
    const fileInput = document.getElementById('fileInput');
    const status = document.getElementById('uploadStatus');

    if (!fileInput.files.length) {
        status.textContent = 'Please choose a file first.';
        status.className = 'status error';
        return;
    }

    const formData = new FormData();
    formData.append('file', fileInput.files[0]);

    status.textContent = 'Uploading and analyzing...';
    status.className = 'status';

    try {
        const response = await fetch('/api/upload', { method: 'POST', body: formData });
        const payload = await response.json();
        if (response.ok && payload.status === 'ok') {
            status.textContent = `Analysis complete: ${payload.rows} rows processed.`;
            status.className = 'status success';
            await loadDashboard();
            await fetchSources();
        } else {
            status.textContent = payload.message || 'Upload failed. Please try again.';
            status.className = 'status error';
        }
    } catch (error) {
        status.textContent = 'Upload failed. Please try again.';
        status.className = 'status error';
    }
}

function setupTabs() {
    document.querySelectorAll('.tab').forEach(tab => {
        tab.addEventListener('click', () => {
            document.querySelectorAll('.tab').forEach(t => t.classList.remove('active'));
            document.querySelectorAll('.tabBody').forEach(b => b.classList.add('hidden'));
            tab.classList.add('active');
            document.getElementById(`tab-${tab.dataset.tab}`).classList.remove('hidden');
        });
    });
}

document.getElementById('addSourceBtn').addEventListener('click', () => {
    document.getElementById('fileInput').click();
});
document.getElementById('fileInput').addEventListener('change', uploadFile);
document.getElementById('riskFilter').addEventListener('change', renderRows);
document.getElementById('roleSelect').addEventListener('change', loadDashboard);
document.getElementById('exportTableauBtn').addEventListener('click', () => {
    if (!predictionData || !predictionData.length) {
        alert("No prediction data available to export. Please upload a customer file first.");
        return;
    }
    window.open('/api/export/tableau', '_blank');
});
document.getElementById('exportPowerBiBtn').addEventListener('click', () => {
    if (!predictionData || !predictionData.length) {
        alert("No prediction data available to export. Please upload a customer file first.");
        return;
    }
    window.open('/api/export/powerbi', '_blank');
});
document.getElementById('exportExcelBtn').addEventListener('click', () => {
    if (!predictionData || !predictionData.length) {
        alert("No prediction data available to export. Please upload a customer file first.");
        return;
    }
    window.open('/api/export/excel', '_blank');
});
document.getElementById('exportPdfBtn').addEventListener('click', () => {
    if (!predictionData || !predictionData.length) {
        alert("No prediction data available to export. Please upload a customer file first.");
        return;
    }
    window.open('/api/export/pdf', '_blank');
});
document.getElementById('companyNameInput').addEventListener('input', () => {
    const name = document.getElementById('companyNameInput').value.trim();
    if (name) document.getElementById('brandTitle').textContent = name;
});

function animateLogo() {
    const el = document.getElementById('logoChar');
    if (!el) return;
    const glyphs = ['R', 'A', 'I', '◷', '⬡', '✦', '◉'];
    let i = Math.floor(Math.random() * glyphs.length);
    el.textContent = glyphs[i];
    setInterval(() => {
        i = (i + 1) % glyphs.length;
        el.textContent = glyphs[i];
    }, 2500);
}

setupTabs();
animateLogo();
loadDashboard();

// AI Copilot Integration
let chatHistory = [];

function setupCopilot() {
    const storedKey = localStorage.getItem('show_ai_model_key') || '';
    const keyInput = document.getElementById('geminiApiKeyInput');
    if (keyInput) {
        keyInput.value = storedKey;
        keyInput.addEventListener('input', (e) => {
            localStorage.setItem('show_ai_model_key', e.target.value.trim());
            loadDashboard();
        });
    }

    const chatForm = document.getElementById('chatForm');
    if (chatForm) {
        chatForm.addEventListener('submit', handleChatMessage);
    }

    const suggestionChips = document.getElementById('suggestionChips');
    if (suggestionChips) {
        suggestionChips.querySelectorAll('.chip').forEach(chip => {
            chip.addEventListener('click', () => {
                const input = document.getElementById('chatInput');
                if (input) {
                    input.value = chip.textContent;
                    handleChatMessage();
                }
            });
        });
    }

    // Initialize Business Hub, Presentation, and Notes
    setupBusinessHub();
    setupPresentation();
    const createNoteBtn = document.getElementById('createNoteBtn');
    if (createNoteBtn) {
        createNoteBtn.addEventListener('click', createNote);
    }
}

async function handleChatMessage(event) {
    if (event) event.preventDefault();

    const input = document.getElementById('chatInput');
    if (!input) return;
    const text = input.value.trim();
    if (!text) return;

    input.value = '';
    appendMessage('user', text);

    const chatSendButton = document.getElementById('chatSendButton');
    if (chatSendButton) chatSendButton.disabled = true;

    const loadingId = appendMessage('bot', 'Thinking...');

    try {
        const apiKey = localStorage.getItem('show_ai_model_key') || '';
        const response = await fetch('/api/chat', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
                message: text,
                history: chatHistory,
                model_key: apiKey
            })
        });

        const payload = await response.json();
        removeMessage(loadingId);

        if (response.ok && payload.response) {
            appendMessage('bot', payload.response, true);
            chatHistory.push({ role: 'user', text: text });
            chatHistory.push({ role: 'model', text: payload.response });
            if (chatHistory.length > 20) {
                chatHistory.shift();
                chatHistory.shift();
            }
        } else {
            appendMessage('bot', payload.error || payload.response || 'An error occurred. Please try again.');
        }
    } catch (error) {
        removeMessage(loadingId);
        appendMessage('bot', 'Could not reach server. Please check your connection.');
    } finally {
        if (chatSendButton) chatSendButton.disabled = false;
    }
}

function appendMessage(role, text, isMarkdown = false) {
    const messagesContainer = document.getElementById('chatMessages');
    if (!messagesContainer) return null;
    const msgDiv = document.createElement('div');
    msgDiv.className = `msg ${role}`;
    const msgId = 'msg-' + Date.now() + '-' + Math.random().toString(36).substr(2, 9);
    msgDiv.id = msgId;

    if (isMarkdown && typeof marked !== 'undefined') {
        let parsed = marked.parse(text);
        parsed = parsed.replace(/\[((?:C|U|N)\d+)\]/g, '<span class="citation-badge" onclick="highlightCustomer(\'$1\')">[$1]</span>');
        msgDiv.innerHTML = parsed;
    } else {
        let parsed = text.replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;");
        parsed = parsed.replace(/\[((?:C|U|N)\d+)\]/g, '<span class="citation-badge" onclick="highlightCustomer(\'$1\')">[$1]</span>');
        msgDiv.innerHTML = parsed;
    }

    messagesContainer.appendChild(msgDiv);
    messagesContainer.scrollTop = messagesContainer.scrollHeight;
    return msgId;
}

function removeMessage(id) {
    const msg = document.getElementById(id);
    if (msg) msg.remove();
}

// NotebookLM Extensions

// 1. Sources Management
async function fetchSources() {
    try {
        const res = await fetch('/api/sources');
        const data = await res.json();
        renderSourcesList(data.sources || []);
    } catch (e) {
        console.error("Failed to fetch sources", e);
    }
}

function renderSourcesList(sources) {
    const container = document.getElementById('sourcesList');
    if (!container) return;
    if (!sources.length) {
        container.innerHTML = '<p class="emptyHint">No source documents loaded yet. Click + Add to begin.</p>';
        return;
    }
    
    container.innerHTML = sources.map(src => {
        const activeClass = src.is_active ? 'active' : '';
        const checked = src.is_active ? 'checked' : '';
        return `
            <div class="sourceItem ${activeClass}" data-id="${src.source_id}">
                <div class="sourceItemLeft">
                    <input type="checkbox" class="sourceCheckbox" ${checked} onchange="toggleSource('${src.source_id}', this.checked)" />
                    <span class="sourceName" title="${src.filename}">${src.filename}</span>
                </div>
                <div class="sourceItemRight">
                    <span class="sourceRows">${src.row_count} rows</span>
                    <button class="deleteSourceBtn" onclick="deleteSource('${src.source_id}')" title="Delete source">&times;</button>
                </div>
            </div>
        `;
    }).join('');
}

async function toggleSource(sourceId, isChecked) {
    try {
        const res = await fetch('/api/sources/toggle', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ source_id: sourceId, is_active: isChecked ? 1 : 0 })
        });
        if (res.ok) {
            await loadDashboard();
        }
    } catch (e) {
        console.error("Failed to toggle source", e);
    }
}

async function deleteSource(sourceId) {
    if (!confirm("Are you sure you want to delete this source? This will remove all associated customers and re-train the model.")) return;
    try {
        const res = await fetch(`/api/sources/${sourceId}`, { method: 'DELETE' });
        if (res.ok) {
            await loadDashboard();
            await fetchSources();
        }
    } catch (e) {
        console.error("Failed to delete source", e);
    }
}

// 2. Notes Management
async function fetchNotes() {
    try {
        const res = await fetch('/api/notes');
        const data = await res.json();
        renderNotesList(data.notes || []);
    } catch (e) {
        console.error("Failed to fetch notes", e);
    }
}

function renderNotesList(notes) {
    const container = document.getElementById('notesList');
    if (!container) return;
    if (!notes.length) {
        container.innerHTML = '<p class="emptyHint">No saved notes in your notebook. Click + to add one.</p>';
        return;
    }
    
    container.innerHTML = notes.map(n => `
        <div class="noteItem" id="note-${n.note_id}">
            <div class="noteItemHead">
                <h4>${n.title}</h4>
                <button class="deleteNoteBtn" onclick="deleteNote(${n.note_id})">&times;</button>
            </div>
            <div class="noteItemContent">${marked.parse(n.content)}</div>
        </div>
    `).join('');
}

async function createNote() {
    const title = prompt("Enter note title:");
    if (!title) return;
    const content = prompt("Enter note content:");
    if (!content) return;
    
    try {
        const res = await fetch('/api/notes', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ title, content })
        });
        if (res.ok) {
            fetchNotes();
        }
    } catch (e) {
        console.error("Failed to create note", e);
    }
}

async function deleteNote(noteId) {
    try {
        const res = await fetch(`/api/notes/${noteId}`, { method: 'DELETE' });
        if (res.ok) {
            fetchNotes();
        }
    } catch (e) {
        console.error("Failed to delete note", e);
    }
}

async function saveSnippetToNotes(title, content) {
    try {
        const res = await fetch('/api/notes', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ title, content })
        });
        if (res.ok) {
            fetchNotes();
            alert("Saved to Notes!");
        }
    } catch (e) {
        console.error("Failed to save snippet", e);
    }
}

// 3. Business Analytics & Campaign ROI Simulator
let currentCurrencySymbol = '$';
let currentCurrencyRate = 1.0;
let businessAnalyticsData = null;

async function loadBusinessAnalytics() {
    try {
        const res = await fetch('/api/business-analytics');
        businessAnalyticsData = await res.json();
        renderBusinessAnalytics();
    } catch (e) {
        console.error("Failed to load business analytics", e);
    }
}

function renderBusinessAnalytics() {
    if (!businessAnalyticsData) return;
    
    const charges = businessAnalyticsData.total_charges * currentCurrencyRate;
    const loss = businessAnalyticsData.expected_loss * currentCurrencyRate;
    
    document.getElementById('bizTotalCharges').textContent = `${currentCurrencySymbol}${Math.round(charges).toLocaleString()}`;
    document.getElementById('bizExpectedLoss').textContent = `${currentCurrencySymbol}${Math.round(loss).toLocaleString()}`;
    document.getElementById('bizRiskExposurePct').textContent = `${businessAnalyticsData.risk_exposure_pct}%`;
    
    renderBusinessSegments(businessAnalyticsData.segments || []);
    runCampaignSimulation();
}

function renderBusinessSegments(segments) {
    const tbody = document.getElementById('bizSegmentRows');
    if (!tbody) return;
    if (!segments.length) {
        tbody.innerHTML = '<tr><td colspan="5" class="empty">No segment data available.</td></tr>';
        return;
    }
    tbody.innerHTML = segments.map(s => {
        const loss = s.expected_loss * currentCurrencyRate;
        return `
            <tr>
                <td><strong>${s.dimension}</strong></td>
                <td><span class="badge low">${s.value}</span></td>
                <td>${s.count}</td>
                <td>${(s.avg_risk * 100).toFixed(1)}%</td>
                <td class="danger-text"><strong>${currentCurrencySymbol}${Math.round(loss).toLocaleString()}</strong></td>
            </tr>
        `;
    }).join('');
}

function setupBusinessHub() {
    const thresholdInput = document.getElementById('simRiskThreshold');
    const discountInput = document.getElementById('simDiscount');
    const successInput = document.getElementById('simSuccessRate');
    const currencySelect = document.getElementById('currencySelect');
    
    if (thresholdInput) {
        thresholdInput.addEventListener('input', runCampaignSimulation);
    }
    if (discountInput) {
        discountInput.addEventListener('input', runCampaignSimulation);
    }
    if (successInput) {
        successInput.addEventListener('input', runCampaignSimulation);
    }
    if (currencySelect) {
        currencySelect.addEventListener('change', (e) => {
            const opt = e.target.options[e.target.selectedIndex];
            currentCurrencySymbol = opt.getAttribute('data-symbol') || '$';
            currentCurrencyRate = parseFloat(opt.getAttribute('data-rate') || '1.0');
            renderBusinessAnalytics();
        });
    }
}

function runCampaignSimulation() {
    const threshold = parseFloat(document.getElementById('simRiskThreshold').value) / 100;
    const discount = parseFloat(document.getElementById('simDiscount').value) / 100;
    const successRate = parseFloat(document.getElementById('simSuccessRate').value) / 100;
    
    // Update label text indicators
    document.getElementById('valRiskThreshold').textContent = `${Math.round(threshold * 100)}%`;
    document.getElementById('valDiscount').textContent = `${Math.round(discount * 100)}%`;
    document.getElementById('valSuccessRate').textContent = `${Math.round(successRate * 100)}%`;
    
    // Compute targeted pool
    const targeted = predictionData.filter(item => Number(item.predicted_probability || 0) >= threshold);
    const count = targeted.length;
    
    const targetedRevenue = targeted.reduce((sum, item) => {
        const charges = item.monthly_charges !== undefined && item.monthly_charges !== null 
            ? Number(item.monthly_charges) 
            : 100.0;
        return sum + charges;
    }, 0);
    
    const campaignCost = targetedRevenue * discount * currentCurrencyRate;
    const grossSaved = targetedRevenue * successRate * currentCurrencyRate;
    const netSaved = grossSaved - campaignCost;
    
    const roi = campaignCost > 0 ? (netSaved / campaignCost) * 100 : 0;
    
    document.getElementById('simTargetedCount').textContent = count.toLocaleString();
    document.getElementById('simCampaignCost').textContent = `${currentCurrencySymbol}${Math.round(campaignCost).toLocaleString()}`;
    document.getElementById('simSavedRevenue').textContent = `${currentCurrencySymbol}${Math.round(grossSaved).toLocaleString()}`;
    
    const netSavedEl = document.getElementById('simNetSavedRevenue');
    netSavedEl.textContent = `${currentCurrencySymbol}${Math.round(netSaved).toLocaleString()}`;
    if (netSaved >= 0) {
        netSavedEl.parentElement.classList.remove('danger');
        netSavedEl.parentElement.classList.add('success');
    } else {
        netSavedEl.parentElement.classList.remove('success');
        netSavedEl.parentElement.classList.add('danger');
    }
    
    const roiBadge = document.getElementById('simRoiBadge');
    roiBadge.textContent = `ROI: ${Math.round(roi)}%`;
    if (roi >= 20) {
        roiBadge.className = 'roiBadge success';
    } else if (roi >= 0) {
        roiBadge.className = 'roiBadge warning';
    } else {
        roiBadge.className = 'roiBadge danger';
    }
}

// 5. Clickable Citations
function highlightCustomer(customerId) {
    const tabBtn = document.querySelector('.tab[data-tab="customers"]');
    if (tabBtn) tabBtn.click();
    
    const filter = document.getElementById('riskFilter');
    if (filter) {
        filter.value = 'all';
        renderRows();
    }
    
    setTimeout(() => {
        const rows = document.getElementById('predictionRows').querySelectorAll('tr');
        let foundRow = null;
        rows.forEach(row => {
            const cells = row.querySelectorAll('td');
            if (cells.length && cells[0].textContent.trim() === customerId) {
                foundRow = row;
            }
        });
        
        if (foundRow) {
            foundRow.scrollIntoView({ behavior: 'smooth', block: 'center' });
            foundRow.classList.add('highlightFlash');
            setTimeout(() => {
                foundRow.classList.remove('highlightFlash');
            }, 2500);
        }
    }, 250);
}

// 4. Presentation Builder Controller
let presentationSlides = [];
let currentSlideIndex = 0;

function setupPresentation() {
    const genBtn = document.getElementById('generatePresBtn');
    if (genBtn) {
        genBtn.addEventListener('click', generatePresentationDeck);
    }

    const prevBtn = document.getElementById('prevSlideBtn');
    if (prevBtn) {
        prevBtn.addEventListener('click', () => changeSlide(-1));
    }

    const nextBtn = document.getElementById('nextSlideBtn');
    if (nextBtn) {
        nextBtn.addEventListener('click', () => changeSlide(1));
    }

    const fullscreenBtn = document.getElementById('fullscreenPresBtn');
    if (fullscreenBtn) {
        fullscreenBtn.addEventListener('click', enterFullscreenPresentation);
    }

    const downloadBtn = document.getElementById('downloadPresBtn');
    if (downloadBtn) {
        downloadBtn.addEventListener('click', downloadStandalonePresentation);
    }

    // Keyboard Arrow Navigation
    document.addEventListener('keydown', (e) => {
        const presentationTab = document.querySelector('.tab[data-tab="presentation"]');
        if (presentationTab && presentationTab.classList.contains('active')) {
            if (e.key === 'ArrowLeft') {
                changeSlide(-1);
            } else if (e.key === 'ArrowRight') {
                changeSlide(1);
            } else if (e.key === 'f' || e.key === 'F') {
                enterFullscreenPresentation();
            }
        }
    });

    // Bind Presentation Q&A buttons
    document.querySelectorAll('.qa-btn').forEach(btn => {
        btn.addEventListener('click', () => {
            const question = btn.getAttribute('data-question');
            triggerQuickQA(question);
        });
    });
}

async function generatePresentationDeck() {
    const genBtn = document.getElementById('generatePresBtn');
    const status = document.getElementById('deckStatus');
    const viewport = document.getElementById('slideViewport');
    const prevBtn = document.getElementById('prevSlideBtn');
    const nextBtn = document.getElementById('nextSlideBtn');
    const fullscreenBtn = document.getElementById('fullscreenPresBtn');
    const downloadBtn = document.getElementById('downloadPresBtn');

    genBtn.disabled = true;
    genBtn.textContent = 'Compiling...';
    status.textContent = 'Analyzing active data sources and formatting professional slide templates...';

    try {
        const apiKey = localStorage.getItem('gemini_api_key') || '';
        const res = await fetch('/api/presentation', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ api_key: apiKey })
        });
        const payload = await res.json();

        if (res.ok && payload.slides) {
            presentationSlides = payload.slides;
            currentSlideIndex = 0;

            renderSlides(payload.slides);

            viewport.classList.remove('hidden');
            prevBtn.classList.remove('hidden');
            nextBtn.classList.remove('hidden');
            fullscreenBtn.classList.remove('hidden');
            downloadBtn.classList.remove('hidden');
            status.classList.add('hidden');

            updateSlideView();
        } else {
            status.textContent = 'Failed to generate presentation deck: ' + (payload.error || 'Unknown error');
            genBtn.disabled = false;
            genBtn.textContent = 'Generate Deck';
        }
    } catch (e) {
        status.textContent = 'Could not reach server to generate presentation.';
        genBtn.disabled = false;
        genBtn.textContent = 'Generate Deck';
    } finally {
        genBtn.disabled = false;
    }
}

function renderSlides(slides) {
    const viewport = document.getElementById('slideViewport');
    if (!viewport) return;

    viewport.innerHTML = slides.map((slide, idx) => {
        let contentHtml = '';
        if (slide.layout === 'title') {
            contentHtml = `
                <div class="slideContent layout-title">
                    <div class="slideDecor"></div>
                    <div class="slideHeader">
                        <div class="presMiniLogo">RetentionIQ</div>
                    </div>
                    <h1>${slide.title}</h1>
                    <p class="slideSubtitle">${slide.subtitle}</p>
                    <div class="slideFooter">
                        <span>Executive Summary & Churn Briefing</span>
                    </div>
                </div>
            `;
        } else if (slide.layout === 'split_metrics') {
            const listHtml = slide.bullets.map(b => `<li>${b}</li>`).join('');
            contentHtml = `
                <div class="slideContent layout-split">
                    <div class="slideHeader">
                        <div class="presMiniLogo">RetentionIQ</div>
                        <span>Executive Churn Summary</span>
                    </div>
                    <div class="slideSplitBody">
                        <div class="slideLeftPane">
                            <div class="statCallout pink">
                                <span>Risk Analysis Status</span>
                                <h2>ACTIVE</h2>
                            </div>
                            <div class="statCallout">
                                <span>Evaluation Method</span>
                                <h4>DATA-GROUNDED</h4>
                            </div>
                        </div>
                        <div class="slideRightPane">
                            <h2>Key Findings & Executive Insights</h2>
                            <ul>${listHtml}</ul>
                        </div>
                    </div>
                    <div class="slideFooter">
                        <span>Slide 2 of 3</span>
                    </div>
                </div>
            `;
        } else if (slide.layout === 'segment_comparison') {
            const listHtml = slide.bullets.map(b => `
                <div class="riskComparisonCard">
                    <div class="cardIcon">🎯</div>
                    <div class="cardContent">
                        <p>${b}</p>
                    </div>
                </div>
            `).join('');
            contentHtml = `
                <div class="slideContent layout-grid">
                    <div class="slideHeader">
                        <div class="presMiniLogo">RetentionIQ</div>
                        <span>Priority Segments & Strategic Roadmap</span>
                    </div>
                    <h2>Prioritized Risk Segments & Action Plan</h2>
                    <div class="slideGridBody">
                        ${listHtml}
                    </div>
                    <div class="slideFooter">
                        <span>Slide 3 of 3</span>
                    </div>
                </div>
            `;
        } else if (slide.layout === 'journey_workflow') {
            const stepsHtml = slide.steps.map((st, i) => `
                <div class="workflowStepCard" style="animation-delay: ${i * 0.15}s;">
                    <div class="workflowStepNum">0${i+1}</div>
                    <div class="workflowStepContent">
                        <h4>${st.title}</h4>
                        <p>${st.description}</p>
                    </div>
                </div>
                ${i < slide.steps.length - 1 ? '<div class="workflowConnector">➔</div>' : ''}
            `).join('');

            contentHtml = `
                <div class="slideContent layout-workflow">
                    <div class="slideHeader">
                        <div class="presMiniLogo">Show AI</div>
                        <span>Interactive Customer Journey Workflow</span>
                    </div>
                    <h2>${slide.title}</h2>
                    <div class="slideWorkflowBody">
                        ${stepsHtml}
                    </div>
                    <div class="slideFooter">
                        <span>Slide 4 of 4</span>
                    </div>
                </div>
            `;
        }

        return `
            <div class="slide" id="slide-${idx}">
                ${contentHtml}
            </div>
        `;
    }).join('');
}

function changeSlide(direction) {
    if (!presentationSlides.length) return;
    currentSlideIndex = (currentSlideIndex + direction + presentationSlides.length) % presentationSlides.length;
    updateSlideView();
}

function updateSlideView() {
    document.querySelectorAll('.slide').forEach((slide, idx) => {
        slide.classList.remove('active', 'previous', 'next');
        if (idx === currentSlideIndex) {
            slide.classList.add('active');
        } else if (idx === currentSlideIndex - 1) {
            slide.classList.add('previous');
        } else if (idx === currentSlideIndex + 1) {
            slide.classList.add('next');
        }
    });

    const indicator = document.getElementById('presIndicator');
    if (indicator) {
        indicator.innerHTML = presentationSlides.map((_, idx) => {
            const activeClass = idx === currentSlideIndex ? 'active' : '';
            return `<span class="indicatorDot ${activeClass}" onclick="jumpToSlide(${idx})"></span>`;
        }).join('') + `<span class="indicatorText">Slide ${currentSlideIndex + 1} of ${presentationSlides.length}</span>`;
    }
}

function jumpToSlide(idx) {
    currentSlideIndex = idx;
    updateSlideView();
}

function enterFullscreenPresentation() {
    const container = document.querySelector('.presContainer');
    if (!container) return;

    if (container.requestFullscreen) {
        container.requestFullscreen();
    } else if (container.webkitRequestFullscreen) {
        container.webkitRequestFullscreen();
    }
}

function downloadStandalonePresentation() {
    if (!presentationSlides.length) return;

    const slidesHtml = document.getElementById('slideViewport').innerHTML;

    const standaloneHtml = `<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>RetentionIQ Executive Slide Deck</title>
    <style>
        :root {
            --bg: #000000;
            --surface: #070709;
            --surface-2: #0e0e12;
            --text: #ffeef6;
            --muted: #a0a0b0;
            --accent: #ff007f;
            --accent-2: #ff3399;
            --accent-soft: rgba(255, 0, 127, 0.18);
            --border: rgba(255, 0, 127, 0.25);
            --shadow: 0 0 16px rgba(255, 0, 127, 0.25);
            --radius: 16px;
            --radius-sm: 12px;
            --font: 'Google Sans', 'Segoe UI', Roboto, system-ui, Arial, sans-serif;
        }

        body {
            margin: 0;
            padding: 0;
            background: var(--bg);
            color: var(--text);
            font-family: var(--font);
            height: 100vh;
            display: flex;
            justify-content: center;
            align-items: center;
            overflow: hidden;
        }

        .presContainer {
            width: 90vw;
            height: 50.625vw;
            max-width: 1280px;
            max-height: 720px;
            position: relative;
            background: var(--surface);
            border: 1px solid var(--border);
            border-radius: var(--radius);
            box-shadow: 0 12px 48px rgba(219, 39, 119, 0.2);
            overflow: hidden;
            display: flex;
            justify-content: center;
            align-items: center;
        }

        .slideViewport {
            position: absolute;
            top: 0; left: 0; right: 0; bottom: 0;
        }

        .slide {
            position: absolute;
            top: 0; left: 0; right: 0; bottom: 0;
            opacity: 0;
            transform: scale(0.95) translateY(10px);
            transition: opacity 0.5s ease, transform 0.5s ease;
            pointer-events: none;
            display: flex;
            justify-content: center;
            align-items: center;
            padding: 40px 60px;
            box-sizing: border-box;
        }

        .slide.active {
            opacity: 1;
            transform: scale(1) translateY(0);
            pointer-events: auto;
            z-index: 10;
        }

        .slideContent {
            width: 100%;
            height: 100%;
            display: flex;
            flex-direction: column;
            justify-content: space-between;
            position: relative;
        }

        .layout-title {
            justify-content: center;
            align-items: center;
            text-align: center;
        }

        .layout-title h1 {
            font-size: 2.8rem;
            margin: 0 0 16px;
            color: #ffffff;
            font-weight: 800;
            background: linear-gradient(135deg, #ffffff, var(--accent-2));
            -webkit-background-clip: text;
            -webkit-text-fill-color: transparent;
        }

        .layout-title .slideSubtitle {
            font-size: 1.25rem;
            color: var(--muted);
            margin: 0;
            max-width: 700px;
        }

        .slideDecor {
            position: absolute;
            width: 120px;
            height: 4px;
            background: linear-gradient(90deg, var(--accent), var(--accent-2));
            bottom: calc(50% + 80px);
            border-radius: 2px;
        }

        .slideHeader {
            width: 100%;
            display: flex;
            justify-content: space-between;
            align-items: center;
            border-bottom: 1px solid rgba(236, 72, 153, 0.1);
            padding-bottom: 12px;
            font-size: 0.8rem;
            color: var(--muted);
            text-transform: uppercase;
            letter-spacing: 0.05em;
        }

        .presMiniLogo {
            font-weight: 800;
            color: var(--accent-2);
        }

        .slideFooter {
            width: 100%;
            display: flex;
            justify-content: space-between;
            align-items: center;
            border-top: 1px solid rgba(236, 72, 153, 0.05);
            padding-top: 12px;
            font-size: 0.78rem;
            color: var(--muted);
        }

        .slideSplitBody {
            display: flex;
            gap: 40px;
            flex: 1;
            align-items: center;
            margin: 20px 0;
        }

        .slideLeftPane {
            flex: 0 0 260px;
            display: flex;
            flex-direction: column;
            gap: 16px;
        }

        .statCallout {
            background: var(--surface-2);
            border: 1px solid rgba(236, 72, 153, 0.1);
            padding: 16px;
            border-radius: var(--radius-sm);
            text-align: center;
        }

        .statCallout span {
            font-size: 0.7rem;
            color: var(--muted);
            text-transform: uppercase;
            letter-spacing: 0.05em;
            display: block;
            margin-bottom: 4px;
        }

        .statCallout h2 {
            margin: 0;
            font-size: 1.8rem;
            color: var(--accent-2);
        }

        .statCallout h4 {
            margin: 0;
            font-size: 1.1rem;
            color: #ffffff;
        }

        .slideRightPane {
            flex: 1;
        }

        .slideRightPane h2 {
            margin: 0 0 16px;
            font-size: 1.4rem;
            color: #ffffff;
        }

        .slideRightPane ul {
            margin: 0;
            padding-left: 20px;
        }

        .slideRightPane li {
            margin-bottom: 12px;
            font-size: 1rem;
            line-height: 1.5;
            color: var(--text);
        }

        .layout-grid h2 {
            margin: 20px 0 16px;
            font-size: 1.4rem;
            color: #ffffff;
        }

        .slideGridBody {
            display: grid;
            grid-template-columns: repeat(3, 1fr);
            gap: 16px;
            flex: 1;
            margin-bottom: 20px;
        }

        .riskComparisonCard {
            background: var(--surface-2);
            border: 1px solid rgba(236, 72, 153, 0.1);
            border-radius: var(--radius-sm);
            padding: 20px;
            display: flex;
            flex-direction: column;
            gap: 12px;
        }

        .cardIcon {
            font-size: 1.5rem;
        }

        .cardContent p {
            margin: 0;
            font-size: 0.88rem;
            line-height: 1.55;
            color: var(--text);
        }

        .layout-workflow {
            display: flex;
            flex-direction: column;
            gap: 20px;
            justify-content: space-between;
        }
        .slideWorkflowBody {
            display: flex;
            align-items: center;
            justify-content: space-between;
            gap: 12px;
            margin: 20px 0;
            width: 100%;
        }
        .workflowStepCard {
            flex: 1;
            background: var(--surface-2);
            border: 1px solid var(--border);
            border-radius: var(--radius-sm);
            padding: 20px;
            display: flex;
            flex-direction: column;
            gap: 12px;
            position: relative;
            box-shadow: var(--shadow);
            transition: all 0.3s ease;
        }
        .workflowStepNum {
            font-size: 1.5rem;
            font-weight: 800;
            color: var(--accent);
            line-height: 1;
        }
        .workflowStepContent h4 {
            margin: 0 0 6px;
            font-size: 0.95rem;
            color: #ffffff;
        }
        .workflowStepContent p {
            margin: 0;
            font-size: 0.8rem;
            line-height: 1.4;
            color: var(--muted);
        }
        .workflowConnector {
            font-size: 1.4rem;
            color: var(--accent-2);
        }

        .controls {
            position: absolute;
            bottom: 24px;
            left: 50%;
            transform: translateX(-50%);
            display: flex;
            gap: 12px;
            align-items: center;
            background: rgba(10, 11, 14, 0.8);
            backdrop-filter: blur(8px);
            padding: 8px 16px;
            border-radius: 20px;
            border: 1px solid rgba(236, 72, 153, 0.15);
            z-index: 100;
        }

        .controlBtn {
            background: transparent;
            border: none;
            color: var(--text);
            font-size: 1.5rem;
            cursor: pointer;
            padding: 0 8px;
            line-height: 1;
        }

        .controlBtn:hover {
            color: var(--accent-2);
        }

        .slideNum {
            font-size: 0.84rem;
            color: var(--muted);
            min-width: 80px;
            text-align: center;
        }
        
        .helpText {
            position: absolute;
            bottom: 24px;
            right: 24px;
            font-size: 0.72rem;
            color: var(--muted);
            z-index: 100;
            background: rgba(0,0,0,0.5);
            padding: 4px 8px;
            border-radius: 4px;
        }
    </style>
</head>
<body>
    <div class="presContainer">
        <div class="slideViewport">
            ${slidesHtml}
        </div>

        <div class="controls">
            <button class="controlBtn" onclick="changeSlide(-1)">&lsaquo;</button>
            <span class="slideNum" id="slideNum">Slide 1 of 3</span>
            <button class="controlBtn" onclick="changeSlide(1)">&rsaquo;</button>
        </div>
        
        <div class="helpText">Use Left/Right arrow keys to navigate</div>
    </div>

    <script>
        let currentSlide = 0;
        const slides = document.querySelectorAll('.slide');

        function updateSlides() {
            slides.forEach((slide, idx) => {
                slide.classList.remove('active');
                if (idx === currentSlide) {
                    slide.classList.add('active');
                }
            });
            document.getElementById('slideNum').textContent = "Slide " + (currentSlide + 1) + " of " + slides.length;
        }

        function changeSlide(direction) {
            currentSlide = (currentSlide + direction + slides.length) % slides.length;
            updateSlides();
        }

        document.addEventListener('keydown', (e) => {
            if (e.key === 'ArrowLeft') {
                changeSlide(-1);
            } else if (e.key === 'ArrowRight') {
                changeSlide(1);
            }
        });

        updateSlides();
    </script>
</body>
</html>`;

    const blob = new Blob([standaloneHtml], { type: 'text/html' });
    const url = URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url;
    a.download = 'RetentionIQ_Executive_Presentation.html';
    document.body.appendChild(a);
    a.click();
    document.body.removeChild(a);
    URL.revokeObjectURL(url);
}

async function triggerQuickQA(question) {
    const box = document.getElementById('qaResponseBox');
    if (!box) return;

    box.classList.remove('hidden');
    box.innerHTML = `<div class="qaLoading">Data Scientist processing metrics for presentation Q&A...</div>`;

    try {
        const apiKey = localStorage.getItem('show_ai_model_key') || '';
        const res = await fetch('/api/chat', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ message: question, model_key: apiKey, history: [] })
        });
        const payload = await res.json();

        if (res.ok && payload.response) {
            const htmlContent = marked.parse ? marked.parse(payload.response) : payload.response;
            box.innerHTML = `
                <div class="qaSlideCard">
                    <div class="qaSlideHeader">
                        <span class="qaTag">Presentation Q&A Response</span>
                        <span>Factual Data Science Verification</span>
                    </div>
                    <div class="qaSlideBody">
                        <h3>Query: "${question}"</h3>
                        <div class="qaSlideText">${htmlContent}</div>
                    </div>
                    <div class="qaSlideFooter">
                        <span>RetentionIQ Corporate Presentation Suite</span>
                    </div>
                </div>
            `;
        } else {
            box.innerHTML = `<div class="status error">Failed to process Q&A query: ${payload.error || 'Unknown error'}</div>`;
        }
    } catch (e) {
        box.innerHTML = `<div class="status error">Could not connect to database analyst: ${e}</div>`;
    }
}

setupCopilot();
