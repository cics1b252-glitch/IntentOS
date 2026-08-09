import { ThemeEngine } from '../../ids/theme/index.js';
import { runRecoverable } from './recovery.js';
import { formatTimestamp } from './timestamps.js';

const root = document.getElementById('intent-shell');
const APP_VERSION = '0.4.4-alpha';
const PROTOCOL_VERSION = '1.0';
const themeEngine = new ThemeEngine();
themeEngine.load();
const pending = new Map();
let state = null;
let onboardingStep = 1;
let settingsOpen = false;
let settingsSection = 'general';
let busy = false;
let lastError = '';
let lastDiagnostics = null;
let lastFailedMessage = '';
let lastFailureDiagnostic = '';
let lastCorrelationId = '';
let lastMissionId = '';

const hasHost = Boolean(globalThis.chrome?.webview);
const text = (value = '') => String(value).replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));

function request(action, payload = {}) {
  if (!hasHost) return browserFallback(action, payload);
  const requestId = crypto.randomUUID();
  return new Promise((resolve, reject) => {
    pending.set(requestId, {resolve, reject});
    globalThis.chrome.webview.postMessage({requestId, action, uiVersion:APP_VERSION, protocolVersion:PROTOCOL_VERSION, ...payload});
    setTimeout(() => {
      if (pending.delete(requestId)) {
        const error = new Error('A operação demorou mais que o esperado. Você pode tentar novamente.');
        error.code = 'bridge_timeout';
        reject(error);
      }
    }, 65000);
  });
}

globalThis.chrome?.webview?.addEventListener('message', event => {
  if (event.data?.event === 'startup_state') {
    if (state) {
      state.startupState = event.data.state;
      if (event.data.state === 'ready') { state.bridgeState = 'ready'; state.bridgeReady = true; }
      if (event.data.state === 'degraded' || event.data.state === 'failed') {
        state.bridgeState = event.data.state; state.bridgeReady = false; busy = false;
        lastError = 'O núcleo não ficou disponível. Você pode tentar novamente.';
      }
      render();
    }
    return;
  }
  const item = pending.get(event.data.requestId);
  if (!item) return;
  pending.delete(event.data.requestId);
  item.resolve(event.data.result);
});

function browserFallback(action) {
  if (action === 'get_state') return Promise.resolve({onboardingComplete:false,mode:'real',locale:'pt-BR',provider:'',providerStatus:'não configurado',bridgeState:'ready',bridgeReady:true,history:[],dataPath:'%LOCALAPPDATA%/IntentOS/Data',theme:'system',ambient:'neutral',density:'comfortable',reducedMotion:false});
  return Promise.resolve({ok:false,error:'Abra o aplicativo Windows para usar esta função.'});
}

async function boot() {
  state = await request('get_state');
  if (state?.ok === false) throw new Error(state.error || 'A interface não é compatível com o núcleo instalado.');
  applyPreferences();
  render();
}

function applyPreferences() {
  themeEngine.set({appearance:state.theme || 'system',ambient:state.ambient || 'neutral',density:state.density || 'comfortable',motion:state.reducedMotion ? 'reduced' : 'full'});
  document.documentElement.lang = state.locale || 'pt-BR';
}

function render() {
  root.innerHTML = `<main class="product-shell">
    ${state.mode === 'demo' ? '<div class="demo-banner">Modo demonstração — nenhuma IA real está conectada. <button class="product-button" data-action="exit-demo">Sair da demonstração</button></div>' : ''}
    <header class="product-header"><span class="product-brand">Intent OS</span><span class="status-dot" data-ready="${state.bridgeState === 'ready'}"></span><span class="status-label">Núcleo: ${text(bridgeLabel(state.bridgeState))}</span><span class="product-header__spacer"></span><button class="product-button" data-action="settings">Configurações</button></header>
    ${conversationView()}
    ${!state.onboardingComplete ? onboardingView() : ''}
    ${settingsOpen ? settingsView() : ''}
  </main>`;
  bind();
  root.querySelector('.conversation-history')?.scrollTo({top:999999});
}

