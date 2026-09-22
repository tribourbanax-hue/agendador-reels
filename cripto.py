"""
Criptografa os tokens do Instagram antes de guardar no banco.

A chave fica SO no .env do servidor (CHAVE_MESTRA). Se alguem copiar o
arquivo do banco sem o .env, nao consegue usar os tokens dos clientes.
Perder a CHAVE_MESTRA = todos os clientes precisam reconectar o Instagram.
Gerar: python -c "from cryptography.fernet import Fernet;print(Fernet.generate_key().decode())"
"""
import os

from cryptography.fernet import Fernet, InvalidToken

_f = None


def _fernet():
    global _f
    if _f is None:
        chave = os.environ.get("CHAVE_MESTRA", "")
        if not chave:
            raise RuntimeError("CHAVE_MESTRA nao configurada no .env")
        _f = Fernet(chave.encode())
    return _f


def cifrar(texto: str) -> str:
    return _fernet().encrypt(texto.encode()).decode()


def decifrar(cifrado: str) -> str:
    try:
        return _fernet().decrypt(cifrado.encode()).decode()
    except InvalidToken as e:
        raise RuntimeError("token nao pode ser lido (CHAVE_MESTRA mudou?)") from e
