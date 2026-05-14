const API_BASE = (location.protocol === 'http:' || location.protocol === 'https:') ? '' : 'http://127.0.0.1:8000';

const VIEW_META = {
    dashboard:  { title: 'Visão Geral do Sistema', subtitle: 'Organize, higienize e garanta a conformidade dos arquivos corporativos.' },
    arquivos:   { title: 'Arquivos Escaneados',    subtitle: 'Lista detalhada dos arquivos com problemas detectados na última varredura.' },
    remediacao: { title: 'Remediação',              subtitle: 'Aplique correções e mova arquivos de mídia para destinos apropriados.' }
};

let latestReport = null;
let lastScannedPath = '';
let mediaFiles = [];
let activeMediaCategory = null;
let latestReportGroups = new Map();
let recordsById = new Map();
let cachedFilteredGroups = [];
let cachedTotalMatched = 0;
let lastFilesFilterKey = null;
let visibleFilesPage = 1;
let mediaFilteredGroups = [];
let lastMediaFilterKey = null;
let visibleMediaPage = 1;
const GROUPS_PAGE_SIZE = 30;

const MEDIA_LABELS = {
    imagens: 'Imagens',
    audio: 'Áudio',
    video: 'Vídeos',
    outros: 'Outros'
};

const RISK_LABELS = {
    CRITICAL: 'Crítico',
    HIGH: 'Alto',
    MEDIUM: 'Médio',
    LOW: 'Baixo',
    NONE: 'Nenhum'
};

const CLASSIFICATION_LABELS = {
    BUSINESS_DOCUMENT: 'Documento de Negócio',
    CACHE: 'Cache',
    TEMPORARY: 'Temporário',
    TECHNICAL_METADATA: 'Metadados Técnicos',
    SYSTEM_BACKUP: 'Backup de Sistema',
    DEVELOPMENT_ENVIRONMENT: 'Ambiente de Desenvolvimento',
    UNKNOWN: 'Não Classificado'
};

const ACTION_LABELS = {
    AUTO_RENAME: 'Renomear Automaticamente',
    SUGGEST_RENAME: 'Sugerir Renomeação',
    SUGGEST_RENAME_CAUTION: 'Sugerir Renomeação com Atenção',
    BLOCKED: 'Bloqueado (Compartilhado)',
    NONE: 'Manter Original',
    RENAME: 'Renomear',
    IGNORE: 'Ignorar'
};

function translate(map, key) {
    if (!key) return '';
    return map[String(key).toUpperCase()] || key;
}

document.addEventListener('DOMContentLoaded', () => {
    setupNavigation();
    setupScanner();
    setupRemediation();
    setupFilesView();
    setupMediaList();
    setupGlobalCellDelegation();
    autoReattachClassification();
});

// Se o backend já tem uma classificação rodando ou concluída,
// habilita o botão e (se rodando) reabre o modal automaticamente.
async function applyRenamesFlow() {
    if (!latestReport) {
        alert('Nenhum relatório carregado. Aguarde o carregamento ou rode um scan.');
        return;
    }

    // Conta itens elegíveis (com sugestão diferente, não bloqueados)
    let eligible = 0;
    let blocked = 0;
    for (const r of latestReport) {
        if (r.is_shared) { blocked++; continue; }
        const orig = r.original_name || '';
        const sugg = r.suggested_name || '';
        const action = r.action_required || '';
        if (sugg && sugg !== orig && ['AUTO_RENAME', 'SUGGEST_RENAME', 'SUGGEST_RENAME_CAUTION', 'RENAME'].includes(action)) {
            eligible++;
        }
    }

    if (eligible === 0) {
        alert('Nenhuma renomeação aplicável encontrada no relatório atual.');
        return;
    }

    const ok = confirm(
        `Aplicar ${eligible.toLocaleString('pt-BR')} renomeações sugeridas?\n\n` +
        `Itens BLOQUEADOS (compartilhados, ${blocked.toLocaleString('pt-BR')}) serão ignorados.\n\n` +
        `Operação real — os arquivos serão renomeados no disco. ` +
        `Recomendo ter o relatório aberto pra referência caso queira reverter manualmente.`
    );
    if (!ok) return;

    const btn = document.getElementById('btn-apply-renames');
    const originalText = btn.innerHTML;
    btn.innerHTML = '<i class="ph ph-spinner"></i> Renomeando...';
    btn.disabled = true;

    try {
        const res = await fetch(`${API_BASE}/api/apply-renames`, { method: 'POST' });
        const data = await res.json();
        if (!res.ok) {
            alert(`Erro: ${data.detail || 'desconhecido'}`);
            btn.innerHTML = originalText;
            btn.disabled = false;
            return;
        }
        let msg = `✓ Renomeação concluída!\n\n`;
        msg += `Renomeados: ${data.renamed}\n`;
        if (data.skipped_blocked) msg += `Ignorados (bloqueados): ${data.skipped_blocked}\n`;
        if (data.skipped_unchanged) msg += `Ignorados (sem mudança): ${data.skipped_unchanged}\n`;
        if (data.skipped_missing) msg += `Ignorados (não existem mais): ${data.skipped_missing}\n`;
        if (data.errors_count) msg += `Erros: ${data.errors_count}\n`;
        msg += `\nClique em "Atualizar" pra recarregar o relatório.`;
        alert(msg);
        btn.innerHTML = originalText;
        btn.disabled = false;
    } catch (e) {
        alert(`Erro de conexão: ${e.message}`);
        btn.innerHTML = originalText;
        btn.disabled = false;
    }
}

async function autoReattachClassification() {
    try {
        const res = await fetch(`${API_BASE}/api/classify/status`);
        if (!res.ok) return;
        const status = await res.json();

        const hasRunningOrCompleted =
            status.running ||
            (status.completed_at && status.done > 0 && !status.error);

        if (!hasRunningOrCompleted) return;

        const btn = document.getElementById('btn-trash');
        if (btn) btn.disabled = false;

        // Mostra um aviso visual no painel pra deixar claro que tem resultado disponível
        let banner = document.getElementById('classify-banner');
        if (!banner) {
            const panel = document.querySelector('#view-remediacao .action-panel');
            if (panel) {
                banner = document.createElement('div');
                banner.id = 'classify-banner';
                banner.className = 'info-box';
                banner.style.marginTop = '16px';
                panel.parentElement.insertBefore(banner, panel.nextSibling);
            }
        }
        if (banner) {
            if (status.running) {
                banner.innerHTML = `
                    <i class="ph ph-sparkle"></i>
                    <div>
                        <strong>Classificação por IA em andamento</strong> no backend
                        (${status.done}/${status.total}).
                        Reabrindo o painel de progresso…
                    </div>`;
            } else {
                // Pega o count de irrelevantes pra mostrar
                fetch(`${API_BASE}/api/classify/results`).then(r => r.json()).then(d => {
                    banner.innerHTML = `
                        <i class="ph ph-sparkle"></i>
                        <div>
                            <strong>Há resultados de classificação prontos:</strong>
                            ${d.total_classified.toLocaleString('pt-BR')} imagem(ns) analisadas,
                            <strong>${d.irrelevant_count.toLocaleString('pt-BR')} marcada(s) como irrelevante(s)</strong>.
                            Clique em <em>"Mover para Lixeira"</em> acima para ver.
                        </div>`;
                });
            }
        }

        if (status.running) {
            console.log('[auto-reattach] classificação em andamento, reabrindo modal');
            openClassifyModal(status.total);
            startClassifyPolling();
        }
    } catch {
        // backend offline na hora do load — silencioso
    }
}