function conversationView() {
  const history = state.history || [];
  const bridgeReady = state.bridgeState === 'ready' || state.mode === 'demo';
  const content = history.length ? history.map(item => `<article class="message message--${(item.role || item.Role) === 'user' ? 'user' : 'assistant'}">${text(item.content ?? item.Content ?? '')}<small>${(item.provider || item.Provider) ? `${text(providerLabel(item.provider || item.Provider))} · ` : ''}${formatTimestamp(item.timestamp ?? item.Timestamp)}</small></article>`).join('') : `<section class="empty-state"><h1>Como posso ajudar?</h1><p>${state.providerStatus === 'conectado' ? 'Sua conexão está pronta. Escreva naturalmente o que deseja fazer.' : 'Conecte um Provider nas Configurações ou explore a demonstração.'}</p></section>`;
  const unavailable = !bridgeReady ? 'Não foi possível iniciar o núcleo do Intent OS.' : '';
  const recovery = !busy && (lastError || !bridgeReady) ? `<div class="actions recovery-actions"><button class="product-button" type="button" data-action="retry-message" ${lastFailedMessage && bridgeReady ? '' : 'disabled'}>Tentar novamente</button><button class="product-button" type="button" data-action="restart-core">Reiniciar núcleo</button><button class="product-button" type="button" data-action="copy-failure-diagnostic">Copiar diagnóstico</button><button class="product-button" type="button" data-action="open-diagnostics">Abrir diagnóstico</button></div>` : '';
  return `<section class="conversation" aria-label="Conversa"><div class="conversation-history" aria-live="polite">${content}</div><form class="composer"><div class="execution" role="status">${busy ? 'Processando sua solicitação…' : text(lastError || unavailable)}</div>${recovery}<div class="composer-row"><textarea class="chat-input" aria-label="Mensagem" placeholder="${bridgeReady ? 'Escreva sua mensagem…' : 'Aguardando o núcleo…'}" ${busy || !bridgeReady ? 'disabled' : ''}></textarea><button class="product-button product-button--primary" type="submit" ${busy || !bridgeReady ? 'disabled' : ''}>Enviar</button></div></form></section>`;
}

function onboardingView() {
  const steps = [welcomeStep,dataStep,providerStep,preferencesStep,completeStep];
  return `<div class="overlay"><section class="onboarding" aria-modal="true" role="dialog"><div class="panel-body"><div class="step">Etapa ${onboardingStep} de 5</div>${steps[onboardingStep-1]()}</div></section></div>`;
}
const welcomeStep = () => `<h1>Bem-vindo ao Intent OS</h1><p>Vamos preparar o sistema para trabalhar com você.</p><div class="actions"><button class="product-button" data-action="quit">Sair</button><button class="product-button" data-action="demo">Explorar demonstração</button><button class="product-button product-button--primary" data-action="next">Configurar agora</button></div>`;
const dataStep = () => `<h1>Seus dados continuam sob seu controle</h1><p>Configurações e histórico ficam neste computador. Nenhuma conta externa será conectada sem sua autorização.</p><div class="notice">Local: ${text(state.dataPath)}</div>${nextBack()}`;
const providerStep = () => `<h1>Escolha uma inteligência</h1><div class="provider-choice"><div class="provider-card"><h2>OpenAI</h2><p>Conexão real por chave oficial da API.</p><label class="field">Chave OpenAI<input id="openai-key" type="password" autocomplete="off" placeholder="sk-…"></label><button class="product-button" data-action="connect-openai">Conectar e testar</button></div><div class="provider-card"><h2>Google Gemini</h2><p>Conexão real por chave oficial da Gemini API.</p><label class="field">Chave Gemini<input id="gemini-key" type="password" autocomplete="off"></label><button class="product-button" data-action="connect-gemini">Conectar e testar</button><small>O nível gratuito possui limites por projeto. Conforme a política do Google, o conteúdo do nível gratuito pode ser usado para melhorar produtos.</small></div><div class="provider-card"><h2>Demonstração</h2><p>Sem IA conectada.</p><button class="product-button" data-action="demo">Usar demonstração</button></div></div><p class="error">${text(lastError)}</p>${nextBack(state.providerStatus === 'conectado' || state.mode === 'demo')}`;
const preferencesStep = () => `<h1>Preferências básicas</h1>${preferenceFields()}${nextBack()}`;
const completeStep = () => `<h1>Pronto para começar</h1><p>Armazenamento local pronto. Configuração preservada. ${state.providerStatus === 'conectado' ? `${text(providerLabel(state.provider))} conectado e validado.` : 'Modo demonstração selecionado.'}</p><div class="actions"><button class="product-button" data-action="back">Voltar</button><button class="product-button product-button--primary" data-action="finish">Abrir conversa</button></div>`;
const nextBack = (enabled = true) => `<div class="actions"><button class="product-button" data-action="back">Voltar</button><button class="product-button product-button--primary" data-action="next" ${enabled ? '' : 'disabled'}>Continuar</button></div>`;

