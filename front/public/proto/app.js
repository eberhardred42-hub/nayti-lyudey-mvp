/* Proto UI helper: safe API + auth state */
const API_BASE = "/api";
const LS = {
  token: "nl_token",
  role: "nl_role",
  phone: "nl_phone",
  userId: "nl_user_id",
};

const ADMIN_PHONES = ["89062592834"]; // временно: список админов (UI-логика)

function qs(sel, root = document){ return root.querySelector(sel); }
function qsa(sel, root = document){ return Array.from(root.querySelectorAll(sel)); }

function onlyDigits(s){ return (s || "").replace(/\D/g, ""); }
function normalizePhone(raw){
  let d = onlyDigits(raw);
  if (!d) return "";
  // 8xxxxxxxxxx -> 7xxxxxxxxxx
  if (d.length === 11 && d.startsWith("8")) d = "7" + d.slice(1);
  // +7 already becomes 7xxxxxxxxxx via digits
  return d;
}

function toast(msg, isErr=false){
  const el = qs("#toast");
  if(!el) return;
  el.classList.toggle("err", !!isErr);
  qs("#toastText").textContent = msg;
  el.classList.add("show");
  clearTimeout(el._t);
  el._t = setTimeout(()=>el.classList.remove("show"), 2600);
}

function isAdminPhone(phoneRaw){
  const d = onlyDigits(phoneRaw);
  if(!d) return false;
  if(ADMIN_PHONES.includes(d)) return true;
  if(d.length === 11 && d.startsWith("7")){
    const as8 = "8" + d.slice(1);
    return ADMIN_PHONES.includes(as8);
  }
  return false;
}

function getAuth(){
  return {
    token: localStorage.getItem(LS.token) || "",
    role: localStorage.getItem(LS.role) || "user",
    phone: localStorage.getItem(LS.phone) || "",
    userId: localStorage.getItem(LS.userId) || "",
  };
}
function setAuth({token, role, phone, userId}){
  if(token) localStorage.setItem(LS.token, token);
  if(role) localStorage.setItem(LS.role, role);
  if(phone) localStorage.setItem(LS.phone, phone);
  if(userId) localStorage.setItem(LS.userId, userId);
}
function clearAuth(){
  Object.values(LS).forEach(k => localStorage.removeItem(k));
}

async function fetchJSON(path, {method="GET", body, headers={}, timeoutMs=12000} = {}){
  const controller = new AbortController();
  const t = setTimeout(()=>controller.abort(), timeoutMs);

  const auth = getAuth();
  const h = {
    "Content-Type": "application/json",
    ...headers,
  };
  if(auth.token) h["Authorization"] = `Bearer ${auth.token}`;

  try{
    const res = await fetch(`${API_BASE}${path}`, {
      method,
      headers: h,
      body: body ? JSON.stringify(body) : undefined,
      signal: controller.signal,
    });
    const ct = res.headers.get("content-type") || "";
    let data = null;
    if(ct.includes("application/json")) data = await res.json().catch(()=>null);
    else data = await res.text().catch(()=>null);

    return { ok: res.ok, status: res.status, data };
  } catch(e){
    return { ok:false, status:0, data:{ error: String(e) } };
  } finally {
    clearTimeout(t);
  }
}

/* ===== Login modal flow ===== */
function openModal(id){ qs(id)?.classList.add("open"); }
function closeModal(id){ qs(id)?.classList.remove("open"); }

function bindGlobalUI(){
  // top-right buttons
  qsa("[data-open-login]").forEach(btn => {
    btn.addEventListener("click", ()=> openLogin());
  });
  qsa("[data-open-help]").forEach(btn => {
    toast("Обучение появится позже");
  });

  // close modals
  qsa("[data-close]").forEach(btn=>{
    btn.addEventListener("click", ()=> closeModal(btn.getAttribute("data-close")));
  });

  // Escape closes
  document.addEventListener("keydown",(e)=>{
    if(e.key === "Escape"){
      qsa(".modalOverlay.open").forEach(m => m.classList.remove("open"));
    }
  });

  renderAuthBadges();
}

function renderAuthBadges(){
  const a = getAuth();
  qsa("[data-auth-badge]").forEach(el=>{
    if(a.token){
      el.textContent = a.role === "admin" ? "Админ" : "Вход выполнен";
    } else {
      el.textContent = "Гость";
    }
  });
  qsa("[data-admin-link]").forEach(el=>{
    el.style.display = (a.role === "admin") ? "inline-flex" : "none";
  });
  qsa("[data-logout]").forEach(el=>{
    el.style.display = a.token ? "inline-flex" : "none";
    el.addEventListener("click", ()=>{
      clearAuth();
      toast("Вы вышли");
      renderAuthBadges();
    });
  });

  // Show phone on account page, if any
  const phoneEl = qs("#mePhone");
  const roleEl = qs("#meRole");
  if(phoneEl) phoneEl.textContent = a.phone ? `+${a.phone}` : "—";
  if(roleEl) roleEl.textContent = a.role || "user";
}

