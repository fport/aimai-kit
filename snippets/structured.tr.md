- [ ] **Şema strict**: `additionalProperties: false`, her alan `required`, opsiyoneller
      `anyOf: [type, null]` ile.
- [ ] **Bilinen değer kümeleri `Literal`, serbest metin değil.** Bu bir doğrulama
      değişikliği değil, bir doğruluk değişikliği — serbest metin kendi kelimelerini
      uyduruyor.
- [ ] **Para tam sayı alt birim.** Float olarak "1.250.000,50" ayrıştırmak
      isteyeceğinden daha çok biçimde geliyor.
- [ ] **Alan açıklamaları modele talimat olarak yazılmış**, okuyucuya dokümantasyon
      olarak değil. Modelin gerçekten uyduğu kısım orası.
- [ ] **Repair döngüsü iki üç denemeyle sınırlı.** Sınırsızken kötü bir prompt faturaya
      dönüşür.
- [ ] **Repair hataları okunabilir.** Ham bir `ValidationError` repr'ı, bir modelin
      üzerine iş yapabileceği bir mesaj değil.
- [ ] **Ortalama deneme sayısı alarma bağlı.** 1.0'a yakınsa şema oturmuş; tavana doğru
      kayıyorsa prompt ya da şema yanlış ve döngü bunu gizliyor.
- [ ] **Atıflar kaynağa karşı doğrulanıyor.** Şema biçimi doğrular, içeriği asla —
      söylemediği bir şeyi söyleyen belgeye yapılmış düzgün biçimli bir atıf, bir
      modelin baskı altında ürettiği şeyin tam kendisi.
