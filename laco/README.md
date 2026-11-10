# Laço: rede de apoio de vizinhança para idosos e pessoas com deficiência

Protótipo da **Global Solution 2026 (CitizenTech)** da disciplina **Coding for Security**, FIAP.

Idosos que moram sozinhos e pessoas com deficiência muitas vezes precisam de uma ajuda
pontual: buscar um remédio, ir junto a uma consulta, fazer compras pequenas, usar um
aplicativo do governo. O **Laço** liga esses pedidos a voluntários da mesma região de
São Paulo e, em dias de **calor extremo ou ar seco** (dados do Open-Meteo), dá prioridade
aos pedidos e mostra cuidados de saúde na tela.

**ODS:** 3 (Saúde e bem-estar), 10 (Redução das desigualdades), 11 (Cidades e comunidades
sustentáveis) e 13 (Ação contra a mudança global do clima).

---

## Como funciona

```
 Navegador (HTML/CSS/JS)                      Open-Meteo (API externa, JSON)
   │  fetch + JSON                                   ▲
   ▼                                                 │ requests (timeout 5 s, cache 15 min)
 ┌──────────────────────────── API Flask (app.py) ───┴──────────────────────────┐
 │ validacao.py → seguranca.py (chave, limite de taxa, cabeçalhos) → database.py │
 │ auditoria.py grava logs/laco.log (data/hora | ação | resultado)               │
 └────────┬───────────────────────────────────────────────────────┬─────────────┘
          │ SQL parametrizado (mysql-connector, sem ORM)           │ socket TCP + HMAC
          ▼                                                       ▼
   MySQL: voluntarios 1 ── N pedidos                  central_tcp.py (central de voluntários)
```

1. A pessoa (ou um familiar) faz o pedido na página: apelido, região, tipo de ajuda, período e uma descrição curta.
2. A API valida tudo, calcula a prioridade (farmácia/acompanhamento ou região em alerta climático = **alta**) e grava no MySQL.
3. A API avisa a **central de voluntários** na hora, por **socket TCP** com mensagem assinada (HMAC).
4. Na central, com a chave de acesso, o voluntário vê a lista, assume o pedido, conclui ou exclui.

## Onde está cada requisito da GS

| Requisito | Onde |
|---|---|
| API REST com GET, POST, PUT, DELETE e status corretos | `app.py` (200, 201, 204, 400, 401, 404, 405, 409, 413, 415, 429, 500, 503) |
| MySQL com CRUD em Python, sem ORM | `database.py`, `sql/schema.sql`, `setup_db.py` |
| Fonte externa com requests + JSON | `clima.py` (Open-Meteo) |
| Interface web que consome a API | `templates/index.html` (+ `templates/partes/`), `static/app.js`, `static/style.css` |
| Log em arquivo (data/hora, ação, resultado) | `auditoria.py` → `logs/laco.log` e `logs/central.log` |
| Módulo à escolha: sockets TCP | `notificador.py` (cliente), `central_tcp.py` (servidor), `protocolo.py` |
| Funções, módulos e tratamento de exceções | todos os `.py`; erros tratados em `app.py` (`@app.errorhandler`) |
| Credenciais em .env | `config.py`, `.env.example` |
| Consultas parametrizadas | `database.py` (todos os valores vão em `%s`) |
| Validação de toda entrada | `validacao.py` (whitelist) |
| Erros sem detalhes internos | `app.py`: o cliente recebe mensagem genérica, o detalhe vai pro log |
| Coleta mínima (LGPD) | sem nome completo, CPF, endereço, telefone, idade ou tipo de deficiência |
| Testes automatizados | `tests/` (73 testes com pytest) |

## A interface

