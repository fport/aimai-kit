# 3. Tool katmanı

Üç sorumluluk, üç dosya — ve onları ayrı tutmak buradaki asıl tasarım kararı:

| Soru | Nerede cevaplanıyor |
|---|---|
| Hangi tool'lar var, kim görebilir? | `decorator.py`, `registry.py` |
| Her provider nasıl söylenmesini istiyor? | `export.py` |
| Bir tool çalıştığında ne oluyor? | `executor.py` |

Bunları tek sınıfta toplamak alışılmış kestirme yol, ve tool yetkilendirmesinin
neden bu kadar sık ajan döngüsünün içinde bittiğinin sebebi — orada koşu
başlatmadan test edilemez.

!!! done "Burada ne yaptık"

    `@tool` dekoratörü (imzadan JSON Schema), allowlist'li `ToolRegistry`, üç
    provider için dışa aktarım, beş kapılı `ToolExecutor`, idempotency
    imzaları, beş tool'luk gerçekçi bir örnek ve seçim doğruluğunu ölçen bir
    golden set.

## Şema imzadan geliyor

Fonksiyonu ve JSON Schema'sını ayrı yazmak, ikisinin ayrışmasını garanti eder.
Biri bir parametreyi yeniden adlandırır, şema hâlâ eski adı ilan eder, model
artık bağlanmayan argümanlar göndermeye devam eder. Hiçbir şey hata vermez;
tool sadece varsayılanları alır.

`@tool` şemayı `inspect.signature`'dan türetiyor, yani bu hata sınıfı yapısal
olarak imkânsız.

```python
from datetime import date
from typing import Annotated, Literal
from pydantic import Field
from aimai_kit.tools import tool

@tool
def find_orders(
    customer_id: Annotated[str, Field(description="Customer id, e.g. c-100.")],
    status: Literal["open", "shipped", "cancelled", "any"] = "any",
    since: date | None = None,
    limit: int = 20,
) -> list[dict]:
    """List a customer's orders, most recent first.

    Use this when you need a LIST of orders. To fetch ONE order whose id you
    already know, use get_order instead.

    Read-only.
    """
    ...
```

Üretilen şema:

```json
{
  "type": "object",
  "properties": {
    "customer_id": {"type": "string", "description": "Customer id, e.g. c-100."},
    "status": {"type": "string", "enum": ["open", "shipped", "cancelled", "any"]},
    "since": {"anyOf": [{"type": "string"}, {"type": "null"}]},
    "limit": {"type": "integer"}
  },
  "required": ["customer_id", "status", "since", "limit"],
  "additionalProperties": false
}
```

Desteklenen tipler bilerek kısıtlı: `str`, `int`, `float`, `bool`, `date`,
`Literal` ve bunların listeleri. Desteklenmeyen bir annotation import anında
hata veriyor, provider'ın çalışma anında reddedeceği bir şema üretmek yerine.
Bu tekniğin sınırı değil, tasarım tercihi: derin iç içe argüman nesnesi
gereken bir tool neredeyse her zaman iki tool'dur.

Boş docstring hata. Açıklama, modelin bir tool'u **ne zaman** çağıracağına
karar vermek için elindeki tek şey.

## Yan etki bayrakları şemada değil, spec'te

`side_effect` ve `requires_approval` tool'un özellikleri, argümanları değil.
Şemaya koymak, modelin kendi çağrısında `requires_approval=false` ayarlamasına
izin vermek demek — ki bu bir onay kapısı değildir.

```python
@tool(side_effect=True, requires_approval=True)
def cancel_order(ctx: CallContext, order_id: str, reason: str) -> dict:
    """Cancel an order. THIS CHANGES DATA and requires human approval."""
    ...

spec = cancel_order.tool_spec
assert spec.requires_approval is True
assert "requires_approval" not in spec.parameters["properties"]   # şemada yok
```

## Allowlist ilanı filtreliyor

`registry.visible(allowlist)` neyin **ilan edildiğini** filtreliyor, sadece
neyin çalışmasına izin verildiğini değil.

Kullanıcının kullanamayacağı bir tool yine de modele ilan edilirse, model
eninde sonunda onu çağırır, executor reddeder ve önlenebilir bir reddediş
için bir adım harcanır. Daha kötüsü, reddediş mesajı modele o tool'un var
olduğunu öğretir.

```python
registry.names()                 # ['build_report', 'cancel_order', 'find_orders', ...]
[t.name for t in registry.visible(["find_orders", "get_order"])]
# ['find_orders', 'get_order']   — model diğerlerini hiç görmüyor
```

