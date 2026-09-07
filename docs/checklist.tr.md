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

--8<-- "provider.tr.md"

## Bir prompt yazarken

→ [2. Prompt ve context](02-prompts.md)

--8<-- "prompt.tr.md"

## Structured output isterken

→ [2. Prompt ve context](02-prompts.md#sema-tasarm-bir-ckt-kalitesi-karar)

--8<-- "structured.tr.md"

## Bir tool eklerken

→ [3. Tool katmanı](03-tools.md)

--8<-- "tools.tr.md"

## Bir agent döngüsü kurarken

→ [4. Ajan döngüsü](04-agent.md)

--8<-- "agent.tr.md"

## İş uzadığında

→ [5. Harness](05-harness.md)

--8<-- "harness.tr.md"

## Proda çıkmadan

Kesişen maddeler; sonraya bırakılması en kolay olan kısım.

--8<-- "ship.tr.md"

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

---

!!! done "Tek kaynak, iki yer"

    Yukarıdaki her blok, geldiği bölümün sonunda da duruyor; ikisi de `snippets/`
    altındaki aynı dosyadan geliyor. Orada düzenle, ikisi birden değişsin — kendisini
    açıklayan bölümden kaymış bir checklist, hiç checklist olmamasından kötüdür.