function debounce(fn, wait) {
    let t;
    return function(...args) {
        clearTimeout(t);
        t = setTimeout(() => fn.apply(this, args), wait);
    };
}

function setupGlobalCellDelegation() {
    document.addEventListener('click', (e) => {
        const sugg = e.target.closest('.suggestion-cell');
        if (sugg) {
            e.stopPropagation();
            const rid = parseInt(sugg.dataset.rid, 10);
            const record = recordsById.get(rid);
            if (record) openSuggestionPopover(sugg, record);
            return;
        }
        const path = e.target.closest('.path-cell');
        if (path) {
            e.stopPropagation();
            openPathPopover(path);
            return;
        }
        const header = e.target.closest('.folder-header');
        if (header) {
            const kind = header.dataset.folderKind;
            const gIdx = parseInt(header.dataset.folderIdx, 10);
            if (isNaN(gIdx)) return;
            if (kind === 'files') {
                if (filesAllExpanded) {
                    filesAllExpanded = false;
                    document.getElementById('btn-expand-files').innerHTML = '<i class="ph ph-folders"></i> Expandir tudo';
                }
                toggleFilesFolderByIdx(gIdx);
            } else if (kind === 'media') {
                if (allFoldersExpanded) {
                    allFoldersExpanded = false;
                    document.getElementById('btn-expand-folders').innerHTML = '<i class="ph ph-folders"></i> Expandir tudo';
                }
                toggleMediaFolderByIdx(gIdx);
            }
        }
    });
}

function setupNavigation() {
    const links = document.querySelectorAll('.nav-link');
    links.forEach(link => {
        link.addEventListener('click', (e) => {
            e.preventDefault();
            const view = link.dataset.view;
            switchView(view);
        });
    });
}

function switchView(view) {
    document.querySelectorAll('.nav-link').forEach(l => l.classList.toggle('active', l.dataset.view === view));
    document.querySelectorAll('.view').forEach(v => v.classList.add('hidden'));
    document.getElementById(`view-${view}`).classList.remove('hidden');

    const meta = VIEW_META[view];
    document.getElementById('view-title').innerText = meta.title;
    document.getElementById('view-subtitle').innerText = meta.subtitle;

    if (view === 'arquivos') loadLatestReport();
}

function setupScanner() {
    const btnScan = document.getElementById('btn-scan');
    const inputPath = document.getElementById('target-path');
    const statusMsg = document.getElementById('scan-status');
    const statusText = document.getElementById('scan-status-text');
    const statsDashboard = document.getElementById('stats-dashboard');

    btnScan.addEventListener('click', async () => {
        const path = inputPath.value.trim();
        if (!path) {
            alert('Por favor, informe o caminho do diretório.');
            return;
        }

        btnScan.disabled = true;
        statsDashboard.classList.add('hidden');
        statusMsg.classList.remove('hidden');
        statusText.innerText = 'Analisando arquivos... isso pode levar alguns minutos.';

        try {
            const response = await fetch(`${API_BASE}/api/scan`, {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ path })
            });
            const result = await response.json();

            if (response.ok) {
                lastScannedPath = path;
                const stats = result.data.stats;
                document.getElementById('stat-total-files').innerText = stats.total_files || 0;
                document.getElementById('stat-long-paths').innerText = stats.long_paths || 0;
                document.getElementById('stat-deep-folders').innerText = stats.excessive_depth || 0;
                document.getElementById('stat-forbidden').innerText = stats.forbidden_chars || 0;

                const mediaCount = result.data.media_move_plan_count || 0;
                const statMedia = document.getElementById('stat-media');
                if (statMedia) statMedia.innerText = mediaCount;
                const btnTrash = document.getElementById('btn-trash');
                if (btnTrash) btnTrash.disabled = mediaCount === 0;
                const btnAudio = document.getElementById('btn-audio-trash');
                const audioCount = (result.data.media_breakdown && result.data.media_breakdown.audio && result.data.media_breakdown.audio.count) || 0;
                if (btnAudio) btnAudio.disabled = audioCount === 0;
                renderMediaBreakdown(result.data.media_breakdown || {});
                mediaFiles = result.data.media_files || [];
                closeMediaList();

                statusMsg.classList.add('hidden');
                statsDashboard.classList.remove('hidden');
                latestReport = null;
            } else {
                alert(`Erro: ${result.detail}`);
                statusMsg.classList.add('hidden');
            }
        } catch (error) {
            console.error(error);
            alert('Erro ao conectar com a API. Certifique-se de que o backend FastAPI está rodando.');
            statusMsg.classList.add('hidden');
        } finally {
            btnScan.disabled = false;
        }
    });
}

let classifyPollTimer = null;
let lastClassifyTotal = 0;

function setupRemediation() {
    const btnTrash = document.getElementById('btn-trash');
    const btnAudio = document.getElementById('btn-audio-trash');
    const trashModal = document.getElementById('trash-modal');
    const audioModal = document.getElementById('audio-trash-modal');
    const classifyModal = document.getElementById('classify-modal');

    btnTrash.addEventListener('click', startClassificationFlow);
    btnAudio.addEventListener('click', startAudioBackupFlow);

    document.getElementById('audio-modal-close').addEventListener('click', closeAudioModal);
    document.getElementById('btn-audio-cancel').addEventListener('click', closeAudioModal);
    document.getElementById('btn-audio-confirm').addEventListener('click', confirmAudioBackup);
    audioModal.addEventListener('click', (e) => {
        if (e.target === audioModal) closeAudioModal();
    });

    document.getElementById('trash-modal-close').addEventListener('click', closeTrashModal);
    document.getElementById('btn-trash-cancel').addEventListener('click', closeTrashModal);
    document.getElementById('btn-classify-close').addEventListener('click', closeClassifyModal);

    document.getElementById('btn-trash-confirm').addEventListener('click', async () => {
        const count = parseInt(document.getElementById('modal-count').innerText.replace(/\D/g, ''), 10) || 0;
        const confirmReal = confirm(
            `Confirma a movimentação REAL de ${count.toLocaleString('pt-BR')} arquivo(s) ` +
            `para a pasta "backup de imagens" na raiz do scan?\n\n` +
            `Os arquivos serão movidos (não deletados). Podem ser arrastados de volta a qualquer momento.`
        );
        if (!confirmReal) return;

        const btn = document.getElementById('btn-trash-confirm');
        const originalText = btn.innerHTML;
        btn.innerHTML = '<i class="ph ph-spinner"></i> Movendo...';
        btn.disabled = true;

        try {
            const res = await fetch(`${API_BASE}/api/move-irrelevant-to-image-trash`, { method: 'POST' });
            const data = await res.json();
            if (!res.ok) {
                alert(`Erro: ${data.detail || 'desconhecido'}`);
                btn.innerHTML = originalText;
                btn.disabled = false;
                return;
            }
            closeTrashModal();
            let msg = `✓ Concluído!\n\nArquivos movidos: ${data.moved}\n`;
            if (data.skipped_missing) msg += `Ignorados (não existem mais): ${data.skipped_missing}\n`;
            if (data.errors_count) msg += `Erros: ${data.errors_count}\n`;
            msg += `\nDestino: ${data.destination}`;
            alert(msg);
        } catch (e) {
            alert(`Erro de conexão: ${e.message}`);
            btn.innerHTML = originalText;
            btn.disabled = false;
        }
    });

    trashModal.addEventListener('click', (e) => { if (e.target === trashModal) closeTrashModal(); });
    classifyModal.addEventListener('click', (e) => { if (e.target === classifyModal && !document.getElementById('btn-classify-close').disabled) closeClassifyModal(); });

    document.addEventListener('keydown', (e) => {
        if (e.key !== 'Escape') return;
        if (!trashModal.classList.contains('hidden')) closeTrashModal();
        else if (!classifyModal.classList.contains('hidden') && !document.getElementById('btn-classify-close').disabled) closeClassifyModal();
    });
}

