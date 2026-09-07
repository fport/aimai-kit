# Proda çıkmadan checklist

Aşağıdaki her madde, beş bölümden birinin düzeltmek zorunda kaldığı bir şey. Hiçbiri
genel tavsiye değil — her satır, bir bölümde açıklaması olan bir arızayı adlandırıyor
ve çoğu sessiz arıza: proda çıkan, staging'de çalışan, sonra bir faturada ya da bir
incident'ta ortaya çıkan cinsten.

İşe göre kullan. Bir prompt yazmak, bir tool eklemek ya da bir budget ayarlamak
üzeresin: o bloğu oku.

!!! done "İşaretlenmemiş olması sorun değil. Düşünülmemiş olması sorun."

    Bunların birçoğu küçük bir iç araç için geçerli değil. Mesele karar vermiş olmak —
    bilerek atladığın madde bir karardır, hiç görmediğin madde trafiği bekleyen bir
    hatadır.

    PR template'ine yapıştırılacak hâli [en altta](#kopyala-yapstr).

---

## Bir provider bağlarken

→ [1. Provider katmanı](01-provider.md)

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

## Bir prompt yazarken

→ [2. Prompt ve context](02-prompts.md)

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

## Structured output isterken

→ [2. Prompt ve context](02-prompts.md#sema-tasarm-bir-ckt-kalitesi-karar)

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

## Bir tool eklerken

→ [3. Tool katmanı](03-tools.md)

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

## Bir agent döngüsü kurarken

→ [4. Ajan döngüsü](04-agent.md)

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

## İş uzadığında

→ [5. Harness](05-harness.md)

- [ ] **Context segment'lerden kuruluyor ve sondan kırpılıyor.** Baştan kırpmak
      talimatları siler.
- [ ] **Büyük veriler spill ediliyor, gömülmüyor.** Referansı ve özeti tut; o 200 KB'ın
      sonraki her turda bulunması gerekmiyor.
- [ ] **Compaction eşikle tetikleniyor, adım başına değil.** Her adımda compaction,
      zaten sıkışmadığın token'ları kurtarmak için bir model çağrısı harcar.
- [ ] **Compaction adım sınırında oluyor**, asla bir tool turunun ortasında değil.
- [ ] **Compaction prompt'u versiyonlu bir dosya** ve versiyon, ürettiği durumla
      birlikte kaydediliyor. Compaction kayıplıdır; "bu durumu hangi summarizer yazdı"
      sana sorulacak bir soru.
- [ ] **Compaction prompt'unun bir needle testi var.** Bir sayıyı koruyan bir
      summarizer, sayıları koruyan bir summarizer değildir — testi tarihler, id'ler ve
      tutarlarla yaz.
- [ ] **Memory yazımları deterministik bir kapıdan geçiyor** ve redler sayılıyor. Her
      şeyi kabul eden bir memory, thread'i kaybetmenin daha yavaş bir yoludur.
- [ ] **Bayat memory recall'da filtreleniyor**, yazarken değil. Yazıldığında doğru olan,
      şimdi doğru olan değil.
- [ ] **Alt-ajan düzyazı değil, doğrulanabilir kanıtı olan kısıtlı bir sonuç dönüyor.**
      Düzyazı, çağırana kullanacağı bir şey değil yorumlayacağı bir şey verir.
- [ ] **İzolasyon katmanlarından hangisinin gerçek sınır olduğunu biliyorsun.** Üçünün
      ikisi genelde değil.

## Proda çıkmadan

Kesişen maddeler; sonraya bırakılması en kolay olan kısım.

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

## Kopyala yapıştır

PR template'ine ya da bir issue'ya at, uymayanları sil.

```markdown
### Provider
- [ ] SDK retry kapalı, tek retry katmanı
- [ ] retry edilebilirlik hata sınıfında, mesaj metninde değil
- [ ] Retry-After'a uyuluyor; jitter var; toplam deadline var
- [ ] ilk stream chunk'ından sonra retry yok
- [ ] cache'lenen token'lar provider'lar arasında normalize
- [ ] fallback'ler sayılıyor, TTFT süreden ayrı, p95 (ortalama değil)

### Prompt
- [ ] versiyonlu dosya; her koşuda prompt_ref kaydediliyor
- [ ] StrictUndefined açık
- [ ] cache prefix'i sabit, imzası testte pinlenmiş
- [ ] kırpma raporluyor; kırpılamazlar hata veriyor; pencere altında güvenlik payı
- [ ] güvenilmeyen içerik sınırlandırılmış ve veri olarak etiketli; injection testi var

### Structured output
- [ ] strict şema (additionalProperties false, hepsi required, anyOf null)
- [ ] serbest metin yerine Literal; para tam sayı alt birim
- [ ] açıklamalar talimat olarak yazılmış
- [ ] repair döngüsü sınırlı, hatalar okunabilir, ortalama deneme alarma bağlı
- [ ] atıflar kaynağa karşı doğrulanıyor

### Tool
- [ ] şema imzadan türetiliyor
- [ ] yan etkiler spec'te; allowlist bildirimi filtreliyor
- [ ] not_allowed tool adını vermiyor
- [ ] server context enjekte ediliyor, modelden gelmiyor
- [ ] ayrı hata kodları; timeout döngünün dışında; kırpma bildiriliyor
- [ ] yazmalar sıralı, okumalar paralel; idempotency anahtarı çağrı imzasından
- [ ] tool açıklamalarında sınır cümleleri duruyor

### Agent döngüsü
- [ ] dört budget ayarlı ve adımdan önce kontrol ediliyor
- [ ] her tool çağrısı sonuç alıyor; budget bitince tool'suz son tur
- [ ] döngü tespiti önce uyarıyor sonra durduruyor; stop_reason kaydediliyor
- [ ] thread serileşiyor
- [ ] metrikler loop rate -> budget stop rate -> recovery rate sırasıyla okunuyor

### Harness
- [ ] segment'ler sondan kırpılıyor; büyük veriler spill ediliyor
- [ ] compaction eşikle, adım sınırında, prompt versiyonlu
- [ ] compaction prompt'unda needle testi
- [ ] memory yazma kapısı deterministik, redler sayılıyor, bayat kayıt recall'da eleniyor
- [ ] alt-ajanlar kanıtlı ve kısıtlı sonuç dönüyor

### Çıkış
- [ ] yayınlanan sayılar depodan tekrar üretilebiliyor
- [ ] sayaçlar sadece export değil, alarma bağlı
- [ ] fallback yolu staging'de denenmiş
- [ ] prompt_ref + model + thread id + stop reason tek log satırında
- [ ] budget'lar deploy olmadan değiştirilebiliyor
- [ ] anahtarlar ne depoda ne hata mesajlarında
```
