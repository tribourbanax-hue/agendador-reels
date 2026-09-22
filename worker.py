"""
Worker — publica na hora marcada, para todos os clientes.

Roda sem parar (servico systemd `agendador-worker`). A cada 30s pega os
posts AGENDADO vencidos de clientes ATIVOS e publica cada um com o token da
conta do Instagram daquele cliente.

Seguranca:
  - PUBLICAR_DE_VERDADE != 1 -> modo teste (sobe e processa, nao publica).
  - Trava atomica por post (nunca duplica).
  - Falha temporaria: 3 tentativas, 10 min entre elas.
  - Token recusado pela Meta (erro 190) -> conta marcada 'desconectada',
    posts dela viram ERRO com aviso pra reconectar.
  - Atrasado mais que ATRASO_MAX_H (servidor caiu / cliente vencido) nao sai sozinho.
"""
import argparse
import logging
import os
import time
from datetime import datetime, timedelta
from logging.handlers import RotatingFileHandler
from pathlib import Path

from dotenv import load_dotenv

load_dotenv(Path(__file__).parent / ".env")

import cripto  # noqa: E402
import db  # noqa: E402
from ig_client import IGClient  # noqa: E402

PUBLICAR_DE_VERDADE = os.environ.get("PUBLICAR_DE_VERDADE") == "1"
INTERVALO_S = 30
MAX_TENTATIVAS = 3
ESPERA_RETENTATIVA = timedelta(minutes=10)
ATRASO_MAX = timedelta(hours=float(os.environ.get("ATRASO_MAX_H", "12")))
APAGAR_ARQUIVO_APOS_DIAS = int(os.environ.get("APAGAR_ARQUIVO_APOS_DIAS", "7"))

LOG_DIR = Path(os.environ.get("LOG_DIR", Path(__file__).parent / "logs"))
LOG_DIR.mkdir(exist_ok=True)
log = logging.getLogger("worker")
log.setLevel(logging.INFO)
_h = RotatingFileHandler(LOG_DIR / "worker.log", maxBytes=5_000_000, backupCount=5, encoding="utf-8")
_h.setFormatter(logging.Formatter("%(asctime)s %(message)s", "%Y-%m-%d %H:%M:%S"))
log.addHandler(_h)
log.addHandler(logging.StreamHandler())


def travar_proximo():
    """Pega UM post vencido de cliente ativo, com conta ok, e marca PUBLICANDO."""
    with db.conexao() as con:
        row = con.execute(
            "SELECT p.*, a.caminho, a.nome_original, c.token_enc, c.ig_user_id, c.username, c.status AS conta_status "
            "FROM posts p JOIN arquivos a ON a.id=p.arquivo_id JOIN contas c ON c.id=p.conta_id "
            "JOIN usuarios u ON u.id=p.usuario_id "
            "WHERE p.status=? AND p.agendado_para<=? AND u.bloqueado=0 "
            "  AND (u.admin=1 OR u.ativo_ate >= ?) "
            "ORDER BY p.agendado_para, p.id LIMIT 1",
            (db.AGENDADO, db.agora_iso(), db.hoje_iso()),
        ).fetchone()
        if not row:
            return None
        cur = con.execute("UPDATE posts SET status=?, tentativas=tentativas+1 WHERE id=? AND status=?",
                          (db.PUBLICANDO, row["id"], db.AGENDADO))
        return dict(row) if cur.rowcount == 1 else None


def finalizar(post_id, **campos):
    sets = ", ".join(f"{k}=?" for k in campos)
    with db.conexao() as con:
        con.execute(f"UPDATE posts SET {sets} WHERE id=?", (*campos.values(), post_id))


def desconectar_conta(conta_id, msg):
    with db.conexao() as con:
        con.execute("UPDATE contas SET status='desconectada', erro=? WHERE id=?", (msg, conta_id))
        con.execute("UPDATE posts SET status=?, erro=? WHERE conta_id=? AND status=?",
                    (db.ERRO, "A conta do Instagram foi desconectada. Reconecte em 'Contas' e reagende.",
                     conta_id, db.AGENDADO))


