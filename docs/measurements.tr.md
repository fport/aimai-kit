# Ölçümler

Buradaki her rakam, depodan kimlik bilgisi olmadan tekrar üretilebilir.

!!! warning "Modeller stub, provider değil"

    Hepsi deterministik stub'lara karşı koşuyor. Stub'lar gerçek iş yapıyor —
    extraction stub'ı sözleşmeleri regex'le ayrıştırıyor, seçim stub'ı
    sorguları tool açıklamalarına göre puanlıyor, harness stub'ı yalnızca
    context'inde olandan cevap veriyor — ama sentetik verinin şeklini
    bildikleri için doğrulukları iyimser.

    Bu bilinçli. Bu tabloların amacı ölçüm altyapısının çalıştığını ve
    karşılaştırmaların tekrar üretilebildiğini göstermek. Model hakkında sayı
    için aynı komutları `--model anthropic:claude-opus-5` ile koştur.

Golden setler sentetik: `scripts/generate_golden_set.py` (36 sözleşme, 10'u
kasıtlı kenar vaka) ve `evals/tool_cases/cases.py` (22 vaka, 3'ü tool
çağrılmamasını bekliyor). Gerçek bir değerlendirme için kendi verinle
değiştir.

## 1. Şema ve prompt sürümleri

```bash
uv run prompt-lab eval --prompt extract_contract@v2 --schema v2 \
  --pricing config/pricing.toml --pricing-model claude-opus-5
```

36 belge, `max_attempts=3`. Maliyet sütunu bir **projeksiyon**: token profili
stub'ın, fiyatlar `claude-opus-5`'in.

| prompt_ref | şema | İlk denemede geçme | Ort. deneme | Grounding | Girdi tok p50 | Maliyet/belge |
|---|---|---|---|---|---|---|
| `extract_contract@v1+099030d1` | v1 | **%83,3** | 1,17 | %0,0 | 729 | $0,0080 |
| `extract_contract@v2+19009d12` | v2 | %72,2 | 1,28 | **%100,0** | 1.982 | $0,0089 |

**v2 ilk denemede daha az geçiyor ve bu bir gerileme değil.** v2, provider'ın
doğrulamadığı çapraz alan kurallarını uyguluyor (bitiş başlangıçtan sonra,
yüksek risk gerekçe ister, tutar para birimi ister). v1 hiçbirini
uygulamıyor, yani daha zayıf bir sınavdan "geçiyor".

Bedeli belge başına 0,11 fazladan deneme ve %11 daha yüksek maliyet. Karşılığı
%0 → %100 grounding.

## 2. Alan bazlı doğruluk

`v1*` aynı koşunun `--no-grounding-drop` hâli; "şema bunu ifade edemiyordu" ile
"grounding doğrulayamadı"yı ayırıyor.

