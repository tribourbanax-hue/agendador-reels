// Painel do cliente: lote de Reels/Stories + fila, por conta do Instagram
// O lote fica so no navegador ate clicar em "Agendar"; os videos ja sobem pro
// servidor assim que entram na lista (pra agendar ser instantaneo).

const $ = (s, el = document) => el.querySelector(s);
const $$ = (s, el = document) => [...el.querySelectorAll(s)];
const esc = (s) => String(s ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
const pad = (n) => String(n).padStart(2, "0");
const isoData = (d) => `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}`;
const DIAS = ["dom", "seg", "ter", "qua", "qui", "sex", "sáb"];
const STORY_MAX = 60, LEGENDA_MAX = 2200, HASHTAG_MAX = 30;

let tipoPadrao = null;
const seletorConta = $("#conta");
function lerPref(k) { try { return localStorage.getItem(k); } catch (_) { return null; } }
function salvarPref(k, v) { try { localStorage.setItem(k, v); } catch (_) {} }
const contaSalva = lerPref("conta");
if (contaSalva && [...seletorConta.options].some((o) => o.value === contaSalva)) seletorConta.value = contaSalva;
const contaId = () => Number(seletorConta.value);
function contaOk() { return seletorConta.selectedOptions[0]?.dataset.status === "ok"; }
function atualizarConta() {
  $("#aviso-conta").hidden = contaOk();
  salvarPref("conta", seletorConta.value);
  atualizarBarra(); carregarFila();
}
seletorConta.addEventListener("change", atualizarConta);
let lote = [];
let uidSeq = 0;

function toast(msg, ms = 3500) {
  const t = $("#toast");
  t.textContent = msg;
  t.hidden = false;
  clearTimeout(toast._t);
  toast._t = setTimeout(() => (t.hidden = true), ms);
}

async function api(url, opts = {}) {
  const r = await fetch(url, opts);
  if (r.status === 401) { location.href = "/entrar"; throw new Error("sessão expirou"); }
  let data = {};
  try { data = await r.json(); } catch (_) {}
  if (!r.ok) { const e = new Error(data.erro || `erro ${r.status}`); e.data = data; throw e; }
  return data;
}

// ------------------------------------------------------------ abas
$$(".aba").forEach((b) => b.addEventListener("click", () => abrirAba(b.dataset.aba)));
function abrirAba(nome) {
  $$(".aba").forEach((b) => b.classList.toggle("ativa", b.dataset.aba === nome));
  $("#aba-novo").hidden = nome !== "novo";
  $("#aba-fila").hidden = nome !== "fila";
  atualizarBarra();
  if (nome === "fila") carregarFila();
}

// ------------------------------------------------------------ passo 1
$$("#escolha-tipo button").forEach((b) => b.addEventListener("click", () => {
  tipoPadrao = b.dataset.tipo;
  $$("#escolha-tipo button").forEach((x) => x.classList.toggle("selecionado", x === b));
  $("#passo-videos").hidden = false;
  // muda o tipo dos que ainda nao foram mexidos um a um
  lote.forEach((i) => { if (!i.tipoManual) i.tipo = tipoPadrao; });
  renderLote();
}));

// ------------------------------------------------------------ passo 2: arquivos do PC
const zona = $("#zona-soltar");
$("#input-arquivos").addEventListener("change", (e) => { adicionarArquivos([...e.target.files]); e.target.value = ""; });
["dragenter", "dragover"].forEach((ev) => zona.addEventListener(ev, (e) => { e.preventDefault(); zona.classList.add("arrastando"); }));
["dragleave", "drop"].forEach((ev) => zona.addEventListener(ev, (e) => { e.preventDefault(); zona.classList.remove("arrastando"); }));
zona.addEventListener("drop", (e) => adicionarArquivos([...e.dataTransfer.files]));

function proximaDataPadrao() {
  const d = new Date(); d.setDate(d.getDate() + 1);
  return isoData(d);
}

function novoItem(extra) {
  return {
    uid: ++uidSeq, arquivoId: null, progresso: 0, duracao: null, erro: "", estado: "enviando",
    tipo: tipoPadrao || "reels", tipoManual: false, legenda: "", data: proximaDataPadrao(), hora: "09:00",
    ...extra,
  };
}

function adicionarArquivos(files) {
  const videos = files.filter((f) => /\.(mp4|mov|m4v)$/i.test(f.name) || f.type.startsWith("video/"));
  if (videos.length < files.length) toast("Alguns arquivos não são vídeo (mp4/mov) e ficaram de fora.");
  videos.forEach((f) => {
    const item = novoItem({ nome: f.name, origem: "upload", previa: URL.createObjectURL(f), arquivo: f });
    lote.push(item);
    lerDuracao(item.previa).then((d) => { item.duracao = d; atualizarItem(item); });
  });
  renderLote();
  filaUploads();
}

function lerDuracao(src) {
  return new Promise((res) => {
    const v = document.createElement("video");
    v.preload = "metadata"; v.muted = true;
    v.onloadedmetadata = () => res(isFinite(v.duration) ? Math.round(v.duration * 10) / 10 : null);
    v.onerror = () => res(null);
    v.src = src;
  });
}

let enviando = 0;
function filaUploads() {
  while (enviando < 2) {
    const item = lote.find((i) => i.estado === "enviando" && !i._subindo && i.arquivo);
    if (!item) break;
    enviando++; item._subindo = true;
    subir(item).finally(() => { enviando--; filaUploads(); });
  }
}

function subir(item) {
  return new Promise((resolve) => {
    const fd = new FormData();
    fd.append("arquivo", item.arquivo);
    if (item.duracao) fd.append("duracao", item.duracao);
    const xhr = new XMLHttpRequest();
    xhr.open("POST", "/api/upload");
    xhr.upload.onprogress = (e) => { if (e.lengthComputable) { item.progresso = e.loaded / e.total; atualizarItem(item); } };
    xhr.onload = () => {
      let data = {}; try { data = JSON.parse(xhr.responseText); } catch (_) {}
      if (xhr.status === 401) { location.href = "/entrar"; return; }
      if (xhr.status >= 400) { item.estado = "erro"; item.erro = data.erro || `falha no envio (${xhr.status})`; }
      else { item.estado = "ok"; item.arquivoId = data.id; item.arquivo = null; }
      atualizarItem(item); resolve();
    };
    xhr.onerror = () => { item.estado = "erro"; item.erro = "sem conexão: remova e tente de novo"; atualizarItem(item); resolve(); };
    xhr.send(fd);
  });
}

// ------------------------------------------------------------ passo 3: lista
function problemas(item) {
  const p = [];
  if (item.estado === "erro") p.push(item.erro);
  const temReels = item.tipo !== "story", temStory = item.tipo !== "reels";
  if (temStory && item.duracao && item.duracao > STORY_MAX + 0.5) p.push(`Story aceita até ${STORY_MAX}s (este tem ${Math.round(item.duracao)}s)`);
  if (temReels && item.duracao && item.duracao < 3) p.push("Reels precisa de pelo menos 3s");
  if (temReels && item.legenda.length > LEGENDA_MAX) p.push(`legenda passa de ${LEGENDA_MAX} caracteres`);
  if (temReels && (item.legenda.match(/#/g) || []).length > HASHTAG_MAX) p.push(`mais de ${HASHTAG_MAX} hashtags`);
  if (!item.data || !item.hora) p.push("falta data ou hora");
  else if (new Date(`${item.data}T${item.hora}`) < new Date()) p.push("data/hora já passou");
  return p;
}

function textoEstado(item) {
  if (item.estado === "enviando") return `enviando… ${Math.round(item.progresso * 100)}%`;
  const p = problemas(item);
  if (p.length) return "⚠ " + p.join(" · ");
  const d = new Date(`${item.data}T${item.hora}`);
  return `pronto · ${DIAS[d.getDay()]} ${pad(d.getDate())}/${pad(d.getMonth() + 1)} às ${item.hora}`;
}

function renderLote() {
  $("#passo-lote").hidden = !lote.length;
  const lista = $("#lista-lote");
  lista.innerHTML = lote.map((item, idx) => `
    <div class="item-lote" data-uid="${item.uid}">
      <div class="previa">
        ${item.previa ? `<video src="${item.previa}#t=0.5" muted playsinline preload="metadata"></video>`
                      : `<img src="${item.miniatura || ""}" alt="">`}
        <span class="ordem">${idx + 1}</span>
        <span class="dur">${item.duracao ? Math.round(item.duracao) + "s" : ""}</span>
        <div class="progresso" ${item.estado === "enviando" ? "" : "hidden"}><i style="width:${item.progresso * 100}%"></i></div>
      </div>
      <div class="item-corpo">
        <div class="item-cabeca">
          <div><div class="item-nome">${esc(item.nome)}</div><div class="item-estado"></div></div>
          <div class="item-acoes">
            <button type="button" data-acao="subir" title="subir na ordem" ${idx === 0 ? "disabled" : ""}>↑</button>
            <button type="button" data-acao="descer" title="descer na ordem" ${idx === lote.length - 1 ? "disabled" : ""}>↓</button>
            <button type="button" data-acao="remover" title="tirar do lote">×</button>
          </div>
        </div>
        <div class="tipo-toggle">
          ${["reels", "story", "ambos"].map((t) => `<button type="button" data-tipo="${t}" class="${item.tipo === t ? "sel" : ""}">${{ reels: "Reels", story: "Story", ambos: "Os dois" }[t]}</button>`).join("")}
        </div>
        <div class="linha-campos">
          <label>Data<input class="campo" type="date" data-campo="data" value="${item.data}"></label>
          <label>Hora<input class="campo" type="time" data-campo="hora" value="${item.hora}"></label>
        </div>
        <div class="grupo-legenda" ${item.tipo === "story" ? "hidden" : ""}>
          <label>Legenda do Reels<textarea class="campo" data-campo="legenda" rows="3">${esc(item.legenda)}</textarea></label>
          <div class="contagem-legenda"></div>
        </div>
      </div>
    </div>`).join("");
  lote.forEach(atualizarItem);
  atualizarBarra();
}

function atualizarItem(item) {
  const el = $(`.item-lote[data-uid="${item.uid}"]`);
  if (!el) return;
  const est = $(".item-estado", el);
  est.textContent = textoEstado(item);
  const ruim = item.estado !== "enviando" && problemas(item).length > 0;
  est.classList.toggle("erro", ruim);
  el.classList.toggle("com-erro", ruim);
  const barra = $(".progresso", el);
  barra.hidden = item.estado !== "enviando";
  $("i", barra).style.width = item.progresso * 100 + "%";
  $(".dur", el).textContent = item.duracao ? Math.round(item.duracao) + "s" : "";
  const n = item.legenda.length, h = (item.legenda.match(/#/g) || []).length;
  const cl = $(".contagem-legenda", el);
  cl.textContent = `${n}/${LEGENDA_MAX} · ${h} hashtag${h === 1 ? "" : "s"}`;
  cl.classList.toggle("ruim", n > LEGENDA_MAX || h > HASHTAG_MAX);
  atualizarBarra();
}

$("#lista-lote").addEventListener("input", (e) => {
  const el = e.target.closest(".item-lote"); if (!el) return;
  const item = lote.find((i) => i.uid == el.dataset.uid);
  const campo = e.target.dataset.campo;
  if (campo) { item[campo] = e.target.value; atualizarItem(item); }
});

$("#lista-lote").addEventListener("click", (e) => {
  const b = e.target.closest("button"); if (!b) return;
  const el = b.closest(".item-lote");
  const idx = lote.findIndex((i) => i.uid == el.dataset.uid);
  const item = lote[idx];
  if (b.dataset.tipo) { item.tipo = b.dataset.tipo; item.tipoManual = true; renderLote(); return; }
  if (b.dataset.acao === "remover") { lote.splice(idx, 1); renderLote(); return; }
  if (b.dataset.acao === "subir" && idx > 0) { [lote[idx - 1], lote[idx]] = [lote[idx], lote[idx - 1]]; renderLote(); }
  if (b.dataset.acao === "descer" && idx < lote.length - 1) { [lote[idx + 1], lote[idx]] = [lote[idx], lote[idx + 1]]; renderLote(); }
});

// ------------------------------------------------------------ ferramentas em massa
$("#m-inicio").value = proximaDataPadrao();
$("#m-ritmo").addEventListener("change", () => ($("#m-intervalo-grupo").hidden = $("#m-ritmo").value !== "horas"));

$("#m-aplicar-datas").addEventListener("click", () => {
  if (!lote.length) return;
  const [h, m] = $("#m-hora").value.split(":").map(Number);
  let d = new Date(`${$("#m-inicio").value}T00:00`);
  if (isNaN(d)) return toast("Escolha a data de início.");
  d.setHours(h, m, 0, 0);
  const ritmo = $("#m-ritmo").value, semDomingo = $("#m-pular-domingo").checked;
  const passo = Math.max(1, parseInt($("#m-intervalo").value) || 1);
  const ajustaDomingo = () => { while (semDomingo && d.getDay() === 0) d.setDate(d.getDate() + 1); };
  ajustaDomingo();
  lote.forEach((item, i) => {
    if (i > 0) {
      if (ritmo === "dia") d.setDate(d.getDate() + 1);
      else if (ritmo === "dias2") d.setDate(d.getDate() + 2);
      else if (ritmo === "horas") d.setHours(d.getHours() + passo);
      ajustaDomingo();
    }
    item.data = isoData(d); item.hora = `${pad(d.getHours())}:${pad(d.getMinutes())}`;
  });
  renderLote();
  const fim = new Date(`${lote.at(-1).data}T00:00`);
  toast(`Datas distribuídas: ${lote.length} vídeo(s) até ${pad(fim.getDate())}/${pad(fim.getMonth() + 1)}.`);
});

function aplicarLegenda(todas) {
  const txt = $("#m-legenda").value;
  if (!txt.trim()) return toast("Escreva a legenda primeiro.");
  let n = 0;
  lote.forEach((i) => { if (i.tipo !== "story" && (todas || !i.legenda.trim())) { i.legenda = txt; n++; } });
  renderLote();
  toast(n ? `Legenda aplicada em ${n} Reels.` : "Nenhum Reels para aplicar.");
}
$("#m-legenda-vazias").addEventListener("click", () => aplicarLegenda(false));
$("#m-legenda-todas").addEventListener("click", () => aplicarLegenda(true));
$$("[data-tipo-todos]").forEach((b) => b.addEventListener("click", () => {
  lote.forEach((i) => { i.tipo = b.dataset.tipoTodos; i.tipoManual = true; });
  renderLote();
}));

// ------------------------------------------------------------ agendar
function contarPosts() { return lote.reduce((n, i) => n + (i.tipo === "ambos" ? 2 : 1), 0); }

function atualizarBarra() {
  const naAbaNovo = !$("#aba-novo").hidden;
  $("#barra-agendar").hidden = !naAbaNovo || !lote.length;
  if (!lote.length) return;
  const subindo = lote.filter((i) => i.estado === "enviando").length;
  const ruins = lote.filter((i) => i.estado !== "enviando" && problemas(i).length).length;
  const n = contarPosts();
  const arroba = seletorConta.selectedOptions[0]?.textContent.split(" ")[0] || "";
  $("#resumo-lote").textContent = `· ${lote.length} vídeo(s), ${n} publicação(ões) em ${arroba}`;
  $("#barra-status").textContent = subindo ? `enviando ${subindo} vídeo(s)…` : ruins ? `${ruins} com problema (em vermelho)` : "tudo pronto";
  const btn = $("#btn-agendar");
  btn.disabled = subindo > 0 || ruins > 0 || !contaOk();
  if (!contaOk()) $("#barra-status").textContent = "conta desconectada: reconecte para agendar";
  btn.textContent = `Agendar ${n} publicaç${n === 1 ? "ão" : "ões"} em ${arroba}`;
}

$("#btn-agendar").addEventListener("click", async () => {
  const itens = [];
  lote.forEach((i) => {
    const base = { arquivo_id: i.arquivoId, quando: `${i.data}T${i.hora}`, duracao: i.duracao };
    if (i.tipo !== "story") itens.push({ ...base, tipo: "reels", legenda: i.legenda });
    if (i.tipo !== "reels") itens.push({ ...base, tipo: "story" });
  });
  const btn = $("#btn-agendar");
  btn.disabled = true; btn.textContent = "Agendando…";
  try {
    const r = await api("/api/agendar-lote", {
      method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ conta_id: contaId(), itens }),
    });
    lote = []; renderLote();
    toast(`✓ ${r.total} publicação(ões) agendada(s).` + (r.avisos?.length ? " " + r.avisos.join(" ") : ""), 6000);
    abrirAba("fila");
  } catch (e) {
    toast("Não agendou: " + e.message + (e.data?.itens ? ": " + e.data.itens.map((x) => `#${x.indice + 1}: ${x.erro}`).join("; ") : ""), 8000);
    atualizarBarra();
  }
});

window.addEventListener("beforeunload", (e) => { if (lote.length) { e.preventDefault(); e.returnValue = ""; } });

// ------------------------------------------------------------ fila
let verFila = "proximos";
$$(".seg button").forEach((b) => b.addEventListener("click", () => {
  verFila = b.dataset.ver;
  $$(".seg button").forEach((x) => x.classList.toggle("ativo", x === b));
  carregarFila();
}));
$("#atualizar-fila").addEventListener("click", () => carregarFila());

const ROTULO_STATUS = { AGENDADO: "agendado", PUBLICANDO: "publicando…", PUBLICADO: "publicado", ERRO: "erro", CANCELADO: "cancelado" };

async function carregarFila() {
  let d;
  try { d = await api(`/api/fila?ver=${verFila}&conta_id=${contaId()}`); } catch (e) { $("#lista-fila").innerHTML = `<p class="vazio">${esc(e.message)}</p>`; return; }
  const ag = d.resumo.AGENDADO || 0, er = d.resumo.ERRO || 0;
  $("#contador-fila").textContent = ag + er ? String(ag + er) : "";
  if (!d.itens.length) {
    $("#lista-fila").innerHTML = `<p class="vazio">${verFila === "proximos" ? "Nada agendado. Monte um lote na aba “Novo lote”." : "Nada publicado ainda por aqui."}</p>`;
    return;
  }
  let html = "", diaAtual = "";
  d.itens.forEach((p) => {
    const quando = new Date(verFila === "historico" && p.publicado_em ? p.publicado_em : p.agendado_para);
    const dia = `${DIAS[quando.getDay()]}, ${pad(quando.getDate())}/${pad(quando.getMonth() + 1)}`;
    if (dia !== diaAtual) { html += `<div class="dia-titulo">${dia}</div>`; diaAtual = dia; }
    const teste = (p.media_id || "").startsWith("TESTE-");
    const editavel = ["AGENDADO", "ERRO"].includes(p.status);
    html += `
      <div class="item-fila" data-id="${p.id}">
        <div class="mini">${p.apagado ? "" : `<video src="/arquivo/${p.arquivo_id}#t=0.5" muted playsinline preload="metadata"></video>`}</div>
        <div class="info">
          <b>${esc(p.nome_original)}</b>
          <span>${pad(quando.getHours())}:${pad(quando.getMinutes())} · ${p.tipo === "reels" ? "Reels" : "Story"}${p.legenda ? " · " + esc(p.legenda.slice(0, 60)) + (p.legenda.length > 60 ? "…" : "") : ""}</span>
          ${p.erro && p.status !== "PUBLICADO" ? `<span class="msg-erro">${esc(p.erro)}</span>` : ""}
          ${teste ? `<span>modo teste: não foi ao ar</span>` : ""}
          ${p.permalink ? `<span><a href="${esc(p.permalink)}" target="_blank" rel="noopener">ver no Instagram ↗</a></span>` : ""}
        </div>
        <div class="lado">
          <span class="pill pill-${p.status}">${teste ? "teste ok" : ROTULO_STATUS[p.status]}</span>
          ${editavel ? `<div class="acoes-fila">
            <button type="button" data-acao="editar">editar</button>
            <button type="button" data-acao="agora">publicar agora</button>
            <button type="button" data-acao="cancelar" class="perigo">cancelar</button>
          </div>` : ""}
          ${p.status === "CANCELADO" ? `<div class="acoes-fila"><button type="button" data-acao="editar">reagendar</button></div>` : ""}
        </div>
      </div>`;
  });
  $("#lista-fila").innerHTML = html;
  $("#lista-fila")._itens = Object.fromEntries(d.itens.map((p) => [p.id, p]));
}

function confirmarDuplo(btn, texto, acao) {
  if (btn.dataset.armado) { acao(); return; }
  const orig = btn.textContent;
  btn.dataset.armado = "1"; btn.textContent = texto;
  setTimeout(() => { delete btn.dataset.armado; btn.textContent = orig; }, 4000);
}

$("#lista-fila").addEventListener("click", async (e) => {
  const b = e.target.closest("button[data-acao]"); if (!b) return;
  const el = b.closest(".item-fila");
  const id = el.dataset.id;
  const p = $("#lista-fila")._itens[id];
  const patch = (body) => api(`/api/post/${id}`, { method: "PATCH", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) });

  if (b.dataset.acao === "cancelar") return confirmarDuplo(b, "confirmar?", async () => {
    try { await patch({ acao: "cancelar" }); toast("Cancelado."); carregarFila(); } catch (err) { toast(err.message); }
  });
  if (b.dataset.acao === "agora") return confirmarDuplo(b, "publicar mesmo?", async () => {
    try { await patch({ acao: "publicar_agora" }); toast("Vai sair em até 1 minuto."); carregarFila(); } catch (err) { toast(err.message); }
  });
  if (b.dataset.acao === "editar") {
    if ($(".editor-fila", el)) { $(".editor-fila", el).remove(); return; }
    const q = new Date(p.agendado_para);
    let quandoData = isoData(q), quandoHora = `${pad(q.getHours())}:${pad(q.getMinutes())}`;
    if (q < new Date()) { quandoData = proximaDataPadrao(); quandoHora = "09:00"; }
    const ed = document.createElement("div");
    ed.className = "editor-fila";
    ed.innerHTML = `
      <div class="tipo-toggle">
        <button type="button" data-t="reels" class="${p.tipo === "reels" ? "sel" : ""}">Reels</button>
        <button type="button" data-t="story" class="${p.tipo === "story" ? "sel" : ""}">Story</button>
      </div>
      <div class="linha-campos">
        <label>Data<input class="campo" type="date" value="${quandoData}"></label>
        <label>Hora<input class="campo" type="time" value="${quandoHora}"></label>
      </div>
      <label class="leg" ${p.tipo === "story" ? "hidden" : ""}>Legenda<textarea class="campo" rows="4">${esc(p.legenda || "")}</textarea></label>
      <div class="linha-botoes"><button class="botao" type="button" data-salvar>Salvar</button></div>`;
    el.appendChild(ed);
    let tipo = p.tipo;
    $$("[data-t]", ed).forEach((t) => t.addEventListener("click", () => {
      tipo = t.dataset.t;
      $$("[data-t]", ed).forEach((x) => x.classList.toggle("sel", x === t));
      $(".leg", ed).hidden = tipo === "story";
    }));
    $("[data-salvar]", ed).addEventListener("click", async () => {
      const [dt, hr] = $$("input", ed).map((x) => x.value);
      try {
        await patch({ tipo, quando: `${dt}T${hr}`, legenda: $("textarea", ed).value });
        toast("Salvo."); carregarFila();
      } catch (err) { toast(err.message); }
    });
  }
});

setInterval(() => { if (!$("#aba-fila").hidden) carregarFila(); }, 30000);
atualizarConta();
