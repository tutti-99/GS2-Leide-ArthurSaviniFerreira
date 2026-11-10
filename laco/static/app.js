"use strict";
/* =====================================================================
   Laço: comportamento da página (consome a API REST em /api/...).

   Segurança no navegador:
   - Todo texto vindo da API entra na página com textContent, nunca innerHTML.
     Assim um "<script>" escrito num pedido aparece como texto e não executa (anti-XSS).
   - A chave da central fica só numa variável: some ao recarregar ou clicar em "Sair".
   - Este arquivo é externo porque a CSP do servidor bloqueia scripts dentro do HTML.
   ===================================================================== */

const estado = {
  chave: "",            // chave da central (só em memória)
  voluntarios: [],      // lista vinda de /api/voluntarios
  pedidos: [],          // lista vinda de /api/pedidos
  filtro: "aberto",     // filtro ativo no painel da central
  relogio: null,        // atualização automática da central
};

const $ = (id) => document.getElementById(id);

// Nomes legíveis para os códigos que a API usa
const NOMES = {
  regiao: { "centro": "Centro", "zona-norte": "Zona Norte", "zona-sul": "Zona Sul",
            "zona-leste": "Zona Leste", "zona-oeste": "Zona Oeste" },
  tipo: { farmacia: "Farmácia", acompanhamento: "Consulta", compras: "Compras",
          tecnologia: "Celular", companhia: "Companhia" },
  periodo: { manha: "Manhã", tarde: "Tarde", noite: "Noite" },
  status: { aberto: "Aberto", em_atendimento: "Em atendimento",
            concluido: "Concluído", cancelado: "Cancelado" },
};
// "do Centro", mas "da Zona Norte"
const NA_REGIAO = { "centro": "do Centro", "zona-norte": "da Zona Norte", "zona-sul": "da Zona Sul",
                    "zona-leste": "da Zona Leste", "zona-oeste": "da Zona Oeste" };

const ATUALIZAR_A_CADA_MS = 30000;  // a central se atualiza sozinha a cada 30 s
const CONFIRMAR_POR_MS = 4000;      // botão "Confirmar ..." volta ao normal depois de 4 s

/* ---------------------------------------------------------------------
   Utilitários
   --------------------------------------------------------------------- */

/** Chamada genérica à API. Sempre devolve {ok, status, dados}, mesmo sem rede. */
async function chamarApi(caminho, { metodo = "GET", corpo, autenticado = false } = {}) {
  const cabecalhos = { Accept: "application/json" };
  if (corpo !== undefined) cabecalhos["Content-Type"] = "application/json";
  if (autenticado) cabecalhos["X-API-Key"] = estado.chave;
  try {
    const resposta = await fetch(caminho, {
      method: metodo,
      headers: cabecalhos,
      body: corpo !== undefined ? JSON.stringify(corpo) : undefined,
    });
    let dados = null;
    if (resposta.status !== 204) {
      try { dados = await resposta.json(); } catch { dados = null; }
    }
    return { ok: resposta.ok, status: resposta.status, dados };
  } catch {
    return { ok: false, status: 0, dados: { erro: "Sem conexão com o servidor. Verifique se a API está rodando." } };
  }
}

/** Cria um elemento com texto seguro (textContent) e classe opcional. */
function criar(tag, texto, classe) {
  const el = document.createElement(tag);
  if (texto !== undefined && texto !== null) el.textContent = texto;
  if (classe) el.className = classe;
  return el;
}

/** Cria um ícone do sprite SVG (definido em templates/partes/icones.svg). */
function icone(nome) {
  const NS = "http://www.w3.org/2000/svg";
  const svg = document.createElementNS(NS, "svg");
  svg.setAttribute("class", "icone");
  svg.setAttribute("aria-hidden", "true");
  svg.setAttribute("focusable", "false");
  const uso = document.createElementNS(NS, "use");
  uso.setAttribute("href", "#i-" + nome);
  svg.append(uso);
  return svg;
}