function startAudioBackupFlow() {
    const audios = (mediaFiles || []).filter(f => f.category === 'audio');
    if (audios.length === 0) {
        alert('Nenhum áudio identificado no último scan.');
        return;
    }
    document.getElementById('audio-modal-count').innerText = audios.length.toLocaleString('pt-BR');
    renderAudioFileList(audios);
    document.getElementById('audio-trash-modal').classList.remove('hidden');
}

function closeAudioModal() {
    document.getElementById('audio-trash-modal').classList.add('hidden');
}

function renderAudioFileList(files) {
    const list = document.getElementById('audio-modal-file-list');
    const CAP = 500;
    const slice = files.slice(0, CAP);
    let html = slice.map(f => {
        const name = escapeHtml(f.name || '—');
        const path = escapeHtml(f.path || '');
        const src = escapeHtml(f.source_folder || '');
        return `<div class="modal-file-row">
            <div class="modal-file-name">${name}</div>
            <div class="modal-file-meta">
                ${src ? `<span class="badge badge-source">${src}</span>` : ''}
                <span class="modal-file-path" title="${path}">${path}</span>
            </div>
        </div>`;
    }).join('');
    if (files.length > CAP) {
        html += `<div class="modal-file-more">…e mais ${(files.length - CAP).toLocaleString('pt-BR')} arquivo(s) (todos serão movidos).</div>`;
    }
    list.innerHTML = html;
}

async function confirmAudioBackup() {
    const count = parseInt(document.getElementById('audio-modal-count').innerText.replace(/\D/g, ''), 10) || 0;
    const ok = confirm(
        `Confirma a movimentação REAL de ${count.toLocaleString('pt-BR')} áudio(s) ` +
        `para "backup de audios" na raiz do scan?\n\n` +
        `Os arquivos serão movidos (não deletados). Podem ser arrastados de volta a qualquer momento.`
    );
    if (!ok) return;

    const btn = document.getElementById('btn-audio-confirm');
    const originalText = btn.innerHTML;
    btn.innerHTML = '<i class="ph ph-spinner"></i> Movendo...';
    btn.disabled = true;

    try {
        const res = await fetch(`${API_BASE}/api/move-all-audio-to-trash`, { method: 'POST' });
        const data = await res.json();
        if (!res.ok) {
            alert(`Erro: ${data.detail || 'desconhecido'}`);
            btn.innerHTML = originalText;
            btn.disabled = false;
            return;
        }
        closeAudioModal();
        let msg = `✓ Concluído!\n\nÁudios movidos: ${data.moved}\n`;
        if (data.skipped_missing) msg += `Ignorados (não existem mais): ${data.skipped_missing}\n`;
        if (data.errors_count) msg += `Erros: ${data.errors_count}\n`;
        msg += `\nDestino: ${data.destination}`;
        alert(msg);
    } catch (e) {
        alert(`Erro de conexão: ${e.message}`);
        btn.innerHTML = originalText;
        btn.disabled = false;
    }
}

async function startClassificationFlow() {
    // Checagem de status acontece PRIMEIRO — assim mesmo após Ctrl+F5 (com
    // mediaFiles vazio) conseguimos reanexar a um job que continua no backend.
    try {
        const statusRes = await fetch(`${API_BASE}/api/classify/status`);
        const status = await statusRes.json();

        if (status.running) {
            openClassifyModal(status.total);
            startClassifyPolling();
            return;
        }

        if (status.completed_at && status.done > 0 && !status.error) {
            const useExisting = confirm(
                `Já existe uma classificação CONCLUÍDA no backend ` +
                `(${status.done.toLocaleString('pt-BR')} imagens analisadas).\n\n` +
                `OK = ver os resultados.\n` +
                `Cancelar = rodar uma nova classificação do zero.`
            );
            if (useExisting) {
                openTrashModalFromResults();
                return;
            }
        }
    } catch {
        // backend pode estar fora — segue pro fluxo normal de início
    }

    // Pra iniciar do zero precisamos do scan na memória do browser
    if (!mediaFiles || mediaFiles.length === 0) {
        alert('Nenhum arquivo de mídia identificado nesta sessão. Rode um scan primeiro.');
        return;
    }
    const imgCount = mediaFiles.filter(f => f.category === 'imagens').length;
    if (imgCount === 0) {
        alert('Nenhuma IMAGEM identificada no último scan. A classificação por IA só roda em imagens.');
        return;
    }
    const ok = confirm(
        `Iniciar classificação por IA?\n\n` +
        `Imagens a analisar: ${imgCount.toLocaleString('pt-BR')}\n` +
        `Modelo: Gemini 2.5 Flash (Thinking)\n` +
        `Tempo estimado: ~${Math.ceil(imgCount * 1.5 / 60)} min com 4 chamadas paralelas\n` +
        `Custo: depende do seu plano Google AI\n\n` +
        `Ao fim, você vê só as IRRELEVANTES antes de simular o move.`
    );
    if (!ok) return;

    try {
        const res = await fetch(`${API_BASE}/api/classify/start`, { method: 'POST' });
        const data = await res.json();
        if (!res.ok) {
            alert(`Erro ao iniciar: ${data.detail || 'desconhecido'}`);
            return;
        }
        lastClassifyTotal = data.total || 0;
        openClassifyModal(data.total);
        startClassifyPolling();
    } catch (e) {
        alert(`Erro de conexão: ${e.message}`);
    }
}

