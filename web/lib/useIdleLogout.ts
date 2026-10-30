import { useCallback, useEffect, useRef, useState } from "react";
import { api, ApiError, UNAUTHORIZED_EVENT } from "./api";

/** Última actividad compartida entre pestañas: usar el tablero en una mantiene abiertas las demás. */
const STORAGE_KEY = "minos.lastActivity";
const EVENTS = ["pointerdown", "pointermove", "keydown", "wheel", "touchstart", "scroll"] as const;
// Se avisa al servidor a lo más una vez por minuto; él cierra la sesión por su cuenta si deja de oír al tablero.
const PING_EVERY = 60_000;
const WARN_BEFORE = 2 * 60_000;

function stored(): number {
  try {
    return Number(localStorage.getItem(STORAGE_KEY)) || 0;
  } catch {
    return 0;
  }
}

/**
 * Cuenta el tiempo sin actividad de la persona (clics, teclas, toques, desplazarse). Los datos que llegan solos (el
 * WebSocket en vivo, las consultas automáticas) no cuentan. Avisa dos minutos antes y al vencer llama a onIdle.
 * Devuelve los segundos que faltan mientras se muestra el aviso (o null) y stay() para seguir conectado.
 */
export function useIdleLogout(timeoutSeconds: number | null | undefined, onIdle: () => void) {
  const [warningLeft, setWarningLeft] = useState<number | null>(null);
  const lastActivity = useRef(Date.now());
  const lastPing = useRef(Date.now()); // entrar o abrir el tablero ya contó en el servidor
  const lastStored = useRef(0);
  const warning = useRef(false);
  const onIdleRef = useRef(onIdle);
  onIdleRef.current = onIdle;

  const ping = useCallback(() => {
    lastPing.current = Date.now();
    api.activity().catch((err) => {
      if (err instanceof ApiError && err.status === 401) window.dispatchEvent(new Event(UNAUTHORIZED_EVENT));
    });
  }, []);

  const mark = useCallback((force = false) => {
    if (warning.current && !force) return; // con el aviso en pantalla hay que elegir "Seguir conectado"
    const now = Date.now();
    lastActivity.current = now;
    if (now - lastStored.current > 5_000) {
      lastStored.current = now;
      try {
        localStorage.setItem(STORAGE_KEY, String(now));
      } catch {
        /* sin almacenamiento: cada pestaña cuenta por su lado */
      }
    }
  }, []);

  const stay = useCallback(() => {
    mark(true);
    warning.current = false;
    setWarningLeft(null);
    ping();
  }, [mark, ping]);

  useEffect(() => {
    if (!timeoutSeconds) return;
    const timeout = timeoutSeconds * 1000;
    const warnAt = Math.min(WARN_BEFORE, timeout / 2);
    lastActivity.current = Date.now();
    const onEvent = () => mark();
    for (const e of EVENTS) window.addEventListener(e, onEvent, { passive: true, capture: true });

    const tick = () => {
      const now = Date.now();
      // Solo la actividad de esta pestaña se avisa al servidor; la de otras pestañas la avisan ellas.
      if (lastActivity.current > lastPing.current && now - lastPing.current >= PING_EVERY) ping();
      const left = Math.max(lastActivity.current, stored()) + timeout - now;
      if (left <= 0) {
        warning.current = false;
        setWarningLeft(null);
        onIdleRef.current();
      } else if (left <= warnAt) {
        warning.current = true;
        setWarningLeft(Math.ceil(left / 1000));
      } else if (warning.current) {
        warning.current = false; // hubo actividad en otra pestaña
        setWarningLeft(null);
      }
    };
    const timer = setInterval(tick, 1_000);
    // Al volver a la pestaña (o despertar la computadora) se revisa al momento, sin esperar al siguiente segundo.
    document.addEventListener("visibilitychange", tick);
    return () => {
      for (const e of EVENTS) window.removeEventListener(e, onEvent, { capture: true });
      document.removeEventListener("visibilitychange", tick);
      clearInterval(timer);
    };
  }, [timeoutSeconds, mark, ping]);

  return { warningLeft, stay };
}