/** Mensagem de erro da API em texto, incluindo os detalhes por campo. */
function textoDoErro(r, padrao) {
  if (!r.dados) return padrao;
  const detalhes = r.dados.detalhes ? " " + Object.values(r.dados.detalhes).join(" ") : "";
  return (r.dados.erro || padrao) + detalhes;
}

/** Aviso rápido no canto da tela (toast). */
function avisar(texto, sucesso = true) {
  const aviso = criar("div", null, "aviso" + (sucesso ? "" : " falha"));
  aviso.append(icone(sucesso ? "check" : "alerta"), criar("span", texto));
  $("avisos").append(aviso);
  setTimeout(() => aviso.remove(), 5000);
}

/** "há 5 min", "há 2 h" ou a data, a partir do texto ISO que a API devolve. */
function quandoFoi(iso) {
  const data = new Date(iso);
  if (Number.isNaN(data.getTime())) return "";
  const minutos = Math.round((Date.now() - data.getTime()) / 60000);
  if (minutos >= 0 && minutos < 1) return "agora há pouco";
  if (minutos >= 1 && minutos < 60) return `há ${minutos} min`;
  if (minutos >= 60 && minutos < 24 * 60) return `há ${Math.round(minutos / 60)} h`;
  return data.toLocaleString("pt-BR", { dateStyle: "short", timeStyle: "short" });
}

/* ---------------------------------------------------------------------
   Ajustes de leitura: tamanho do texto e alto contraste
   --------------------------------------------------------------------- */
// O CSS já ajusta o texto à largura da tela; aqui só multiplicamos essa base
// (de 84% a 144%), assim A− e A+ não desligam a responsividade.
let escalaFonte = 1;
function ajustarFonte(delta) {
  escalaFonte = Math.round(Math.min(1.44, Math.max(0.84, escalaFonte + delta)) * 100) / 100;
  document.documentElement.style.setProperty("--escala", String(escalaFonte));
}
$("fonte-menor").addEventListener("click", () => ajustarFonte(-0.12));
$("fonte-maior").addEventListener("click", () => ajustarFonte(0.12));

$("alto-contraste").addEventListener("click", (evento) => {
  const ligado = document.documentElement.classList.toggle("alto-contraste");
  evento.currentTarget.setAttribute("aria-pressed", String(ligado));
});

/* ---------------------------------------------------------------------
   1. Pedido de apoio
   --------------------------------------------------------------------- */
const CAMPOS = ["apelido", "tipo", "regiao", "periodo", "descricao"];
const GRUPOS_DE_RADIO = { tipo: "grupo-tipo", periodo: "grupo-periodo" };

/** Lê o valor de um campo: texto/select pelo id, rádios pelo item marcado. */
function valorDoCampo(campo) {
  if (GRUPOS_DE_RADIO[campo]) {
    const marcado = document.querySelector(`input[name="${campo}"]:checked`);
    return marcado ? marcado.value : "";
  }
  return $(campo).value.trim();
}

/** Elemento que recebe aria-invalid e foco quando o campo tem erro. */
function alvoDoCampo(campo) {
  if (GRUPOS_DE_RADIO[campo]) return document.querySelector(`input[name="${campo}"]`);
  return $(campo);
}

function limparErros() {
  for (const campo of CAMPOS) {
    $("erro-" + campo).textContent = "";
    alvoDoCampo(campo).removeAttribute("aria-invalid");
  }
  $("mensagem-pedido").textContent = "";
}

$("descricao").addEventListener("input", () => {
  $("contador-numero").textContent = $("descricao").value.length;
});

