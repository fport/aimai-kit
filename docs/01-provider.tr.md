# 1. Provider katmanı

Bu katmanın işi, üstündeki her şeye bütün provider'ları aynı göstermek —
ama önemli olan farkları ezmeden. Bu iki zıt baskı, ve buradaki kararların
çoğu ikisi arasındaki çizgiyi nereye koyduğumuzla ilgili.

!!! done "Burada ne yaptık"

    `ChatRequest` / `ChatResult` / `Usage` / `Message` iç modelini,
    `LLMClient` protokolünü, beş hata sınıfını, dört adaptörü (OpenAI,
    Anthropic, Gemini, Azure), retry + fallback wrapper'ını ve
    `model-probe` ölçüm CLI'ını yazdık. Sonraki dört katmanın tamamı bu
    protokolün üstünde duruyor ve adaptörlere bir daha dokunulmadı.

## İç mesaj formatı

Paketin geri kalanının konuştuğu tek dil bu dört tip. İçlerindeki üç seçim
açıklamaya değer.

### `system` üst düzey bir alan, mesaj listesinin öğesi değil

Anthropic ve Gemini sistem talimatını zaten üst düzeyde bekliyor. OpenAI onu
mesaj olarak istiyor ve çevirmek adaptörde tek satır. Ters yönde normalize
etmek — sistem prompt'unu mesaj listesine gömüp üç adaptörün ikisinde geri
ayıklamak — her çağrıda string ayıklaması demekti, hem de bunun için en
uygunsuz yerde.

```python
from aimai_kit.provider.types import ChatRequest, Message, Role

req = ChatRequest(
    messages=[Message(role=Role.USER, content="Bedel nedir?")],
    system="Sen bir hukuk asistanısın.",   # üst düzey
    max_output_tokens=512,
)
```

Adaptörler bunu kendi biçimlerine çeviriyor:

```python
# anthropic_.py
kwargs["system"] = req.system                    # üst düzey parametre
# openai_.py
kwargs["instructions"] = req.system               # ayrı parametre
# gemini_.py
config["system_instruction"] = req.system         # config'in içinde
```

### Kullanılmayan alanlar baştan var ve boş duruyor

`ChatRequest` en başından beri `json_schema` ve `tools` alanlarını taşıyordu;
2. ve 3. katman onları doldurdu. Alan eklemek geriye dönük uyumludur, alan
adını değiştirmek değildir. Kararlı bir protokolün bütün amacı, üst katmanın
alt katmanı değiştirmeden büyüyebilmesi — ve buna ulaşmanın yolu doğru tahmin
etmek değil, yer bırakmak.

### Providerya özel ayarlar `extra` içinde

Gemini'nin `thinking_config`'inin ya da OpenAI'ın `reasoning_effort`'ünün
diğerlerinde karşılığı yok. İç modele koymak onu kirletirdi; erişilemez
bırakmak çağıranları soyutlamanın etrafından dolaşmaya zorlardı. İsim
alanlı bir kaçış kapısı ikisini de çözüyor.

```python
req = ChatRequest(
    messages=[...],
    extra={"gemini": {"thinking_config": {"thinking_budget": 2048}}},
)
```

## Paraya mal olan tuzak: `usage` alan adları

Bu katmandaki en pahalı ayrıntı.

OpenAI cache'lenmiş token'ları `input_tokens`'ın **içinde** raporluyor; detay
nesnesinde cache'li kısmı ayrıca veriyor. Anthropic ise
`cache_read_input_tokens`'ı **ayrı** raporluyor, input'a dahil değil. İkisi de
makul; aynı şey değiller.

Bir konvansiyon seç ve adaptörlerde ona normalize et. Bu paket cache'lenmiş
token'ları **input'un alt kümesi** sayıyor — OpenAI'ın konvansiyonu — ve
Anthropic adaptörü giriş yolunda cache okuma/yazmayı input'a katıyor:

```python
# anthropic_.py — normalizasyon
cache_read = getattr(usage, "cache_read_input_tokens", 0) or 0
cache_write = getattr(usage, "cache_creation_input_tokens", 0) or 0

Usage(
    input_tokens=usage.input_tokens + cache_read + cache_write,
    output_tokens=usage.output_tokens,
    cached_input_tokens=cache_read,
)
```

Bunu atlarsan Anthropic maliyetleri sistematik olarak düşük çıkar. Yuvarlama
hatası kadar değil: cache ağırlıklı bir iş yükünde input'un çoğu zaten
cache'li kısımdır. Hata sessizdir, yalnızca fatura raporunda görünür ve
muhasebe hatası gibi değil fiyatlandırma hatası gibi durur.

`ModelPricing.cost()` artık `cached_input_tokens > input_tokens` olduğunda
hata veriyor — normalize edilmemiş bir adaptörün ürettiği şekil tam olarak bu:

```python
>>> price.cost(input_tokens=100, output_tokens=10, cached_input_tokens=200)
ValueError: cached_input_tokens must be a subset of input_tokens (200 > 100).
Some adapter is not normalizing its usage fields.
```

## Hata sınıflandırması

Beş sınıf, ve sınıflandırma retry kararını taşıyor:

| Sınıf | Retry? | Neden |
|---|---|---|
| `RateLimited` | evet | provider beklemeni söyledi, hatta ne kadar bekleyeceğini de |
| `TransientError` | evet | 5xx ve bağlantı kopması bir denemeye daha değer |
| `InvalidRequest` | hayır | aynı 400 geri gelir |
| `AuthError` | hayır | anahtar hâlâ yanlış |
| `AllProvidersFailed` | hayır | zincirdeki her halka çöktü |

`retryable` sınıfın kendisinde duruyor, böylece retry politikası onu tek
yerden okuyor:

```python
class RateLimited(LLMError):
    retryable = True

class InvalidRequest(LLMError):
    retryable = False
```

Alternatifi — hata mesajlarında "rate limit" gibi kelimeler aramak — provider
metnini değiştirdiği gün sessizce bozulur, ve bozulma bir kesinti gibi görünür.

## Retry ve fallback

**SDK'nın kendi retry'ı kapalı** (`max_retries=0`). İki katman retry çarpılır:
üç deneme iki katmanda altı çağrı eder ve üç için hesaplanmış bir süre tavanı
anlamsızlaşır. Tam olarak bir katman karar verir.

**Toplam süre tavanı var.** Üç deneme × 60 saniyelik `Retry-After`, üç dakika
asılı kalan bir istek demektir. Kullanıcının istemcisi çoktan vazgeçmiştir.
Tavan olmadan retry'ın kendisi bir kesintiye dönüşür.

**Jitter süs değil.** 429 alan elli istemci tam iki saniye beklerse aynı anda
geri gelip aynı duvara çarparlar. Rastgele saçılma sürüyü tekrar kuyruğa
çevirir.

```python
policy = RetryPolicy(
    max_attempts=3,
    base_delay_s=0.5,
    max_delay_s=20.0,
    jitter_s=0.25,
    total_deadline_s=45.0,   # retry'ın kendisi kesinti olmasın
    honor_retry_after=True,  # provider'ın süresi bizim tahminimizi yener
)
```

**Akışta retry yok.** İlk parça kullanıcıya ulaştıktan sonra yeniden denemek,
ekranda yarım cümleyi silmek demek. Bu bir arayüz kararı ve çağırana ait;
kütüphane onu gizlemeye çalışmıyor.

**Fallback bir olay, sessiz bir kurtarma değil.** `llm_fallbacks_total` sayacı
etiketli olarak dışarı veriliyor:

```python
resilient = ResilientClient(
    primary,
    [backup],
    on_fallback=lambda src, dst, err: alert(f"{src} -> {dst}: {err}"),
)
```