Bu aynı zamanda "yirmi tool'um olunca ne olacak" sorusunun da cevabı: yirmi
tane göndermiyorsun. Bu isteğin kullanmasına izin verilen alt kümeyi
gönderiyorsun.

`visible()` ada göre sıralıyor. Süs değil — tool ilanları cache'lenmiş
prompt önekinin içinde duruyor ve küme sıralaması her süreç yeniden
başladığında farklı byte üretirdi.

## Üç dışa aktarım, tek şema

Providerlar iki şeyde anlaşamıyor, başka hiçbir şeyde:

| Provider | Şekil | Şema anahtarı |
|---|---|---|
| OpenAI Responses | düz | `parameters` |
| OpenAI Chat | `function` altında iç içe | `parameters` |
| Anthropic | düz | `input_schema` |

```python
from aimai_kit.tools import export_for

export_for("openai", registry.visible())[0]
# {'type': 'function', 'name': 'find_orders', 'description': '...',
#  'parameters': {...}}

export_for("anthropic", registry.visible())[0]
# {'name': 'find_orders', 'description': '...', 'input_schema': {...}}
```

Bu tam olarak, soyutlanmadığında her çağrı yerine kopyalanan türden bir fark.
Tek iç temsil, üç ince dışa aktarıcı — ve `export_for` adaptör katmanının
üstünde provider kimliğine bakan tek yer, o da bir isme bakıyor, bir tipe
değil.

## Beş kapı

Her kapı farklı bir soruya cevap veriyor ve modelin üzerine iş yapabileceği
bir mesaj üretiyor, asla bir stack trace değil:

| Kapı | Kod | Retry? | Mesaj |
|---|---|---|---|
| Tool var mı? | `no_such_tool` | evet | mevcutları **listeler** |
| İzin var mı? | `not_allowed` | hayır | tool'un adını **vermez** |
| Geçerli JSON mu? | `bad_json` | evet | ayrıştırmanın nerede koptuğunu söyler |
| Şemaya uyuyor mu? | `bad_args` | evet | hatalı alanı adlandırır |
| Onay gerekiyor mu? | `needs_approval` | hayır | döngüyü temiz durdurur |

```python
from aimai_kit.tools import CallContext, ToolExecutor

executor = ToolExecutor(registry)
ctx = CallContext(user_id="u-1", tenant_id="t-1")

executor.call("get_ordr", "{}", ctx).content
# "There is no tool named 'get_ordr'. Available tools: build_report,
#  cancel_order, find_orders, get_customer, get_order. Pick one of those or
#  answer without a tool."

executor.call("cancel_order", '{"order_id":"1"}', ctx, allowlist=["get_order"]).content
# "You are not permitted to use that tool in this context. Continue with the
#  tools you have been given."          <- 'cancel_order' adı geçmiyor

executor.call("get_order", '{"wrong": 1}', ctx).content
# "The arguments for 'get_order' do not match its schema. order_id: Field
#  required. Fix those fields and call the tool again."
```

1. ve 2. kapı arasındaki asimetri bilinçli. 1. kapı mevcut tool'ları listeler,
çünkü `fetch_customer` yerine `get_customer` çağıran bir model kendini bir
sonraki turda düzeltir. 2. kapı listelemez, çünkü yetkisiz bir çağırana hangi
tool'ların var olduğunu söylemek bir ifşadır — ve bir tool'un var olduğunu
öğrenen model onu denemeye devam eder.

`retryable`, `ok` ile aynı şey değil. Şema hatası retry edilebilir: model
kendi argümanlarını düzeltebilir. İzin hatası edilemez: tekrar denemek hiçbir
şeyi değiştirmez ve döngü adım harcamak yerine durmalıdır.

## Kapılardan sonra

**Sunucu bağlamı çağrıdan enjekte ediliyor.** `user_id` ve `tenant_id` oturumdan
geliyor ve şemadan çıkarılıyor:

```python
@tool
def get_order(ctx: CallContext, order_id: str) -> dict:
    """Fetch a single order by its id."""
    # ctx.tenant_id sorguya girer; model onu göremez, gönderemez
    ...

# Model kiracı göndermeye çalışsa bile şema fazladan alanı reddeder.
executor.call("get_order", '{"order_id":"1", "tenant_id":"t-evil"}', ctx)
```

**Timeout bir worker thread ile uygulanıyor.** Asılı kalan bir tool ajanı
askıya almıyor; döngünün üzerine düşünebileceği bir `timeout` sonucu üretiyor.
Thread çalışmaya devam ediyor, çünkü Python bir thread'i öldüremez — sert
iptal gereken bir tool alt sürece taşınmalı.