function openLogin(){
  // reset steps
  qs("#loginStepPhone").style.display = "grid";
  qs("#loginStepCode").style.display = "none";
  qs("#loginStepAdminAsk").style.display = "none";
  qs("#loginStepAdminCode").style.display = "none";

  qs("#loginPhone").value = getAuth().phone ? `+${getAuth().phone}` : "";
  qs("#loginCode").value = "";
  qs("#adminCode").value = "";

  openModal("#modalLogin");
}

function switchToCodeStep(phoneNorm){
  qs("#loginStepPhone").style.display = "none";
  qs("#loginStepCode").style.display = "grid";
  qs("#loginPhoneEcho").textContent = `+${phoneNorm}`;
}

function switchToAdminAsk(){
  qs("#loginStepCode").style.display = "none";
  qs("#loginStepAdminAsk").style.display = "grid";
}
function switchToAdminCode(){
  qs("#loginStepAdminAsk").style.display = "none";
  qs("#loginStepAdminCode").style.display = "grid";
}

async function doLogin(phoneRaw, code){
  const phoneNorm = normalizePhone(phoneRaw);
  if(!phoneNorm){ toast("Введите телефон", true); return {ok:false}; }
  if(!code || String(code).length < 4){ toast("Введите код", true); return {ok:false}; }

  const r = await fetchJSON("/sessions", { method:"POST", body:{ phone: phoneRaw, code: String(code) } });

  // контракт может быть разный — пытаемся вытащить токен/роль максимально мягко
  if(!r.ok){
    toast("Пока не подключено (ошибка API)", true);
    return {ok:false, r};
  }

  const data = r.data || {};
  const token = data.token || data.access_token || "";
  const role = data.role || (data.ok && data.role) || "user";
  const userId = data.user_id || data.userId || "";

  // даже если токена нет — сохраняем phone/role, чтобы UI не рушился
  setAuth({ token, role, phone: phoneNorm, userId });
  renderAuthBadges();
  return {ok:true, role, token, userId, raw:data};
}

function setupLoginHandlers(){
  const btnSend = qs("#btnSendCode");
  const btnLogin = qs("#btnLogin");
  const btnAdminYes = qs("#btnAdminYes");
  const btnAdminNo = qs("#btnAdminNo");
  const btnAdminLogin = qs("#btnAdminLogin");

  btnSend?.addEventListener("click", ()=>{
    const phoneNorm = normalizePhone(qs("#loginPhone").value);
    if(!phoneNorm){ toast("Введите телефон", true); return; }
    // Здесь будет реальная SMS интеграция позже.
    // Сейчас просто переходим на шаг ввода кода.
    toast("Код отправлен (если SMS подключена)");
    switchToCodeStep(phoneNorm);
  });

  btnLogin?.addEventListener("click", async ()=>{
    const phone = qs("#loginPhone").value;
    const code = qs("#loginCode").value;

    const res = await doLogin(phone, code);
    if(!res.ok) return;

    // admin flow (UI): если телефон админский — спросить
    if(isAdminPhone(phone)){
      switchToAdminAsk();
    } else {
      closeModal("#modalLogin");
      toast("Вход выполнен");
      maybeRouteAfterLogin();
    }
  });

  btnAdminNo?.addEventListener("click", ()=>{
    closeModal("#modalLogin");
    toast("Вошли как пользователь");
    maybeRouteAfterLogin();
  });

  btnAdminYes?.addEventListener("click", ()=>{
    switchToAdminCode();
  });

  btnAdminLogin?.addEventListener("click", async ()=>{
    const phone = qs("#loginPhone").value;
    const code = qs("#adminCode").value;

    const res = await doLogin(phone, code); // ожидаем, что админ-код даст admin
    if(!res.ok) return;

    // если бэк не вернул роль admin — всё равно не падаем
    if(getAuth().role !== "admin"){
      toast("Пока не подключено", true);
      // остаёмся как user
      setAuth({ role: "user" });
    } else {
      toast("Админ-вход выполнен");
    }

    closeModal("#modalLogin");
    maybeRouteAfterLogin();
  });
}

function maybeRouteAfterLogin(){
  // Если есть кнопка "Админка" и роль admin — покажем в UI (без автопрыжка).
  renderAuthBadges();
}

/* ===== Proto: search + docs ===== */
async function runSearch(query){
  // предполагаемый endpoint; если его нет — gracefully fallback
  const r = await fetchJSON("/search", { method:"POST", body:{ query } });
  if(!r.ok) return null;
  return r.data;
}

function saveDocLocal(doc){
  const key = "nl_docs";
  const arr = JSON.parse(localStorage.getItem(key) || "[]");
  arr.unshift({ ...doc, saved_at: new Date().toISOString() });
  localStorage.setItem(key, JSON.stringify(arr.slice(0,50)));
}

function getDocsLocal(){
  return JSON.parse(localStorage.getItem("nl_docs") || "[]");
}