def publicar(post):
    rotulo = f"#{post['id']} u{post['usuario_id']} @{post['username']} {post['tipo']} {post['agendado_para']}"
    atraso = db.agora() - datetime.fromisoformat(post["agendado_para"])
    if atraso > ATRASO_MAX:
        finalizar(post["id"], status=db.ERRO,
                  erro=f"Não publicado: passou {int(atraso.total_seconds() // 3600)}h do horário. "
                       "Reagende ou use 'Publicar agora'.")
        log.info(f"{rotulo}: atrasado {atraso} -> ERRO")
        return
    if post["conta_status"] != "ok":
        finalizar(post["id"], status=db.ERRO, erro="A conta do Instagram está desconectada. Reconecte em 'Contas'.")
        return
    caminho = Path(post["caminho"])
    if not caminho.exists():
        finalizar(post["id"], status=db.ERRO, erro="O arquivo de vídeo não existe mais no servidor.")
        return

    log.info(f"{rotulo}: publicando (tentativa {post['tentativas'] + 1}, de_verdade={PUBLICAR_DE_VERDADE})")
    try:
        cliente = IGClient(cripto.decifrar(post["token_enc"]), post["ig_user_id"])
        if post["tipo"] == "reels":
            res = cliente.publish_reel(caminho, post["legenda"] or "", confirm=PUBLICAR_DE_VERDADE)
        else:
            res = cliente.publish_story(caminho, confirm=PUBLICAR_DE_VERDADE)
    except Exception as e:  # noqa: BLE001
        msg = str(e)[:800]
        if '"code":190' in msg.replace(" ", "") or "OAuthException" in msg and "190" in msg:
            desconectar_conta(post["conta_id"], msg)
            finalizar(post["id"], status=db.ERRO,
                      erro="A Meta recusou o acesso (conexão removida ou senha do Facebook trocada). "
                           "Reconecte em 'Contas' e reagende.")
            log.info(f"{rotulo}: token recusado -> conta desconectada")
            return
        if post["tentativas"] + 1 >= MAX_TENTATIVAS:
            finalizar(post["id"], status=db.ERRO, erro=msg)
            log.info(f"{rotulo}: ERRO definitivo: {msg}")
        else:
            nova = (db.agora() + ESPERA_RETENTATIVA).isoformat()
            finalizar(post["id"], status=db.AGENDADO, agendado_para=nova, erro=f"Tentativa falhou, vai tentar de novo: {msg}")
            log.info(f"{rotulo}: falhou, nova tentativa {nova}: {msg}")
        return

    if not PUBLICAR_DE_VERDADE:
        finalizar(post["id"], status=db.PUBLICADO, media_id=f"TESTE-{res['container_id']}",
                  publicado_em=db.agora_iso(), erro="Modo teste: vídeo processado, nada foi publicado.")
        log.info(f"{rotulo}: [TESTE] ok, nada publicado")
        return
    media_id = res.get("media_id")
    link = cliente.permalink(media_id) if post["tipo"] == "reels" else None
    finalizar(post["id"], status=db.PUBLICADO, media_id=media_id, permalink=link, publicado_em=db.agora_iso(), erro=None)
    log.info(f"{rotulo}: PUBLICADO {media_id}")


def destravar_orfaos():
    with db.conexao() as con:
        n = con.execute("UPDATE posts SET status=?, erro=? WHERE status=?",
                        (db.ERRO, "O servidor reiniciou durante a publicação. Confira no Instagram se saiu antes de reagendar.",
                         db.PUBLICANDO)).rowcount
    if n:
        log.info(f"{n} post(s) orfao(s) -> ERRO")


def limpar_arquivos_antigos():
    limite = (db.agora() - timedelta(days=APAGAR_ARQUIVO_APOS_DIAS)).isoformat()
    with db.conexao() as con:
        rows = con.execute(
            "SELECT a.id, a.caminho FROM arquivos a WHERE a.apagado=0 AND a.criado_em < ? AND NOT EXISTS ("
            " SELECT 1 FROM posts p WHERE p.arquivo_id=a.id AND (p.status IN (?,?,?) OR p.publicado_em >= ?))",
            (limite, db.AGENDADO, db.PUBLICANDO, db.ERRO, limite)).fetchall()
        for r in rows:
            p = Path(r["caminho"])
            if p.exists():
                p.unlink()
            con.execute("UPDATE arquivos SET apagado=1 WHERE id=?", (r["id"],))
    if rows:
        log.info(f"{len(rows)} video(s) antigo(s) apagado(s) do disco")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--uma-vez", action="store_true")
    args = ap.parse_args()
    db.iniciar()
    destravar_orfaos()
    log.info(f"worker iniciado (PUBLICAR_DE_VERDADE={PUBLICAR_DE_VERDADE})")
    ultima_limpeza = 0.0
    while True:
        try:
            while True:
                post = travar_proximo()
                if not post:
                    break
                publicar(post)
            if time.time() - ultima_limpeza > 3600:
                limpar_arquivos_antigos()
                ultima_limpeza = time.time()
        except Exception as e:  # noqa: BLE001
            log.exception(f"erro inesperado: {e}")
        if args.uma_vez:
            break
        time.sleep(INTERVALO_S)


if __name__ == "__main__":
    main()