- **Identidade visual de São Paulo:** roxo do jacarandá, amarelo do ipê e o "fio" dourado que liga quem pede a quem ajuda (ele se desenha na ilustração ao abrir a página).
- **Feita para quem vai usar:** fonte **Atkinson Hyperlegible Next**, criada pelo Braille Institute para pessoas com baixa visão; botões **A−/A+**; modo de **alto contraste**; foco sempre visível; alvos de toque grandes; respeita quem prefere menos movimento.
- **Pedido em poucos toques:** tipo de ajuda em cartões com ícones, período em botões, contador de caracteres, erros explicados embaixo de cada campo e tela de confirmação.
- **Tempo hoje:** temperatura, sensação, máxima e umidade da região, com orientações em dia de calor ou ar seco.
- **Central de voluntários:** resumo com contadores (calculados no banco), filtros por status, linha do tempo de cada pedido e ações de assumir, concluir, devolver, cancelar e excluir. Ações sem volta (cancelar e excluir) pedem um 2º clique de confirmação, e a lista se atualiza sozinha a cada 30 s.
- **Qualidade verificada:** HTML aprovado no `html-validate` e **0 violações WCAG 2.1 AA** no `axe-core` (desktop, celular e alto contraste).
- Ilustração e ícones são **SVG originais**; a fonte fica em `static/fonts/` (a CSP só permite arquivos do próprio site, e assim nenhum dado do visitante vai para servidores de terceiros).

---

## Executar do zero

### 1. Pré-requisitos
- **Python 3.10+**
- **MySQL Server 8.0.16 ou mais novo** instalado e rodando (no Windows, pelo *MySQL Installer*; anote a senha do `root`)
- Git (opcional, para clonar)

### 2. Baixar o projeto e criar o ambiente virtual

Windows (PowerShell ou CMD):
```bat
cd laco
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
```

Linux / macOS:
```bash
cd laco
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

### 3. Criar o `.env`
```bat
copy .env.example .env        (Windows)
cp .env.example .env          (Linux/macOS)
```
Abra o `.env` e troque `DB_PASSWORD`, `API_KEY_CENTRAL` e `SOCKET_SECRET`. Para gerar valores aleatórios:
```bash
python -c "import secrets; print(secrets.token_urlsafe(32))"
```

### 4. Preparar o banco
```bash
python setup_db.py
```
Ele pede o usuário/senha de **administrador** do MySQL (ex.: `root`) só na hora e:
cria o banco `laco` e as tabelas, insere dados **fictícios** e cria o usuário da aplicação
(`DB_USER` do `.env`) com **privilégio mínimo**: só `SELECT, INSERT, UPDATE, DELETE`.

<details>
<summary>Alternativa manual (MySQL Workbench)</summary>

Execute `sql/schema.sql`, depois `sql/dados_ficticios.sql`, e por fim (com a mesma senha do `.env`):
```sql
CREATE USER 'laco_app'@'localhost' IDENTIFIED BY 'sua-senha-do-env';
CREATE USER 'laco_app'@'127.0.0.1' IDENTIFIED BY 'sua-senha-do-env';
GRANT SELECT, INSERT, UPDATE, DELETE ON laco.* TO 'laco_app'@'localhost';
GRANT SELECT, INSERT, UPDATE, DELETE ON laco.* TO 'laco_app'@'127.0.0.1';
```
</details>

### 5. Rodar (dois terminais, ambos com o `.venv` ativado)
```bash
# Terminal 1: central de voluntários (socket TCP)
python central_tcp.py

