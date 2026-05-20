import { useEffect, useState } from "react";

const MQ = "(max-width: 639px)";

export function useMobile(): boolean {
  const [mobile, setMobile] = useState(() => window.matchMedia(MQ).matches);
  useEffect(() => {
    const mq = window.matchMedia(MQ);
    const handler = (e: MediaQueryListEvent): void => {
      setMobile(e.matches);
    };
    mq.addEventListener("change", handler);
    return (): void => {
      mq.removeEventListener("change", handler);
    };
  }, []);
  return mobile;
}