function openClassifyModal(total) {
    document.getElementById('classify-progress-fill').style.width = '0%';
    document.getElementById('classify-progress-label').innerText = `0 / ${total.toLocaleString('pt-BR')} (0%)`;
    document.getElementById('classify-status-text').innerText = 'Analisando imagens com Gemini 2.5 Flash (Thinking)…';
    document.getElementById('classify-error').classList.add('hidden');
    const closeBtn = document.getElementById('btn-classify-close');
    closeBtn.disabled = true;
    closeBtn.innerText = 'Aguarde…';
    document.getElementById('classify-modal').classList.remove('hidden');
}

function closeClassifyModal() {
    if (classifyPollTimer) { clearInterval(classifyPollTimer); classifyPollTimer = null; }
    document.getElementById('classify-modal').classList.add('hidden');
}

function startClassifyPolling() {
    if (classifyPollTimer) clearInterval(classifyPollTimer);
    classifyPollTimer = setInterval(pollClassifyStatus, 2000);
    pollClassifyStatus();
}

async function pollClassifyStatus() {
    try {
        const res = await fetch(`${API_BASE}/api/classify/status`);
        const s = await res.json();
        const fill = document.getElementById('classify-progress-fill');
        const label = document.getElementById('classify-progress-label');
        fill.style.width = `${s.percent.toFixed(1)}%`;
        const cacheInfo = (s.cache_hits || s.api_calls)
            ? ` — cache: ${(s.cache_hits || 0).toLocaleString('pt-BR')}, API: ${(s.api_calls || 0).toLocaleString('pt-BR')}`
            : '';
        label.innerText = `${s.done.toLocaleString('pt-BR')} / ${s.total.toLocaleString('pt-BR')} (${s.percent.toFixed(1)}%)${cacheInfo}`;

        if (s.error) {
            document.getElementById('classify-error').innerText = `Erro: ${s.error}`;
            document.getElementById('classify-error').classList.remove('hidden');
        }

        if (!s.running) {
            if (classifyPollTimer) { clearInterval(classifyPollTimer); classifyPollTimer = null; }
            const closeBtn = document.getElementById('btn-classify-close');
            closeBtn.disabled = false;
            closeBtn.innerText = 'Continuar';
            document.getElementById('classify-status-text').innerText = s.error
                ? 'Classificação interrompida com erro.'
                : 'Classificação concluída — abrindo lista de irrelevantes…';
            if (!s.error) {
                setTimeout(() => {
                    closeClassifyModal();
                    openTrashModalFromResults();
                }, 800);
            }
        }
    } catch (e) {
        console.error('poll falhou', e);
    }
}

async function openTrashModalFromResults() {
    try {
        const res = await fetch(`${API_BASE}/api/classify/results`);
        const data = await res.json();
        const irrelevant = data.irrelevant || [];

        document.getElementById('modal-count').innerText = irrelevant.length.toLocaleString('pt-BR');
        const totalEl = document.getElementById('modal-total');
        if (totalEl) totalEl.innerText = data.total_classified.toLocaleString('pt-BR');

        renderTrashFileList(irrelevant);
        document.getElementById('trash-modal').classList.remove('hidden');
    } catch (e) {
        alert(`Erro ao buscar resultados: ${e.message}`);
    }
}

function closeTrashModal() {
    document.getElementById('trash-modal').classList.add('hidden');
}

function renderTrashFileList(files) {
    const list = document.getElementById('modal-file-list');
    if (files.length === 0) {
        list.innerHTML = `<div class="modal-file-more">A IA não classificou nenhuma imagem como irrelevante. 🎉</div>`;
        return;
    }
    const CAP = 500;
    const slice = files.slice(0, CAP);

    let html = slice.map(f => {
        const name = escapeHtml(f.name || '—');
        const path = escapeHtml(f.path || '');
        const src = escapeHtml(f.source_folder || '');
        const conf = f.confianca != null ? f.confianca : 0;
        const motivo = escapeHtml(f.motivo || '');
        const confColor = conf >= 90 ? '#991b1b' : (conf >= 70 ? '#92400e' : '#4b5563');
        return `<div class="modal-file-row">
            <div class="modal-file-name">${name}
                <span style="font-size: 11px; padding: 2px 8px; border-radius: 999px; background: #fee2e2; color: ${confColor}; margin-left: 8px;">${conf}%</span>
            </div>
            <div class="modal-file-meta">
                ${src ? `<span class="badge badge-source">${src}</span>` : ''}
                <span style="color: #4b5563; font-style: italic;">${motivo}</span>
            </div>
            <div class="modal-file-meta" style="margin-top: 2px;">
                <span class="modal-file-path" title="${path}">${path}</span>
            </div>
        </div>`;
    }).join('');

    if (files.length > CAP) {
        html += `<div class="modal-file-more">…e mais ${(files.length - CAP).toLocaleString('pt-BR')} arquivo(s) (todos seriam movidos).</div>`;
    }
    list.innerHTML = html;
}

let filesExpandedFolders = new Set();
let filesAllExpanded = false;
let filesGroupsCache = new Map();
let mediaGroupsCache = new Map();

function setupFilesView() {
    const debouncedRender = debounce(renderFilesTable, 150);
    document.getElementById('btn-refresh-files').addEventListener('click', () => loadLatestReport(true));
    document.getElementById('filter-input').addEventListener('input', debouncedRender);
    document.getElementById('filter-issue').addEventListener('change', renderFilesTable);
    document.getElementById('filter-kind').addEventListener('change', renderFilesTable);
    document.getElementById('filter-suggestions').addEventListener('change', renderFilesTable);
    document.getElementById('btn-apply-renames').addEventListener('click', applyRenamesFlow);
    document.getElementById('btn-expand-files').addEventListener('click', () => {
        filesAllExpanded = !filesAllExpanded;
        filesExpandedFolders.clear();
        document.getElementById('btn-expand-files').innerHTML = filesAllExpanded
            ? '<i class="ph ph-folders"></i> Recolher tudo'
            : '<i class="ph ph-folders"></i> Expandir tudo';
        renderFilesTable();
    });
}

async function loadLatestReport(force = false) {
    const empty = document.getElementById('files-empty');
    const loading = document.getElementById('files-loading');
    const content = document.getElementById('files-content');

    if (latestReport && !force) {
        empty.classList.add('hidden');
        loading.classList.add('hidden');
        content.classList.remove('hidden');
        renderFilesTable();
        return;
    }

    empty.classList.add('hidden');
    content.classList.add('hidden');
    loading.classList.remove('hidden');

    try {
        const response = await fetch(`${API_BASE}/api/reports/latest`);
        const result = await response.json();
        loading.classList.add('hidden');

        const records = Array.isArray(result.data) ? result.data : (result.data && result.data.issues);
        const truncated = !!(result.data && result.data.truncated);
        const totalCount = result.data && result.data.total_count;
        if (result.status === 'success' && Array.isArray(records) && records.length > 0) {
            latestReport = records;
            enrichAndGroupReport(records);
            content.classList.remove('hidden');
            lastFilesFilterKey = null;
            visibleFilesPage = 1;
            renderFilesTable();
            const banner = document.getElementById('truncation-banner');
            if (banner) {
                if (truncated) {
                    banner.classList.remove('hidden');
                    banner.querySelector('.truncation-text').innerText =
                        `Mostrando os ${records.length.toLocaleString('pt-BR')} itens de maior risco de um total de ${totalCount.toLocaleString('pt-BR')}. Use filtros para refinar.`;
                } else {
                    banner.classList.add('hidden');
                }
            }
        } else {
            empty.classList.remove('hidden');
        }
    } catch (error) {
        console.error(error);
        loading.classList.add('hidden');
        empty.classList.remove('hidden');
    }
}

