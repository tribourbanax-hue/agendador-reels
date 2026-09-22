"""
Cliente minimo pra publicar Reels e Stories no Instagram via Graph API,
usando o protocolo de upload resumivel (nao precisa hospedar o video em URL
publica).

Fluxo (ver developers.facebook.com/docs/instagram-platform/content-publishing/resumable-uploads):
  1. POST /{ig_user_id}/media  {media_type: REELS|STORIES, upload_type: resumable}  -> container_id
  2. POST https://rupload.facebook.com/ig-api-upload/{ver}/{container_id}  (bytes do arquivo)
  3. GET  /{container_id}?fields=status_code  (poll ate FINISHED)
  4. POST /{ig_user_id}/media_publish  {creation_id: container_id}

Requer host graph.facebook.com + permissoes instagram_basic/instagram_content_publish
(fluxo "Instagram API com login do Facebook" — ver a skill instagram-reels-scheduler,
references/app-setup.md, pra qual produto configurar no App Dashboard e por que o
outro produto nao serve).

Stories: sem caption (a API nao aceita texto pra Stories), expira em 24h como
qualquer story normal. So video testado/suportado aqui por ora (imagem em Story
exige image_url publica, que este pipeline nao tem — ver README).
"""
import hashlib
import hmac
import time
from pathlib import Path

import requests
GRAPH = "https://graph.facebook.com"
RUPLOAD = "https://rupload.facebook.com/ig-api-upload"
HTTP_TIMEOUT = (10, 60)
UPLOAD_TIMEOUT = (10, 600)


class IGClientError(Exception):
    pass


class IGClient:
    def __init__(self, token, ig_user_id, api_version="v21.0", app_secret=""):
        """Credenciais vem da conta do cliente (tabela contas), nao do .env."""
        self.token = token
        self.ig_user_id = ig_user_id
        self.api_version = api_version
        self.app_secret = app_secret or ""
        if not self.token or not self.ig_user_id:
            raise IGClientError("conta sem token ou sem ig_user_id")

    def _appsecret_proof(self):
        if not self.app_secret:
            return None
        return hmac.new(self.app_secret.encode(), self.token.encode(), hashlib.sha256).hexdigest()

    def _params(self, extra=None):
        p = {"access_token": self.token}
        proof = self._appsecret_proof()
        if proof:
            p["appsecret_proof"] = proof
        if extra:
            p.update(extra)
        return p

    def get_account_info(self):
        r = requests.get(
            f"{GRAPH}/{self.api_version}/{self.ig_user_id}",
            params=self._params({"fields": "username,name,ig_id"}),
            timeout=HTTP_TIMEOUT,
        )
        r.raise_for_status()
        return r.json()

    def list_recent_media(self, limit=50, max_pages=5):
        """SEMPRE chamar isso antes de qualquer publicacao de teste ou catch-up
        retroativo — checa o que ja foi publicado de verdade na conta pra nunca
        duplicar (Stories nao aparecem aqui, so Reels/Feed — expiram em 24h e
        o endpoint /media so lista posts permanentes)."""
        items = []
        url = f"{GRAPH}/{self.api_version}/{self.ig_user_id}/media"
        params = self._params({"fields": "id,media_type,media_product_type,permalink,timestamp", "limit": limit})
        for _ in range(max_pages):
            r = requests.get(url, params=params, timeout=HTTP_TIMEOUT)
            r.raise_for_status()
            data = r.json()
            items.extend(data.get("data", []))
            nxt = data.get("paging", {}).get("next")
            if not nxt:
                break
            url, params = nxt, None
        return items

    def _create_container(self, media_type, caption=None):
        payload = {"media_type": media_type, "upload_type": "resumable"}
        if caption:
            payload["caption"] = caption
        r = requests.post(
            f"{GRAPH}/{self.api_version}/{self.ig_user_id}/media",
            params=self._params(),
            json=payload,
            timeout=HTTP_TIMEOUT,
        )
        if r.status_code >= 400:
            raise IGClientError(f"create_container ({media_type}) falhou: {r.status_code} {r.text}")
        return r.json()["id"]

    def upload_video(self, container_id, video_path: Path):
        size = video_path.stat().st_size
        headers = {"Authorization": f"OAuth {self.token}", "offset": "0", "file_size": str(size)}
        with open(video_path, "rb") as f:
            r = requests.post(
                f"{RUPLOAD}/{self.api_version}/{container_id}",
                headers=headers,
                data=f,
                timeout=UPLOAD_TIMEOUT,
            )
        if r.status_code >= 400:
            raise IGClientError(f"upload_video falhou: {r.status_code} {r.text}")
        return r.json()

    def wait_container_ready(self, container_id, timeout_s=300, poll_s=5):
        deadline = time.time() + timeout_s
        while time.time() < deadline:
            r = requests.get(
                f"{GRAPH}/{self.api_version}/{container_id}",
                params=self._params({"fields": "status_code,status"}),
                timeout=HTTP_TIMEOUT,
            )
            r.raise_for_status()
            data = r.json()
            status = data.get("status_code")
            if status == "FINISHED":
                return data
            if status == "ERROR":
                raise IGClientError(f"Processamento do video falhou: {data}")
            time.sleep(poll_s)
        raise IGClientError("Timeout esperando o container ficar FINISHED")

    def publish(self, container_id):
        r = requests.post(
            f"{GRAPH}/{self.api_version}/{self.ig_user_id}/media_publish",
            params=self._params({"creation_id": container_id}),
            timeout=HTTP_TIMEOUT,
        )
        if r.status_code >= 400:
            raise IGClientError(f"media_publish falhou: {r.status_code} {r.text}")
        return r.json()

    def _publish_video(self, media_type, video_path: Path, caption, confirm):
        container_id = self._create_container(media_type, caption)
        self.upload_video(container_id, video_path)
        status = self.wait_container_ready(container_id)
        if not confirm:
            return {"container_id": container_id, "status": status, "published": False}
        result = self.publish(container_id)
        return {"container_id": container_id, "status": status, "published": True, "media_id": result.get("id")}

    def publish_reel(self, video_path: Path, caption: str, confirm=False):
        """Sem confirm=True: dry-run real (sobe e processa, nao publica)."""
        return self._publish_video("REELS", video_path, caption, confirm)

    def publish_story(self, video_path: Path, confirm=False):
        """Story de video, sem caption (API nao aceita texto pra Stories).
        Sem confirm=True: dry-run real (sobe e processa, nao publica)."""
        return self._publish_video("STORIES", video_path, None, confirm)

    def permalink(self, media_id):
        """Link publico do post (Stories nao tem permalink util depois de 24h)."""
        try:
            r = requests.get(f"{GRAPH}/{self.api_version}/{media_id}",
                             params=self._params({"fields": "permalink"}), timeout=HTTP_TIMEOUT)
            return r.json().get("permalink")
        except Exception:  # noqa: BLE001 — link e so conveniencia
            return None
