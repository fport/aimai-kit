# 5. Harness

Ajan döngüsü bir koşuyu sınırlıyor; bu katman **uzun** bir koşuyu yaşanabilir
kılıyor. Her parçası, uzun koşuların belirli bir bozulma biçiminden doğdu.

!!! done "Burada ne yaptık"

    Segment modeli ve `ContextManager`, büyük tool çıktısı için spill ve
    scratchpad, sürümlü prompt'la eşik tetiklemeli compaction, deterministik
    yazma kapılı SQLite bellek deposu, şema kısıtlı alt-ajan ve üç katmanlı
    izolasyonun kodla yazılabilen iki katmanı.

## Context'in atomik birimi mesaj değil, segment

Bir tool çağrısı ve sonucu tek bir şeydir.

Sonucu atıp çağrıyı tutarsan model, hiç cevaplanmamış bir istekle bakakalır.
Çağrıyı atıp sonucu tutarsan kimsenin sormadığı bir soruya cevap kalır. Çoğu
sağlayıcı birinci şekli doğrudan reddeder.

O yüzden kırpılan birim bir **segment**: birlikte yaşayan ya da birlikte
düşen bir veya daha fazla mesaj.

```python
from aimai_kit.harness import segments_from_messages

segments = segments_from_messages(thread.messages)
for s in segments:
    print(s.kind.value, len(s.messages), "droppable" if s.droppable else "FIXED")
# task 1 FIXED
# tool_turn 2 droppable      <- asistan turu + tool sonucu, birlikte
# tool_turn 2 droppable
# assistant 1 droppable
```

Aşağıdaki her şey — doluluk oranı, kırpma sırası, compaction — segmentler
üzerinde çalışıyor ve eşleşme değişmezi böylece bedavaya geliyor, her birinin
ayrı ayrı hatırlaması gereken bir kural olmak yerine.

Önek (sistem blokları, orijinal görev) düşürülemez işaretli, ki "sondan kırp"
umutlu bir kural değil güvenli bir kural olsun.

Orijinal görevi korumak ayrıntı değil: ne sorulduğunu unutan bir ajan
kendinden emin şekilde başka bir soruya cevap verir, ve bu başarısızlık
cevabın kendisi dışında hiçbir metrikte görünmez.

## Her zaman sondan kırp

Konuşmanın ortasından kesmek, kesim noktasından sonraki bütün cache'lenmiş
token'ları geçersiz kılar. 2.000 token kazandıran bir kırpma, yeniden işlemede
40.000'e mal olabilir — **cache öneki, kırpmanın kazandırdığı token'lardan
daha değerlidir.**

```python
from aimai_kit.harness import ContextManager

manager = ContextManager(window=200_000, output_reserve=4_000)
messages, stats = manager.build(thread.messages, step=thread.step)

print(stats.as_dict())
# {'step': 12, 'input_tokens': 148_204, 'fill_ratio': 0.756,
#  'segments': 22, 'dropped_segments': 3, 'compacted': False}

print(manager.fill_percentile(95))   # 0.81
```

Doluluk oranı **her adımda** kaydediliyor, yalnızca bir şey bozulduğunda değil.
Otuz adım boyunca 0,92'de duran bir koşu bozulmamıştır; uzun bir tool
sonucu uzaklıktadır, ve bunu önceden bilmenin tek yolu izliyor olmaktır. p95
doluluk oranı sürekli 0,9'un üstündeyse bütçe yanlıştır, koşular şanssız
değil.

## Spill: bilgiyi tut, token'ı bırak

Kırpma tek bir sonucun pencereyi doldurmasını engeller. Alttaki sorunu
çözmez — bilgi gitmiştir, ve 900 satırlık dosyanın 400. satırına ihtiyacı olan
ajan ona ulaşamaz **ve ulaşamadığını bilmez**.

Spill iki özelliği de koruyor: tam çıktı diske gidiyor, context'e kısa bir
özet ve `spill://` referansı geliyor, bir tool da ajanın orijinalin herhangi
bir satır aralığını okumasını sağlıyor.

