# 4. Ajan döngüsü

Döngü kısa, ve tasarım bu. Soğurabileceği her şey kendi sınırının arkasında
duruyor:

| Sorumluluk | Nerede |
|---|---|
| Tool çalıştırma | tool katmanının executor'ı |
| İstek kurulumu | prompt katmanı |
| Telemetri | provider katmanının dayanıklı istemcisi |
| Döngü tespiti | kendi testleri olan ayrı bir nesne |

Geriye kalan, gerçekten döngüyle ilgili olan kısım: bütçeyi kontrol et, modeli
çağır, tool çağrılarını executor'a devret, **her** sonucu geri besle,
tekrarla.

!!! done "Burada ne yaptık"

    Durumsuz `Agent` ve serileştirilebilir `Thread`, dört bütçe ve tek bir
    `StopReason`, bütçe dolduğunda tool'suz son tur, kademeli döngü tespiti,
    checkpoint'ten devam, `ScriptedClient` ile deterministik testler ve okuma
    sırası belgelenmiş koşu metrikleri.

## Durumsuz ajan, durumlu thread

`Agent` yapılandırmayı tutuyor. `Thread` geri kalan her şeyi: mesajlar, adım
sayısı, harcama, iz kaydı, tool sonucu önbelleği, döngü sayaçları.

Bundan iki şey bedavaya geliyor. Durumsuz bir ajan eşzamanlı isteklerde
paylaşılabilir. Ve checkpoint bir alt sistem değil — tek bir nesnenin
`to_dict` / `from_dict`'i.

```python
from aimai_kit.agent import Agent, Budgets, Thread

agent = Agent(client, executor, budgets=Budgets(max_steps=8))

thread = Thread()
run = agent.run(thread, "1002 numaralı siparişin durumu ne?", ctx=ctx)

# Koşunun tamamı tek bir JSON'da.
snapshot = thread.to_json()
resumed = Thread.from_json(snapshot)
```

İz kaydı, ayrı bir loglama kanalı yerine durumun parçası — aynı sebeple:
devam ettirebildiğin ama açıklayamadığın bir koşu ancak yarı kurtarılmıştır.

## Dört bütçe

Her biri farklı bir başarısızlığı sınırlıyor:

| Bütçe | Neyi sınırlıyor |
|---|---|
| adım | ilerleyen ama yakınsamayan döngü |
| token | kendi context'ini pencere patlayana kadar büyüten döngü |
| maliyet | finansın sorduğu sayı |
| saniye | kullanıcının hissettiği sayı |

Bütçeler adımdan **önce** kontrol ediliyor. Parayı harcadıktan sonra bütçeyi
aştığını öğrenmek bir denetimdir, bütçe değil.

```python
from decimal import Decimal

budgets = Budgets(
    max_steps=12,
    max_tokens=120_000,
    max_usd=Decimal("0.50"),
    max_seconds=120.0,
)

run = agent.run(Thread(), task, ctx=ctx)
print(run.stop_reason)         # StopReason.STEP_BUDGET
print(run.stop_reason.is_budget)   # True
print(run.stop_reason.is_success)  # False
```

Maliyet bütçesi bir fiyat kataloğuna ihtiyaç duyuyor, o yüzden opsiyonel.
Katalog yoksa sessizce devre dışı kalmıyor — harcama sıfırda kalıyor ve bütçe
hiç tetiklenmiyor, ki bu metriklerde görünür bir durum.

## Tool'suz son tur

Koşuyu tavanda ölü kesmek kullanıcıya hiçbir şey bırakmaz.

Bunun yerine bütçe durması, `tool_choice="none"` ile son bir çağrı tetikliyor
ve modele ne olduğunu söyleyip elindekiyle cevap vermesini istiyor:

```python
# loop.py
thread.add(
    Role.USER,
    "You have reached the limit for this task "
    f"({reason.value}). Do not call any more tools. Answer with what you "
    "already have, and state explicitly what is still missing.",
)
```

Eksiği adlandıran kısmi bir cevap, sessizlikten neredeyse her zaman daha
faydalıdır — ve eksiğin olmadığını varsayan bir cevaptan çok daha faydalıdır.

O son turun maliyeti seçtiğin tavanın **içinde** olmalı, üstünde değil. Ve bir
provider `tool_choice="none"`'ı yok sayarsa, iz kaydı son turu `ok=False`
olarak işaretliyor — boş bir cevabın normal bir durma gibi görünmesi yerine.

## Her tool çağrısı bir sonuç alıyor

Reddedilenler dahil, timeout olanlar dahil.

Üç çağrı isteyip iki sonuç dönen bir asistan turu, çoğu provider'ın doğrudan
reddettiği bir konuşma şekli bırakır; kabul edenler de karışık çıktı üretir.
Döngü yarım turu imkânsız kılıyor:

```python
results = self.executor.call_many(pairs, ctx, allowlist=self.allowlist)

for call, result in zip(calls, results, strict=True):
    ...
    thread.add(Role.TOOL, json.dumps({
        "tool_call_id": call.id,
        "tool": call.name,
        "ok": result.ok,
        "error_code": result.error_code,
        "content": content,
    }))
```

Tool hataları, hata sınıfı ve düzeltme talimatıyla veri olarak geri besleniyor.
Model ancak kendisine gösterilen bir hatadan kurtulabilir. Toplam tool hatası
için bir tavan var, çünkü dört denemede kurtulamayan bir model kırk denemede de
kurtulamaz.

## Döngü tespiti: önce uyar, sonra kes

Yakaladığı hata çok belirli: ajan `get_order(id=42)` çağırıyor, cevabı
beğenmiyor, `get_order(id=42)` çağırıyor. Hiçbir şey hata vermiyor. Her adım
sağlıklı görünüyor. Bütçe boşalıyor.