function bindHome(){
  const btn = qs("#btnFind");
  const inp = qs("#q");
  btn?.addEventListener("click", async ()=>{
    const q = (inp.value || "").trim();
    if(!q){ toast("Введите запрос", true); return; }
    localStorage.setItem("nl_last_query", q);
    toast("Открываю чат…");
    location.href = "/proto/chat.html";
  });
}

function bindChat(){
  const log = qs("#chatLog");
  const ta = qs("#chatText");
  const send = qs("#btnSendMsg");

  const lastQ = localStorage.getItem("nl_last_query") || "Найти людей…";
  qs("#chatTopic").textContent = lastQ;

  function addMsg(text, who="system"){
    const el = document.createElement("div");
    el.className = "msg " + (who==="me" ? "me" : "");
    const meta = document.createElement("div");
    meta.className = "mmeta";
    meta.textContent = who==="me" ? "Вы" : "Система";
    const body = document.createElement("div");
    body.textContent = text;
    el.appendChild(meta);
    el.appendChild(body);
    log.appendChild(el);
    log.scrollTop = log.scrollHeight;
  }

  addMsg("Опиши, кого ты ищешь: роль, навыки, город, бюджет. Я соберу документы и вопросы.", "system");

  async function onSend(){
    const text = (ta.value || "").trim();
    if(!text) return;
    ta.value = "";
    addMsg(text, "me");

    // Пытаемся дернуть реальный API, если он уже есть.
    const api = await runSearch(text);

    if(!api){
      addMsg("Пока не подключено к реальному LLM/поиску. Я сохранил запрос. На следующем этапе подключим OpenRouter и генерацию документов.", "system");
      // Сохраним “черновик документа” локально
      saveDocLocal({ id: "draft-" + Date.now(), title: "Черновик запроса", kind: "draft", content: text });
      return;
    }

    // Если API вернул документы — покажем кратко и сохраним.
    if(api.documents && Array.isArray(api.documents)){
      addMsg(`Готово. Сгенерировано документов: ${api.documents.length}. Открой «Документы».`, "system");
      api.documents.forEach(d => saveDocLocal({
        id: d.id || ("doc-" + Math.random().toString(16).slice(2)),
        title: d.title || "Документ",
        kind: d.kind || "doc",
        content: d.content || JSON.stringify(d, null, 2),
      }));
      return;
    }

    addMsg("Ответ получен, но формат пока не стандартизирован. Сохранил как документ.", "system");
    saveDocLocal({ id: "api-" + Date.now(), title: "Ответ системы", kind: "api", content: JSON.stringify(api, null, 2) });
  }

  send?.addEventListener("click", onSend);
  ta?.addEventListener("keydown", (e)=>{
    if(e.key==="Enter" && (e.ctrlKey || e.metaKey)){
      onSend();
    }
  });
}

function bindDocs(){
  const list = qs("#docsList");
  const docs = getDocsLocal();

  if(!docs.length){
    list.innerHTML = `
      <div class="item">
        <div class="meta">
          <div class="title">Пока пусто</div>
          <div class="desc">Сгенерируй что-нибудь в чате — документы появятся здесь.</div>
        </div>
        <span class="badge">—</span>
      </div>`;
    return;
  }

  list.innerHTML = "";
  docs.slice(0,20).forEach(d=>{
    const el = document.createElement("div");
    el.className = "item";
    el.innerHTML = `
      <div class="meta">
        <div class="title">${escapeHtml(d.title || "Документ")}</div>
        <div class="desc">${escapeHtml((d.kind||"").toUpperCase())} • ${new Date(d.saved_at).toLocaleString()}</div>
      </div>
      <a class="btn btnPrimary" href="/proto/doc.html?id=${encodeURIComponent(d.id)}">Открыть</a>
    `;
    list.appendChild(el);
  });
}

function bindDocView(){
  const id = new URLSearchParams(location.search).get("id");
  const titleEl = qs("#docTitle");
  const bodyEl = qs("#docBody");

  const docs = getDocsLocal();
  const doc = docs.find(d => d.id === id);

  if(!doc){
    titleEl.textContent = "Документ не найден";
    bodyEl.textContent = "Сначала сгенерируй документы в чате.";
    return;
  }

  titleEl.textContent = doc.title || "Документ";
  bodyEl.textContent = doc.content || "";
}

function bindAccount(){
  const docs = getDocsLocal();
  qs("#docsCount").textContent = String(docs.length);
}

function escapeHtml(s){
  return String(s || "")
    .replaceAll("&","&amp;")
    .replaceAll("<","&lt;")
    .replaceAll(">","&gt;")
    .replaceAll('"',"&quot;");
}

/* Boot */
document.addEventListener("DOMContentLoaded", ()=>{
  bindGlobalUI();
  setupLoginHandlers();

  const page = document.body.getAttribute("data-page");
  if(page==="home") bindHome();
  if(page==="chat") bindChat();
  if(page==="docs") bindDocs();
  if(page==="doc") bindDocView();
  if(page==="account") bindAccount();
});
