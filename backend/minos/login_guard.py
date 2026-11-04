"""Protección del inicio de sesión contra fuerza bruta y credential stuffing.

Tres contadores de fallos con vencimiento, en el bus (Redis si hay, compartido por todas las réplicas de la API):

- correo + IP: max_failed_logins fallos bloquean ese correo desde esa IP durante lockout. Quien adivina desde una IP
  ya no puede seguir, pero la persona dueña de la cuenta sigue entrando desde la suya.
- correo (cualquier IP): account_max_failed_logins fallos en account_window bloquean el correo para todos durante
  lockout. Frena un ataque repartido en muchas IP contra una sola cuenta.
- IP (cualquier correo): ip_max_failed_logins fallos en ip_window bloquean la IP durante lockout. Frena a quien prueba
  muchos correos desde un mismo lugar.

Los contadores son iguales para correos con y sin cuenta, así que un bloqueo (429) no revela qué correos existen.
En las llaves va el SHA-256 del correo y de la IP, no el texto.
"""
import hashlib
import math
from dataclasses import dataclass

from .bus import Bus
from .config import AuthSettings


def _h(value: str) -> str:
    return hashlib.sha256(value.encode()).hexdigest()[:32]


@dataclass(frozen=True)
class Trip:
    """Un bloqueo que acaba de activarse con este fallo."""
    scope: str  # "pair" (correo + IP), "account" (correo) o "ip"
    seconds: float


class LoginGuard:
    def __init__(self, bus: Bus, settings: AuthSettings) -> None:
        self._bus = bus
        self._s = settings

    @staticmethod
    def _keys(email: str, ip: str) -> dict[str, str]:
        e, i = _h(email), _h(ip)
        return {
            "pair": f"login:pair:{e}:{i}", "pair_lock": f"login:lock:pair:{e}:{i}",
            "account": f"login:acct:{e}", "account_lock": f"login:lock:acct:{e}",
            "ip": f"login:ip:{i}", "ip_lock": f"login:lock:ip:{i}",
        }

    async def retry_after(self, email: str, ip: str) -> tuple[str, int] | None:
        """(motivo, segundos) si este intento debe rechazarse sin revisar la contraseña; None si puede intentar."""
        k = self._keys(email, ip)
        ip_wait = await self._bus.blocked_for(k["ip_lock"])
        if ip_wait:
            return "ip_blocked", math.ceil(ip_wait)
        wait = max(await self._bus.blocked_for(k["pair_lock"]), await self._bus.blocked_for(k["account_lock"]))
        return ("locked", math.ceil(wait)) if wait else None

    async def failure(self, email: str, ip: str) -> list[Trip]:
        """Anota un fallo; da los bloqueos que este fallo activó."""
        s, k = self._s, self._keys(email, ip)
        lockout = s.lockout.total_seconds()
        trips: list[Trip] = []
        if await self._bus.hit(k["pair"], lockout) >= s.max_failed_logins > 0:
            await self._bus.block(k["pair_lock"], lockout)
            await self._bus.forget(k["pair"])
            trips.append(Trip("pair", lockout))
        if await self._bus.hit(k["account"], s.account_window.total_seconds()) >= s.account_max_failed_logins > 0:
            await self._bus.block(k["account_lock"], lockout)
            await self._bus.forget(k["account"])
            trips.append(Trip("account", lockout))
        if await self._bus.hit(k["ip"], s.ip_window.total_seconds()) >= s.ip_max_failed_logins > 0:
            await self._bus.block(k["ip_lock"], lockout)
            await self._bus.forget(k["ip"])
            trips.append(Trip("ip", lockout))
        return trips

    async def success(self, email: str, ip: str) -> None:
        """Entró: se olvidan sus fallos desde esa IP (los del correo en general y los de la IP siguen contando)."""
        await self._bus.forget(self._keys(email, ip)["pair"])

    async def unlock(self, email: str) -> None:
        """Quita los bloqueos y contadores de un correo desde cualquier IP (al restablecer su contraseña)."""
        e = _h(email)
        for prefix in (f"login:pair:{e}:", f"login:lock:pair:{e}:", f"login:acct:{e}", f"login:lock:acct:{e}"):
            await self._bus.forget(prefix)

    async def may_alert(self) -> bool:
        """Tope de avisos de seguridad por hora, para que un ataque grande no inunde el correo o el WhatsApp."""
        limit = self._s.security_alerts_per_hour
        return limit > 0 and await self._bus.hit("login:alerts", 3600) <= limit