```python
from aimai_kit.harness import SpillStore, build_spill_tools

store = SpillStore(Path("runs/abc123"), threshold_chars=4_000)
summary = store.spill("find_orders", huge_output)
print(summary)
# [find_orders returned 25089 characters over 900 lines; the full output is
#  stored at spill://7e721695fa0a]
#
# First 600 characters:
# ...
#
# [use read_spill with ref=spill://7e721695fa0a and a line range to read any
#  part of the full output]

registry = ToolRegistry(build_spill_tools(store))
registry.names()   # ['read_notes', 'read_spill', 'write_note']
```

Bunu işe yaratan şey özet. Çıplak bir referans, ajanı okumaya değip
değmeyeceğine karar vermek için dosyayı okumaya zorlar — yani spill'in
kazandıracağı token'ları harcar. O yüzden özet boyutu, satır sayısını ve ilk
birkaç yüz karakteri söylüyor.

Scratchpad aynı fikrin diğer yönü: ara bulguları koyacak, context penceresi
olmayan bir yer — yazan ve okuyan iki tool ile.

## Compaction: geçmişi at değil, dönüştür

Kırpma bilgi kaybeder. Compaction onu dönüştürür: en eski segmentler tek bir
özet segmentiyle değiştirilir ve koşu çalışacak yerle devam eder.

Üç karar şekillendiriyor:

**Eşik tetiklemeli, adım başına değil.** Her adımda compaction yapmak, henüz
kıt olmayan token'ları kurtarmak için bir model çağrısı harcar. Tetikleyici
bir doluluk oranı **ve** yeterli geçmiş; kısa bir konuşmayı sıkıştırmak dört
turu üçe indirmek için bir çağrı harcamaktır.

```python
from aimai_kit.harness import Compactor

compactor = Compactor(client, registry, prompt_key="compaction@v2",
                      trigger_ratio=0.75, keep_recent=4)

if compactor.should_compact(stats.fill_ratio, segments):
    result = compactor.compact(segments)
    print(result.compacted_count, result.saved_tokens)
    # 14 41203
```

**Adım sınırında tetikleniyor.** Tool turunun ortasında bir compaction, çağrıyı
sonucundan ayırırdı — segment modelinin var olma sebebinin tam tersi.

**Prompt sürümlü bir dosya.** Compaction, ajanın kendi belleğine uygulanan
kayıplı bir dönüşüm; "bu durumu hangi özetleyici sürümü üretti" sorusunun
cevabı olmalı. Diğer bütün prompt'larla aynı registry'den geçiyor ve özet
segmenti `prompt_ref`'i kaydediyor.

Özet segmenti kendisi de düşürülebilir. Kalıcı işaretlemek çok uzun koşuları
imkânsız kılardı, çünkü sonunda özetler pencereyi doldurur.

## Needle testleri ve compaction prompt'unun uzunluğu

Neyin korunacağı modelin takdirine bırakılmıyor, prompt'ta açıkça yazılı:
kararlar, kısıtlar, sayılar, açık sorular, denenip başarısız olan yollar,
referanslar. **İyi okunan ve bir sayıyı düşüren bir özet, özetsizlikten
kötüdür** — çünkü güvenilir görünür.

Needle testi bilinen bir gerçeği konuşmanın başına koyuyor, compaction
tetiklenene kadar gürültüyle gömüyor, sonra gerçeğin sağ kalıp kalmadığına
bakıyor. Üç farklı needle — bir kimlik, bir tutar, bir tarih — çünkü tesadüfen
bir sayıyı koruyan bir özetleyici, sayıları koruyan bir özetleyici değildir.

| Prompt | Sipariş no `ORD-88421` | Tutar `125,000` | Tarih `2025-03-14` |
|---|---|---|---|
| `compaction@v1` ("kısa tut") | kayıp | kayıp | kayıp |
| `compaction@v2` (neyin kalacağını sayar) | korundu | korundu | korundu |

```bash
uv run pytest tests/test_compaction.py -v
```

Bu karşılaştırma asıl mesele. "Context'i sıkıştırıyoruz" üzerine iş
yapılabilecek bir cümle değil; "v1 üç planlanmış gerçeğin üçünü de kaybediyor,
v2 hiçbirini kaybetmiyor" hangi prompt'un yayınlanacağını söylüyor.

