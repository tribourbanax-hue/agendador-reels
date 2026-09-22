"""
Banco SQLite do Agendador (multi-cliente).

  usuarios — quem assina (login por e-mail/senha; admin libera acesso por data)
  contas   — contas do Instagram que cada usuario conectou (token criptografado)
  arquivos — videos enviados (cada um pertence a um usuario)
  posts    — publicacoes agendadas (usuario + conta + arquivo)

Horarios em texto ISO no fuso de Sao Paulo, sem offset.
"""
import os
import sqlite3
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

BASE_DIR = Path(__file__).parent
DADOS_DIR = Path(os.environ.get("DADOS_DIR", BASE_DIR / "dados"))
ARQUIVOS_DIR = DADOS_DIR / "arquivos"
DB_PATH = DADOS_DIR / "agendador.db"
FUSO = ZoneInfo(os.environ.get("FUSO", "America/Sao_Paulo"))

ARQUIVOS_DIR.mkdir(parents=True, exist_ok=True)

AGENDADO = "AGENDADO"
PUBLICANDO = "PUBLICANDO"
PUBLICADO = "PUBLICADO"
ERRO = "ERRO"
CANCELADO = "CANCELADO"

SCHEMA = """
CREATE TABLE IF NOT EXISTS usuarios (
  id            INTEGER PRIMARY KEY AUTOINCREMENT,
  nome          TEXT NOT NULL,
  email         TEXT NOT NULL UNIQUE,
  whatsapp      TEXT,
  senha_hash    TEXT NOT NULL,
  admin         INTEGER NOT NULL DEFAULT 0,
  ativo_ate     TEXT,                   -- data (YYYY-MM-DD) ate quando pode agendar
  bloqueado     INTEGER NOT NULL DEFAULT 0,
  max_contas    INTEGER NOT NULL DEFAULT 1,
  observacao    TEXT,
  criado_em     TEXT NOT NULL,
  ultimo_acesso TEXT
);
CREATE TABLE IF NOT EXISTS contas (
  id            INTEGER PRIMARY KEY AUTOINCREMENT,
  usuario_id    INTEGER NOT NULL REFERENCES usuarios(id),
  ig_user_id    TEXT NOT NULL,
  username      TEXT,
  foto_url      TEXT,
  page_id       TEXT,
  page_nome     TEXT,
  app_id        TEXT,
  token_enc     TEXT NOT NULL,
  token_expira  TEXT,                   -- NULL = nao expira (token de Pagina)
  status        TEXT NOT NULL DEFAULT 'ok',   -- 'ok' | 'desconectada'
  erro          TEXT,
  criado_em     TEXT NOT NULL,
  removida      INTEGER NOT NULL DEFAULT 0,
  UNIQUE (usuario_id, ig_user_id)
);
CREATE TABLE IF NOT EXISTS arquivos (
  id            INTEGER PRIMARY KEY AUTOINCREMENT,
  usuario_id    INTEGER NOT NULL REFERENCES usuarios(id),
  nome_original TEXT NOT NULL,
  caminho       TEXT NOT NULL,
  tamanho       INTEGER NOT NULL,
  duracao_s     REAL,
  apagado       INTEGER NOT NULL DEFAULT 0,
  criado_em     TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS posts (
  id            INTEGER PRIMARY KEY AUTOINCREMENT,
  usuario_id    INTEGER NOT NULL REFERENCES usuarios(id),
  conta_id      INTEGER NOT NULL REFERENCES contas(id),
  arquivo_id    INTEGER NOT NULL REFERENCES arquivos(id),
  tipo          TEXT NOT NULL,          -- 'reels' | 'story'
  legenda       TEXT,
  agendado_para TEXT NOT NULL,
  status        TEXT NOT NULL,
  tentativas    INTEGER NOT NULL DEFAULT 0,
  media_id      TEXT,
  permalink     TEXT,
  erro          TEXT,
  lote          TEXT,
  criado_em     TEXT NOT NULL,
  publicado_em  TEXT
);
CREATE INDEX IF NOT EXISTS idx_posts_fila ON posts(status, agendado_para);
CREATE INDEX IF NOT EXISTS idx_posts_usuario ON posts(usuario_id, conta_id, status);
"""


def agora():
    return datetime.now(FUSO).replace(tzinfo=None, microsecond=0)


def agora_iso():
    return agora().isoformat()


def hoje_iso():
    return agora().date().isoformat()


@contextmanager
def conexao():
    con = sqlite3.connect(DB_PATH, timeout=30)
    con.row_factory = sqlite3.Row
    con.execute("PRAGMA journal_mode=WAL")
    con.execute("PRAGMA foreign_keys=ON")
    try:
        yield con
        con.commit()
    finally:
        con.close()


def iniciar():
    with conexao() as con:
        con.executescript(SCHEMA)


def usuario_ativo(u):
    """Pode agendar/publicar? (nao bloqueado e dentro da data liberada)."""
    if not u or u["bloqueado"]:
        return False
    if u["admin"]:
        return True
    return bool(u["ativo_ate"]) and u["ativo_ate"] >= hoje_iso()
