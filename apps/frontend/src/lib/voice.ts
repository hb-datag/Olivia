export function speakText(text: string) {
  try {
    const synth = window.speechSynthesis;
    if (!synth) return;
    synth.cancel();
    const u = new SpeechSynthesisUtterance(text);
    u.rate = 1.0;
    u.pitch = 1.0;
    synth.speak(u);
  } catch {
    // ignore
  }
}

export function startSpeechToText(onText: (t: string) => void, onError?: (e: any) => void) {
  try {
    const SR: any = (window as any).SpeechRecognition || (window as any).webkitSpeechRecognition;
    if (!SR) throw new Error("SpeechRecognition not supported in this browser.");
    const rec = new SR();
    rec.lang = "en-US";
    rec.interimResults = false;
    rec.maxAlternatives = 1;

    rec.onresult = (ev: any) => {
      const t = ev?.results?.[0]?.[0]?.transcript?.trim?.() || "";
      if (t) onText(t);
    };
    rec.onerror = (e: any) => { if (onError) onError(e); };
    rec.start();
  } catch (e: any) {
    if (onError) onError(e);
  }
}
