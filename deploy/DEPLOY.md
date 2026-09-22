# Colocar o Agendador no ar (VPS Ubuntu + nginx)

São 2 serviços que ficam sempre ligados:
- **agendador-web**: site, cadastro, painel dos clientes e /admin (porta 5070, atrás do nginx).
- **agendador-worker**: a cada 30s publica o que venceu, de todos os clientes.

> Rode sempre **1 processo** da tela (`-w 1`, já está no serviço). A proteção contra força bruta
> e a etapa "Verificar → Conectar" guardam estado em memória.

## 1. Domínio
Aponte um registro **A** do domínio do produto (ex: `app.suamarca.com.br`) para o IP da VPS.

## 2. Arquivos e dependências
Envie para `/opt/agendador/`:
`app.py worker.py db.py meta.py cripto.py ig_client.py gerenciar.py requirements.txt .env.example templates/ static/ deploy/`
(**não** envie `.env`, `dados/`, `logs/` do seu PC).

```bash
sudo useradd --system --home /opt/agendador --shell /usr/sbin/nologin agendador
sudo apt install -y python3-venv
cd /opt/agendador
sudo python3 -m venv venv && sudo venv/bin/pip install -r requirements.txt
sudo venv/bin/python gerenciar.py gerar-chaves      # copie as 2 linhas
sudo cp .env.example .env && sudo nano .env          # cole as chaves e preencha sua marca
sudo mkdir -p dados logs && sudo chown -R agendador:agendador /opt/agendador && sudo chmod 600 .env
```
**Guarde uma cópia da `CHAVE_MESTRA`** fora do servidor (gerenciador de senhas). Sem ela os tokens
dos clientes não abrem, e todos teriam que reconectar.

## 3. Seu usuário administrador
```bash
sudo -u agendador venv/bin/python gerenciar.py criar-admin
```

## 4. Serviços
```bash
sudo cp deploy/agendador-web.service deploy/agendador-worker.service /etc/systemd/system/
sudo systemctl daemon-reload && sudo systemctl enable --now agendador-web agendador-worker
sudo systemctl status agendador-web agendador-worker --no-pager
```

## 5. nginx + HTTPS
```bash
sudo cp deploy/nginx-agendador.conf /etc/nginx/sites-available/agendador
sudo nano /etc/nginx/sites-available/agendador       # troque SEU-DOMINIO.com.br
sudo ln -s /etc/nginx/sites-available/agendador /etc/nginx/sites-enabled/
sudo nginx -t && sudo systemctl reload nginx
sudo certbot --nginx -d SEU-DOMINIO.com.br
```

## 6. Teste e ligar pra valer
1. Abra o site, entre com o admin, conecte **o seu** Instagram em "contas" e agende 1 Story para
   daqui a 2 min. Com a faixa amarela "MODO TESTE", ele deve aparecer como **"teste ok"**.
2. Troque `PUBLICAR_DE_VERDADE=1` no `.env` e rode `sudo systemctl restart agendador-web agendador-worker`.
3. Agende mais 1 Story e confira no Instagram.

## Backup (importante: são dados de clientes)
Todo dia, copie para fora da VPS o arquivo `dados/agendador.db` (os vídeos não precisam, eles são
temporários). Exemplo de cron diário às 3h:
```bash
0 3 * * * sqlite3 /opt/agendador/dados/agendador.db ".backup /root/backup-agendador-$(date +\%u).db"
```
(e leve esses arquivos para outro lugar: outro servidor, Google Drive via rclone, etc.)

## Atualizar a versão
Envie os arquivos alterados → `sudo systemctl restart agendador-web agendador-worker`.
`dados/` (banco + vídeos) e `.env` não são tocados.

## Onde olhar quando der problema
- `journalctl -u agendador-worker -n 100` ou `logs/worker.log`: toda publicação, erro e nova tentativa, com o id do cliente.
- `journalctl -u agendador-web -n 100`: erros do site.
- /admin: clientes com contas desconectadas ou posts com erro aparecem em vermelho.
