# Agendador de Reels e Stories (produto)

Site onde cada cliente cria conta, conecta o próprio Instagram e agenda Reels e Stories em lote.
O servidor publica sozinho, na hora marcada. Você (dono) libera e renova o acesso em `/admin`.

- **Vender e operar:** `GUIA-DO-DONO.md`
- **Colocar no ar:** `deploy/DEPLOY.md`
- **Rodar no PC (modo teste, nada vai ao ar):** `python gerenciar.py gerar-chaves` → montar `.env` a partir do
  `.env.example` → `python gerenciar.py criar-admin` → `python app.py` (http://127.0.0.1:5070) e `python worker.py`.

| Arquivo | O que faz |
|---|---|
| `app.py` | site de vendas, cadastro/login, painel do cliente, assistente de conexão, /admin |
| `worker.py` | publica os posts vencidos de todos os clientes ativos |
| `meta.py` | valida as chaves do cliente e troca por token de Página (não expira) |
| `ig_client.py` | envio de vídeo e publicação na API do Instagram (upload resumível) |
| `cripto.py` | criptografa os tokens no banco (`CHAVE_MESTRA`) |
| `db.py` | SQLite em `dados/` |
| `gerenciar.py` | criar admin, listar clientes, gerar chaves |

Nasceu do `decorcolors-publicador` (uso interno da Decor Colors), que continua separado.
