import asyncio
import aiohttp
from urllib.parse import urlencode


class TCGPlayerAPI:
    BEARER_TOKEN: str = None
    PUBLIC_KEY: str = None
    PRIVATE_KEY: str = None

    API_BASE: str = "https://api.tcgplayer.com/v1.37.0"
    manifests: dict = None
    categories: dict = None
    POKEMON_ID: int = None
    MAGIC_ID: int = None
    YUGIOH_ID: int = None
    VANGUARD_ID: int = None

    def __init__(self, public_key, private_key, token=None, loop=None, session=None):
        if session is None:
            if loop is None:
                self._loop = asyncio.get_event_loop()
            self._session = aiohttp.ClientSession(loop=loop)
        else:
            self._session = session

        if token is not None:
            self.BEARER_TOKEN = token

        self.PUBLIC_KEY = public_key
        self.PRIVATE_KEY = private_key

    async def refresh_token(self):
        while True:
            response = await self._session.get(
                "https://api.tcgplayer.com/token",
                headers={
                    "Content-Type": "application/x-www-form-urlencoded",
                    # f"X-Tcg-Access-Token": "{self.ACCESS_TOKEN}"
                },
                data=urlencode({
                    "grant_type": "client_credentials",
                    "client_id": self.PUBLIC_KEY,
                    "client_secret": self.PRIVATE_KEY
                })
            )
            data = await response.json()
            self.BEARER_TOKEN = data["access_token"]
            assert data["userName"].lower() == self.PUBLIC_KEY.lower()

            self.manifests = {}

            response = await self._session.get(
                f"{self.API_BASE}/catalog/categories",
                headers={
                    "Authorization": f"bearer {self.BEARER_TOKEN}",
                    "Accept": "application/json"
                },
                params={"limit": 60}
            )
            rjson = await response.json()

            self.categories = {v["name"]: v["categoryId"] for v in rjson["results"]}
            self.POKEMON_ID = self.categories["Pokemon"]
            self.MAGIC_ID = self.categories["Magic"]
            self.YUGIOH_ID = self.categories["YuGiOh"]
            self.VANGUARD_ID = self.categories["Cardfight Vanguard"]

            for id in [self.POKEMON_ID, self.MAGIC_ID, self.YUGIOH_ID, self.VANGUARD_ID]:
                response = await self._session.get(
                    f"{self.API_BASE}/catalog/categories/{id}/search/manifest",
                    headers={
                        "Authorization": f"bearer {self.BEARER_TOKEN}"
                    },
                )
                self.manifests[id] = await response.json()

            await asyncio.sleep(data["expires_in"])