function enrichAndGroupReport(records) {
    latestReportGroups = new Map();
    recordsById = new Map();

    let rid = 0;
    for (const record of records) {
        record._rid = rid++;
        recordsById.set(record._rid, record);

        record._issues = parseViolations(record.detected_problems);

        record._hay = ((record.original_name || '') + ' ' + (record.full_path || '')).toLowerCase();

        const orig = record.original_name || '';
        const sugg = record.suggested_name || '';
        record._hasSugg = !!(sugg && sugg !== orig);
        record._isShortening = record._hasSugg && sugg.length < orig.length;

        const folder = parentFolder(record.full_path || '');
        if (!latestReportGroups.has(folder)) latestReportGroups.set(folder, []);
        latestReportGroups.get(folder).push(record);
    }
}

function computeFilteredFiles() {
    const nameFilter = document.getElementById('filter-input').value.toLowerCase();
    const issueFilter = document.getElementById('filter-issue').value;
    const kindFilter = document.getElementById('filter-kind').value;
    const onlySuggestions = document.getElementById('filter-suggestions').checked;

    const filterKey = `${nameFilter}|${issueFilter}|${kindFilter}|${onlySuggestions}`;
    const filterActive = !!(nameFilter || issueFilter || kindFilter || onlySuggestions);
    if (filterKey === lastFilesFilterKey) return { filterActive };

    const groups = [];
    let total = 0;

    for (const [folder, records] of latestReportGroups) {
        let kept;
        if (!filterActive) {
            kept = records;
        } else {
            kept = [];
            for (const r of records) {
                if (kindFilter === 'file' && r.is_dir) continue;
                if (kindFilter === 'folder' && !r.is_dir) continue;
                if (onlySuggestions && !r._hasSugg) continue;
                if (issueFilter === 'shortening') {
                    if (!r._isShortening) continue;
                } else if (issueFilter && !r._issues.has(issueFilter)) {
                    continue;
                }
                if (nameFilter && !r._hay.includes(nameFilter)) continue;
                kept.push(r);
            }
        }
        if (kept.length > 0) {
            groups.push([folder, kept]);
            total += kept.length;
        }
    }

    groups.sort((a, b) => b[1].length - a[1].length);

    cachedFilteredGroups = groups;
    cachedTotalMatched = total;
    lastFilesFilterKey = filterKey;
    visibleFilesPage = 1;

    return { filterActive };
}

function renderFilesTable() {
    if (!latestReport) return;
    const { filterActive } = computeFilteredFiles();

    filesGroupsCache = new Map(cachedFilteredGroups);

    const AUTO_EXPAND_LIMIT = 5;
    const autoExpandSet = filterActive
        ? new Set(cachedFilteredGroups.slice(0, AUTO_EXPAND_LIMIT).map(([f]) => f))
        : new Set();

    const visibleCount = Math.min(cachedFilteredGroups.length, visibleFilesPage * GROUPS_PAGE_SIZE);
    const visible = cachedFilteredGroups.slice(0, visibleCount);

    let html = visible.map(([folder, items], gIdx) => {
        const isOpen = filesAllExpanded || autoExpandSet.has(folder) || filesExpandedFolders.has(folder);
        return renderFileFolderGroup(folder, items, gIdx, isOpen);
    }).join('');

    if (cachedFilteredGroups.length > visibleCount) {
        const remaining = cachedFilteredGroups.length - visibleCount;
        const next = Math.min(remaining, GROUPS_PAGE_SIZE);
        html += `<button type="button" class="show-more-btn btn-secondary" id="btn-show-more-files">
            <i class="ph ph-arrow-down"></i> Mostrar mais ${next} pasta(s) (${remaining} restantes)
        </button>`;
    }

    const container = document.getElementById('files-folder-groups');
    container.innerHTML = html;

    document.getElementById('files-count').innerText =
        `${cachedTotalMatched} item(ns) em ${cachedFilteredGroups.length} pasta(s).`;

    const moreBtn = document.getElementById('btn-show-more-files');
    if (moreBtn) moreBtn.addEventListener('click', appendMoreFileGroups);
}

function appendMoreFileGroups() {
    visibleFilesPage++;
    const startIdx = (visibleFilesPage - 1) * GROUPS_PAGE_SIZE;
    const endIdx = visibleFilesPage * GROUPS_PAGE_SIZE;
    const slice = cachedFilteredGroups.slice(startIdx, endIdx);

    document.getElementById('btn-show-more-files')?.remove();

    let html = slice.map(([folder, items], i) => {
        const gIdx = startIdx + i;
        const isOpen = filesAllExpanded || filesExpandedFolders.has(folder);
        return renderFileFolderGroup(folder, items, gIdx, isOpen);
    }).join('');

    if (cachedFilteredGroups.length > endIdx) {
        const remaining = cachedFilteredGroups.length - endIdx;
        const next = Math.min(remaining, GROUPS_PAGE_SIZE);
        html += `<button type="button" class="show-more-btn btn-secondary" id="btn-show-more-files">
            <i class="ph ph-arrow-down"></i> Mostrar mais ${next} pasta(s) (${remaining} restantes)
        </button>`;
    }

    const container = document.getElementById('files-folder-groups');
    container.insertAdjacentHTML('beforeend', html);

    const moreBtn = document.getElementById('btn-show-more-files');
    if (moreBtn) moreBtn.addEventListener('click', appendMoreFileGroups);
}

function parseViolations(raw) {
    const r = (raw || '').toUpperCase();
    const out = new Set();
    if (r.includes('FILENAME_TOO_LONG')) out.add('filename_too_long');
    if (r.includes('PATH_TOO_LONG')) out.add('path_too_long');
    if (r.includes('FORBIDDEN_CHARS')) out.add('forbidden_chars');
    if (r.includes('RESERVED_NAME')) out.add('reserved_name');
    if (r.includes('INVALID_EDGE_CHARS')) out.add('invalid_edges');
    if (r.includes('SUSPICIOUS_DOUBLE_EXT')) out.add('suspicious_double_ext');
    return out;
}

function getIssues(record) {
    if (record._issues) return [...record._issues];
    return [...parseViolations(record.detected_problems)];
}

function hasSuggestion(record) {
    const orig = record.original_name || record.name || '';
    const sugg = record.suggested_name || '';
    return sugg && sugg !== orig;
}

