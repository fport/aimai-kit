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
