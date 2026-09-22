"""
Agendador de Reels e Stories — versao produto (varios clientes).

Cada cliente: cria conta no site -> conecta o Instagram com o app Meta DELE
(assistente passo a passo) -> sobe videos em lote e agenda -> worker.py
publica na hora. O dono do produto libera/estende o acesso em /admin.

Rodar local:  python app.py   (http://127.0.0.1:5070, modo teste por padrao)
Criar admin:  python gerenciar.py criar-admin
Na VPS:       deploy/DEPLOY.md
"""
import hmac
import os
import secrets
import time
import uuid
from datetime import datetime, timedelta
from functools import wraps
from pathlib import Path
from urllib.parse import urlparse

from dotenv import load_dotenv
from flask import (Flask, abort, g, jsonify, redirect, render_template, request, send_file, session,
                   url_for)
from werkzeug.security import check_password_hash, generate_password_hash
from werkzeug.utils import secure_filename

load_dotenv(Path(__file__).parent / ".env")

import cripto  # noqa: E402
import db  # noqa: E402
import meta  # noqa: E402

app = Flask(__name__)
app.secret_key = os.environ.get("FLASK_SECRET_KEY") or secrets.token_hex(32)
app.config.update(
    MAX_CONTENT_LENGTH=1024 * 1024 * 1024,
    SESSION_COOKIE_HTTPONLY=True,
    SESSION_COOKIE_SAMESITE="Lax",
    SESSION_COOKIE_SECURE=os.environ.get("COOKIE_SEGURO") == "1",
    PERMANENT_SESSION_LIFETIME=timedelta(days=30),
)

CONFIG = {
    "nome": os.environ.get("NOME_PRODUTO", "Agendador de Reels"),
    "suporte_whatsapp": "".join(ch for ch in os.environ.get("SUPORTE_WHATSAPP", "") if ch.isdigit()),
    "suporte_email": os.environ.get("SUPORTE_EMAIL", ""),
    "preco": os.environ.get("PRECO_TEXTO", "R$ 00/mês"),
    "empresa": os.environ.get("EMPRESA_RAZAO", "[RAZÃO SOCIAL / CNPJ]"),
    "teste_dias": int(os.environ.get("TESTE_DIAS", "7")),
    "modo_teste": os.environ.get("PUBLICAR_DE_VERDADE") != "1",
}
QUOTA_BYTES = int(os.environ.get("QUOTA_MB", "3000")) * 1024 * 1024
EXTENSOES = {".mp4", ".mov", ".m4v"}
LEGENDA_MAX, HASHTAGS_MAX = 2200, 30
STORY_MAX_S, REELS_MIN_S, REELS_MAX_S = 60, 3, 15 * 60
LIMITE_24H = 50

db.iniciar()


@app.context_processor
def _ctx():
    return {"cfg": CONFIG, "usuario": g.get("usuario"), "ativo": db.usuario_ativo(g.get("usuario"))}


# ================================================================ sessao / seguranca

@app.before_request
def carregar_usuario():
    g.usuario = None
    uid = session.get("uid")
    if uid:
        with db.conexao() as con:
            u = con.execute("SELECT * FROM usuarios WHERE id=?", (uid,)).fetchone()
        if not u or u["bloqueado"] or session.get("ver") != u["senha_hash"][-12:]:
            session.clear()
        else:
            g.usuario = u
    # CSRF simples: toda escrita tem que vir do proprio site
    if request.method in ("POST", "PATCH", "PUT", "DELETE"):
        origem = request.headers.get("Origin") or request.headers.get("Referer") or ""
        if origem and urlparse(origem).netloc != request.host:
            abort(403)


def exige_login(f):
    @wraps(f)
    def w(*a, **kw):
        if not g.usuario:
            if request.path.startswith(("/api/", "/arquivo/")):
                return jsonify({"erro": "sessão expirada, entre de novo"}), 401
            return redirect(url_for("entrar", proximo=request.path))
        return f(*a, **kw)
    return w


