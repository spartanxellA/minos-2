"use client";

import { useEffect, useState } from "react";

/** Ancho máximo en el que el tablero usa su diseño de teléfono (igual que en globals.css). */
export const PHONE = "(max-width: 640px)";

/** Si la consulta de medios se cumple; se actualiza al girar el teléfono o cambiar el tamaño de la ventana. */
export function useMediaQuery(query: string) {
  const [matches, setMatches] = useState(false);
  useEffect(() => {
    const mq = window.matchMedia(query);
    const update = () => setMatches(mq.matches);
    update();
    mq.addEventListener("change", update);
    return () => mq.removeEventListener("change", update);
  }, [query]);
  return matches;
}
