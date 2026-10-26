"""Facebook e Instagram: lo que otros publican en las cuentas propias del objetivo (comentarios, publicaciones de
visitantes y etiquetas), vía la Graph API con el token de la empresa. Meta no ofrece búsqueda pública de menciones.

Cada objetivo indica sus cuentas en handles: "facebook" → id de la página, "instagram" → id de la cuenta profesional.
"""
from collections.abc import AsyncIterator
from datetime import timedelta

import httpx

from ..config import MetaSettings
from ..domain.mentions import AuthorInfo, Engagement, MentionDraft
from ..domain.targets import MonitoredTarget
from .base import ConnectorCursor, MentionConnector, parse_datetime, parse_since


class GraphApiError(RuntimeError):
    pass


class _MetaConnector(MentionConnector):
    handle_key: str

    def __init__(self, http: httpx.AsyncClient, settings: MetaSettings) -> None:
        self._http = http
        self._settings = settings

    @property
    def poll_interval(self) -> timedelta:
        return self._settings.poll_interval

    @property
    def is_configured(self) -> bool:
        return bool(self._settings.access_token)

    async def _get(self, path: str, **params) -> dict:
        response = await self._http.get(
            f"{self._settings.graph_url}/{path}", params={**params, "access_token": self._settings.access_token}
        )
        if response.is_error:
            # El mensaje de Meta dice qué permiso o id falló; se guarda como último error del conector.
            try:
                message = response.json()["error"]["message"]
            except (ValueError, KeyError, TypeError):
                message = response.text[:300]
            raise GraphApiError(f"Graph API {response.status_code}: {message}")
        return response.json()

    async def fetch(self, target: MonitoredTarget, cursor: ConnectorCursor) -> AsyncIterator[MentionDraft]:
        account = (target.handles.get(self.handle_key) or "").strip()
        if not account:
            return
        since = parse_since(cursor.value)
        newest = since
        async for draft in self._drafts(account):
            if draft.published_at <= since:
                continue
            newest = max(newest, draft.published_at)
            yield draft
        cursor.value = newest.isoformat()

    def _drafts(self, account: str) -> AsyncIterator[MentionDraft]:
        raise NotImplementedError


class FacebookPageConnector(_MetaConnector):
    source = "facebook"
    handle_key = "facebook"

    async def _drafts(self, page_id: str) -> AsyncIterator[MentionDraft]:
        comment_fields = "id,message,created_time,from{id,name},like_count,comment_count,permalink_url"
        feed = await self._get(
            f"{page_id}/feed", limit=self._settings.recent_posts,
            fields="id,message,created_time,permalink_url,from{id,name},"
                   f"comments.order(reverse_chronological).limit(50){{{comment_fields}}}",
        )
        for post in feed.get("data", []):
            # Lo que publica la propia página no es una mención; sí lo que publican visitantes y los comentarios.
            if (post.get("from") or {}).get("id") not in (None, page_id):
                yield self._draft(post, post.get("permalink_url"))
            for comment in (post.get("comments") or {}).get("data", []):
                if (comment.get("from") or {}).get("id") != page_id:
                    yield self._draft(comment, comment.get("permalink_url") or post.get("permalink_url"))

        tagged = await self._get(
            f"{page_id}/tagged", limit=self._settings.recent_posts,
            fields="id,message,created_time,permalink_url,from{id,name}",
        )
        for post in tagged.get("data", []):
            yield self._draft(post, post.get("permalink_url"))

    def _draft(self, item: dict, url: str | None) -> MentionDraft:
        author = item.get("from") or {}
        return MentionDraft(
            source=self.source,
            external_id=item["id"],
            url=url or f"https://www.facebook.com/{item['id']}",
            # Sin el permiso de contenido de usuarios, Meta no dice quién comentó.
            author=AuthorInfo(author.get("name") or "Usuario de Facebook", author.get("name")),
            published_at=parse_datetime(item["created_time"]),
            text=item.get("message") or "",
            engagement=Engagement(likes=item.get("like_count", 0), replies=item.get("comment_count", 0)),
            own_channel=True,
        )


class InstagramConnector(_MetaConnector):
    source = "instagram"
    handle_key = "instagram"

    def __init__(self, http: httpx.AsyncClient, settings: MetaSettings) -> None:
        super().__init__(http, settings)
        self._usernames: dict[str, str] = {}

    async def _drafts(self, account_id: str) -> AsyncIterator[MentionDraft]:
        if account_id not in self._usernames:
            self._usernames[account_id] = (await self._get(account_id, fields="username")).get("username", "")
        own = self._usernames[account_id]

        media = await self._get(
            f"{account_id}/media", limit=self._settings.recent_posts,
            fields="id,permalink,comments.limit(50){id,text,timestamp,username,like_count}",
        )
        for post in media.get("data", []):
            for c in (post.get("comments") or {}).get("data", []):
                if c.get("username") == own:
                    continue  # respuestas de la propia cuenta
                yield MentionDraft(
                    source=self.source, external_id=c["id"], url=post.get("permalink") or "",
                    author=AuthorInfo("@" + c.get("username", "instagram")),
                    published_at=parse_datetime(c["timestamp"]), text=c.get("text") or "",
                    engagement=Engagement(likes=c.get("like_count", 0)), own_channel=True,
                )

        # Publicaciones de otros que etiquetan a la cuenta.
        tags = await self._get(
            f"{account_id}/tags", limit=self._settings.recent_posts,
            fields="id,caption,timestamp,permalink,username,like_count,comments_count",
        )
        for post in tags.get("data", []):
            yield MentionDraft(
                source=self.source, external_id=post["id"], url=post.get("permalink") or "",
                author=AuthorInfo("@" + post.get("username", "instagram")),
                published_at=parse_datetime(post["timestamp"]), text=post.get("caption") or "",
                engagement=Engagement(likes=post.get("like_count", 0), replies=post.get("comments_count", 0)),
                own_channel=True,
            )
