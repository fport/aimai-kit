- [ ] **Şema imzadan geliyor.** Tek doğruluk kaynağı; elle yazılmış bir şema ilk
      refactor'da fonksiyondan ayrışır.
- [ ] **Yan etkiler spec'te bildirilmiş** — idempotent mi, yıkıcı mı, onay ister mi —
      açıklamadan çıkarılmıyor.
- [ ] **Allowlist bildirimi filtreliyor.** Çağıranın kullanamayacağı bir tool modele hiç
      gösterilmiyor, dolayısıyla çağrılıp sonra reddedilemiyor.
- [ ] **`not_allowed` tool'un adını vermiyor.** Bir tool'un var olduğunu doğrulayan hata
      mesajı bir enumeration oracle'dır.
- [ ] **Server context çağrıdan enjekte ediliyor.** `user_id` ve `tenant_id` senin
      oturumundan geliyor, asla modelin verdiği bir argümandan değil. Bütün mesele bu.
- [ ] **Her reddin ayrı bir kodu** ve modelin üzerine iş yapabileceği bir mesajı var —
      hangi alan, ne bekleniyordu.
- [ ] **Timeout'lar bir worker thread'de koşuyor.** Takılan bir tool döngüyü
      takmamalı.
- [ ] **Kırpma sonuçta bildiriliyor.** 200 KB dönen bir tool, sessizce bir önek dönmek
      yerine kırpıldığını söylemeli.
- [ ] **Yazmalar sıralı, okumalar paralel.** Eşzamanlılık tool'un özelliği, executor'ın
      değil.
- [ ] **Idempotency anahtarı çağrı imzasından türetiliyor**, modelden istenmiyor.
      Modelden anahtar istemek, retry ettiğini fark etmesine güvenmek demek.
- [ ] **Açıklamadaki sınır cümleleri duruyor.** Tool golden set'inde ölçüldü: açıklamayı
      ilk cümlesine indirmek seçim doğruluğunu %90.9'da bıraktı, yasak çağrı oranını
      %0.0'dan %4.5'e taşıdı. Açıklamalar bir güvenlik kontrolü ve doğruluk metriği
      bunu göstermiyor.