def exige_ativo(f):
    @wraps(f)
    def w(*a, **kw):
        if not db.usuario_ativo(g.usuario):
            return jsonify({"erro": "Seu acesso está vencido. Fale com o suporte para renovar."}), 402
        return f(*a, **kw)
    return w


def exige_admin(f):
    @wraps(f)
    def w(*a, **kw):
        if not g.usuario or not g.usuario["admin"]:
            abort(404)
        return f(*a, **kw)
    return w


def iniciar_sessao(u):
    session.clear()
    session.permanent = True
    session["uid"] = u["id"]
    session["ver"] = u["senha_hash"][-12:]  # trocar senha derruba outras sessoes
    with db.conexao() as con:
        con.execute("UPDATE usuarios SET ultimo_acesso=? WHERE id=?", (db.agora_iso(), u["id"]))


_tentativas = {}


def limitar(chave, maximo=8, janela=600):
    agora = time.time()
    lista = [t for t in _tentativas.get(chave, []) if agora - t < janela]
    _tentativas[chave] = lista
    if len(lista) >= maximo:
        return True
    lista.append(agora)
    return False


def ip():
    return request.headers.get("X-Real-IP", request.remote_addr)


# ================================================================ site publico

@app.route("/")
def inicio():
    return render_template("site.html")


@app.route("/termos")
def termos():
    return render_template("legal.html", pagina="termos")


@app.route("/privacidade")
def privacidade():
    return render_template("legal.html", pagina="privacidade")


@app.route("/cadastro", methods=["GET", "POST"])
def cadastro():
    erro, f = "", request.form
    if request.method == "POST":
        nome, email = f.get("nome", "").strip(), f.get("email", "").strip().lower()
        senha, whats = f.get("senha", ""), f.get("whatsapp", "").strip()
        if limitar("cad:" + ip(), maximo=5, janela=3600):
            erro = "Muitos cadastros deste endereço. Tente mais tarde."
        elif not nome or "@" not in email or "." not in email.split("@")[-1]:
            erro = "Preencha nome e um e-mail válido."
        elif len(senha) < 8:
            erro = "A senha precisa ter pelo menos 8 caracteres."
        elif not f.get("aceite"):
            erro = "É preciso aceitar os termos de uso e a política de privacidade."
        else:
            ativo_ate = (db.agora().date() + timedelta(days=CONFIG["teste_dias"])).isoformat()
            try:
                with db.conexao() as con:
                    con.execute(
                        "INSERT INTO usuarios (nome, email, whatsapp, senha_hash, ativo_ate, criado_em) VALUES (?,?,?,?,?,?)",
                        (nome, email, whats, generate_password_hash(senha), ativo_ate, db.agora_iso()))
                    u = con.execute("SELECT * FROM usuarios WHERE email=?", (email,)).fetchone()
            except db.sqlite3.IntegrityError:
                erro = "Já existe uma conta com esse e-mail. Entre ou peça ajuda ao suporte."
            else:
                iniciar_sessao(u)
                return redirect(url_for("conectar"))
    return render_template("auth.html", modo="cadastro", erro=erro, form=f)


@app.route("/entrar", methods=["GET", "POST"])
def entrar():
    erro, f = "", request.form
    if request.method == "POST":
        email = f.get("email", "").strip().lower()
        if limitar("login:" + ip()) or limitar("login:" + email, maximo=10):
            erro = "Muitas tentativas. Espere 10 minutos."
        else:
            with db.conexao() as con:
                u = con.execute("SELECT * FROM usuarios WHERE email=?", (email,)).fetchone()
            if u and check_password_hash(u["senha_hash"], f.get("senha", "")):
                if u["bloqueado"]:
                    erro = "Esta conta está bloqueada. Fale com o suporte."
                else:
                    iniciar_sessao(u)
                    proximo = request.args.get("proximo", "")
                    return redirect(proximo if proximo.startswith("/") and not proximo.startswith("//") else url_for("painel"))
            else:
                erro = "E-mail ou senha errados."
    return render_template("auth.html", modo="entrar", erro=erro, form=f)


@app.route("/sair")
def sair():
    session.clear()
    return redirect(url_for("inicio"))


# ================================================================ area do cliente