$("form-pedido").addEventListener("submit", async (evento) => {
  evento.preventDefault();
  limparErros();

  const corpo = {};
  for (const campo of CAMPOS) corpo[campo] = valorDoCampo(campo);

  const botao = $("botao-enviar");
  botao.disabled = true;
  botao.textContent = "Enviando…";
  const r = await chamarApi("/api/pedidos", { metodo: "POST", corpo });
  botao.disabled = false;
  botao.textContent = "Enviar pedido";

  if (r.status === 201) {
    mostrarConfirmacao(r.dados, corpo.regiao);
    return;
  }

  // 400: mostra a mensagem embaixo de cada campo e leva o foco ao primeiro
  if (r.status === 400 && r.dados && r.dados.detalhes) {
    let primeiro = null;
    for (const [campo, mensagem] of Object.entries(r.dados.detalhes)) {
      if (!CAMPOS.includes(campo)) continue;
      $("erro-" + campo).textContent = mensagem.charAt(0).toUpperCase() + mensagem.slice(1) + ".";
      alvoDoCampo(campo).setAttribute("aria-invalid", "true");
      primeiro = primeiro || campo;
    }
    $("mensagem-pedido").textContent = "Confira os campos marcados.";
    $("mensagem-pedido").className = "mensagem-form falha";
    if (primeiro) alvoDoCampo(primeiro).focus();
    return;
  }

  // 429, 500, sem rede...
  $("mensagem-pedido").textContent = textoDoErro(r, "Não foi possível enviar agora. Tente de novo.");
  $("mensagem-pedido").className = "mensagem-form falha";
});

function mostrarConfirmacao(dados, regiao) {
  $("confirmacao-titulo").textContent = `Pedido nº ${dados.id} recebido`;
  $("confirmacao-texto").textContent =
    `Um voluntário ${NA_REGIAO[regiao]} vai assumir em breve. ` +
    "A instituição parceira do bairro entra em contato com você.";
  $("confirmacao-prioridade").hidden = dados.prioridade !== "alta";
  $("form-pedido").hidden = true;
  $("confirmacao").hidden = false;
  $("confirmacao").focus();
}

$("botao-novo-pedido").addEventListener("click", () => {
  $("form-pedido").reset();
  $("contador-numero").textContent = "0";
  limparErros();
  $("confirmacao").hidden = true;
  $("form-pedido").hidden = false;
  $("apelido").focus();
});

/* ---------------------------------------------------------------------
   2. Tempo hoje (Open-Meteo, via /api/clima)
   --------------------------------------------------------------------- */
async function carregarClima() {
  const regiao = $("regiao").value;
  const painel = $("painel-clima");
  const cartao = $("tempo");
  cartao.classList.remove("em-alerta");
  painel.replaceChildren();

  if (!regiao) {
    painel.append(criar("p", "Escolha a sua região no formulário para ver a temperatura e os cuidados do dia.", "tempo-vazio"));
    return;
  }
  painel.append(criar("p", "Consultando o tempo…", "tempo-vazio"));

  const r = await chamarApi("/api/clima?regiao=" + encodeURIComponent(regiao));
  painel.replaceChildren();
  if (!r.ok) {
    painel.append(criar("p", "Não conseguimos consultar o tempo agora. O seu pedido funciona normalmente.", "tempo-vazio"));
    return;
  }
  const d = r.dados;

  const local = criar("p", null, "tempo-regiao");
  local.append(icone("pin"), criar("span", NOMES.regiao[d.regiao] || d.regiao));

  const agora = criar("p", null, "tempo-agora");
  agora.append(criar("span", `${Math.round(d.temperatura)}°`, "tempo-graus"), criar("span", "agora"));

  const detalhes = criar("dl", null, "tempo-detalhes");
  for (const [rotulo, valor] of [
    ["Sensação", `${Math.round(d.sensacao)}°`],
    ["Máxima", `${Math.round(d.maxima_hoje)}°`],
    ["Umidade", `${Math.round(d.umidade)}%`],
  ]) {
    const item = criar("div");
    item.append(criar("dt", rotulo), criar("dd", valor));
    detalhes.append(item);
  }
  painel.append(local, agora, detalhes);

  if (d.alerta) {
    cartao.classList.add("em-alerta");
    const alerta = criar("div", null, "tempo-alerta");
    const titulo = criar("h3");
    titulo.append(icone("alerta"), criar("span", "Dia de cuidado redobrado"));
    alerta.append(titulo);
    for (const orientacao of d.orientacoes) alerta.append(criar("p", orientacao));
    alerta.append(criar("p", "Pedidos desta região passam na frente na central."));
    painel.append(alerta);
  } else {
    const ok = criar("p", null, "tempo-ok");
    ok.append(icone("check"), criar("span", "Sem alerta de calor ou de ar seco hoje."));
    painel.append(ok);
  }
  painel.append(criar("p", "Fonte: " + d.fonte, "tempo-fonte"));
}
$("regiao").addEventListener("change", carregarClima);