## Bellek: deterministik yazma kapısı

Üç kayıt tipi, çünkü farklı sorulara cevap veriyor ve farklı sürelerde
eskiyorlar — episodic (ne oldu), semantic (ne doğru), procedural (nasıl
yapılır).

Yazma kapısı **deterministik**, ve bütün tasarım bu. Modele "bu hatırlanmalı
mı" diye sormak, deponun modelin kendi spekülasyonuyla dolmasına yol açar — ve
yazılmış bir spekülasyon geri okunurken bir gerçek gibi okunur.

```python
from aimai_kit.harness import MemoryStore, MemoryKind, WriteRefused

store = MemoryStore("memory.sqlite3")

store.write(MemoryKind.SEMANTIC,
            "Customer c-100 is on the enterprise tier.", source="crm")

for bad in [
    "Card 4111111111111111 is on file",
    "Contact is buyer@example.com",
    "The customer is probably unhappy",
    "The account is suspended right now",
]:
    try:
        store.write(MemoryKind.EPISODIC, bad, source="chat")
    except WriteRefused as e:
        print(e)
# not stored: looks like a credential or personal identifier
# not stored: looks like a credential or personal identifier
# not stored: reads as speculation rather than an observed fact
# not stored: phrased as something that is only true right now
```

Hassas kalıp listesi bilerek kısa ve kaba. Neyin hassas sayılacağı konusunda
zeki olmaya çalışan bir kapı istisnalarla biter, ve istisnalar sırların
saklanma biçimidir.

`valid_until` var çünkü çoğu bellek eninde sonunda yanlışlanır. "Müşteri
deneme planında" otuz gün doğru, sonrasında yanıltıcıdır. Geri çağırma buna
göre filtreliyor ve bayat oranı sayaç olarak yayınlanıyor, böylece deponun
çürümesi kullanıcıların keşfedeceği bir şey olmaktan çıkıyor.

```python
store.write(MemoryKind.SEMANTIC, "Customer c-101 is on a trial plan.",
            source="crm", valid_until=date.today() - timedelta(days=1))

store.recall()                      # bayat kayıt gelmiyor
store.recall(include_stale=True)    # açıkça istenirse geliyor
store.stale_ratio()                 # 0.25
```

## Alt-ajan: okumayı devret

Otuz belge gerektiren bir görev, ana pencereyi bir kez ihtiyaç duyulan
materyalle doldurur. Yirminci belgede ajan kendi bulgularını sıkıştırıyordur.

Alt-ajan okumayı kendi thread'inde, kendi penceresiyle yapıyor ve **şema
kısıtlı** bir rapor döndürüyor. Ana ajan belgeleri değil, bir özet ve
alıntıları alıyor.

```python
from aimai_kit.harness import Subagent

sub = Subagent(client, executor, allowlist=["read_source"])
result = sub.run("Hangi sipariş etkilendi?")

print(result.report.summary)          # "The affected order is ORD-88421."
print(result.report.evidence)         # ['ORD-88421']
print(result.report.confident)        # True
print(result.compression_ratio)       # 18.4  <- içeride harcanan / dışarı dönen
```

Serbest metin yerine kısıtlı olması, çıkarımın kısıtlı olmasıyla aynı sebeple:
düzyazıyla cevap veren bir alt-ajan, çağırana kullanacağı bir şey değil
yorumlayacağı bir şey verir.

`evidence` programatik olarak doğrulanıyor — atıf yapılan her kimlik,
alt-ajanın gerçekten gördüğü metinde geçmeli. Doğrulanamayan referanslar
düşürülüyor ve güven düşürülüyor, rapor reddedilmek yerine:

```python
# Alt-ajan var olmayan bir kimliğe atıf yaptı
result.unverified_evidence    # ['ORD-00000']
result.report.evidence        # ['ORD-88421']  <- yalnızca doğrulananlar
result.report.confident       # False
```

Kimsenin çözemediği bir atıf, hiçbir şey bulunamadığını kabul etmekten
kötüdür.