function riskClass(level) {
    const k = (level || '').toUpperCase();
    if (k === 'CRITICAL') return 'risk-critical';
    if (k === 'HIGH') return 'risk-high';
    if (k === 'MEDIUM') return 'risk-medium';
    if (k === 'LOW') return 'risk-low';
    return 'risk-none';
}

function renderFileFolderGroup(folder, items, gIdx, isOpen) {
    const folderShort = escapeHtml(shortFolder(folder));
    const folderFull = escapeHtml(folder);
    let sharedCount = 0;
    for (const r of items) if (r.is_shared) sharedCount++;
    const sharedBadge = sharedCount > 0
        ? `<span class="badge badge-locked"><i class="ph ph-lock"></i> ${sharedCount} bloqueado(s)</span>`
        : '';
    const contentHtml = isOpen ? renderFileRows(items) : '';
    return `
        <div class="folder-group ${isOpen ? 'open' : ''}" data-folder-idx="${gIdx}" data-folder-kind="files">
            <div class="folder-header" data-folder-idx="${gIdx}" data-folder-kind="files" role="button">
                <i class="ph ph-caret-right folder-caret"></i>
                <i class="ph ph-folder folder-icon"></i>
                <span class="folder-name path-cell" data-fullpath="${folderFull}" title="Clique para ver / copiar">${folderShort}</span>
                ${sharedBadge}
                <span class="folder-count">${items.length}</span>
            </div>
            <div class="folder-content" data-filled="${isOpen ? '1' : '0'}">${contentHtml}</div>
        </div>
    `;
}

function renderFileRows(items) {
    const CAP = 200;
    const parts = [];
    const limit = Math.min(items.length, CAP);
    for (let i = 0; i < limit; i++) {
        const record = items[i];
        const issues = [...record._issues];
        const badges = issues.map(t => `<span class="badge badge-${t}">${issueLabel(t)}</span>`).join(' ');
        const name = escapeHtml(record.original_name || '—');
        const icon = record.is_dir ? 'ph-folder' : 'ph-file';
        const lockIcon = record.is_shared ? '<i class="ph ph-lock-key file-lock-icon"></i>' : '';
        parts.push(`<tr><td><i class="ph ${icon} file-row-icon"></i> ${name} ${lockIcon}</td><td>${renderSuggestionCell(record)}</td><td>${badges}</td></tr>`);
    }
    const truncated = items.length > CAP
        ? `<tr><td colspan="3" class="folder-truncated">…e mais ${items.length - CAP} item(ns) nesta pasta.</td></tr>`
        : '';
    return `<div class="table-wrapper folder-table"><table class="files-table"><thead><tr><th>Arquivo</th><th>Sugestão</th><th>Problema</th></tr></thead><tbody>${parts.join('')}${truncated}</tbody></table></div>`;
}

function toggleFilesFolderByIdx(gIdx) {
    const group = document.querySelector(`#files-folder-groups .folder-group[data-folder-idx="${gIdx}"]`);
    if (!group) return;
    const entry = cachedFilteredGroups[gIdx];
    if (!entry) return;
    const [folder, items] = entry;
    const content = group.querySelector('.folder-content');
    const isOpen = group.classList.contains('open');

    if (isOpen) {
        group.classList.remove('open');
        filesExpandedFolders.delete(folder);
    } else {
        if (content.dataset.filled !== '1') {
            content.innerHTML = renderFileRows(items);
            content.dataset.filled = '1';
        }
        group.classList.add('open');
        filesExpandedFolders.add(folder);
    }
}

function toggleMediaFolderByIdx(gIdx) {
    const group = document.querySelector(`#media-folder-groups .folder-group[data-folder-idx="${gIdx}"]`);
    if (!group) return;
    const entry = mediaFilteredGroups[gIdx];
    if (!entry) return;
    const [folder, items] = entry;
    const content = group.querySelector('.folder-content');
    const isOpen = group.classList.contains('open');

    if (isOpen) {
        group.classList.remove('open');
        expandedFolders.delete(folder);
    } else {
        if (content.dataset.filled !== '1') {
            content.innerHTML = renderMediaRows(items);
            content.dataset.filled = '1';
        }
        group.classList.add('open');
        expandedFolders.add(folder);
    }
}

function renderSuggestionCell(record) {
    if (record.is_shared) {
        return `<span class="suggestion-locked"><i class="ph ph-lock"></i> Bloqueado</span>`;
    }
    if (!record._hasSugg && !hasSuggestion(record)) {
        return `<span class="suggestion-empty">—</span>`;
    }
    const sugg = escapeHtml(record.suggested_name);
    const risk = (record.risk_level || 'LOW').toUpperCase();
    return `<button type="button" class="suggestion-cell ${riskClass(risk)}" data-rid="${record._rid}">
        <i class="ph ph-sparkle"></i>
        <span class="suggestion-text">${sugg}</span>
    </button>`;
}

function openSuggestionPopover(anchor, record) {
    closePopover();
    const orig = record.original_name || record.name || '—';
    const sugg = record.suggested_name || '—';
    const reason = record.naming_reason || '';
    const conf = record.confidence_score;
    const cls = record.classification || '';
    const risk = (record.risk_level || 'LOW').toUpperCase();
    const action = record.action_required || '';
    const summary = record.semantic_summary || '';

    const pop = document.createElement('div');
    pop.className = 'path-popover suggestion-popover';
    pop.innerHTML = `
        <div class="path-popover-header">
            <span><i class="ph ph-sparkle"></i> Sugestão de Renomeação</span>
            <button class="path-popover-close" type="button" aria-label="Fechar"><i class="ph ph-x"></i></button>
        </div>
        <div class="suggestion-body">
            <div class="suggestion-row">
                <label>Nome original</label>
                <div class="suggestion-value mono">${escapeHtml(orig)}</div>
            </div>
            <div class="suggestion-arrow"><i class="ph ph-arrow-down"></i></div>
            <div class="suggestion-row">
                <label>Nome sugerido</label>
                <div class="suggestion-value mono highlight">${escapeHtml(sugg)}</div>
            </div>

            <div class="suggestion-meta">
                <div class="meta-item">
                    <label>Risco</label>
                    <span class="badge ${riskClass(risk)}">${escapeHtml(translate(RISK_LABELS, risk))}</span>
                </div>
                ${cls ? `<div class="meta-item"><label>Classificação</label><span>${escapeHtml(translate(CLASSIFICATION_LABELS, cls))}</span></div>` : ''}
                ${conf !== '' && conf != null ? `<div class="meta-item"><label>Confiança</label><span>${escapeHtml(String(conf))}%</span></div>` : ''}
                ${action ? `<div class="meta-item"><label>Ação</label><span>${escapeHtml(translate(ACTION_LABELS, action))}</span></div>` : ''}
            </div>

            ${reason ? `<div class="suggestion-row"><label>Motivo</label><div class="suggestion-value">${escapeHtml(reason)}</div></div>` : ''}
            ${summary ? `<div class="suggestion-row"><label>Resumo semântico</label><div class="suggestion-value">${escapeHtml(summary)}</div></div>` : ''}
        </div>
        <div class="path-popover-footer">
            <button class="path-popover-copy btn-primary" type="button">
                <i class="ph ph-copy"></i> Copiar sugestão
            </button>
        </div>
    `;
    document.body.appendChild(pop);

    const rect = anchor.getBoundingClientRect();
    const top = window.scrollY + rect.bottom + 6;
    let left = window.scrollX + rect.left;
    pop.style.top = `${top}px`;
    pop.style.left = `${left}px`;
    const popRect = pop.getBoundingClientRect();
    const overflow = popRect.right - window.innerWidth + 16;
    if (overflow > 0) pop.style.left = `${left - overflow}px`;

    pop.querySelector('.path-popover-close').addEventListener('click', closePopover);
    pop.querySelector('.path-popover-copy').addEventListener('click', async (ev) => {
        ev.stopPropagation();
        const btn = ev.currentTarget;
        try {
            await navigator.clipboard.writeText(sugg);
            btn.innerHTML = '<i class="ph ph-check"></i> Copiado!';
            btn.classList.add('copied');
            setTimeout(closePopover, 800);
        } catch {}
    });

    pop.addEventListener('click', (ev) => ev.stopPropagation());
    currentPopover = pop;

    setTimeout(() => {
        document.addEventListener('click', closePopover, { once: true });
        document.addEventListener('keydown', escClose);
    }, 0);
}