def contas_do_usuario(uid, incluir_token=False):
    with db.conexao() as con:
        rows = con.execute("SELECT * FROM contas WHERE usuario_id=? AND removida=0 ORDER BY id", (uid,)).fetchall()
    out = []
    for r in rows:
        d = dict(r)
        if not incluir_token:
            d.pop("token_enc", None)
        out.append(d)
    return out


def conta_do_usuario(conta_id):
    with db.conexao() as con:
        c = con.execute("SELECT * FROM contas WHERE id=? AND usuario_id=? AND removida=0",
                        (conta_id, g.usuario["id"])).fetchone()
    return c


@app.route("/painel")
@exige_login
def painel():
    contas = contas_do_usuario(g.usuario["id"])
    if not contas:
        return redirect(url_for("conectar"))
    return render_template("painel.html", contas=contas)


@app.route("/minha-conta", methods=["GET", "POST"])
@exige_login
def minha_conta():
    msg = erro = ""
    if request.method == "POST":
        if not check_password_hash(g.usuario["senha_hash"], request.form.get("atual", "")):
            erro = "Senha atual errada."
        elif len(request.form.get("nova", "")) < 8:
            erro = "A nova senha precisa ter pelo menos 8 caracteres."
        else:
            with db.conexao() as con:
                con.execute("UPDATE usuarios SET senha_hash=? WHERE id=?",
                            (generate_password_hash(request.form["nova"]), g.usuario["id"]))
                u = con.execute("SELECT * FROM usuarios WHERE id=?", (g.usuario["id"],)).fetchone()
            iniciar_sessao(u)
            g.usuario = u
            msg = "Senha trocada."
    return render_template("minha_conta.html", msg=msg, erro=erro, contas=contas_do_usuario(g.usuario["id"]))


# ---------------------------------------------------------------- conectar Instagram

_candidatos = {}  # usuario_id -> (hora, [contas com page_token]) — tokens nunca vao pro navegador


@app.route("/conectar")
@exige_login
def conectar():
    return render_template("conectar.html", contas=contas_do_usuario(g.usuario["id"]))


@app.route("/api/conectar/verificar", methods=["POST"])
@exige_login
def api_conectar_verificar():
    if limitar("conectar:%s" % g.usuario["id"], maximo=15, janela=900):
        return jsonify({"erro": "Muitas tentativas seguidas. Espere alguns minutos."}), 429
    b = request.get_json(force=True) or {}
    try:
        contas = meta.conectar(b.get("app_id", ""), b.get("app_secret", ""), b.get("token", ""))
    except meta.MetaErro as e:
        return jsonify({"erro": str(e)}), 400
    except Exception as e:  # noqa: BLE001
        return jsonify({"erro": f"Não consegui falar com a Meta agora ({type(e).__name__}). Tente de novo."}), 502
    for c in contas:
        c["app_id"] = b["app_id"].strip()
    _candidatos[g.usuario["id"]] = (time.time(), contas)
    ja = {c["ig_user_id"] for c in contas_do_usuario(g.usuario["id"])}
    return jsonify({"contas": [{
        "ig_user_id": c["ig_user_id"], "username": c["username"], "foto_url": c["foto_url"],
        "page_nome": c["page_nome"], "nao_expira": c["token_expira"] == 0, "ja_conectada": c["ig_user_id"] in ja,
    } for c in contas], "max_contas": g.usuario["max_contas"]})


