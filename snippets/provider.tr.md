- [ ] **SDK'nın kendi retry'ı kapalı** (`max_retries=0`). İki retry katmanı çarpılır:
      senin üçün ile onların üçü dokuz çağrı ve dokuz kat fatura eder.
- [ ] **Retry edilebilirlik hata sınıfının özelliği**, mesajda string araması değil.
      Provider'ın kelimeleri haber vermeden değişir, senin retry mantığın değişmemeli.
- [ ] **`Retry-After` senin backoff'unu yener.** Ne zaman hazır olacağını provider
      biliyor, sen bilmiyorsun.
- [ ] **Backoff'ta jitter var.** Hepsi 429 alıp hepsi tam iki saniye bekleyen elli
      client, o 429'a sebep olan yükü yeniden üretir.
- [ ] **Toplam bir deadline var**, sadece deneme sayısı değil. Her biri 60 saniyelik
      `Retry-After`'a uyan üç deneme, kimsenin bütçelemediği üç dakikalık bir istektir.
- [ ] **Stream başladıktan sonra retry yok.** Kullanıcı ilk chunk'ı gördü bile; retry
      cevabı onun gözü önünde baştan başlatır.
- [ ] **Cache'lenen token'lar normalize ediliyor.** Anthropic
      `cache_read_input_tokens`'ı `input_tokens`'ın **dışında**, OpenAI **içinde**
      raporluyor. Bunu kaçırırsan maliyet paneli faturayla uyuşmaz — hem de ancak ay
      sonunda fark edeceğin bir yönde.
- [ ] **Fallback bir olaydır.** `llm_fallbacks_total` artar. Sessizce kurtaran bir
      fallback, birincil provider'ın bir hafta boyunca çökük kalabilmesi demektir.
- [ ] **TTFT ile toplam süre ayrı metrikler.** Stream eden bir arayüzde farklı soruları
      cevaplıyorlar ve tek bir ortalama ikisini de gizler.
- [ ] **p95'e bakıyorsun, ortalamaya değil.** Ortalama kimsenin yaşadığı şey değil.
