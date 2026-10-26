import logo from "@/assets/minos-logo.png";

/** Logo oficial de minOS (el ícono de la pestaña sale de app/icon.png y app/apple-icon.png). */
export function Logo({ size = 32 }: { size?: number }) {
  return <img src={logo.src} width={size} height={size} alt="" className="logo" />;
}
