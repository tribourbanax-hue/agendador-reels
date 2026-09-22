"""
Conexao da conta do cliente com a Meta (assistente "Conectar Instagram").

O cliente cola, do app Meta DELE: App ID, token gerado no Graph API Explorer
e (se o token for curto) a Chave Secreta. Aqui:
  1. troca o token por um de longa duracao (precisa da Chave Secreta);
  2. lista as Paginas do Facebook dele que tem Instagram profissional ligado;
  3. pega o token DA PAGINA escolhida — derivado de token longo, ele NAO
     expira (expires_at=0, testado 22/09/2026 com upload+processamento real).
Resultado: o cliente conecta uma vez e esquece.
"""
import time

import requests

GRAPH = "https://graph.facebook.com/v21.0"
TIMEOUT = (10, 30)
PERMISSOES_NECESSARIAS = {"instagram_basic", "instagram_content_publish", "pages_show_list"}


class MetaErro(Exception):
    pass


def _get(path, **params):
    r = requests.get(f"{GRAPH}/{path}", params=params, timeout=TIMEOUT)
    data = r.json()
    if "error" in data:
        raise MetaErro(traduzir_erro(data["error"]))
    return data


def traduzir_erro(err):
    code, msg = err.get("code"), err.get("message", "")
    if code == 190:
        return "Token inválido ou expirado. Gere um token novo no Graph API Explorer."
    if code == 1 and "client secret" in msg.lower():
        return "Chave Secreta não confere com esse App ID. Copie de novo em Configurações do app > Básico."
    if code == 101 or "application id" in msg.lower():
        return "App ID inválido. Confira o número em Configurações do app > Básico."
    if code in (10, 200) or "permission" in msg.lower():
        return "Faltou permissão no token. Gere de novo marcando todas as permissões do passo 4."
    return f"A Meta recusou: {msg}"


def token_longo(app_id, app_secret, token):
    data = _get("oauth/access_token", grant_type="fb_exchange_token",
                client_id=app_id, client_secret=app_secret, fb_exchange_token=token)
    return data["access_token"]


def info_token(token):
    d = _get("debug_token", input_token=token, access_token=token).get("data", {})
    if not d.get("is_valid"):
        raise MetaErro("Token inválido ou expirado. Gere um token novo no Graph API Explorer.")
    return d


def listar_contas_instagram(user_token):
    """Paginas do usuario que tem Instagram profissional ligado."""
    data = _get("me/accounts", limit=100, access_token=user_token,
                fields="id,name,access_token,instagram_business_account{id,username,profile_picture_url}")
    contas = []
    for p in data.get("data", []):
        ig = p.get("instagram_business_account")
        if ig:
            contas.append({
                "page_id": p["id"], "page_nome": p["name"], "page_token": p["access_token"],
                "ig_user_id": ig["id"], "username": ig.get("username"), "foto_url": ig.get("profile_picture_url"),
            })
    return contas


def conectar(app_id, app_secret, token):
    """Valida tudo e devolve as contas encontradas. Levanta MetaErro com mensagem pro cliente.

    A Chave Secreta e opcional: serve pra trocar um token curto (~1h) por um longo.
    Se o token colado ja for longo, da pra seguir sem ela."""
    app_id, app_secret, token = app_id.strip(), app_secret.strip(), token.strip()
    if not (app_id and token):
        raise MetaErro("Preencha o ID do app e o token.")
    if not app_id.isdigit():
        raise MetaErro("O ID do app tem só números. Confira em Configurações do app > Básico.")
    longo = token_longo(app_id, app_secret, token) if app_secret else token
    info = info_token(longo)
    expira = info.get("expires_at") or 0
    if expira and expira - time.time() < 7 * 86400:
        raise MetaErro("Esse token é de curta duração (vence em horas). Preencha a Chave Secreta do app "
                       "(passo 3) para o sistema trocar por um acesso que não expira.")
    if str(info.get("app_id")) != app_id:
        raise MetaErro("Esse token foi gerado em OUTRO app. No Graph API Explorer, selecione o app certo antes de gerar.")
    faltando = PERMISSOES_NECESSARIAS - set(info.get("scopes", []))
    if faltando:
        raise MetaErro("O token está sem as permissões: " + ", ".join(sorted(faltando)) +
                       ". Gere de novo marcando todas as do passo 4.")
    contas = listar_contas_instagram(longo)
    if not contas:
        raise MetaErro("Nenhum Instagram profissional encontrado. O Instagram precisa ser conta Profissional "
                       "(Empresa ou Criador) e estar ligado a uma Página do Facebook que você administra.")
    for c in contas:
        pinfo = _get("debug_token", input_token=c["page_token"], access_token=longo).get("data", {})
        c["token_expira"] = pinfo.get("expires_at") or 0
    return contas
