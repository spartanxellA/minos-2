import { AuthGate } from "@/components/AuthGate";
import { I18nProvider } from "@/lib/i18n";

export default function Page() {
  return (
    <I18nProvider>
      <AuthGate />
    </I18nProvider>
  );
}