@app.route("/api/conectar/salvar", methods=["POST"])
@exige_login
def api_conectar_salvar():
    escolhidas = set((request.get_json(force=True) or {}).get("ig_user_ids") or [])
    hora, candidatos = _candidatos.get(g.usuario["id"], (0, []))
    if time.time() - hora > 900:
        return jsonify({"erro": "A verificação expirou. Clique em Verificar de novo."}), 400
    novas = [c for c in candidatos if c["ig_user_id"] in escolhidas]
    if not novas:
        return jsonify({"erro": "Escolha pelo menos uma conta."}), 400
    atuais = {c["ig_user_id"] for c in contas_do_usuario(g.usuario["id"])}
    total = len(atuais | {c["ig_user_id"] for c in novas})
    if total > g.usuario["max_contas"]:
        return jsonify({"erro": f"Seu plano permite {g.usuario['max_contas']} conta(s) do Instagram. "
                                "Fale com o suporte para aumentar."}), 400
    with db.conexao() as con:
        for c in novas:
            expira = None if c["token_expira"] == 0 else datetime.fromtimestamp(c["token_expira"]).isoformat()
            con.execute(
                "INSERT INTO contas (usuario_id, ig_user_id, username, foto_url, page_id, page_nome, app_id, token_enc, "
                " token_expira, status, erro, criado_em, removida) VALUES (?,?,?,?,?,?,?,?,?,'ok',NULL,?,0) "
                "ON CONFLICT(usuario_id, ig_user_id) DO UPDATE SET username=excluded.username, foto_url=excluded.foto_url, "
                " page_id=excluded.page_id, page_nome=excluded.page_nome, app_id=excluded.app_id, token_enc=excluded.token_enc, "
                " token_expira=excluded.token_expira, status='ok', erro=NULL, removida=0",
                (g.usuario["id"], c["ig_user_id"], c["username"], c["foto_url"], c["page_id"], c["page_nome"],
                 c["app_id"], cripto.cifrar(c["page_token"]), expira, db.agora_iso()))
    _candidatos.pop(g.usuario["id"], None)
    return jsonify({"ok": True})


@app.route("/api/contas/<int:conta_id>/remover", methods=["POST"])
@exige_login
def api_conta_remover(conta_id):
    if not conta_do_usuario(conta_id):
        return jsonify({"erro": "conta não encontrada"}), 404
    with db.conexao() as con:
        con.execute("UPDATE contas SET removida=1, token_enc='' WHERE id=?", (conta_id,))
        n = con.execute("UPDATE posts SET status=?, erro='Conta removida.' WHERE conta_id=? AND status=?",
                        (db.CANCELADO, conta_id, db.AGENDADO)).rowcount
    return jsonify({"ok": True, "cancelados": n})


# ---------------------------------------------------------------- arquivos

def uso_disco(uid):
    with db.conexao() as con:
        return con.execute("SELECT COALESCE(SUM(tamanho),0) FROM arquivos WHERE usuario_id=? AND apagado=0",
                           (uid,)).fetchone()[0]


@app.route("/api/upload", methods=["POST"])
@exige_login
@exige_ativo
def api_upload():
    f = request.files.get("arquivo")
    if not f or not f.filename:
        return jsonify({"erro": "nenhum arquivo"}), 400
    ext = Path(f.filename).suffix.lower()
    if ext not in EXTENSOES:
        return jsonify({"erro": f"formato {ext or '?'} não aceito (use mp4 ou mov)"}), 400
    if uso_disco(g.usuario["id"]) > QUOTA_BYTES:
        return jsonify({"erro": "Seu espaço de vídeos está cheio. Vídeos publicados são apagados sozinhos em alguns dias."}), 400
    pasta = db.ARQUIVOS_DIR / str(g.usuario["id"])
    pasta.mkdir(exist_ok=True)
    destino = pasta / f"{uuid.uuid4().hex}{ext}"
    f.save(destino)
    with db.conexao() as con:
        cur = con.execute(
            "INSERT INTO arquivos (usuario_id, nome_original, caminho, tamanho, duracao_s, criado_em) VALUES (?,?,?,?,?,?)",
            (g.usuario["id"], secure_filename(f.filename) or "video" + ext, str(destino), destino.stat().st_size,
             request.form.get("duracao", type=float), db.agora_iso()))
    return jsonify({"id": cur.lastrowid, "nome": f.filename})


@app.route("/arquivo/<int:arquivo_id>")
@exige_login
def arquivo(arquivo_id):
    with db.conexao() as con:
        row = con.execute("SELECT caminho FROM arquivos WHERE id=? AND usuario_id=? AND apagado=0",
                          (arquivo_id, g.usuario["id"])).fetchone()
    if not row or not Path(row["caminho"]).exists():
        abort(404)
    return send_file(row["caminho"], conditional=True, max_age=3600)