Tespit, tool katmanının çağrı imzasını yeniden kullanıyor; argüman sırasını
değiştirmek tekrarı gizleyemiyor.

Tepki kademeli:

- **ikinci tekrar** — uyarı **tool sonucunun içine** enjekte ediliyor
- **üçüncü tekrar** — koşu `loop_detected` ile duruyor

```python
REPEAT_WARNING = (
    "\n\n[note: this exact call was already made earlier in this run and "
    "returned the same result. Repeating it will not produce new information. "
    "Use a different tool, different arguments, or answer with what you have.]"
)
```

Kesmeden önce uyarmak faydalı olan kısım. "Bu çağrı aynı sonucu döndürdü;
farklı bir yol dene" denen bir model sık sık farklı bir yol deniyor ve koşu
tamamlanıyor. İkinci tekrarda kesmek, toparlanmak üzere olan koşuları
öldürür; hiç kesmemek ise takılı bir koşuyu tam bütçe yanmasına çevirir.

Uyarı ayrı bir sistem mesajına değil tool sonucunun içine giriyor, çünkü model
zaten oraya bakıyor.

## Döngü tespitinin bedeli, ölçülmüş

Yirmi senaryolu görev, beşi takılı koşu, tek farkı tekrarın koşuyu durdurup
durdurmadığı olan iki konfigürasyon:

| Konfigürasyon | Tamamlanma | p50 adım | p95 adım | Döngü oranı |
|---|---|---|---|---|
| tespit açık | %75,0 | 2,0 | **3,0** | %25,0 |
| tespit kapalı | **%100,0** | 2,0 | 7,0 | %0,0 |

Bunu dikkatli oku, çünkü naif okuma "tespit işleri kötüleştirdi" der.

Bu senaryolarda takılı koşular altı tekrardan sonra kendiliğinden toparlanıyor.
Bu iyimser bir varsayım — gerçek bir model hiç toparlanmayabilir — ama takası
görünür kılıyor: **döngü tespiti p95'te 4 adım kazandırıyor ve 25 puan
tamamlanma kaybettiriyor**, çünkü kendi yolunu bulacak koşuları da kesiyor.

`stop_at` bu takasın kadranı, ve nereye ayarlanacağı adımlarının mı yoksa
tamamlanmalarının mı pahalı olduğuna bağlı.

```python
from aimai_kit.agent.loopdetect import LoopDetector

thread = Thread()
thread.detector = LoopDetector(warn_at=2, stop_at=4)   # daha toleranslı
```

## Metrikleri doğru sırayla okumak

1. **döngü oranı** — koşular takılıyor mu?
2. **bütçe durma oranı** — kesiliyorlar mı?
3. **kurtarma oranı** — tool hatasından sağ çıkıyorlar mı?

Önce döngü oranı, çünkü bir döngü aşağıdaki her şeyi şişirir: adım, maliyet ve
bütçe durma oranı. Döngü oranı yüksekken bütçe ayarlamak, boşa giden işin
tavanını yükseltmekten ibarettir.

Sonra bütçe durma oranı. Düşük döngü oranıyla birlikte yüksekse bütçe
gerçekten dar demektir; yüksek döngü oranıyla birlikte aynı sayı bütçenin
işini yaptığı anlamına gelir.

En son kurtarma oranı, ve en ilginci o: tool hatası alıp yine de tamamlanan
koşuların oranı. Düşük bir kurtarma oranı, tool katmanının hata mesajlarının
üzerine iş yapılabilir olmadığını söyler — bu bir prompt ve açıklama sorunu,
bütçe sorunu değil.

```python
from aimai_kit.agent import run_metrics

metrics = run_metrics(threads)
print(metrics.as_dict())
# {'runs': 20, 'completion_rate': 0.75, 'steps_p50': 2.0, 'steps_p95': 3.0,
#  'tool_error_rate': 0.091, 'loop_rate': 0.25, 'budget_stop_rate': 0.0,
#  'recovery_rate': 1.0, 'mean_usd': '0.000000'}
```

Hiç hata almayan koşular kurtarma oranının paydasından dışlanıyor; onları
dahil etmek bunu "tool'lar ne kadar seyrek bozuluyor" ölçüsüne çevirirdi.

## Checkpoint ve garantinin sınırı

Devam ettirmek, mevcut bir thread'i `run()`'a vermekten ibaret — checkpoint
kurtarmanın özel bir yol olmamasının sebebi bu.

```python
# Onay bekleyerek duran bir koşu
run = agent.run(thread, "1002'yi iptal et", ctx=ctx)
assert run.stop_reason is StopReason.NEEDS_APPROVAL
print(thread.pending_approval)   # 'cancel_order:9f2c...'

# İnsan onayladıktan sonra, aynı thread'den devam
approved = CallContext(approved_calls=frozenset({thread.pending_approval}))
run = agent.run(thread, ctx=approved)
assert run.stop_reason is StopReason.FINISHED
```

Yan etkili sonuçlar çağrı imzasıyla saklanıyor, böylece aynı çağrıyı tekrar
oynatan bir koşu ikinci kez ücret çekmiyor.

Kapatmadığı pencere: süreç, tool çalıştıktan sonra ve checkpoint yazılmadan
önce ölebilir. Bunu ancak idempotent bir tool kapatır. **Sınırı yazılmamış
bir garanti, garantisizlikten kötüdür**, çünkü birisi ona güvenecektir.

---

## Checklist

Bu katman proda çıkmadan önce:

--8<-- "agent.tr.md"


Gerisi — tool'lar, budget'lar, çıkışın kendisi — ve PR template'ine yapıştırılacak
hâli: **[proda çıkmadan checklist](checklist.md)**.
