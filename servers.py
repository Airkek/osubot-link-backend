from dataclasses import dataclass

import settings


@dataclass(frozen=True)
class OAuthServer:
    id: str
    name: str
    base_url: str
    client_id: str
    client_secret: str
    redirect_url: str
    bot_command: str
    state_cookie: str

    @property
    def configured(self) -> bool:
        return bool(self.client_id and self.client_secret and self.redirect_url)


SERVERS = {
    "bancho": OAuthServer(
        "bancho", "osu!", "https://osu.ppy.sh",
        settings.OSU_CLIENT_ID, settings.OSU_CLIENT_SECRET, settings.OSU_REDIRECT_URL,
        settings.BOT_LINK_COMMAND, "osu_link_state",
    ),
    "morasooma": OAuthServer(
        "morasooma", "Morasooma", "https://morasooma.net",
        settings.MORASOOMA_CLIENT_ID, settings.MORASOOMA_CLIENT_SECRET, settings.MORASOOMA_REDIRECT_URL,
        settings.MORASOOMA_BOT_LINK_COMMAND, "morasooma_link_state",
    ),
}