İki thread havuzu var, bir tane değil. `call_many` fan-out havuzuna gönderiyor
ve o çağrıların her biri kendi timeout'unu uygulamak için tekrar gönderiyor.
Tek havuz paylaşılırsa dış görevler bütün worker'ları doldurur ve iç görevler
arkalarında kuyruğa girer — yani timeout'lar hiç başlamamış işler için tetiklenir.
Bu hatayı sonuç sırasını doğrulayan bir test yakaladı.

**Kırpma duyuruluyor.** 200 KB JSON dönen bir tool hata vermez — sessizce
pencereyi yer ve sonraki turlar görünür bir sebep olmadan bozulur.

```python
result = executor.call("build_report", "{}", ctx)
print(result.content[-120:])
# ...[truncated: 194201 more characters were omitted. Narrow the query or
#  request a specific section.]
```

**`raw` context'e girmiyor.** İz kaydına gidiyor, böylece hata ayıklama tam
yükü görürken model yalnızca `content`'i görüyor.

## Paralel okuma, seri yazma

Salt okunur çağrılar tanımı gereği bağımsız, o yüzden arka arkaya beklemek
güvenlik kazancı olmadan zaman kaybı.

Yan etkili çağrılar **modelin ilan ettiği sırayla seri** çalışıyor, çünkü
birbirlerine bağımlı olabilirler ("siparişi iptal et, sonra müşteriye haber
ver") ve kısmi bir başarısızlık bilinen bir sırada çok daha kolay
yorumlanır.

Bir çağrının patlaması diğerlerini asla kaybettirmiyor:

```python
results = executor.call_many([
    ("get_order", '{"order_id": "1"}'),
    ("get_order", "{broken"),
    ("get_order", '{"order_id": "3"}'),
], ctx)

[r.ok for r in results]          # [True, False, True]
[r.error_code for r in results]  # [None, 'bad_json', None]
```

## Modele sormadan idempotency

Çağrı imzası tool adı + normalize argümanlar, yani `{"a":1,"b":2}` ile
`{"b":2,"a":1}` aynı çağrı olarak tanınıyor.

```python
from aimai_kit.tools.idempotency import call_signature

call_signature("charge", {"a": 1, "b": 2}) == call_signature("charge", {"b": 2, "a": 1})
# True
```

Anahtar modelden **istenmiyor**. İdempotency anahtarını modelden istemek,
garantinin ancak model kararlı bir anahtar göndermeyi hatırladığı sıklıkta
geçerli olması demektir — ki bu bir garanti değildir.

Yan etkili sonuçlar imzayla saklanıyor, böylece devam eden bir koşu kartı iki
kez çekmiyor. Sınır açıkça yazılı: süreç, tool çalıştıktan sonra ve sonuç
yazılmadan önce ölebilir. Bu pencereyi daraltır; kapatan tek şey tool'un
kendisinin idempotent olmasıdır.

Salt okunur çağrılar bilinçli olarak **cache'lenmiyor** — bir okumayı
cache'lemek, çağrılar arasında değişen veriyi gizlerdi.

## Açıklamaların değeri, ölçülmüş

Örnek tool'ların her açıklaması üç şey taşıyor, ve insanların atladığı
üçüncüsü:

1. tool ne yapar,
2. ne zaman **kullanılmaz**, komşu tool'a yönlendirerek,
3. yan etkisi var mı.

`scripts/tool_description_experiment.py` aynı golden set'i aynı registry'nin
üç varyantına karşı koşuyor — şemalar özdeş, yalnızca açıklama metni farklı:

| Varyant | Seçim doğruluğu | Yasak tool oranı |
|---|---|---|
| tam | %90,9 | %0,0 |
| sınır cümleleri kaldırılmış | %90,9 | %0,0 |
| yalnızca ilk cümle | %90,9 | **%4,5** |

Beklenen sonuç çıkmadı, ve raporlanmaya değer olan da bu: bu seçiciyle
açıklama kalitesi seçim doğruluğunu hiç oynatmadı. **Güvenlik** sayısını
oynattı. Açıklamaları tek cümleye indirmek ajanın doğru tool'u seçme
olasılığını aynı bıraktı ve yıkıcı olana uzanma olasılığını ölçülebilir
şekilde artırdı.

Bu, panoya hangi metriğin konacağı hakkında bir şey söylüyor. Seçim doğruluğu
bir kalite sinyali; yasak tool oranı bir güvenlik sinyali — ve önce o bozuldu.