function issueLabel(key) {
    return {
        filename_too_long: 'Nome > 255',
        path_too_long: 'Caminho > 400',
        forbidden_chars: 'Caractere Proibido',
        reserved_name: 'Nome Reservado',
        invalid_edges: 'Borda Inválida',
        suspicious_double_ext: 'Dupla Extensão'
    }[key] || key;
}

let currentPopover = null;

function openPathPopover(anchor) {
    closePopover();
    const fullPath = anchor.dataset.fullpath || anchor.innerText;

    const pop = document.createElement('div');
    pop.className = 'path-popover';
    pop.innerHTML = `
        <div class="path-popover-header">
            <span><i class="ph ph-folder-open"></i> Caminho completo</span>
            <button class="path-popover-close" type="button" aria-label="Fechar">
                <i class="ph ph-x"></i>
            </button>
        </div>
        <div class="path-popover-body"></div>
        <div class="path-popover-footer">
            <button class="path-popover-copy btn-primary" type="button">
                <i class="ph ph-copy"></i> Copiar
            </button>
        </div>
    `;
    pop.querySelector('.path-popover-body').innerText = fullPath;
    document.body.appendChild(pop);

    const rect = anchor.getBoundingClientRect();
    const top = window.scrollY + rect.bottom + 6;
    let left = window.scrollX + rect.left;
    pop.style.top = `${top}px`;
    pop.style.left = `${left}px`;

    const popRect = pop.getBoundingClientRect();
    const overflow = popRect.right - window.innerWidth + 16;
    if (overflow > 0) {
        pop.style.left = `${left - overflow}px`;
    }

    pop.querySelector('.path-popover-close').addEventListener('click', closePopover);
    pop.querySelector('.path-popover-copy').addEventListener('click', async (ev) => {
        ev.stopPropagation();
        const btn = ev.currentTarget;
        try {
            await navigator.clipboard.writeText(fullPath);
            btn.innerHTML = '<i class="ph ph-check"></i> Copiado!';
            btn.classList.add('copied');
            setTimeout(closePopover, 800);
        } catch {
            const range = document.createRange();
            range.selectNodeContents(pop.querySelector('.path-popover-body'));
            const sel = window.getSelection();
            sel.removeAllRanges();
            sel.addRange(range);
        }
    });

    pop.addEventListener('click', (ev) => ev.stopPropagation());
    currentPopover = pop;

    setTimeout(() => {
        document.addEventListener('click', closePopover, { once: true });
        document.addEventListener('keydown', escClose);
    }, 0);
}

function escClose(e) {
    if (e.key === 'Escape') closePopover();
}

function closePopover() {
    if (currentPopover) {
        currentPopover.remove();
        currentPopover = null;
    }
    document.removeEventListener('keydown', escClose);
    // Limpa o listener pendente de click-outside (registrado com {once:true})
    // pra não fechar uma popover nova que acabou de abrir no mesmo evento.
    document.removeEventListener('click', closePopover);
}

function renderMediaBreakdown(breakdown) {
    const container = document.getElementById('media-breakdown');
    if (!container) return;
    const total = Object.values(breakdown).reduce((sum, b) => sum + (b.count || 0), 0);
    container.classList.toggle('hidden', total === 0);

    ['imagens', 'audio', 'video', 'outros'].forEach(cat => {
        const data = breakdown[cat] || { count: 0, extensions: {} };
        const card = container.querySelector(`[data-category="${cat}"]`);
        const countEl = container.querySelector(`[data-count="${cat}"]`);
        const extEl = container.querySelector(`[data-ext="${cat}"]`);
        const count = data.count || 0;
        if (countEl) countEl.innerText = count;
        if (extEl) {
            const exts = Object.entries(data.extensions || {})
                .sort((a, b) => b[1] - a[1])
                .map(([ext, n]) => `${ext} (${n})`)
                .join(', ');
            extEl.innerText = exts || '—';
        }
        if (card) {
            card.classList.toggle('clickable', count > 0);
        }
    });
}

let expandedFolders = new Set();
let allFoldersExpanded = false;

function setupMediaList() {
    document.querySelectorAll('.media-card').forEach(card => {
        card.addEventListener('click', () => {
            const cat = card.dataset.category;
            if (!cat) return;
            const items = mediaFiles.filter(f => f.category === cat);
            if (items.length === 0) return;
            openMediaList(cat);
        });
    });
    document.getElementById('btn-close-media-list').addEventListener('click', closeMediaList);
    document.getElementById('media-filter-input').addEventListener('input', debounce(renderMediaTable, 150));
    document.getElementById('btn-expand-folders').addEventListener('click', toggleAllFolders);
}

function toggleAllFolders() {
    allFoldersExpanded = !allFoldersExpanded;
    expandedFolders.clear();
    document.getElementById('btn-expand-folders').innerHTML = allFoldersExpanded
        ? '<i class="ph ph-folders"></i> Recolher tudo'
        : '<i class="ph ph-folders"></i> Expandir tudo';
    renderMediaTable();
}

function parentFolder(p) {
    if (!p) return '(sem caminho)';
    const sep = p.includes('\\') ? '\\' : '/';
    const idx = p.lastIndexOf(sep);
    return idx >= 0 ? p.substring(0, idx) : p;
}

function shortFolder(p) {
    if (!p) return '';
    const sep = p.includes('\\') ? '\\' : '/';
    const parts = p.split(sep).filter(Boolean);
    if (parts.length <= 2) return p;
    return '…' + sep + parts.slice(-2).join(sep);
}