# ---------------------------------------------------------------- agendamento

def validar_post(p, duracao=None):
    if p.get("tipo") not in ("reels", "story"):
        return "escolha Reels ou Story"
    try:
        quando = datetime.fromisoformat(p.get("quando", ""))
    except ValueError:
        return "data/hora inválida"
    if quando < db.agora().replace(second=0) and not p.get("permitir_passado"):
        return "data/hora já passou"
    if quando > db.agora() + timedelta(days=180):
        return "dá para agendar até 6 meses à frente"
    legenda = p.get("legenda") or ""
    if p["tipo"] == "reels":
        if len(legenda) > LEGENDA_MAX:
            return f"legenda passa de {LEGENDA_MAX} caracteres"
        if legenda.count("#") > HASHTAGS_MAX:
            return f"mais de {HASHTAGS_MAX} hashtags (o Instagram recusa)"
    if duracao:
        if p["tipo"] == "story" and duracao > STORY_MAX_S + 0.5:
            return f"vídeo tem {int(duracao)}s, e o Story aceita no máximo {STORY_MAX_S}s"
        if p["tipo"] == "reels" and not (REELS_MIN_S <= duracao <= REELS_MAX_S):
            return "Reels precisa ter entre 3s e 15min"
    return None


def avisos_limite(conta_id):
    with db.conexao() as con:
        horas = [datetime.fromisoformat(r[0]) for r in con.execute(
            "SELECT agendado_para FROM posts WHERE conta_id=? AND status IN (?,?) ORDER BY agendado_para",
            (conta_id, db.AGENDADO, db.PUBLICANDO))]
    j = 0
    for i, h in enumerate(horas):
        while (h - horas[j]).total_seconds() >= 86400:
            j += 1
        if i - j + 1 > LIMITE_24H:
            return [f"Mais de {LIMITE_24H} posts em 24h a partir de {horas[j]:%d/%m %H:%M}. O Instagram recusa o excesso."]
    return []


@app.route("/api/agendar-lote", methods=["POST"])
@exige_login
@exige_ativo
def api_agendar_lote():
    b = request.get_json(force=True) or {}
    conta = conta_do_usuario(b.get("conta_id") or 0)
    if not conta:
        return jsonify({"erro": "Escolha a conta do Instagram."}), 400
    if conta["status"] != "ok":
        return jsonify({"erro": "Essa conta está desconectada. Reconecte em Contas antes de agendar."}), 400
    itens = b.get("itens") or []
    if not itens:
        return jsonify({"erro": "lote vazio"}), 400
    if len(itens) > 200:
        return jsonify({"erro": "no máximo 200 publicações por lote"}), 400
    with db.conexao() as con:
        duracoes = {r["id"]: r["duracao_s"] for r in con.execute(
            "SELECT id, duracao_s FROM arquivos WHERE usuario_id=? AND apagado=0", (g.usuario["id"],))}
    erros = []
    for i, p in enumerate(itens):
        if p.get("arquivo_id") not in duracoes:
            erros.append({"indice": i, "erro": "vídeo não encontrado no servidor"})
            continue
        e = validar_post(p, p.get("duracao") or duracoes[p["arquivo_id"]])
        if e:
            erros.append({"indice": i, "erro": e})
    if erros:
        return jsonify({"erro": "alguns itens têm problema", "itens": erros}), 400
    lote = uuid.uuid4().hex[:8]
    with db.conexao() as con:
        for p in itens:
            if p.get("duracao"):
                con.execute("UPDATE arquivos SET duracao_s=? WHERE id=?", (p["duracao"], p["arquivo_id"]))
            con.execute(
                "INSERT INTO posts (usuario_id, conta_id, arquivo_id, tipo, legenda, agendado_para, status, lote, criado_em) "
                "VALUES (?,?,?,?,?,?,?,?,?)",
                (g.usuario["id"], conta["id"], p["arquivo_id"], p["tipo"],
                 (p.get("legenda") or None) if p["tipo"] == "reels" else None,
                 datetime.fromisoformat(p["quando"]).replace(second=0).isoformat(), db.AGENDADO, lote, db.agora_iso()))
    return jsonify({"ok": True, "total": len(itens), "avisos": avisos_limite(conta["id"])})