/* ---------------------------------------------------------------------
   3. Central de voluntários
   --------------------------------------------------------------------- */
$("form-chave").addEventListener("submit", async (evento) => {
  evento.preventDefault();
  estado.chave = $("chave").value;
  $("chave").value = "";

  const r = await chamarApi("/api/voluntarios", { autenticado: true });
  if (!r.ok) {
    estado.chave = "";
    const mensagens = { 401: "Chave incorreta.", 429: "Muitas tentativas. Aguarde alguns minutos." };
    $("mensagem-chave").textContent = mensagens[r.status] || textoDoErro(r, "Não foi possível entrar.");
    $("mensagem-chave").className = "mensagem-form falha";
    return;
  }
  $("mensagem-chave").textContent = "";
  estado.voluntarios = r.dados;
  $("form-chave").hidden = true;
  $("area-central").hidden = false;
  $("central-sessao").hidden = false;
  await carregarPedidos();
  estado.relogio = setInterval(atualizarSozinho, ATUALIZAR_A_CADA_MS);
  avisar("Você entrou na central.");
});

$("botao-sair").addEventListener("click", () => {
  clearInterval(estado.relogio);
  estado.chave = "";
  estado.voluntarios = [];
  estado.pedidos = [];
  $("lista-pedidos").replaceChildren();
  $("area-central").hidden = true;
  $("central-sessao").hidden = true;
  $("form-chave").hidden = false;
  $("chave").focus();
});

$("botao-atualizar").addEventListener("click", async () => {
  if (await carregarPedidos()) avisar("Lista atualizada.");
});

/** Atualização automática, mas nunca no meio de uma ação do voluntário
    (escolhendo alguém na lista ou confirmando um botão) nem com a aba escondida. */
function atualizarSozinho() {
  const lista = $("lista-pedidos");
  if (document.hidden || lista.contains(document.activeElement) || lista.querySelector(".confirmar")) return;
  carregarPedidos();
}

for (const botao of document.querySelectorAll(".filtro")) {
  botao.addEventListener("click", () => {
    estado.filtro = botao.dataset.status;
    for (const outro of document.querySelectorAll(".filtro")) {
      outro.setAttribute("aria-pressed", String(outro === botao));
    }
    carregarPedidos();
  });
}

/** Busca os pedidos do filtro ativo e a contagem por status, ao mesmo tempo.
    O filtro é aplicado no servidor e a contagem vem do banco, então os números
    estão sempre certos, mesmo com muitos pedidos. */
async function carregarPedidos() {
  const caminho = "/api/pedidos" + (estado.filtro ? "?status=" + encodeURIComponent(estado.filtro) : "");
  const [r, resumo] = await Promise.all([
    chamarApi(caminho, { autenticado: true }),
    chamarApi("/api/pedidos/resumo", { autenticado: true }),
  ]);
  if (!r.ok || !resumo.ok) {
    const falha = r.ok ? resumo : r;
    avisar(textoDoErro(falha, "Falha ao carregar os pedidos."), false);
    if (falha.status === 401) $("botao-sair").click();
    return false;
  }
  estado.pedidos = r.dados;
  desenharResumo(resumo.dados);
  desenharLista();
  return true;
}

function desenharResumo(resumo) {
  for (const status of ["aberto", "em_atendimento", "concluido", "cancelado"]) {
    const cartao = $("resumo-" + status);
    if (cartao) cartao.textContent = resumo[status];
    document.querySelector(`[data-contagem="${status}"]`).textContent = resumo[status];
  }
  $("resumo-alta").textContent = resumo.alta_abertos;
  document.querySelector('[data-contagem="todos"]').textContent = resumo.todos;
}

