/**
 * EthicTech Web UI JavaScript
 * Document-centric design with inline badges and detail panel
 */

(function () {
    'use strict';

    // DOM Elements - Upload
    const uploadSection = document.getElementById('upload-section');
    const uploadZone = document.getElementById('upload-zone');
    const uploadLoading = document.getElementById('upload-loading');
    const fileInput = document.getElementById('file-input');

    // DOM Elements - Model Selection
    const providerSelect = document.getElementById('provider-select');
    const modelSelect = document.getElementById('model-select');
    const modelStatus = document.getElementById('model-status');

    // DOM Elements - Results
    const resultsSection = document.getElementById('results-section');
    const headerActions = document.getElementById('header-actions');
    const currentFileName = document.getElementById('current-file-name');
    const newAnalysisBtn = document.getElementById('new-analysis-btn');
    const exportPdfBtn = document.getElementById('export-pdf-btn');

    // Summary Cards
    const statusCard = document.getElementById('status-card');
    const summaryStatus = document.getElementById('summary-status');
    const errorCount = document.getElementById('error-count');
    const warningCount = document.getElementById('warning-count');
    const llmSummary = document.getElementById('llm-summary');

    // Document
    const documentContent = document.getElementById('document-content');

    // Detail Panel
    const detailPanel = document.getElementById('detail-panel');
    const detailBadge = document.getElementById('detail-badge');
    const detailTitle = document.getElementById('detail-title');
    const detailContent = document.getElementById('detail-content');
    const detailClose = document.getElementById('detail-close');

    // LLM Progress Card
    const llmProgressCard = document.getElementById('llm-progress-card');
    const llmStatusDot = document.getElementById('llm-status-dot');
    const llmStatusText = document.getElementById('llm-status-text');
    const llmProgressFill = document.getElementById('llm-progress-fill');
    const llmProgressText = document.getElementById('llm-progress-text');
    const llmThinking = document.getElementById('llm-thinking');
    const thinkingTheme = document.getElementById('thinking-theme');
    const thinkingContent = document.getElementById('thinking-content');
    const llmMinimize = document.getElementById('llm-minimize');
    const llmResultsSummary = document.getElementById('llm-results-summary');
    const llmProgressBody = document.getElementById('llm-progress-body');

    // Layer 3 DOM elements
    const layer3Btn             = document.getElementById('layer3-btn');
    const layer3Card            = document.getElementById('layer3-card');
    const layer3StatusText      = document.getElementById('layer3-status-text');
    const layer3ProgressFill    = document.getElementById('layer3-progress-fill');
    const layer3Thinking        = document.getElementById('layer3-thinking');
    const layer3ThinkingContent = document.getElementById('layer3-thinking-content');
    const layer3ResultsDiv      = document.getElementById('layer3-results');
    const layer3ResultsPanel    = document.getElementById('layer3-results-panel');
    const layer3ResultsBody     = document.getElementById('layer3-results-body');
    const layer3VerdictBadge    = document.getElementById('layer3-verdict-badge');
    const layer3RiskLabel       = document.getElementById('layer3-risk-label');

    // State
    let currentReport = null;
    let currentSessionId = null;
    let currentFileName_ = null;
    let llmEventSource = null;
    let llmResults = {};
    let lintIssuesMap = {};  // Store lint issues by dataRef for click handling
    let layer3EventSource = null;
    let layer3Results = null;

    const TOTAL_LLM_THEMES = 12;

    // LLM Theme to Document Section Mapping (11 themes)
    const THEME_TO_SECTIONS = {
        'three_Rs_alternatives':         ['alternatives'],
        'N_and_justification':           ['summaries', 'animals-totals'],
        'severity_monitoring_analgesia': [],   // → all experiment sections
        'euthanasia_and_endpoints':      [],   // → all experiment sections
        'harm_benefit_analysis':         ['summaries'],
        'sex_and_reuse':                 ['animals-totals'],
        'housing_and_husbandry':         [],   // → all experiment sections
        'scientific_coherence':          ['summaries', 'animals-totals'],
        'personnel_and_training':        ['pi', 'participants'],
        'hazardous_agents':              [],   // → all experiment sections
        'surgical_standards':            [],   // → all experiment sections
        'writing_quality':               ['summaries', 'alternatives'],
    };

    // Fetch available models from Ollama
    async function fetchModels() {
        modelSelect.disabled = true;
        modelSelect.innerHTML = '<option value="">Loading models...</option>';
        modelStatus.textContent = '';
        modelStatus.className = 'model-status';

        try {
            const response = await fetch('/api/ollama-models');
            const data = await response.json();

            if (data.success && data.models.length > 0) {
                const defaultModel = 'qwen3.5:35b';
                modelSelect.innerHTML = data.models.map(m =>
                    `<option value="${escapeHtml(m)}">${escapeHtml(m)}</option>`
                ).join('');
                if (data.models.includes(defaultModel)) {
                    modelSelect.value = defaultModel;
                }
                modelSelect.disabled = false;
            } else if (data.success && data.models.length === 0) {
                modelSelect.innerHTML = '<option value="">No models found</option>';
                modelStatus.textContent = 'No models installed in Ollama';
                modelStatus.className = 'model-status error';
            } else {
                modelSelect.innerHTML = '<option value="">(Ollama unavailable)</option>';
                modelStatus.textContent = data.error || 'Could not reach Ollama';
                modelStatus.className = 'model-status error';
            }
        } catch (err) {
            modelSelect.innerHTML = '<option value="">(Ollama unavailable)</option>';
            modelStatus.textContent = 'Could not connect to server';
            modelStatus.className = 'model-status error';
        }
    }

    // Initialize
    function init() {
        setupUploadZone();
        setupDetailPanel();
        setupNewAnalysisButton();
        setupExportButton();
        setupLLMMinimize();
        if (layer3Btn) layer3Btn.addEventListener('click', startLayer3Review);
        fetchModels();
        providerSelect.addEventListener('change', fetchModels);
    }

    // Upload Zone Setup
    function setupUploadZone() {
        uploadZone.addEventListener('click', () => fileInput.click());

        fileInput.addEventListener('change', (e) => {
            if (e.target.files.length > 0) {
                handleFile(e.target.files[0]);
            }
        });

        uploadZone.addEventListener('dragover', (e) => {
            e.preventDefault();
            uploadZone.classList.add('drag-over');
        });

        uploadZone.addEventListener('dragleave', () => {
            uploadZone.classList.remove('drag-over');
        });

        uploadZone.addEventListener('drop', (e) => {
            e.preventDefault();
            uploadZone.classList.remove('drag-over');
            if (e.dataTransfer.files.length > 0) {
                handleFile(e.dataTransfer.files[0]);
            }
        });
    }

    // Detail Panel Setup
    function setupDetailPanel() {
        detailClose.addEventListener('click', closeDetailPanel);

        // Close on escape
        document.addEventListener('keydown', (e) => {
            if (e.key === 'Escape') {
                closeDetailPanel();
            }
        });
    }

    // New Analysis Button
    function setupNewAnalysisButton() {
        newAnalysisBtn.addEventListener('click', resetToUpload);
    }

    // Export PDF Button
    function setupExportButton() {
        exportPdfBtn.addEventListener('click', exportPDF);

        const llmExportBtn = document.getElementById('llm-export-btn');
        if (llmExportBtn) {
            llmExportBtn.addEventListener('click', exportPDF);
        }
    }

    function exportPDF() {
        // Adjust textarea height before printing to ensure all text is visible
        const notesInput = document.getElementById('reviewer-notes-input');
        if (notesInput) {
            const originalHeight = notesInput.style.height;
            notesInput.style.height = 'auto';
            notesInput.style.height = (notesInput.scrollHeight) + 'px';

            window.print();

            setTimeout(() => {
                notesInput.style.height = originalHeight;
            }, 100);
        } else {
            window.print();
        }
    }

    // Build/update the print-only summary block at top of document for PDF export
    function updatePrintSummary() {
        let block = document.getElementById('print-summary-block');
        if (!block) {
            block = document.createElement('div');
            block.id = 'print-summary-block';
            block.className = 'print-only-details';
            documentContent.insertBefore(block, documentContent.firstChild);
        }

        let html = '<div class="print-llm-box ok" style="border-left-color:#1a56db; background-color:#dbeafe;">';
        html += `<strong>EthicTech IACUC Protocol Review</strong><br>`;
        html += `<strong>File:</strong> ${escapeHtml(currentFileName_ || '')}`;

        // Linter stats
        if (currentReport) {
            html += ` &nbsp;|&nbsp; <strong>Status:</strong> ${escapeHtml((currentReport.status || '').toUpperCase())}`;
            html += ` &nbsp;|&nbsp; <strong>Errors:</strong> ${currentReport.errors || 0}`;
            html += ` &nbsp;|&nbsp; <strong>Warnings:</strong> ${currentReport.warnings || 0}`;
        }

        // LLM theme scores
        const themeKeys = Object.keys(llmResults);
        if (themeKeys.length > 0) {
            html += `<br><br><strong>LLM Review (${themeKeys.length} themes):</strong><br>`;
            let totalScore = 0;
            themeKeys.forEach(theme => {
                const result = llmResults[theme];
                const meta = getThemeGradeMeta(result);
                const scoreLabel = formatGradeLabel(result.label, meta.score);
                totalScore += meta.score;
                html += `&bull; ${escapeHtml(formatThemeName(theme))}: ${meta.short} ${escapeHtml(scoreLabel)}<br>`;
            });
            const avg = (totalScore / themeKeys.length).toFixed(1);
            html += `<strong>Average: ${avg}/3</strong>`;
        }

        // Layer 3 results
        if (layer3Results && !layer3Results.skipped) {
            const verdict = layer3Results.overall_verdict || 'unknown';
            const risk = layer3Results.risk_profile || '';
            const summary = layer3Results.summary || '';
            html += `<br><br><strong>Human Eye Review (Layer 3):</strong> ${escapeHtml(verdict.toUpperCase())}`;
            if (risk) html += ` | Risk: ${escapeHtml(risk)}`;
            if (summary) html += `<br>${escapeHtml(summary)}`;
        }

        html += '</div>';
        block.innerHTML = html;
    }

    function setExportReady(ready) {
        exportPdfBtn.disabled = !ready;
        exportPdfBtn.title = ready
            ? 'Save full report as PDF'
            : 'Waiting for LLM verification to complete…';
    }

    // LLM Minimize Setup
    function setupLLMMinimize() {
        llmMinimize.addEventListener('click', () => {
            llmProgressCard.classList.toggle('minimized');
            if (llmProgressCard.classList.contains('minimized')) {
                llmResultsSummary.hidden = false;
            } else {
                llmResultsSummary.hidden = true;
            }
        });
    }

    // Reset to Upload State
    function resetToUpload() {
        if (llmEventSource) {
            llmEventSource.close();
            llmEventSource = null;
        }
        if (layer3EventSource) { layer3EventSource.close(); layer3EventSource = null; }
        layer3Results = null;
        if (layer3Btn) layer3Btn.hidden = true;
        if (layer3Card) layer3Card.hidden = true;
        if (layer3ResultsDiv) { layer3ResultsDiv.innerHTML = ''; layer3ResultsDiv.hidden = true; }
        if (layer3ResultsPanel) { layer3ResultsPanel.hidden = true; }
        if (layer3ResultsBody) { layer3ResultsBody.innerHTML = ''; }

        resultsSection.hidden = true;
        uploadSection.hidden = false;
        headerActions.hidden = true;
        uploadLoading.hidden = true;
        // Reset upload zone visibility
        const uploadCard = uploadZone.parentElement;
        if (uploadCard) uploadCard.hidden = false;
        fileInput.value = '';
        currentReport = null;
        currentSessionId = null;
        currentFileName_ = null;
        llmResults = {};
        lintIssuesMap = {};

        setExportReady(false);
        const llmExportCta = document.getElementById('llm-export-cta');
        if (llmExportCta) llmExportCta.hidden = true;

        closeDetailPanel();
        resetLLMPanel();
    }

    // Reset LLM Panel
    function resetLLMPanel() {
        setLLMStatus('waiting', 'Waiting for analysis...');
        llmProgressFill.style.width = '0%';
        llmProgressText.textContent = `0 / ${TOTAL_LLM_THEMES} themes`;
        llmThinking.classList.remove('active');
        thinkingContent.textContent = '';
        llmResultsSummary.innerHTML = '';
        llmResultsSummary.hidden = true;
        llmProgressCard.classList.remove('minimized', 'hidden');
        llmSummary.textContent = '--';
    }

    function normalizeThemeScore(result) {
        const score = Number(result?.score);
        return Number.isInteger(score) && score >= 0 && score <= 3 ? score : 1;
    }

    function formatGradeLabel(label, fallbackScore = 1) {
        const normalized = String(label || '').toLowerCase().replaceAll('-', '_').replaceAll(' ', '_');
        const fallbackMap = {
            0: 'Not Addressed',
            1: 'Inadequate',
            2: 'Partially Adequate',
            3: 'Adequate',
        };
        const labelMap = {
            not_addressed: 'Not Addressed',
            inadequate: 'Inadequate',
            partially_adequate: 'Partially Adequate',
            adequate: 'Adequate',
        };
        return labelMap[normalized] || fallbackMap[fallbackScore] || 'Inadequate';
    }

    function getThemeGradeMeta(result) {
        const score = normalizeThemeScore(result);
        if (score === 3) {
            return { score, color: 'var(--status-pass)', short: '3/3', label: 'Adequate' };
        }
        if (score === 2) {
            return { score, color: 'var(--status-warning)', short: '2/3', label: 'Partially Adequate' };
        }
        if (score === 1) {
            return { score, color: 'var(--status-error)', short: '1/3', label: 'Inadequate' };
        }
        return { score, color: 'var(--status-error)', short: '0/3', label: 'Not Addressed' };
    }

    // Set LLM Status
    function setLLMStatus(state, text) {
        llmStatusDot.className = 'status-dot';
        if (state === 'running') llmStatusDot.classList.add('running');
        else if (state === 'done') llmStatusDot.classList.add('done');
        else if (state === 'error') llmStatusDot.classList.add('error');

        llmStatusText.textContent = text;
    }

    // Handle File Upload
    async function handleFile(file) {
        if (!file.name.match(/\.html?$/i)) {
            alert('Please upload an HTML file.');
            return;
        }

        currentFileName_ = file.name;
        uploadZone.parentElement.hidden = true;
        uploadLoading.hidden = false;

        try {
            const formData = new FormData();
            formData.append('file', file);
            formData.append('provider', providerSelect.value);
            formData.append('model', modelSelect.value);

            const response = await fetch('/api/analyze-with-session', {
                method: 'POST',
                body: formData
            });

            const data = await response.json();

            if (data.success) {
                currentReport = data.lint_report;
                currentSessionId = data.session_id;
                showResults(data.rendered_html, data.lint_report);
                startLLMVerification(data.session_id);
            } else {
                throw new Error(data.error || 'Analysis failed');
            }
        } catch (error) {
            console.error('Analysis error:', error);
            alert('Error: ' + error.message);
            uploadZone.parentElement.hidden = false;
            uploadLoading.hidden = true;
        }
    }

    // Show Results
    function showResults(renderedHtml, lintReport) {
        uploadSection.hidden = true;
        resultsSection.hidden = false;
        headerActions.hidden = false;
        currentFileName.textContent = currentFileName_;
        setExportReady(false);

        // Update summary cards
        const status = lintReport.status;
        summaryStatus.textContent = status.toUpperCase();
        statusCard.className = 'summary-card status-card ' + status;

        errorCount.textContent = lintReport.errors;
        warningCount.textContent = lintReport.warnings;

        // Render document with inline badges
        renderDocument(renderedHtml, lintReport);

        // Add print summary (linter stats only at this point)
        updatePrintSummary();
    }

    // Render Document with Inline Badges
    function renderDocument(html, lintReport) {
        documentContent.innerHTML = '';

        const parser = new DOMParser();
        const doc = parser.parseFromString(html, 'text/html');
        const body = doc.body;

        // Build and store issues map globally for click handling
        lintIssuesMap = buildRefIssueMap(lintReport.checklist);
        markSectionsWithIssues(body, lintIssuesMap);

        documentContent.appendChild(body.cloneNode(true));

        // Re-attach event listeners for badges
        attachBadgeListeners();
    }

    // Build Reference to Issue Map
    function buildRefIssueMap(checklist) {
        const refMap = {};

        checklist.forEach(item => {
            if (item.status !== 'fail') return;

            const ref = item.reference || '';
            const dataRef = mapReferenceToDataRef(ref);

            if (!dataRef) return;

            if (!refMap[dataRef]) {
                refMap[dataRef] = { errors: [], warnings: [] };
            }

            if (item.severity === 'error') {
                refMap[dataRef].errors.push(item);
            } else {
                refMap[dataRef].warnings.push(item);
            }
        });

        return refMap;
    }

    // Map lint reference to data-ref attribute
    function mapReferenceToDataRef(ref) {
        if (!ref) return null;

        const mappings = {
            'header': 'header',
            'research': 'research',
            'title:track': 'research',
            'title:pilot-label': 'research',
            'term:track': 'research',
            'continuation': 'research',
            'third-party': 'research',
            'pi': 'pi',
            'pi:training': 'pi',
            'participant:training': 'participants',
            'participant:certified-without-training': 'participants',
            'animals:totals-vs-exps': 'animals-totals',
            'scope:pilot-size': 'summaries',
            'sex:rationale': 'summaries',
            'N:justification-detail': 'summaries',
            'N:power-analysis': 'summaries',
            'summaries:scientific-length': 'summaries',
            'summaries:lay-length': 'summaries',
            'alts:missing': 'alternatives',
            'alts:engines': 'alternatives',
            'alts:queries': 'alternatives',
            'alts:conclusion': 'alternatives',
            'colony:no-invasive': 'research',
            'colony:breeding-plan': 'research',
        };

        if (mappings[ref]) {
            return mappings[ref];
        }

        // Handle new experiment-indexed format: "type:detail:exp-N"
        const expIndexMatch = ref.match(/:exp-(\d+)$/);
        if (expIndexMatch) {
            const expNum = expIndexMatch[1];
            const baseRef = ref.replace(/:exp-\d+$/, '');

            // Map based on the type prefix
            if (baseRef.startsWith('euthanasia:')) {
                return `euthanasia-${expNum}`;
            }
            if (baseRef.startsWith('severity:')) {
                return `monitoring-${expNum}`;
            }
            if (baseRef.startsWith('endpoints:')) {
                return `experiment-${expNum}`;
            }
            if (baseRef.startsWith('special:')) {
                return `experiment-${expNum}`;
            }
            return `experiment-${expNum}`;
        }

        // Legacy format without :exp-N suffix (fallback)
        const expMatch = ref.match(/^(euthanasia|severity|endpoints|special):(.+)$/);
        if (expMatch) {
            // Fall back to experiment-1 for legacy refs without experiment index
            if (ref.startsWith('euthanasia')) {
                return 'euthanasia-1';
            }
            if (ref.startsWith('severity')) {
                return 'monitoring-1';
            }
            return 'experiment-1';
        }

        if (ref.startsWith('required:')) {
            const path = ref.replace('required:', '');
            if (path.includes('experiment')) return 'experiment-1';
            return path;
        }

        return null;
    }

    // Mark Sections with Issues
    function markSectionsWithIssues(container, refIssues) {
        Object.keys(refIssues).forEach(dataRef => {
            const issues = refIssues[dataRef];
            const element = container.querySelector(`[data-ref="${dataRef}"]`);

            if (!element) return;

            const hasErrors = issues.errors.length > 0;
            const hasWarnings = issues.warnings.length > 0;

            if (hasErrors) {
                element.classList.add('has-error');
            }
            if (hasWarnings) {
                element.classList.add('has-warning');
            }

            // Create inline badge (positioned at bottom-left to avoid overlap with LLM badges)
            const totalIssues = issues.errors.length + issues.warnings.length;
            const badge = document.createElement('span');
            badge.className = 'error-marker' + (hasErrors ? '' : ' warning-only');
            badge.textContent = totalIssues + ' ' + (hasErrors ? 'Error' : 'Warning') + (totalIssues > 1 ? 's' : '');
            badge.dataset.ref = dataRef;
            badge.dataset.type = 'lint';

            element.style.position = 'relative';
            element.appendChild(badge);

            // Store issue count as data attribute for reference
            element.dataset.issueCount = totalIssues;
            element.dataset.hasLintIssues = 'true';

            // ADD PRINT-ONLY DETAILS FOR LINTER ISSUES
            let printDetailsHtml = '';
            issues.errors.forEach(issue => {
                printDetailsHtml += `<div class="print-issue-box error"><strong>Linter Error (${escapeHtml(issue.reference || 'general')}):</strong> ${escapeHtml(issue.message)}`;
                if (issue.suggested_fix) {
                    printDetailsHtml += ` <em>(Fix: ${escapeHtml(issue.suggested_fix)})</em>`;
                }
                printDetailsHtml += `</div>`;
            });
            issues.warnings.forEach(issue => {
                printDetailsHtml += `<div class="print-issue-box warning"><strong>Linter Warning (${escapeHtml(issue.reference || 'general')}):</strong> ${escapeHtml(issue.message)}`;
                if (issue.suggested_fix) {
                    printDetailsHtml += ` <em>(Fix: ${escapeHtml(issue.suggested_fix)})</em>`;
                }
                printDetailsHtml += `</div>`;
            });

            if (printDetailsHtml) {
                const printDiv = document.createElement('div');
                printDiv.className = 'print-only-details';
                printDiv.innerHTML = printDetailsHtml;
                element.appendChild(printDiv);
            }
        });
    }

    // Attach Badge Listeners
    function attachBadgeListeners() {
        // Lint issue badges - use global lintIssuesMap
        documentContent.querySelectorAll('.error-marker').forEach(badge => {
            badge.addEventListener('click', (e) => {
                e.stopPropagation();
                const dataRef = badge.dataset.ref;
                if (lintIssuesMap[dataRef]) {
                    showLintIssueDetails(lintIssuesMap[dataRef], dataRef);
                }
            });
        });

        // LLM verdict badges
        documentContent.querySelectorAll('.llm-verdict-badge').forEach(badge => {
            badge.addEventListener('click', (e) => {
                e.stopPropagation();
                const theme = badge.dataset.theme;
                if (llmResults[theme]) {
                    showLLMDetails(theme, llmResults[theme]);
                }
            });
        });

        // Section click - check both lint issues and LLM results
        documentContent.querySelectorAll('[data-ref]').forEach(section => {
            section.addEventListener('click', (e) => {
                // Don't trigger if clicking on a badge
                if (e.target.classList.contains('error-marker') ||
                    e.target.classList.contains('llm-verdict-badge')) {
                    return;
                }

                const ref = section.dataset.ref;
                // Prioritize lint issues if present
                if (lintIssuesMap[ref]) {
                    showLintIssueDetails(lintIssuesMap[ref], ref);
                } else if (section.dataset.llmTheme && llmResults[section.dataset.llmTheme]) {
                    showLLMDetails(section.dataset.llmTheme, llmResults[section.dataset.llmTheme]);
                }
            });
        });
    }

    // Show Lint Issue Details in Panel
    function showLintIssueDetails(issues, ref) {
        const allIssues = [...issues.errors, ...issues.warnings];
        const hasErrors = issues.errors.length > 0;

        detailBadge.textContent = hasErrors ? 'Error' : 'Warning';
        detailBadge.className = 'detail-badge ' + (hasErrors ? 'error' : 'warning');
        detailTitle.textContent = `Issues in ${formatRefName(ref)}`;

        let html = '';
        allIssues.forEach((issue, idx) => {
            const isError = issue.severity === 'error';
            html += `
                <div class="detail-issue" style="margin-bottom: 16px; padding-bottom: 16px; ${idx < allIssues.length - 1 ? 'border-bottom: 1px solid var(--border-light);' : ''}">
                    <div style="display: flex; align-items: center; gap: 8px; margin-bottom: 8px;">
                        <span style="padding: 2px 8px; font-size: 0.6875rem; font-weight: 600; border-radius: 4px; background: ${isError ? 'var(--status-fail)' : 'var(--status-warning)'}; color: white;">
                            ${isError ? 'ERROR' : 'WARNING'}
                        </span>
                        <span style="font-size: 0.75rem; color: var(--text-muted); font-family: var(--font-mono);">${escapeHtml(issue.reference || 'general')}</span>
                    </div>
                    <div class="detail-message">${escapeHtml(issue.message)}</div>
                    ${issue.suggested_fix ? `
                        <div class="detail-fix">
                            <div class="detail-fix-label">Suggested Fix</div>
                            <div class="detail-fix-text">${escapeHtml(issue.suggested_fix)}</div>
                        </div>
                    ` : ''}
                </div>
            `;
        });

        detailContent.innerHTML = html;
        openDetailPanel();

        // Highlight section
        highlightSection(ref);
    }

    // Show LLM Details in Panel
    function showLLMDetails(theme, result) {
        detailBadge.textContent = 'LLM Review';
        detailBadge.className = 'detail-badge llm';
        detailTitle.textContent = formatThemeName(theme);

        const meta = getThemeGradeMeta(result);
        const scoreLabel = formatGradeLabel(result.label, meta.score);
        const subQuestions = Array.isArray(result.sub_questions) ? result.sub_questions : [];
        const subQuestionsHtml = subQuestions.length ? `
            <div style="margin-top: 16px;">
                <div class="detail-fix-label">Sub-Questions</div>
                <div style="display: grid; gap: 10px; margin-top: 8px;">
                    ${subQuestions.map((item) => {
                        const itemMeta = getThemeGradeMeta(item);
                        const itemLabel = formatGradeLabel(item.label, itemMeta.score);
                        return `
                            <div style="border: 1px solid var(--border-subtle); border-radius: 10px; padding: 10px 12px;">
                                <div style="display: flex; justify-content: space-between; gap: 12px; margin-bottom: 6px;">
                                    <strong style="font-size: 0.875rem;">${escapeHtml(item.question || 'Sub-question')}</strong>
                                    <span style="color: ${itemMeta.color}; font-weight: 600; white-space: nowrap;">${itemMeta.short} ${escapeHtml(itemLabel)}</span>
                                </div>
                                <div class="detail-rationale">${escapeHtml(item.rationale || 'No rationale provided.')}</div>
                            </div>
                        `;
                    }).join('')}
                </div>
            </div>
        ` : '';

        let html = `
            <div style="display: flex; align-items: center; gap: 8px; margin-bottom: 16px;">
                <span style="padding: 2px 10px; font-size: 0.6875rem; font-weight: 600; border-radius: 4px; background: ${meta.color}; color: white;">
                    ${meta.short} ${escapeHtml(scoreLabel)}
                </span>
            </div>
            <div class="detail-rationale">${escapeHtml(result.rationale || 'No rationale provided.')}</div>
            <div class="detail-confidence">Overall score: ${meta.short}</div>
            ${subQuestionsHtml}
            ${groundingHtml(result.grounding)}
            <p class="advisory-banner">${escapeHtml(advisoryNotice())}</p>
        `;

        detailContent.innerHTML = html;
        openDetailPanel();
    }

    // Format Reference Name
    function formatRefName(ref) {
        const names = {
            'header': 'Header',
            'research': 'Research',
            'pi': 'Principal Investigator',
            'participants': 'Participants',
            'animals-totals': 'Animals Totals',
            'summaries': 'Summaries',
            'alternatives': 'Alternatives Search'
        };

        if (names[ref]) return names[ref];

        // Handle experiment refs
        const expMatch = ref.match(/^(experiment|euthanasia|monitoring)-(\d+)$/);
        if (expMatch) {
            const type = expMatch[1].charAt(0).toUpperCase() + expMatch[1].slice(1);
            return `${type} ${expMatch[2]}`;
        }

        return ref;
    }

    // Format Theme Name (11 themes)
    function formatThemeName(theme) {
        const names = {
            'three_Rs_alternatives':         '3Rs & Alternatives',
            'N_and_justification':           'N & Justification',
            'severity_monitoring_analgesia': 'Severity & Monitoring',
            'euthanasia_and_endpoints':      'Euthanasia & Endpoints',
            'harm_benefit_analysis':         'Harm-Benefit',
            'sex_and_reuse':                 'Sex & Reuse',
            'housing_and_husbandry':         'Housing',
            'scientific_coherence':          'Coherence',
            'personnel_and_training':        'Personnel',
            'hazardous_agents':              'Hazardous Agents',
            'surgical_standards':            'Surgical Standards',
        };
        return names[theme] || theme;
    }

    // Open Detail Panel
    function openDetailPanel() {
        detailPanel.hidden = false;
        // Trigger animation
        requestAnimationFrame(() => {
            detailPanel.classList.add('open');
        });
    }

    // Close Detail Panel
    function closeDetailPanel() {
        detailPanel.classList.remove('open');
        setTimeout(() => {
            detailPanel.hidden = true;
        }, 300);
    }

    // Highlight Section
    function highlightSection(ref) {
        const element = documentContent.querySelector(`[data-ref="${ref}"]`);
        if (!element) return;

        element.scrollIntoView({ behavior: 'smooth', block: 'center' });
        element.classList.add('highlight');
        setTimeout(() => element.classList.remove('highlight'), 1600);
    }

    // Start LLM Verification via SSE
    function startLLMVerification(sessionId) {
        resetLLMPanel();
        setLLMStatus('running', 'Starting LLM review...');

        llmEventSource = new EventSource(`/api/llm-verify-stream/${sessionId}`);

        llmEventSource.onmessage = (event) => {
            try {
                const data = JSON.parse(event.data);
                handleLLMEvent(data);
            } catch (e) {
                console.error('Failed to parse SSE data:', e);
            }
        };

        llmEventSource.onerror = (error) => {
            console.error('SSE error:', error);
            setLLMStatus('error', 'Connection lost');
            setExportReady(true);  // Don't block export on connection loss
            llmEventSource.close();
            llmEventSource = null;
        };
    }

    // Handle LLM Events
    function handleLLMEvent(data) {
        switch (data.type) {
            case 'theme_start':
                handleThemeStart(data);
                break;
            case 'token':
                handleToken(data);
                break;
            case 'theme_done':
                handleThemeDone(data);
                break;
            case 'complete':
                handleComplete(data);
                break;
            case 'warning':
                showStreamWarning(llmProgressCard, data);
                break;
            case 'error':
                handleLLMError(data);
                break;
        }
    }

    // escapeHtml() is a text-node escaper (no quotes); attribute values need this one.
    function escapeAttr(value) {
        return String(value).replace(/&/g, '&amp;').replace(/"/g, '&quot;').replace(/'/g, '&#39;').replace(/</g, '&lt;').replace(/>/g, '&gt;');
    }

    // Grounding sources attached to a theme result (Phase 2). Everything escaped; only
    // http(s) URLs render as links (etiqtech:// anchors are local corpus ids, shown as text).
    function groundingHtml(refs) {
        if (!Array.isArray(refs) || refs.length === 0) return '';
        const items = refs.map((g) => {
            const url = String(g.url || '');
            const label = `[${escapeHtml(g.ref || '')}] ${escapeHtml(g.title || '')}`;
            const src = /^https?:\/\//i.test(url)
                ? `<a href="${escapeAttr(url)}" target="_blank" rel="noopener noreferrer">${escapeHtml(url)}</a>`
                : `<span class="grounding-anchor">${escapeHtml(url)}</span>`;
            const lic = g.license ? ` <span class="grounding-license">(${escapeHtml(g.license)})</span>` : '';
            return `<li>${label}<br>${src}${lic}</li>`;
        }).join('');
        return `<div class="grounding-sources"><div class="detail-fix-label">Sources used for grounding</div><ul>${items}</ul></div>`;
    }

    function groundingPrintText(refs) {
        if (!Array.isArray(refs) || refs.length === 0) return '';
        return '<br><em>Sources:</em> ' + refs.map((g) => `[${escapeHtml(g.ref || '')}] ${escapeHtml(g.title || '')} — ${escapeHtml(g.url || '')}`).join('; ');
    }

    // The advisory statement is rendered server-side into the template; read it from there
    // so the UI has exactly one wording.
    function advisoryNotice() {
        const el = document.querySelector('[data-advisory]');
        if (!el) console.error('advisory notice missing from template');  // no second wording lives in JS
        return el ? el.textContent.trim() : '';
    }

    // Context-budget (and future) warnings from the server: visible, not dismissable, escaped.
    function showStreamWarning(card, data) {
        if (!card) return;
        const note = document.createElement('div');
        note.className = 'stream-warning';
        note.setAttribute('role', 'status');
        note.textContent = data.message || 'Warning from server';
        card.insertBefore(note, card.firstChild);
    }

    // Handle Theme Start
    function handleThemeStart(data) {
        setLLMStatus('running', `Analyzing: ${data.label}`);

        // Update progress
        const progress = (data.progress / data.total) * 100;
        llmProgressFill.style.width = `${progress}%`;
        llmProgressText.textContent = `${data.progress} / ${data.total} themes`;

        // Show thinking area
        llmThinking.classList.add('active');
        thinkingTheme.textContent = data.label;
        thinkingContent.textContent = '';
    }

    // Handle Token (streaming)
    function handleToken(data) {
        thinkingContent.textContent += data.token;
        thinkingContent.scrollTop = thinkingContent.scrollHeight;
    }

    // Handle Theme Done
    function handleThemeDone(data) {
        const result = data.result;
        const theme = data.theme;
        llmResults[theme] = result;

        // Add verdict badge to relevant document sections
        addLLMVerdictToDocument(theme, result);

        // Add chip to results summary
        addResultChip(theme, result);

        // Clear thinking for next theme
        thinkingContent.textContent = '';
    }

    // Add LLM Verdict Badge to Document
    function addLLMVerdictToDocument(theme, result) {
        // Get sections for this theme
        let sections = THEME_TO_SECTIONS[theme] || [];

        // For experiment-related themes, find all experiment sections
        if (sections.length === 0) {
            // Route each experiment-related theme to its own specific section type
            // so badges don't duplicate across overlapping sections
            let selector;
            if (theme === 'severity_monitoring_analgesia') {
                selector = '[data-ref^="monitoring-"]';
            } else if (theme === 'euthanasia_and_endpoints') {
                selector = '[data-ref^="euthanasia-"]';
            } else if (theme === 'surgical_standards') {
                selector = '[data-ref^="monitoring-"]';
            } else {
                // housing_and_husbandry, hazardous_agents, and experiment-level themes
                selector = '[data-ref^="experiment-"]';
            }
            documentContent.querySelectorAll(selector).forEach(section => {
                addVerdictBadgeToSection(section, theme, result);
            });
            return;
        }

        // Add to specific sections — only the first section gets the print block
        // to avoid duplicate LLM rationale text when a theme spans multiple sections
        sections.forEach((sectionRef, idx) => {
            const section = documentContent.querySelector(`[data-ref="${sectionRef}"]`);
            if (section) {
                addVerdictBadgeToSection(section, theme, result, idx === 0);
            }
        });
    }

    // Add Verdict Badge to Section
    // addPrintBlock: false skips the print-only-details div (used for 2nd+ sections
    // of multi-section themes to avoid duplicate LLM rationale in PDF output)
    function addVerdictBadgeToSection(section, theme, result, addPrintBlock = true) {
        // Prevent duplicate badges for the same theme on the same section
        if (section.querySelector(`.llm-verdict-badge[data-theme="${theme}"]`)) return;

        const meta = getThemeGradeMeta(result);
        const scoreLabel = formatGradeLabel(result.label, meta.score);

        // Add LLM styling only if no lint issues
        if (!section.classList.contains('has-error') && !section.classList.contains('has-warning')) {
            if (meta.score >= 3) {
                section.classList.add('has-llm-ok');
            } else {
                section.classList.add('has-llm-warning');
            }
        }

        // Create badge (positioned at top-left, stacked vertically per section)
        const existingBadges = section.querySelectorAll('.llm-verdict-badge').length;
        const badge = document.createElement('button');
        badge.type = 'button';
        badge.className = `llm-verdict-badge ${meta.score >= 3 ? 'ok' : 'needs-fixes'}`;
        badge.dataset.theme = theme;
        badge.textContent = `${meta.short} ${formatThemeName(theme).split(' ')[0]}`;
        badge.style.background = meta.color;
        badge.style.top = `${8 + existingBadges * 30}px`;

        section.style.position = 'relative';
        section.appendChild(badge);
        section.dataset.llmTheme = theme;

        // Ensure enough top padding so badges don't cover content
        const neededPadding = 8 + (existingBadges + 1) * 30 + 4;
        const currentPadding = parseInt(getComputedStyle(section).paddingTop) || 12;
        if (neededPadding > currentPadding) {
            section.style.paddingTop = `${neededPadding}px`;
        }

        // ADD PRINT-ONLY DETAILS FOR LLM RESULTS (skip for 2nd+ sections of multi-section themes)
        if (!addPrintBlock) return;
        const printDiv = document.createElement('div');
        printDiv.className = 'print-only-details';
        const verdictClass = meta.score >= 3 ? 'ok' : 'needs-fixes';

        let printDetailsHtml = `
            <div class="print-llm-box ${verdictClass}">
                <strong>LLM Review - ${escapeHtml(formatThemeName(theme))} [${escapeHtml(meta.short)} ${escapeHtml(scoreLabel)}]:</strong> 
                ${escapeHtml(result.rationale || 'No rationale provided.')}
                ${groundingPrintText(result.grounding)}
        `;
        printDetailsHtml += `</div>`;
        printDiv.innerHTML = printDetailsHtml;
        section.appendChild(printDiv);

        // Attach click listener
        badge.addEventListener('click', (e) => {
            e.stopPropagation();
            showLLMDetails(theme, result);
        });
    }

    // Add Result Chip to Summary
    function addResultChip(theme, result) {
        const meta = getThemeGradeMeta(result);
        const chip = document.createElement('span');
        chip.className = `result-chip ${meta.score >= 3 ? 'ok' : 'needs-fixes'}`;
        chip.textContent = `${meta.short} ${formatThemeName(theme).split(' ')[0]}`;
        chip.style.background = meta.color;
        llmResultsSummary.appendChild(chip);
    }

    // Handle Complete
    function handleComplete(data) {
        llmThinking.classList.remove('active');
        llmProgressFill.style.width = '100%';

        // Count scores
        const themes = data.result.themes || {};
        const totalCount = Object.keys(themes).length;
        const acceptableCount = Object.values(themes).filter(t => normalizeThemeScore(t) >= 2).length;
        const totalScore = Object.values(themes).reduce((sum, t) => sum + normalizeThemeScore(t), 0);
        const averageScore = totalCount ? (totalScore / totalCount).toFixed(1) : '0.0';

        // Update summary card
        llmSummary.textContent = `${averageScore}/3 avg`;

        if (acceptableCount === totalCount) {
            setLLMStatus('done', `All ${totalCount} themes scored 2+`);
        } else {
            setLLMStatus('done', `${acceptableCount}/${totalCount} themes scored 2+`);
        }

        // Hide LLM progress card after delay (export stays disabled until Layer 3 finishes)
        const llmExportCta = document.getElementById('llm-export-cta');
        setTimeout(() => {
            llmProgressCard.classList.add('hidden');
            if (llmExportCta) llmExportCta.hidden = true;
        }, 3000);

        if (llmEventSource) {
            llmEventSource.close();
            llmEventSource = null;
        }

        // Update print summary with LLM results
        updatePrintSummary();

        // Auto-run Layer 3 immediately after Layer 2
        startLayer3Review();
    }

    // Handle LLM Error
    function handleLLMError(data) {
        setLLMStatus('error', `Error: ${data.message}`);
        llmThinking.classList.remove('active');
        llmSummary.textContent = 'Error';
        setExportReady(true);  // Don't block export on LLM failure

        if (llmEventSource) {
            llmEventSource.close();
            llmEventSource = null;
        }
    }

    // -----------------------------------------------------------------------
    // Layer 3 "Human Eye" holistic review
    // -----------------------------------------------------------------------

    function showLayer3Button() {
        if (layer3Btn) layer3Btn.hidden = false;
    }

    function startLayer3Review() {
        if (!currentSessionId) return;
        layer3Btn.hidden = true;
        layer3Card.hidden = false;
        layer3StatusText.textContent = 'Starting Human Eye review...';
        layer3ProgressFill.style.width = '10%';

        layer3EventSource = new EventSource(
            `/api/human-eye-stream/${currentSessionId}?force=1`
        );
        layer3EventSource.onmessage = (event) => {
            try { handleLayer3Event(JSON.parse(event.data)); }
            catch (e) { console.error('Layer3 SSE parse error:', e); }
        };
        layer3EventSource.onerror = () => {
            layer3StatusText.textContent = 'Connection lost';
            setExportReady(true);
            if (layer3EventSource) { layer3EventSource.close(); layer3EventSource = null; }
        };
    }

    function handleLayer3Event(data) {
        switch (data.type) {
            case 'layer3_trigger':
                layer3StatusText.textContent = `Triggered: ${escapeHtml(data.reason || '')}`;
                layer3ProgressFill.style.width = '20%';
                break;
            case 'layer3_skip':
                layer3StatusText.textContent = 'Skipped — no critical issues detected';
                layer3ProgressFill.style.width = '100%';
                setExportReady(true);
                if (layer3EventSource) { layer3EventSource.close(); layer3EventSource = null; }
                break;
            case 'pass_start':
                layer3StatusText.textContent = `Pass ${data.pass}: ${escapeHtml(data.label || '')}`;
                layer3ProgressFill.style.width = data.pass === 1 ? '40%' : '70%';
                layer3Thinking.classList.add('active');
                layer3ThinkingContent.textContent = '';
                break;
            case 'token':
                layer3ThinkingContent.textContent += data.token;
                layer3ThinkingContent.scrollTop = layer3ThinkingContent.scrollHeight;
                break;
            case 'pass_done':
                layer3ProgressFill.style.width = data.pass === 1 ? '65%' : '95%';
                break;
            case 'warning':
                showStreamWarning(document.getElementById('layer3-card'), data);
                break;
            case 'complete':
                layer3ProgressFill.style.width = '100%';
                layer3Thinking.classList.remove('active');
                layer3Results = data.result;
                showLayer3Results(data.result);
                setExportReady(true);
                if (layer3EventSource) { layer3EventSource.close(); layer3EventSource = null; }
                break;
            case 'error':
                layer3StatusText.textContent = `Error: ${escapeHtml(data.message || '')}`;
                layer3Thinking.classList.remove('active');
                setExportReady(true);
                if (layer3EventSource) { layer3EventSource.close(); layer3EventSource = null; }
                break;
        }
    }

    function showLayer3Results(result) {
        if (!result || result.skipped) {
            layer3StatusText.textContent = 'Human Eye review skipped';
            return;
        }
        const verdict  = result.overall_verdict || 'unknown';
        const risk     = result.risk_profile || '';
        const summary  = result.summary || '';
        const issues   = result.cross_reference_issues || [];
        const sections = result.sections || [];

        // Update floating card status text
        const isOk = verdict === 'approve' || verdict === 'ok';
        layer3StatusText.textContent = isOk
            ? 'Human Eye: No critical issues'
            : 'Human Eye: Issues found';

        // Hide the floating card after a short delay (results go to full panel)
        setTimeout(() => { if (layer3Card) layer3Card.hidden = true; }, 3000);

        // --- Populate the full-width results panel ---
        if (layer3ResultsPanel) layer3ResultsPanel.hidden = false;

        // Verdict badge
        if (layer3VerdictBadge) {
            layer3VerdictBadge.textContent = verdict.toUpperCase().replace(/_/g, ' ');
            layer3VerdictBadge.className = 'layer3-verdict-badge ' + (isOk ? 'ok' : 'issues');
        }
        // Risk label
        if (layer3RiskLabel) {
            layer3RiskLabel.textContent = risk ? `Risk: ${risk}` : '';
        }

        // Build body HTML
        let html = '';

        // Summary
        if (summary) {
            html += `<div class="layer3-summary">${escapeHtml(summary)}</div>`;
        }

        // Section findings
        if (sections.length > 0) {
            html += `<div class="layer3-sections-title">Section Findings</div>`;
            html += `<div class="layer3-sections-grid">`;
            sections.forEach(sec => {
                const sev = (sec.severity || '').toLowerCase();
                const status = (sec.status || '').toLowerCase();
                const sevClass = sev === 'critical' ? 'critical'
                    : sev === 'major' ? 'major'
                    : status === 'compliant' ? 'compliant' : 'minor';
                html += `
                    <div class="layer3-finding ${sevClass}">
                        <div class="layer3-finding-header">
                            <span class="layer3-finding-section">${escapeHtml(sec.section || '')}</span>
                            <span class="layer3-finding-severity ${sevClass}">${escapeHtml(sec.severity || sec.status || '')}</span>
                        </div>
                        <div class="layer3-finding-text">${escapeHtml(sec.finding || '')}</div>
                        ${sec.explanation ? `<div class="layer3-finding-detail">${escapeHtml(sec.explanation)}</div>` : ''}
                        ${sec.action_required ? `<div class="layer3-finding-action"><strong>Action:</strong> ${escapeHtml(sec.action_required)}</div>` : ''}
                        ${sec.regulatory_basis ? `<div class="layer3-finding-reg">${escapeHtml(sec.regulatory_basis)}</div>` : ''}
                    </div>`;
            });
            html += `</div>`;
        }

        // Cross-reference issues
        if (issues.length > 0) {
            html += `<div class="layer3-sections-title">Cross-Reference Issues</div>`;
            html += `<ul class="layer3-issues-list">`;
            issues.forEach(iss => {
                const issText = typeof iss === 'string' ? iss
                    : (iss.issue || iss.description || JSON.stringify(iss));
                html += `<li>${escapeHtml(issText)}</li>`;
            });
            html += `</ul>`;
        }

        if (layer3ResultsBody) layer3ResultsBody.innerHTML = html;

        // --- Also keep a mini summary in the floating card for reference ---
        layer3ResultsDiv.innerHTML = `<div style="padding:8px 12px;font-size:.8rem;color:var(--text-secondary);">Full results shown below document.</div>`;
        layer3ResultsDiv.hidden = false;

        // --- Generate print-only output for Layer 3 ---
        const existingPrint = document.getElementById('layer3-print-block');
        if (existingPrint) existingPrint.remove();

        const printBlock = document.createElement('div');
        printBlock.id = 'layer3-print-block';
        printBlock.className = 'print-only-details';

        let printHtml = `<div class="print-llm-box ${isOk ? 'ok' : 'needs-fixes'}">`;
        printHtml += `<strong>Human Eye Review (Layer 3) — Verdict: ${escapeHtml(verdict.toUpperCase())}`;
        if (risk) printHtml += ` | Risk: ${escapeHtml(risk)}`;
        printHtml += `</strong><br>`;
        if (summary) printHtml += `${escapeHtml(summary)}<br>`;

        if (sections.length > 0) {
            printHtml += `<br><strong>Section Findings:</strong><br>`;
            sections.forEach(sec => {
                printHtml += `&bull; <strong>${escapeHtml(sec.section || '')}</strong>`;
                if (sec.severity) printHtml += ` [${escapeHtml(sec.severity)}]`;
                if (sec.finding) printHtml += `: ${escapeHtml(sec.finding)}`;
                if (sec.action_required) printHtml += ` — Action: ${escapeHtml(sec.action_required)}`;
                printHtml += `<br>`;
            });
        }

        if (issues.length > 0) {
            printHtml += `<br><strong>Cross-Reference Issues:</strong><br>`;
            issues.forEach(iss => {
                const issText = typeof iss === 'string' ? iss
                    : (iss.issue || iss.description || JSON.stringify(iss));
                printHtml += `&bull; ${escapeHtml(issText)}<br>`;
            });
        }

        printHtml += `</div>`;
        printBlock.innerHTML = printHtml;

        // Append after document content
        if (documentContent) {
            documentContent.appendChild(printBlock);
        }

        // Update print summary with Layer 3 results
        updatePrintSummary();
    }

    // HTML Escape
    function escapeHtml(text) {
        if (!text) return '';
        const div = document.createElement('div');
        div.textContent = text;
        return div.innerHTML;
    }

    // Initialize on DOM ready
    if (document.readyState === 'loading') {
        document.addEventListener('DOMContentLoaded', init);
    } else {
        init();
    }
})();