Sessizce yedeğe düşen bir servis, birincil provider tamamen çökmüşken bile
her panoda sağlıklı görünür — kullanıcılar hâlâ cevap alıyordur, sadece daha
yavaş, daha pahalı ve muhtemelen daha zayıf bir modelden. **Fallback oranına
alarm koymak gerekir**, çünkü hata oranı grafiği hiçbir şey göstermeyecektir.

## Ölçüm: TTFT ile toplam süre neden ayrı

TTFT kullanıcının hissettiği şey. Toplam süre kapasite planının ihtiyacı olan
şey. 200 ms TTFT + 9 sn süre ile 4 sn TTFT + 5 sn süre benzer ortalamalara ve
tamamen farklı kullanıcı deneyimlerine sahip.

`model-probe` ikisini de gerçekten çalışan tek yoldan ölçüyor: N akış koşusu
TTFT ve süreyi veriyor, ardından tek bir `complete` çağrısı akışta
gelmeyebilecek gerçek `usage`'ı veriyor.

```bash
uv run model-probe --prompt evals/probe/sample-prompt.txt \
  --models anthropic:claude-opus-5 anthropic:claude-haiku-4-5 -n 5
```

Bedeli N+1 çağrı. Kazancı sapma sütunu — yerel tiktoken tahmini ile
provider'ın bildirdiği sayı yan yana. tiktoken OpenAI sözlüğüdür ve
Anthropic ile Gemini'de bu sapma %10-20'ye çıkar; context bütçesinin limite
kadar doldurmak yerine emniyet payı taşımasının sebebi bu.

Anahtar olmadan da bütçe kapısı gözlenebilir:

```console
$ uv run model-probe --prompt evals/probe/sample-prompt.txt \
    --models anthropic:claude-opus-5 openai:gpt-5.5 --dry-run

model                in~     in     drift%  out    USD/1k  ...
claude-opus-5        82      0      -       0      0
gpt-5.5              82      0      -       0      0
  ! gpt-5.5: window not in catalog; budget check skipped
```

## Ortalama değil yüzdelik

Bir LLM servisinde gecikme dağılımı çarpıktır, o yüzden raporlar p50/p95/p99
döndürüyor.

Bir uyarı testlere gömülü: küçük N'de nearest-rank aykırı değerleri yutar.
Yirmi koşuda p95 on dokuzuncu değerdir — tek bir on saniyelik koşu p99'a kadar
görünmez. "p95 iyi" demek "kötü koşu yok" demek değildir. SLO'nun yanına N'i
de yaz.

```python
values = [100.0] * 19 + [10_000.0]
percentiles(values)     # {50: 100.0, 95: 100.0, 99: 10000.0}
```

Başarısız çağrılar gecikmeden dışlanıyor (40 ms'de dönen bir 429 iş
yapılmadığı anlamına gelir) ama maliyete dahil ediliyor (girdi token'ı yine de
faturalanmış olabilir).

## Test edilen sınır

Satıcı SDK'ları yalnızca `provider/adapters/` altında import ediliyor ve
`test_no_vendor_leak.py` bunu regex yerine AST yürüyüşüyle uyguluyor — böylece
yorumlar ve string sabitleri yanlış alarm üretmiyor. Testin bir de ters
kontrolü var: adaptörlerin gerçekten bir SDK import ettiğini doğruluyor, çünkü
aksi hâlde SDK çağrılarını yanlışlıkla silmek testleri yeşil bırakır ve
"sızıntı yok" mesajı boş bir güvenceye dönerdi.

```python
# test_no_vendor_leak.py
@pytest.mark.parametrize("path", _source_files(), ids=lambda p: p.name)
def test_vendor_sdk_does_not_leak_outside_adapters(path: Path) -> None:
    roots = _import_roots(ast.parse(path.read_text(encoding="utf-8")))
    assert not roots & FORBIDDEN_ROOTS
```

---

## Checklist

Bu katman proda çıkmadan önce:

--8<-- "provider.tr.md"


Gerisi — tool'lar, budget'lar, çıkışın kendisi — ve PR template'ine yapıştırılacak
hâli: **[proda çıkmadan checklist](checklist.md)**.