# Terminal 2: API + interface web
python app.py
```
Abra **http://127.0.0.1:5000**. Para entrar na *Central de voluntários* da página, use o valor de `API_KEY_CENTRAL`.
Cada pedido novo aparece na hora no Terminal 1.

### 6. Rodar os testes
```bash
python -m pytest -q
```
Os testes não precisam de MySQL nem de internet: o banco e o Open-Meteo são simulados com `monkeypatch`.

---

## Endpoints

| Método | Rota | Acesso | Sucesso | Erros |
|---|---|---|---|---|
| POST | `/api/pedidos` | público (5/min por IP) | 201 + `Location` | 400, 413, 415, 429 |
| GET | `/api/pedidos?status=&regiao=` | `X-API-Key` | 200 | 400, 401, 429 |
| GET | `/api/pedidos/<id>` | `X-API-Key` | 200 | 401, 404, 429 |
| PUT | `/api/pedidos/<id>` | `X-API-Key` | 200 | 400, 401, 404, 409, 429 |
| DELETE | `/api/pedidos/<id>` | `X-API-Key` | 204 | 401, 404, 429 |
| GET | `/api/pedidos/resumo` | `X-API-Key` | 200 | 401, 429 |
| GET | `/api/voluntarios` | `X-API-Key` | 200 | 401, 429 |
| GET | `/api/clima?regiao=` | público | 200 | 400, 503 |
| GET | `/api/saude` | público | 200 | 503 |

Nas rotas com `X-API-Key`, 10 chaves erradas em 5 minutos bloqueiam o IP temporariamente (429), contra força bruta.

Regras do PUT (as mesmas são garantidas por `CHECK` no banco):
- pedido **aberto** não tem voluntário; ao devolver para a fila, o voluntário é retirado automaticamente;
- pedido **em atendimento** sempre tem voluntário (dá para trocar quem atende);
- pedido **concluído** ou **cancelado** não muda mais (409);
- se outra pessoa alterou o pedido no mesmo instante (dois voluntários clicando em "Assumir"), só a primeira alteração vale e a segunda recebe **409**.

Exemplos com `curl` (no Windows, use o **Git Bash** ou um cliente como Insomnia/Postman):
```bash
# criar
curl -i -X POST http://127.0.0.1:5000/api/pedidos -H "Content-Type: application/json" \
  -d '{"apelido":"Dona Lurdes","regiao":"zona-leste","tipo":"farmacia","periodo":"manha","descricao":"Preciso buscar remédio no posto de saúde."}'

# listar (troque SUA_CHAVE)
curl -i http://127.0.0.1:5000/api/pedidos?status=aberto -H "X-API-Key: SUA_CHAVE"

# assumir com a voluntária de id 1
curl -i -X PUT http://127.0.0.1:5000/api/pedidos/5 -H "X-API-Key: SUA_CHAVE" \
  -H "Content-Type: application/json" -d '{"status":"em_atendimento","voluntario_id":1}'

# excluir
curl -i -X DELETE http://127.0.0.1:5000/api/pedidos/5 -H "X-API-Key: SUA_CHAVE"