const selected = (value, current) => value === current ? 'selected' : '';
function preferenceFields() { return `<label class="field">Idioma<select id="pref-locale"><option value="pt-BR" ${selected('pt-BR',state.locale)}>Português (Brasil)</option><option value="en-US" ${selected('en-US',state.locale)}>English (preparação)</option></select></label><label class="field">Aparência<select id="pref-theme"><option value="system" ${selected('system',state.theme)}>Usar o sistema</option><option value="light" ${selected('light',state.theme)}>Clara</option><option value="dark" ${selected('dark',state.theme)}>Escura</option></select></label><label class="field">Ambiente visual<select id="pref-ambient"><option value="neutral" ${selected('neutral',state.ambient)}>Calmo</option><option value="lavender" ${selected('lavender',state.ambient)}>Lavanda</option><option value="steel" ${selected('steel',state.ambient)}>Foco</option></select></label><label class="field">Densidade<select id="pref-density"><option value="comfortable" ${selected('comfortable',state.density)}>Confortável</option><option value="compact" ${selected('compact',state.density)}>Compacta</option></select></label><label><input id="pref-motion" type="checkbox" ${state.reducedMotion ? 'checked' : ''}> Reduzir movimento</label>`; }

function settingsView() {
  const labels = {general:'Geral',appearance:'Aparência',providers:'Providers de IA',accounts:'Contas e nuvens',privacy:'Dados e privacidade',diagnostics:'Diagnóstico',about:'Sobre'};
  return `<div class="overlay"><section class="settings" role="dialog" aria-modal="true"><div class="settings-layout"><nav class="settings-nav">${Object.entries(labels).map(([id,label]) => `<button class="product-button" data-section="${id}">${label}</button>`).join('')}</nav><div class="settings-content"><button class="product-button" data-action="close-settings">Fechar</button>${settingsContent()}</div></div></section></div>`;
}
function settingsContent() {
  if (settingsSection === 'providers') return `<h1>Providers de IA</h1>${providerSettings('openai')}${providerSettings('gemini')}<label><input id="allow-fallback" type="checkbox" ${state.allowFallback ? 'checked' : ''}> Autorizar fallback para o outro Provider quando o padrão falhar</label><div class="actions"><button class="product-button" data-action="save-fallback">Salvar autorização de fallback</button></div><p class="notice">Gemini gratuito: limites variam por projeto e o conteúdo pode ser usado pelo Google para melhorar produtos. O histórico do Intent OS permanece local e independente do Provider.</p><p>Último teste: ${text(state.lastProviderTest || 'ainda não realizado')}</p>`;
  if (settingsSection === 'appearance') return `<h1>Aparência</h1>${preferenceFields()}<div class="actions"><button class="product-button product-button--primary" data-action="save-preferences">Salvar</button></div>`;
  if (settingsSection === 'accounts') return `<h1>Contas e armazenamento</h1><p>E-mail, calendário, contatos, OneDrive, Google Drive, Dropbox e Mega: <strong>Em preparação</strong>.</p><p>O Intent OS nunca solicitará diretamente a senha do seu e-mail.</p>`;
  if (settingsSection === 'privacy') return `<h1>Dados e privacidade</h1><p>Dados locais: ${text(state.dataPath)}</p><button class="product-button" data-action="clear-history">Limpar histórico de conversa</button>`;
  if (settingsSection === 'diagnostics') return `<h1>Diagnóstico</h1><div class="actions"><button class="product-button" data-action="load-diagnostics">Atualizar diagnóstico</button><button class="product-button" data-action="copy-diagnostics" ${lastDiagnostics ? '' : 'disabled'}>Copiar diagnóstico</button></div><pre class="diagnostic" id="diagnostic-output">${lastDiagnostics ? text(JSON.stringify(lastDiagnostics,null,2)) : 'Nenhum segredo será incluído.'}</pre>`;
  if (settingsSection === 'about') return '<h1>Sobre</h1><p>Intent OS Product Alpha 2.1.4 — versão 0.4.4-alpha.</p>';
  return `<h1>Geral</h1><p>Idioma: ${text(state.locale)}</p><p>Modo: ${text(state.mode)}</p><p>Provider: ${text(state.provider || 'não configurado')}</p>`;
}