Delegasyonun işe yarayıp yaramadığının ölçüsü sıkıştırma oranı: içeride
harcanan token bölü dışarı dönen. 1,0'a yakın bir oran, alt-ajanın okuduğu her
şeyi geri döndürdüğü anlamına gelir — bu yalnızca isimde delegasyondur.

Tek seviye. Alt-ajan alt-ajan doğuramaz. İç içe delegasyon maliyeti ve
başarısızlığı yorumlanamaz hâle getirir, ve buna izin verme girişimlerinin
hepsi zaten bir derinlik sınırıyla biter.

## İzolasyon: üç katman, biri gerçekten önemli

Tool'lar kod çalıştırıyor — modelden gelen, herhangi bir yerden gelmiş
olabilecek bir belgeden gelen argümanlar üzerinde.

| Katman | Ne yapıyor | Nerede |
|---|---|---|
| süreç içi | binary allowlist, path hapishanesi | `sandbox.py` |
| süreç | timeout, temizlenmiş environment | `sandbox.py` |
| konteyner | **ağ kapalı**, kaynak limitleri | dağıtım |

Üçüncüsü asıl önemli olan, ve içindeki en kritik tekil karar ağı kapatmak.
1. ve 2. katman hataları durdurur; dışarı çıkış yolu olmayan bir süreç, o iki
katman aşılsa bile hiçbir şeyi sızdıramaz, çünkü gönderecek yer yoktur. Diğer
her kontrol kademeli olarak bozulur. Ağ erişimi bozulmaz — ya açıktır ya
kapalı.

```python
from aimai_kit.harness import Sandbox, SandboxViolation

sandbox = Sandbox(root=Path("runs/abc123/workspace"))

sandbox.run("cat notes.txt")           # çalışır
sandbox.run("curl https://evil.example")
# SandboxViolation: 'curl' is not on the allowlist (cat, grep, head, ls, tail, wc)

sandbox.resolve("../../etc/passwd")
# SandboxViolation: path '../../etc/passwd' resolves outside the sandbox root
```

Koddaki iki ayrıntı bilinmeye değer. Yollar containment kontrolünden **önce**
çözülüyor, çünkü `../../etc` bir string karşılaştırmasını geçer ve sonra
kaçar; çözme aynı zamanda sembolik bağları da takip ediyor, ki bu da diğer
bariz yolu kapatıyor. Ve `shell=True` asla kullanılmıyor: bir shell, tek bir
komutu boru, ikame ve yönlendirme içeren bir dile çevirir, ve bir dilin
üstündeki allowlist allowlist değildir.

## Üç konfigürasyon, ölçülmüş

Görev: otuz belge oku, biri cevabın ihtiyaç duyduğu bir gerçeği içeriyor. Model
yalnızca context'inde olandan cevap veriyor, dolayısıyla o gerçeği kırpan bir
konfigürasyon cevap veremiyor ve hiçbir prompt ifadesi bunu gizlemiyor.

| Konfigürasyon | Adım | Toplam token | p95 doluluk | Cevap sağ kaldı |
|---|---|---|---|---|
| naif kırpma | 30 | 101.114 | 0,979 | hayır |
| compaction | 30 | 69.539 | 0,692 | hayır |
| compaction + alt-ajan | 30 | **12.018** | **0,134** | **evet** |

Compaction token'ı %31, p95 doluluk oranını 0,98'den 0,69'a düşürdü — uzun bir
sonuç uzaklıkta patlayacak bir koşu, nefes alanı olan bir koşuya döndü. Cevabı
kurtarmadı.

Orta satırı dürüst okumak için önemli bir uyarı: o koşuda needle bir spill
dosyasında duruyor ve `read_spill` ile erişilebilir; simülasyondaki ajan
referansı hiç takip etmiyor. Yani satır şunu söylüyor: "spill özeti +
compaction, **ajan referanslarını takip etmiyorsa** yetmez" — gerçek bir
başarısızlık biçimi, ama "compaction işe yaramıyor"dan farklı bir iddia.

Ders üçüncü satırda. Okumayı devretmek token'ı %88 düşürdü ve cevabı korudu,
çünkü ana context belgeleri zaten hiç tutmadı. **En ucuz context yönetimi, hiç
üstlenmediğin context'i yönetmemektir.**