# clima
curl -i "http://127.0.0.1:5000/api/clima?regiao=centro"
```
Valores aceitos: `regiao` = centro, zona-norte, zona-sul, zona-leste, zona-oeste ·
`tipo` = compras, farmacia, acompanhamento, tecnologia, companhia · `periodo` = manha, tarde, noite ·
`status` = aberto → em_atendimento → concluido (ou cancelado).

---

## Segurança e privacidade (resumo)

- **Segredos no `.env`** (fora do Git pelo `.gitignore`); o programa não inicia se faltar algum.
- **SQL parametrizado** em 100% das consultas + usuário MySQL com **privilégio mínimo** + `ENUM` e `CHECK` no banco (defesa em duas camadas: o banco recusa um pedido incoerente mesmo que a API falhe).
- **Sem condição de corrida:** o `UPDATE` só grava se o pedido ainda estiver no status que a API conferiu (`WHERE id = %s AND status = %s`).
- **Validação por lista branca** (`validacao.py`): campos extras recusados (o cliente não escolhe a prioridade), tamanhos, caracteres e valores fixos. A descrição é **recusada se tiver telefone, CPF, CEP ou e-mail** e também se tiver caracteres invisíveis (como o U+202E, que inverte o texto na tela).
- **Autenticação** da central por chave no cabeçalho `X-API-Key`, comparada com `hmac.compare_digest`, com bloqueio do IP após 10 tentativas erradas em 5 min.
- **Limite de taxa** (5 pedidos/min por IP) contra spam e **limite de corpo** (16 KB). IPs inativos saem da memória, então um ataque com muitos IPs não enche a RAM.
- **Anti-XSS:** a página só usa `textContent` + cabeçalho **CSP** `default-src 'self'`; também `nosniff`, `X-Frame-Options: DENY`, `Permissions-Policy` e `Cross-Origin-Opener-Policy`.
- **Erros genéricos** para o cliente; o detalhe técnico vai só para o log. `debug` desligado por padrão.
- **Log sem dados pessoais** (só ids, ações e resultados) e protegido contra *log injection* (quebras de linha e códigos de escape do terminal viram espaço).
- **Socket TCP com HMAC-SHA256** + validade de 60 s + *nonce*: a central recusa mensagens falsas, alteradas, antigas ou **repetidas** (replay), e atende no máximo 20 conexões ao mesmo tempo.
- **Serviço externo com disjuntor:** se o Open-Meteo cair, a API espera 1 min antes de tentar de novo, em vez de deixar cada pedido 5 s mais lento.
- **Coleta mínima (LGPD):** só apelido, região, tipo de ajuda, período e descrição curta. O contato fica com a instituição parceira (ex.: CRAS/UBS), que já tem o cadastro: o Laço não guarda esses dados.

## Estrutura

```
laco/
├── app.py              rotas da API e tratamento de erros
├── config.py           leitura do .env
├── database.py         CRUD MySQL (SQL parametrizado)
├── validacao.py        validação das entradas
├── seguranca.py        chave da central, limite de taxa, cabeçalhos HTTP
├── clima.py            Open-Meteo (requests + JSON)
├── protocolo.py        mensagens TCP assinadas (HMAC)
├── notificador.py      cliente socket TCP
├── central_tcp.py      servidor socket TCP (central de voluntários)
├── auditoria.py        log em arquivo
├── setup_db.py         prepara o banco do zero
├── sql/                schema.sql e dados_ficticios.sql
├── templates/          index.html e partes/ (ilustração e ícones SVG)
├── static/             style.css, app.js, fonts/ e img/
├── tests/              testes pytest
├── requirements.txt
└── .env.example
```

## Problemas comuns
- **Já criei o banco antes com outra versão do projeto**: no Workbench, rode `DROP DATABASE laco;` e depois `python setup_db.py` de novo (as tabelas desta versão têm regras `CHECK` novas). O `setup_db.py` avisa quando detecta um banco antigo.
- **PowerShell não deixa ativar o `.venv`**: rode `Set-ExecutionPolicy -Scope Process RemoteSigned` e tente de novo (ou use o CMD).
- **`setup_db.py` trava pedindo a senha dentro da IDE**: rode-o num terminal comum (PowerShell, CMD ou terminal do VS Code).
- **`Variável ... ausente no .env`**: crie o `.env` a partir do `.env.example` (passo 3).
- **`Erro interno` na página**: veja `logs/laco.log`; normalmente é o MySQL desligado ou a senha do `.env` diferente da do usuário criado.
- **`Muitos pedidos em pouco tempo`**: é o limite de 5 pedidos/min por IP. Espere 1 minuto.
- **Tempo indisponível**: sem internet ou o Open-Meteo fora do ar. O resto do sistema continua funcionando.
- **Porta 5050 ocupada**: troque `CENTRAL_PORT` no `.env`.

## Dados, créditos e uso de IA
- Dados meteorológicos: [Open-Meteo.com](https://open-meteo.com/), licença CC BY 4.0.
- Fonte: [Atkinson Hyperlegible Next](https://github.com/googlefonts/atkinson-hyperlegible-next), Braille Institute, licença SIL OFL 1.1 (cópia em `static/fonts/`).
- Ilustração, logo e ícones: SVG criados para este projeto.
- Todos os pedidos e voluntários do banco são **fictícios**.
- Bibliotecas: Flask, mysql-connector-python, requests, python-dotenv, pytest (ver `requirements.txt`).
- **Uso de IA generativa:** o Claude (Anthropic) foi usado como apoio no desenvolvimento, na depuração e na revisão do texto, conforme declarado no relatório.