@app.route("/api/fila")
@exige_login
def api_fila():
    conta_id = request.args.get("conta_id", type=int)
    ver = request.args.get("ver", "proximos")
    sql = ("SELECT p.*, a.nome_original, a.duracao_s, a.apagado FROM posts p JOIN arquivos a ON a.id=p.arquivo_id "
           "WHERE p.usuario_id=? AND p.conta_id=? ")
    if ver == "proximos":
        sql += "AND p.status IN ('AGENDADO','PUBLICANDO','ERRO') ORDER BY p.agendado_para, p.id"
    else:
        sql += "AND p.status IN ('PUBLICADO','CANCELADO') ORDER BY COALESCE(p.publicado_em, p.agendado_para) DESC LIMIT 300"
    with db.conexao() as con:
        rows = [dict(r) for r in con.execute(sql, (g.usuario["id"], conta_id))]
        resumo = {r[0]: r[1] for r in con.execute(
            "SELECT status, COUNT(*) FROM posts WHERE usuario_id=? AND conta_id=? GROUP BY status", (g.usuario["id"], conta_id))}
    return jsonify({"itens": rows, "resumo": resumo})


@app.route("/api/post/<int:post_id>", methods=["PATCH"])
@exige_login
@exige_ativo
def api_post_editar(post_id):
    b = request.get_json(force=True) or {}
    with db.conexao() as con:
        row = con.execute("SELECT p.*, a.duracao_s, a.apagado FROM posts p JOIN arquivos a ON a.id=p.arquivo_id "
                          "WHERE p.id=? AND p.usuario_id=?", (post_id, g.usuario["id"])).fetchone()
        if not row:
            return jsonify({"erro": "post não existe"}), 404
        if row["status"] not in (db.AGENDADO, db.ERRO, db.CANCELADO):
            return jsonify({"erro": f"o post já está {row['status'].lower()}, não dá para mudar"}), 409
        if b.get("acao") == "cancelar":
            con.execute("UPDATE posts SET status=? WHERE id=?", (db.CANCELADO, post_id))
            return jsonify({"ok": True})
        if row["apagado"]:
            return jsonify({"erro": "o vídeo desse post já foi apagado do servidor; envie de novo"}), 409
        novo = {"tipo": b.get("tipo", row["tipo"]), "legenda": b.get("legenda", row["legenda"]),
                "quando": b.get("quando", row["agendado_para"])}
        if b.get("acao") == "publicar_agora":
            novo.update(quando=db.agora_iso(), permitir_passado=True)
        e = validar_post(novo, row["duracao_s"])
        if e:
            return jsonify({"erro": e}), 400
        con.execute("UPDATE posts SET tipo=?, legenda=?, agendado_para=?, status=?, tentativas=0, erro=NULL WHERE id=?",
                    (novo["tipo"], novo["legenda"] if novo["tipo"] == "reels" else None,
                     datetime.fromisoformat(novo["quando"]).replace(second=0).isoformat(), db.AGENDADO, post_id))
    return jsonify({"ok": True})


# ================================================================ admin (dono do produto)