const providerLabel = provider => provider === 'gemini' ? 'Google Gemini' : provider === 'openai' ? 'OpenAI' : provider;
const bridgeLabel = value => ({not_started:'não iniciado',starting:'iniciando',ready:'pronto',busy:'ocupado',degraded:'degradado',restarting:'reiniciando',unavailable:'indisponível',stopped:'parado',failed:'falhou'}[value] || value || 'desconhecido');
const providerStatus = provider => state.providerStates?.[provider] || 'não configurado';
function providerSettings(provider) { const label=providerLabel(provider); return `<section class="provider-card"><h2>${label}${state.provider === provider ? ' · padrão' : ''}</h2><p>Estado: <strong>${text(providerStatus(provider))}</strong></p><label class="field">Chave ${label}<input id="settings-${provider}-key" type="password" autocomplete="off"></label><div class="actions"><button class="product-button" data-action="disconnect-${provider}">Remover</button><button class="product-button" data-action="test-${provider}">Testar</button><button class="product-button" data-action="default-${provider}">Usar como padrão</button><button class="product-button product-button--primary" data-action="settings-connect-${provider}">Conectar</button></div></section>`; }

function bind() {
  root.querySelector('.composer')?.addEventListener('submit', sendMessage);
  root.querySelectorAll('[data-action]').forEach(button => button.addEventListener('click', () => act(button.dataset.action)));
  root.querySelectorAll('[data-section]').forEach(button => button.addEventListener('click', () => { settingsSection=button.dataset.section; render(); }));
}

async function act(action) {
  lastError = '';
  if (action === 'next') { savePreferenceDraft(); onboardingStep=Math.min(5,onboardingStep+1); render(); return; }
  if (action === 'back') { onboardingStep=Math.max(1,onboardingStep-1); render(); return; }
  if (action === 'quit') { globalThis.close(); return; }
  if (action === 'settings') { settingsOpen=true; render(); return; }
  if (action === 'close-settings') { settingsOpen=false; render(); return; }
  if (action === 'demo') { const r=await request('explore_demo'); state=r.state || {...state,mode:'demo'}; if(!state.onboardingComplete){onboardingStep=4;} applyPreferences(); render(); return; }
  if (action === 'exit-demo') { const r=await request('exit_demo'); state=r.state; render(); return; }
  if (action === 'connect-openai' || action === 'connect-gemini') { const provider=action.split('-')[1]; await connect(provider,document.getElementById(`${provider}-key`)?.value); return; }
  if (action.startsWith('settings-connect-')) { const provider=action.replace('settings-connect-',''); await connect(provider,document.getElementById(`settings-${provider}-key`)?.value); return; }
  if (action === 'finish') { savePreferenceDraft(); const r=await request('complete_onboarding',{preferences:preferences()}); state=r.state; applyPreferences(); render(); return; }
  if (action === 'save-preferences') { const r=await request('save_preferences',{preferences:preferences()}); state=r.state; applyPreferences(); render(); return; }
  if (action.startsWith('test-')) { const provider=action.replace('test-',''); busy=true; render(); const r=await request('test_provider',{provider}); busy=false; state=r.state || state; lastError=r.error || ''; render(); return; }
  if (action.startsWith('disconnect-')) { const provider=action.replace('disconnect-',''); const r=await request('disconnect_provider',{provider}); state=r.state; render(); return; }
  if (action.startsWith('default-')) { const provider=action.replace('default-',''); const r=await request('set_default_provider',{provider}); state=r.state || state; lastError=r.error || ''; render(); return; }
  if (action === 'save-fallback') { const allowFallback=document.getElementById('allow-fallback')?.checked === true; const r=await request('set_fallback',{allowFallback}); state=r.state; render(); return; }
  if (action === 'clear-history') { if(confirm('Apagar todo o histórico local de conversa?')){const r=await request('clear_history'); state=r.state; render();} return; }
  if (action === 'load-diagnostics') { lastDiagnostics=await request('diagnostics'); render(); return; }
  if (action === 'copy-diagnostics') { if(lastDiagnostics){await navigator.clipboard.writeText(JSON.stringify(lastDiagnostics,null,2)); lastError='Diagnóstico copiado.'; render();} return; }
  if (action === 'retry-message') { if(lastFailedMessage) await submitMessage(lastFailedMessage); return; }
  if (action === 'copy-failure-diagnostic') {
    const diagnostic = lastFailureDiagnostic || JSON.stringify({code:'bridge_failure',message:lastError,version:APP_VERSION,bridgeState:state.bridgeState});
    await navigator.clipboard.writeText(diagnostic);
    lastError='Diagnóstico copiado.'; render(); return;
  }
  if (action === 'restart-core') {
    busy=true; lastError='Reiniciando o núcleo…'; render();
    try { const r=await request('restart_bridge'); state=r.state || state; lastError=r.ok ? '' : r.error; }
    catch(error) { lastError=error.message || 'Não foi possível iniciar o núcleo do Intent OS.'; }
    finally { busy=false; render(); }
    return;
  }
  if (action === 'open-diagnostics') { await request('open_diagnostics'); return; }
}