function desenharLista() {
  const lista = $("lista-pedidos");
  const visiveis = estado.pedidos;
  lista.replaceChildren(...visiveis.map(cartaoPedido));

  const vazio = $("lista-vazia");
  vazio.hidden = visiveis.length > 0;
  if (!visiveis.length) {
    vazio.textContent = estado.filtro === "aberto"
      ? "Nenhum pedido esperando. Quando alguém pedir ajuda, ele aparece aqui."
      : "Nenhum pedido neste filtro.";
  }
}

/** Monta o cartão de um pedido, só com textContent. */
function cartaoPedido(p) {
  const item = criar("li", null, "pedido" + (p.prioridade === "alta" ? " alta" : ""));

  // topo: ícone do tipo, nomes e etiquetas
  const topo = criar("div", null, "pedido-topo");
  const tipo = criar("span", null, "pedido-tipo");
  tipo.append(icone(p.tipo));
  const nomes = criar("div", null, "pedido-nomes");
  nomes.append(criar("h3", `${NOMES.tipo[p.tipo]} para ${p.apelido}`), criar("p", `Pedido nº ${p.id}`));
  const etiquetas = criar("div", null, "etiquetas");
  if (p.prioridade === "alta") etiquetas.append(criar("span", "Prioridade alta", "etiqueta alta"));
  if (p.status === "cancelado") etiquetas.append(criar("span", "Cancelado", "etiqueta cancelado"));
  topo.append(tipo, nomes, etiquetas);

  // descrição e informações
  const descricao = criar("p", p.descricao, "pedido-descricao");
  const meta = criar("ul", null, "pedido-meta");
  const infos = [["pin", NOMES.regiao[p.regiao]], [p.periodo, NOMES.periodo[p.periodo]], ["relogio", quandoFoi(p.criado_em)]];
  if (p.voluntario) infos.push(["pessoa", `Com ${p.voluntario}`]);
  for (const [nomeIcone, texto] of infos) {
    const li = criar("li");
    li.append(icone(nomeIcone), criar("span", texto));
    meta.append(li);
  }

  item.append(topo, descricao, meta);
  if (p.status !== "cancelado") item.append(linhaDoTempo(p.status));
  item.append(acoesDoPedido(p));
  return item;
}

/** Linha do tempo: Aberto, Em atendimento, Concluído. */
function linhaDoTempo(status) {
  const ordem = ["aberto", "em_atendimento", "concluido"];
  const posicao = ordem.indexOf(status);
  const etapas = criar("ol", null, "etapas");
  etapas.setAttribute("aria-label", "Andamento: " + NOMES.status[status]);
  ordem.forEach((etapa, i) => {
    const classe = i < posicao || status === "concluido" ? "feita" : i === posicao ? "atual" : "";
    const li = criar("li", null, "etapa " + classe);
    li.append(criar("span", null, "etapa-ponto"), criar("span", NOMES.status[etapa]));
    etapas.append(li);
  });
  return etapas;
}

/** Botões que fazem sentido para cada status (a API também valida as transições). */
function acoesDoPedido(p) {
  const acoes = criar("div", null, "pedido-acoes");

  if (p.status === "aberto") {
    const campo = criar("div", null, "campo");
    const rotulo = criar("label", "Voluntário");
    const seletor = document.createElement("select");
    seletor.id = `voluntario-${p.id}`;
    rotulo.htmlFor = seletor.id;
    const vazio = criar("option", "Escolha quem vai");
    vazio.value = "";
    seletor.append(vazio);
    // voluntários da mesma região aparecem primeiro
    const ordenados = [...estado.voluntarios].sort((a, b) => (b.regiao === p.regiao) - (a.regiao === p.regiao));
    for (const v of ordenados) {
      const opcao = criar("option", `${v.apelido} (${NOMES.regiao[v.regiao]})`);
      opcao.value = String(v.id);
      seletor.append(opcao);
    }
    const caixa = criar("div", null, "seletor");  // mesma seta do formulário de pedido
    caixa.append(seletor);
    campo.append(rotulo, caixa);

    const assumir = botaoAcao("Assumir pedido", "check", "botao-principal", async () => {
      if (!seletor.value) {
        avisar("Escolha o voluntário antes de assumir.", false);
        seletor.focus();
        return;
      }
      const nome = seletor.options[seletor.selectedIndex].textContent.split(" (")[0];
      await mudarPedido(p.id, { status: "em_atendimento", voluntario_id: Number(seletor.value) },
        `Pedido nº ${p.id} assumido por ${nome}.`);
    });
    acoes.append(campo, assumir, botaoCancelar(p));
  }

  if (p.status === "em_atendimento") {
    acoes.append(
      botaoAcao("Concluir", "check", "botao-principal", () =>
        mudarPedido(p.id, { status: "concluido" }, `Pedido nº ${p.id} concluído.`)),
      botaoAcao("Devolver para a fila", "desfazer", "botao-contorno", () =>
        mudarPedido(p.id, { status: "aberto", voluntario_id: null }, `Pedido nº ${p.id} voltou para a fila.`)),
      botaoCancelar(p),
    );
  }

  acoes.append(botaoExcluir(p));
  return acoes;
}

