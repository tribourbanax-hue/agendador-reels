"""
Comandos do dono do produto (rodar no servidor, dentro da pasta do app).

  python gerenciar.py criar-admin        # cria (ou promove) o seu usuario administrador
  python gerenciar.py listar             # lista clientes e validade
  python gerenciar.py gerar-chaves       # gera FLASK_SECRET_KEY e CHAVE_MESTRA pro .env
"""
import getpass
import secrets
import sys
from pathlib import Path

from dotenv import load_dotenv

load_dotenv(Path(__file__).parent / ".env")

import db  # noqa: E402


def criar_admin():
    from werkzeug.security import generate_password_hash
    db.iniciar()
    email = input("E-mail do administrador: ").strip().lower()
    nome = input("Nome: ").strip() or "Administrador"
    senha = getpass.getpass("Senha (min. 8, nao aparece ao digitar): ")
    if len(senha) < 8:
        sys.exit("Senha curta demais.")
    with db.conexao() as con:
        u = con.execute("SELECT id FROM usuarios WHERE email=?", (email,)).fetchone()
        if u:
            con.execute("UPDATE usuarios SET admin=1, senha_hash=?, bloqueado=0, max_contas=50 WHERE id=?",
                        (generate_password_hash(senha), u["id"]))
            print("Usuario existente promovido a administrador.")
        else:
            con.execute("INSERT INTO usuarios (nome, email, senha_hash, admin, max_contas, criado_em) VALUES (?,?,?,1,50,?)",
                        (nome, email, generate_password_hash(senha), db.agora_iso()))
            print("Administrador criado. Entre em /entrar e acesse /admin.")


def listar():
    db.iniciar()
    with db.conexao() as con:
        for u in con.execute("SELECT id, nome, email, ativo_ate, admin, bloqueado FROM usuarios ORDER BY id"):
            tag = "ADMIN" if u["admin"] else "BLOQ" if u["bloqueado"] else (u["ativo_ate"] or "-")
            print(f"{u['id']:>4}  {tag:<10}  {u['email']:<35}  {u['nome']}")


def gerar_chaves():
    from cryptography.fernet import Fernet
    print(f"FLASK_SECRET_KEY={secrets.token_hex(32)}")
    print(f"CHAVE_MESTRA={Fernet.generate_key().decode()}")
    print("# GUARDE a CHAVE_MESTRA num lugar seguro: sem ela os tokens dos clientes nao abrem.")


if __name__ == "__main__":
    cmd = sys.argv[1] if len(sys.argv) > 1 else ""
    {"criar-admin": criar_admin, "listar": listar, "gerar-chaves": gerar_chaves}.get(
        cmd, lambda: print(__doc__))()