async function connect(provider,apiKey) {
  busy=true; lastError='Conectando e validando…'; render();
  try { const r=await request('connect_provider',{provider,apiKey}); state=r.state || state; lastError=r.error || ''; }
  catch(error) { lastError=error.message || 'A conexão local foi interrompida.'; lastFailureDiagnostic=`${error.code || 'bridge_failure'}/connect`; }
  finally { busy=false; render(); }
}
async function sendMessage(event) {
  event.preventDefault(); const input=root.querySelector('.chat-input'); const message=input?.value.trim();
  if(!message)return; await submitMessage(message);
}
async function submitMessage(message) {
  const correlationId = lastCorrelationId || crypto.randomUUID();
  await runRecoverable(() => request('chat',{message,correlationId,resumeMissionId:lastMissionId || null}), {
    onStart: () => { busy=true; lastError=''; lastFailedMessage=message; lastFailureDiagnostic=''; lastCorrelationId=correlationId; render(); },
    onResult: r => {
      if(r.ok){
        state=r.state;lastError='';lastFailedMessage='';
        if(r.status === 'waiting_context' || r.dialogue_state === 'WAITING_CONTEXT'){
          lastMissionId=r.mission_id || r.missionId || lastMissionId;
        } else {
          lastMissionId='';
        }
        lastCorrelationId='';lastDiagnostics=r.trace || lastDiagnostics;queueMicrotask(()=>request('ui_response_rendered',{correlationId,success:true}).catch(()=>{}));
      }
      else {lastError=r.error || 'Não foi possível responder.';lastMissionId=r.missionId || lastMissionId;lastFailureDiagnostic=JSON.stringify(r.diagnostic || {errorCode:r.errorCode,correlationId});lastDiagnostics=r.diagnostic || lastDiagnostics;queueMicrotask(()=>request('ui_response_rendered',{correlationId,success:false}).catch(()=>{}));}
    },
    onError: error => {
      lastError=error.message || 'A conexão local foi interrompida. Você pode tentar novamente.';
      lastFailureDiagnostic=`${error.code || 'bridge_failure'}/conversation`;
    },
    onFinally: () => { busy=false; render(); },
  });
}
function preferences(){return {locale:document.getElementById('pref-locale')?.value||state.locale,theme:document.getElementById('pref-theme')?.value||state.theme,ambient:document.getElementById('pref-ambient')?.value||state.ambient,density:document.getElementById('pref-density')?.value||state.density,reducedMotion:document.getElementById('pref-motion')?.checked??state.reducedMotion};}
function savePreferenceDraft(){Object.assign(state,preferences());applyPreferences();}

boot().catch(error => { root.innerHTML=`<main class="empty-state"><h1>O Intent OS não pôde iniciar</h1><p>${text(error.message)}</p></main>`; });