function botaoAcao(texto, nomeIcone, classe, aoClicar) {
  const botao = criar("button", null, `botao botao-pequeno ${classe}`);
  botao.type = "button";
  botao.append(icone(nomeIcone), criar("span", texto));
  botao.addEventListener("click", async () => {
    botao.disabled = true;
    await aoClicar();
    botao.disabled = false;
  });
  return botao;
}

/** Ação que não tem volta, em dois cliques e sem janela pop-up: o 1º clique
    troca o texto para "Confirmar ..."; se não vier o 2º em 4 s (ou o foco sair
    do botão), ele volta ao normal sozinho. */
function botaoComConfirmacao(texto, textoConfirmar, nomeIcone, classe, acao) {
  const botao = criar("button", null, `botao botao-pequeno ${classe}`);
  botao.type = "button";
  const rotulo = criar("span", texto);
  botao.append(icone(nomeIcone), rotulo);
  let espera = null;
  const desarmar = () => {
    clearTimeout(espera);
    botao.classList.remove("confirmar");
    rotulo.textContent = texto;
  };
  botao.addEventListener("blur", desarmar);
  botao.addEventListener("click", async () => {
    if (!botao.classList.contains("confirmar")) {
      botao.classList.add("confirmar");
      rotulo.textContent = textoConfirmar;
      espera = setTimeout(desarmar, CONFIRMAR_POR_MS);
      return;
    }
    clearTimeout(espera);
    botao.disabled = true;
    const deuCerto = await acao();
    if (!deuCerto) {
      botao.disabled = false;
      desarmar();
    }
  });
  return botao;
}

function botaoCancelar(p) {
  return botaoComConfirmacao("Cancelar", "Confirmar cancelamento", "x", "botao-perigo", () =>
    mudarPedido(p.id, { status: "cancelado" }, `Pedido nº ${p.id} cancelado.`));
}

function botaoExcluir(p) {
  return botaoComConfirmacao("Excluir", "Confirmar exclusão", "lixeira", "botao-perigo empurra", async () => {
    const r = await chamarApi(`/api/pedidos/${p.id}`, { metodo: "DELETE", autenticado: true });
    if (r.status === 204) {
      await carregarPedidos();
      avisar(`Pedido nº ${p.id} excluído.`);
      return true;
    }
    avisar(textoDoErro(r, "Falha ao excluir."), false);
    if (r.status === 404) await carregarPedidos();  // alguém já tinha excluído
    return false;
  });
}

/** PUT /api/pedidos/<id> e recarrega a lista. Devolve true se salvou. */
async function mudarPedido(id, corpo, mensagemSucesso) {
  const r = await chamarApi(`/api/pedidos/${id}`, { metodo: "PUT", corpo, autenticado: true });
  if (r.ok) {
    await carregarPedidos();
    avisar(mensagemSucesso);
    return true;
  }
  avisar(textoDoErro(r, "Falha ao salvar."), false);
  // 409/404: outra pessoa mexeu no pedido antes; mostra a situação atual
  if (r.status === 409 || r.status === 404) await carregarPedidos();
  return false;
}