@app.route("/admin")
@exige_admin
def admin():
    with db.conexao() as con:
        usuarios = [dict(r) for r in con.execute(
            "SELECT u.*, "
            " (SELECT COUNT(*) FROM contas c WHERE c.usuario_id=u.id AND c.removida=0) AS n_contas, "
            " (SELECT COUNT(*) FROM contas c WHERE c.usuario_id=u.id AND c.removida=0 AND c.status!='ok') AS n_desconectadas, "
            " (SELECT GROUP_CONCAT('@'||c.username, ' ') FROM contas c WHERE c.usuario_id=u.id AND c.removida=0) AS arrobas, "
            " (SELECT COUNT(*) FROM posts p WHERE p.usuario_id=u.id AND p.status='AGENDADO') AS n_agendados, "
            " (SELECT COUNT(*) FROM posts p WHERE p.usuario_id=u.id AND p.status='PUBLICADO' AND p.publicado_em >= ?) AS n_pub30, "
            " (SELECT COUNT(*) FROM posts p WHERE p.usuario_id=u.id AND p.status='ERRO') AS n_erros "
            "FROM usuarios u ORDER BY u.id DESC", ((db.agora() - timedelta(days=30)).isoformat(),))]
    hoje = db.hoje_iso()
    for u in usuarios:
        u["situacao"] = ("bloqueado" if u["bloqueado"] else "admin" if u["admin"]
                         else "ativo" if (u["ativo_ate"] or "") >= hoje else "vencido")
    resumo = {
        "total": len(usuarios),
        "ativos": sum(u["situacao"] == "ativo" for u in usuarios),
        "vencidos": sum(u["situacao"] == "vencido" for u in usuarios),
        "vencem_7d": sum(u["situacao"] == "ativo" and u["ativo_ate"] <= (db.agora().date() + timedelta(days=7)).isoformat()
                         for u in usuarios),
    }
    return render_template("admin.html", usuarios=usuarios, resumo=resumo, hoje=hoje)


@app.route("/admin/usuario/<int:uid>", methods=["POST"])
@exige_admin
def admin_usuario(uid):
    b = request.get_json(force=True) or {}
    acao = b.get("acao")
    with db.conexao() as con:
        u = con.execute("SELECT * FROM usuarios WHERE id=?", (uid,)).fetchone()
        if not u:
            return jsonify({"erro": "usuário não existe"}), 404
        if acao == "estender":
            dias = int(b.get("dias", 30))
            base = max(db.agora().date(), datetime.fromisoformat(u["ativo_ate"]).date() if u["ativo_ate"] else db.agora().date())
            nova = (base + timedelta(days=dias)).isoformat()
            con.execute("UPDATE usuarios SET ativo_ate=? WHERE id=?", (nova, uid))
            return jsonify({"ok": True, "msg": f"Liberado até {datetime.fromisoformat(nova):%d/%m/%Y}."})
        if acao == "data":
            nova = datetime.fromisoformat(b["data"]).date().isoformat()
            con.execute("UPDATE usuarios SET ativo_ate=? WHERE id=?", (nova, uid))
            return jsonify({"ok": True, "msg": f"Liberado até {datetime.fromisoformat(nova):%d/%m/%Y}."})
        if acao in ("bloquear", "desbloquear"):
            if uid == g.usuario["id"]:
                return jsonify({"erro": "não dá para bloquear você mesmo"}), 400
            con.execute("UPDATE usuarios SET bloqueado=? WHERE id=?", (1 if acao == "bloquear" else 0, uid))
            return jsonify({"ok": True, "msg": "Bloqueado." if acao == "bloquear" else "Desbloqueado."})
        if acao == "max_contas":
            n = max(1, min(50, int(b.get("n", 1))))
            con.execute("UPDATE usuarios SET max_contas=? WHERE id=?", (n, uid))
            return jsonify({"ok": True, "msg": f"Agora pode conectar {n} conta(s)."})
        if acao == "observacao":
            con.execute("UPDATE usuarios SET observacao=? WHERE id=?", (b.get("texto", "")[:500], uid))
            return jsonify({"ok": True, "msg": "Anotação salva."})
        if acao == "resetar_senha":
            temp = secrets.token_urlsafe(6)
            con.execute("UPDATE usuarios SET senha_hash=? WHERE id=?", (generate_password_hash(temp), uid))
            return jsonify({"ok": True, "msg": f"Senha provisória: {temp}  (envie ao cliente; ele troca em Minha conta)",
                            "senha": temp})
    return jsonify({"erro": "ação desconhecida"}), 400


@app.route("/saude")
def saude():
    return "ok"


if __name__ == "__main__":
    port = int(os.environ.get("PORTA", 5070))
    print(f"{CONFIG['nome']} em http://127.0.0.1:{port}  (modo teste={CONFIG['modo_teste']})")
    app.run(host="127.0.0.1", port=port, debug=False, threaded=True)
