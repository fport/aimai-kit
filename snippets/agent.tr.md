- [ ] **Dört budget da ayarlı**: adım, token, maliyet, saniye. Her biri farklı bir
      arızayı sınırlıyor ve hiçbiri diğerinin yerine geçmiyor.
- [ ] **Budget'lar adımdan önce kontrol ediliyor.** Sonradan öğrenmek bir denetimdir.
- [ ] **Eksik bir fiyat kataloğu maliyet budget'ını sessizce devre dışı bırakmıyor.**
      Harcama sıfırda kalır ve budget hiç tetiklenmez — bunu faturada keşfetmek yerine
      metriklerde görünür yap.
- [ ] **Her tool çağrısı bir sonuç alıyor**, başarısız olanlar dahil. Sonucu olmayan
      bir tool çağrısı, çoğu provider'ın reddettiği bozuk bir konuşmadır.
- [ ] **Budget bittiğinde tool'suz son bir tur var**, böylece kullanıcı kesilmiş bir
      döngü yerine bir cevap alıyor.
- [ ] **Döngü tespiti durdurmadan önce uyarıyor** ve uyarı, modelin okuyabileceği
      thread'in içinde.
- [ ] **`stop_reason` kaydediliyor ve ayırt edilebiliyor.** "Bitti" ile "adımı bitti"
      aşağı akışta aynı görünmemeli.
- [ ] **Thread serileşiyor**, böylece devam etmek bir kurtarma altsistemi değil, onu
      geri vermek.
- [ ] **Metrikler şu sırayla okunuyor: loop rate → budget stop rate → recovery rate.**
      Bir döngü altındaki her şeyi şişirir; loop rate yüksekken budget ayarlamak sadece
      boşa giden işin tavanını yükseltir.
- [ ] **Düşük recovery rate bir tool katmanı problemi olarak okunuyor**, budget problemi
      olarak değil — hata mesajları üzerine iş yapılabilir değil demektir.
