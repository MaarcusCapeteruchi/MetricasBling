"""Cliente HTTP da API v3 do Bling com rate limit e renovação de token.

O Bling limita ~3 requisições/segundo por app; mantemos folga com um
intervalo mínimo entre chamadas e backoff em HTTP 429.
"""
import time

import requests
from sqlalchemy.orm import Session

from conector.bling_auth import obter_access_token

URL_BASE = "https://api.bling.com.br/Api/v3"
INTERVALO_MINIMO_S = 0.4
MAX_TENTATIVAS_429 = 4


class BlingAPI:
    def __init__(self, sessao: Session, cliente_id: int):
        self.sessao = sessao
        self.cliente_id = cliente_id
        self._ultima_chamada = 0.0

    def _respeitar_rate_limit(self) -> None:
        decorrido = time.monotonic() - self._ultima_chamada
        if decorrido < INTERVALO_MINIMO_S:
            time.sleep(INTERVALO_MINIMO_S - decorrido)
        self._ultima_chamada = time.monotonic()

    def get(self, caminho: str, params: dict | None = None) -> dict:
        for tentativa in range(1, MAX_TENTATIVAS_429 + 2):
            self._respeitar_rate_limit()
            token = obter_access_token(self.sessao, self.cliente_id)
            resposta = requests.get(
                f"{URL_BASE}{caminho}",
                params=params,
                headers={"Authorization": f"Bearer {token}", "Accept": "application/json"},
                timeout=60,
            )

            if resposta.status_code == 429 and tentativa <= MAX_TENTATIVAS_429:
                time.sleep(2 * tentativa)  # backoff progressivo
                continue

            if resposta.status_code != 200:
                raise RuntimeError(
                    f"GET {caminho} falhou (HTTP {resposta.status_code}): {resposta.text[:500]}"
                )
            return resposta.json()

        raise RuntimeError(f"GET {caminho}: rate limit persistente após retries.")

    def listar_paginado(self, caminho: str, params: dict | None = None, limite: int = 100):
        """Percorre todas as páginas de um endpoint de listagem, item a item."""
        pagina = 1
        while True:
            corpo = self.get(
                caminho, {**(params or {}), "pagina": pagina, "limite": limite}
            )
            registros = corpo.get("data") or []
            if not registros:
                return
            yield from registros
            if len(registros) < limite:
                return
            pagina += 1
