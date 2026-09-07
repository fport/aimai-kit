- [ ] **Prompt versiyonlu bir dosya**, Python içinde string değil. Diff'te bir string
      değişikliği "bir satır değişti" diye görünür ve hangi metnin hangi sonucu
      ürettiğine geri dönüş yoktur.
- [ ] **Her koşu `prompt_ref`'ini kaydediyor** (`name@vN+fingerprint`). Versiyon
      insanlar için, fingerprint ise birinin v2'yi versiyonu artırmadan düzenlediği
      durum için.
- [ ] **`StrictUndefined` açık.** Eksik bir template değişkeni hata vermeli. Jinja'nın
      varsayılanı onu boş basar, sen de sonucu "model halüsinasyon gördü" diye
      dosyalarsın — oysa context boştu.
- [ ] **Cache prefix'i sabit.** Çağrı başına değişen hiçbir şey — timestamp, request
      id, kullanıcı adı — cache kesme noktasından önce yer almıyor. Bu, testlerde değil
      faturada bulunan bir hata.
- [ ] **Prefix imzası bir testte sabitlenmiş**, böylece system prompt'a satır ekleyen
      bir sonraki kişi bunu anında öğreniyor.
- [ ] **Kırpma, rapor satırı olan bir karar.** `documents[:10]` iz bırakmayan bir
      tahmindir; on birinci belge cevabı değiştiren belgeyse bunu öğrenmenin yolu yok.
- [ ] **Kırpılamaz bölümler kesilmek yerine hata veriyor.** Talimatlarının yarısıyla
      çalışan bir sistem, neden yanlış cevap verdiğini açıklayamaz.
- [ ] **Pencerenin altında bir güvenlik payı var.** Yerel token sayımı bir tahmindir ve
      Anthropic ile Gemini'de %10–20 sapar; limite kadar doldurmak, tahmin düşük
      geldiğinde 400 demektir.
- [ ] **Güvenilmeyen içerik sınırlandırılmış bir blokta**, asla system prompt'ta değil,
      ve talimatlar o bloğun veri olduğunu söylüyor.
- [ ] **Güven sınırının içinde gerçek bir injection string'i olan bir testi var.**