function openMediaList(category) {
    activeMediaCategory = category;
    expandedFolders = new Set();
    allFoldersExpanded = false;
    lastMediaFilterKey = null;
    visibleMediaPage = 1;
    document.getElementById('btn-expand-folders').innerHTML = '<i class="ph ph-folders"></i> Expandir tudo';
    document.querySelectorAll('.media-card').forEach(c => {
        c.classList.toggle('active', c.dataset.category === category);
    });
    document.getElementById('media-list-title').innerText = `Arquivos — ${MEDIA_LABELS[category] || category}`;
    const panel = document.getElementById('media-list-panel');
    panel.classList.remove('hidden');
    document.getElementById('media-filter-input').value = '';
    renderMediaTable();
    panel.scrollIntoView({ behavior: 'smooth', block: 'start' });
}

function closeMediaList() {
    activeMediaCategory = null;
    document.querySelectorAll('.media-card').forEach(c => c.classList.remove('active'));
    document.getElementById('media-list-panel').classList.add('hidden');
}

function computeFilteredMedia() {
    const filter = document.getElementById('media-filter-input').value.toLowerCase();
    const filterKey = `${activeMediaCategory}|${filter}`;
    if (filterKey === lastMediaFilterKey) return { filterActive: !!filter };

    const groups = new Map();
    for (const f of mediaFiles) {
        if (f.category !== activeMediaCategory) continue;
        if (filter) {
            if (!f._hay) f._hay = ((f.name || '') + ' ' + (f.path || '')).toLowerCase();
            if (!f._hay.includes(filter)) continue;
        }
        const folder = parentFolder(f.path);
        if (!groups.has(folder)) groups.set(folder, []);
        groups.get(folder).push(f);
    }

    const sortedGroups = [...groups.entries()].sort((a, b) => b[1].length - a[1].length);

    mediaFilteredGroups = sortedGroups;
    lastMediaFilterKey = filterKey;
    visibleMediaPage = 1;
    return { filterActive: !!filter };
}

function renderMediaTable() {
    if (!activeMediaCategory) return;
    const { filterActive } = computeFilteredMedia();

    mediaGroupsCache = new Map(mediaFilteredGroups);

    const AUTO_EXPAND_LIMIT = 5;
    const autoExpandSet = filterActive
        ? new Set(mediaFilteredGroups.slice(0, AUTO_EXPAND_LIMIT).map(([f]) => f))
        : new Set();

    const visibleCount = Math.min(mediaFilteredGroups.length, visibleMediaPage * GROUPS_PAGE_SIZE);
    const visible = mediaFilteredGroups.slice(0, visibleCount);

    let html = visible.map(([folder, items], gIdx) => {
        const isOpen = allFoldersExpanded || autoExpandSet.has(folder) || expandedFolders.has(folder);
        return renderMediaFolderGroup(folder, items, gIdx, isOpen);
    }).join('');

    if (mediaFilteredGroups.length > visibleCount) {
        const remaining = mediaFilteredGroups.length - visibleCount;
        const next = Math.min(remaining, GROUPS_PAGE_SIZE);
        html += `<button type="button" class="show-more-btn btn-secondary" id="btn-show-more-media">
            <i class="ph ph-arrow-down"></i> Mostrar mais ${next} pasta(s) (${remaining} restantes)
        </button>`;
    }

    const container = document.getElementById('media-folder-groups');
    container.innerHTML = html;

    let total = 0;
    for (const [, items] of mediaFilteredGroups) total += items.length;
    document.getElementById('media-count').innerText =
        `${total} arquivo(s) em ${mediaFilteredGroups.length} pasta(s).`;

    const moreBtn = document.getElementById('btn-show-more-media');
    if (moreBtn) moreBtn.addEventListener('click', appendMoreMediaGroups);
}

function appendMoreMediaGroups() {
    visibleMediaPage++;
    const startIdx = (visibleMediaPage - 1) * GROUPS_PAGE_SIZE;
    const endIdx = visibleMediaPage * GROUPS_PAGE_SIZE;
    const slice = mediaFilteredGroups.slice(startIdx, endIdx);

    document.getElementById('btn-show-more-media')?.remove();

    let html = slice.map(([folder, items], i) => {
        const gIdx = startIdx + i;
        const isOpen = allFoldersExpanded || expandedFolders.has(folder);
        return renderMediaFolderGroup(folder, items, gIdx, isOpen);
    }).join('');

    if (mediaFilteredGroups.length > endIdx) {
        const remaining = mediaFilteredGroups.length - endIdx;
        const next = Math.min(remaining, GROUPS_PAGE_SIZE);
        html += `<button type="button" class="show-more-btn btn-secondary" id="btn-show-more-media">
            <i class="ph ph-arrow-down"></i> Mostrar mais ${next} pasta(s) (${remaining} restantes)
        </button>`;
    }

    const container = document.getElementById('media-folder-groups');
    container.insertAdjacentHTML('beforeend', html);

    const moreBtn = document.getElementById('btn-show-more-media');
    if (moreBtn) moreBtn.addEventListener('click', appendMoreMediaGroups);
}

function renderMediaFolderGroup(folder, items, gIdx, isOpen) {
    const folderShort = escapeHtml(shortFolder(folder));
    const folderFull = escapeHtml(folder);
    const src = items[0]?.source_folder ? escapeHtml(items[0].source_folder) : '';
    const contentHtml = isOpen ? renderMediaRows(items) : '';
    return `
        <div class="folder-group ${isOpen ? 'open' : ''}" data-folder-idx="${gIdx}" data-folder-kind="media">
            <div class="folder-header" data-folder-idx="${gIdx}" data-folder-kind="media" role="button">
                <i class="ph ph-caret-right folder-caret"></i>
                <i class="ph ph-folder folder-icon"></i>
                <span class="folder-name path-cell" data-fullpath="${folderFull}" title="Clique para ver / copiar">${folderShort}</span>
                ${src ? `<span class="badge badge-source">${src}</span>` : ''}
                <span class="folder-count">${items.length}</span>
            </div>
            <div class="folder-content" data-filled="${isOpen ? '1' : '0'}">${contentHtml}</div>
        </div>
    `;
}

function renderMediaRows(items) {
    const CAP = 200;
    const rowsHtml = items.slice(0, CAP).map(f => {
        const name = escapeHtml(f.name || '—');
        const path = escapeHtml(f.path || '—');
        return `<tr>
            <td>${name}</td>
            <td class="path-cell" data-fullpath="${path}">${path}</td>
        </tr>`;
    }).join('');
    const truncated = items.length > CAP
        ? `<tr><td colspan="2" class="folder-truncated">…e mais ${items.length - CAP} arquivo(s) nesta pasta.</td></tr>`
        : '';
    return `<div class="table-wrapper folder-table">
        <table class="files-table">
            <thead><tr><th>Arquivo</th><th>Caminho</th></tr></thead>
            <tbody>${rowsHtml}${truncated}</tbody>
        </table>
    </div>`;
}

function escapeHtml(str) {
    return String(str)
        .replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;')
        .replace(/"/g, '&quot;').replace(/'/g, '&#039;');
}