| Alan | v1 | v1* (grounding'siz) | v2 | Neden |
|---|---|---|---|---|
| `jurisdiction` | %0,0 | %0,0 | **%100,0** | v1 şemasında alan yok |
| `amount_minor` | %2,8 | %2,8 | **%97,2** | v1'de `amount` float; kuruş tam sayısı hiç üretilmiyor |
| `start_date` | %0,0 | **%88,9** | **%100,0** | v1'in %0'ı tamamen grounding |
| `end_date` | %2,8 | %88,9 | **%100,0** | aynı sebep |
| `termination_notice_days` | %0,0 | %97,2 | %97,2 | aynı sebep; kalan %2,8 "iki ay" çevrimi |
| `auto_renewal` | %97,2 | %97,2 | **%100,0** | v1 şemasında alan yok |
| `risk_rationale` | %97,2 | %97,2 | **%100,0** | v2 yüksek riskte zorunlu tutuyor |
| `parties` | %100,0 | %100,0 | %100,0 | değişmedi |
| `currency` | %100,0 | %100,0 | %100,0 | değişmedi |
| `risk_level` | %100,0 | %100,0 | %100,0 | v1'de serbest string, v2'de `Literal` |

Üç bulgu:

1. **Alıntı alanı olmayan bir şema temellendirilemez.** v1'in `start_date`'i
   %88,9'dan %0'a düşüyor, sadece alıntıyı koyacak yer olmadığı için. Ayrım
   yapılmadan bakılırsa "v1 tarih çıkaramıyor" gibi okunur — yanlış, ve seni
   yanlış şeyi düzeltmeye gönderir.
2. **Şemada olmayan alan çıkarılamaz.** `jurisdiction` ve `auto_renewal`
   belgelerde var ve modelin koyacağı yer yok. Şema tasarımı bir çıktı
   kalitesi kararıdır.
3. **En zayıf alan gerçekten en zayıf.** v2'de kalan iki hata, tam da olması
   gereken iki kenar vaka:

```
fields that failed on edge cases:
  notice_in_months       -> termination_notice_days
  tax_inclusive          -> amount_minor
```

CI kapısı tam olarak o sayıya bağlı:

```bash
uv run prompt-lab eval --min-field-accuracy 0.90
```

## 3. Injection direnci

12 kaçış kalıbı, her biri 5 koşu, yalnızca yapısal savunma.

| Kalıp | Koşu | Tuttu |
|---|---|---|
| `plain_closing`, `spaced_closing`, `uppercase`, `mixed_case` | 20 | %100 |
| `line_break`, `nested_opening`, `trailing_space`, `double_closing` | 20 | %100 |
| `embedded_instruction`, `role_switch`, `prompt_leak`, `format_escape` | 20 | %100 |
| **toplam** | **60** | **%100** |

Bu, wrapper'ın delinip delinemeyeceğini ve belge içeriğinin sistem bloğuna
ulaşıp ulaşamayacağını ölçüyor. Deterministik, dolayısıyla %100 beklenti ve
altına düşmesi bir regresyon.

Davranışsal yarı — gerçek bir model enjekte edilmiş talimatı izliyor mu — ayrı
bir `@pytest.mark.live` testinde ve olasılıksal. Prompt katmanı ilk siper, tek
savunma değil; gerçek yetkilendirme tool katmanının işi.

## 4. Tool açıklamaları

```bash
uv run python scripts/tool_description_experiment.py
```

Tek bir registry'nin üç varyantı. Şemalar özdeş; yalnızca açıklama metni
farklı.

| Varyant | Seçim doğruluğu | Yasak tool oranı | Tool'suz doğruluk |
|---|---|---|---|
| tam | %90,9 | **%0,0** | %100,0 |
| sınır cümleleri kaldırılmış | %90,9 | %0,0 | %100,0 |
| yalnızca ilk cümle | %90,9 | **%4,5** | %100,0 |

**Beklenen sonuç çıkmadı ve çıkan daha faydalı.** Bu seçiciyle açıklama
kalitesi seçim doğruluğunu hiç oynatmadı. Güvenlik sayısını oynattı:
açıklamaları tek cümleye indirmek, ajanın doğru tool'u seçme olasılığını aynı
bıraktı ve yıkıcı olana uzanma olasılığını ölçülebilir şekilde artırdı.

Bu, panolar hakkında bir şey söylüyor. Seçim doğruluğu bir kalite sinyali;
yasak tool oranı bir güvenlik sinyali — ve önce o bozuldu.

## 5. Döngü tespiti

```bash
uv run python scripts/agent_loop_experiment.py
```

20 senaryolu görev, 5'i takılı koşu. Konfigürasyonlar yalnızca tekrarın
koşuyu durdurup durdurmadığında farklı.

| Konfigürasyon | Tamamlanma | p50 adım | p95 adım | Döngü oranı |
|---|---|---|---|---|
| tespit açık | %75,0 | 2,0 | **3,0** | %25,0 |
| tespit kapalı | **%100,0** | 2,0 | 7,0 | %0,0 |

Bu senaryolarda takılı koşular altı tekrardan sonra kendiliğinden toparlanıyor
— iyimser bir varsayım, ve takası görünür kılan şey. **Tespit p95'te 4 adım
kazandırıyor ve 25 puan tamamlanma kaybettiriyor.**

`stop_at` bu takasın kadranı. Nereye ayarlanacağı, adımlarının mı yoksa
tamamlanmalarının mı pahalı olduğuna bağlı.

## 6. Harness konfigürasyonları

```bash
uv run python scripts/harness_experiment.py
```

30 belge oku, biri cevabın ihtiyaç duyduğu gerçeği içeriyor. Model yalnızca
context'inde olandan cevap veriyor.

| Konfigürasyon | Adım | Toplam token | p95 doluluk | Compaction | Cevap sağ kaldı |
|---|---|---|---|---|---|
| naif kırpma | 30 | 101.114 | 0,979 | 0 | hayır |
| compaction | 30 | 69.539 | 0,692 | 2 | hayır |
| compaction + alt-ajan | 30 | **12.018** | **0,134** | 0 | **evet** |

Compaction token'ı %31 ve p95 doluluğu 0,98'den 0,69'a düşürdü. Patlamaya bir
uzun sonuç kalmış bir koşu, nefes alanı olan bir koşuya döndü. Cevabı
kurtarmadı.

Orta satır için dürüst uyarı: needle bir spill dosyasında duruyor ve
`read_spill` ile erişilebilir; simülasyondaki ajan referansı takip etmiyor.
Yani satır "spill özeti + compaction, **ajan referanslarını takip etmiyorsa**
yetmez" diyor — gerçek bir başarısızlık biçimi ama "compaction işe yaramıyor"
iddiasından farklı.

Ders üçüncü satırda: okumayı devretmek token'ı %88 düşürdü ve cevabı korudu,
çünkü ana context belgeleri hiç tutmadı. En ucuz context yönetimi, hiç
üstlenmediğin context'i yönetmemek.

## 7. Compaction needle testleri

Üç planlanmış gerçek, gürültüyle gömülmüş, iki prompt sürümü.

| Prompt | Sipariş no `ORD-88421` | Tutar `125,000` | Tarih `2025-03-14` |
|---|---|---|---|
| `compaction@v1` ("kısa tut") | kayıp | kayıp | kayıp |
| `compaction@v2` (neyin kalacağını sayar) | korundu | korundu | korundu |

```bash
uv run pytest tests/test_compaction.py -v
```

---

## Model karşılaştırması

Bu tablo kendi koşularınla dolar; harness JSON'u üretiyor.

```bash
uv run model-probe --prompt evals/probe/sample-prompt.txt \
  --models anthropic:claude-opus-5 anthropic:claude-haiku-4-5 \
  -n 5 --json evals/probe/result.json
```

| model | in~ | in | drift% | out | USD/1k | TTFT p50 | TTFT p95 | total p50 | total p95 | distinct | modal |
|---|---|---|---|---|---|---|---|---|---|---|---|
| _(senin koşun)_ | | | | | | | | | | | |

`in~` yerel tiktoken tahmini, `in` provider'ın bildirdiği sayı, `drift%`
aradaki fark. tiktoken OpenAI sözlüğüdür; Anthropic ve Gemini'de bu sapma
%10-20'ye çıkar — context bütçesinin limite kadar doldurmak yerine emniyet
payı taşımasının sebebi bu.

Kimlik bilgisi olmadan da bütçe kapısı gözlenebilir:

```console
$ uv run model-probe --prompt evals/probe/sample-prompt.txt \
    --models anthropic:claude-opus-5 openai:gpt-5.5 --dry-run

model                in~     in     drift%  out    USD/1k  ...
claude-opus-5        82      0      -       0      0
gpt-5.5              82      0      -       0      0
  ! gpt-5.5: window not in catalog; budget check skipped
```
