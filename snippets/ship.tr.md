- [ ] **Yayınladığın her sayı depodaki bir komutla tekrar üretilebiliyor.** Yeniden
      koşturamıyorsan o bir ölçüm değil, bir iddia.
- [ ] **Sayaçlar sadece export edilmiyor, alarma bağlı**: `llm_call_errors_total`,
      `llm_retries_total`, `llm_fallbacks_total`, `tool_calls_total`,
      `agent_budget_stops_total`, `context_segments_dropped_total`,
      `memory_writes_refused_total`.
- [ ] **Fallback yolu gerçekten denenmiş.** Staging'de birincil provider'ı boz. Test
      edilmemiş bir fallback, ilk kesintinin içinde bekleyen ikinci bir kesintidir.
- [ ] **Bir koşu uçtan uca izlenebiliyor**: `prompt_ref`, model, thread id, stop reason
      aynı log satırında.
- [ ] **Budget'lar deploy olmadan değiştirilebiliyor.** Onlar senin kill switch'in; bir
      release trenin arkasındaki kill switch, kill switch değildir.
- [ ] **Koşu başı maliyet gerçek trafik şekliyle ölçülmüş**, mutlu yolla değil. Para
      harcayan koşular döngüye girenler.
- [ ] **Anahtarlar ne depoda ne de hata mesajlarında.** Başarısız bir istek isteği
      yazdırır.

---
