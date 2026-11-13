# PROGRESS.md — ilerleme durumu

Son güncelleme: 2026-11-13

## Fazlar
| Faz | Konu | Durum |
|---|---|---|
| 0 | Ortam ve repo | ✅ Tamamlandı (2026-11-13) |
| 1 | Haber toplama | ✅ Tamamlandı (2026-11-13) |
| 2 | Anahtarlar ve metin üretimi | ✅ Tamamlandı (2026-11-13) |
| 3 | Görsel ve tasarım | ✅ Tamamlandı (2026-11-13) |
| 4 | Instagram bağlantısı | 🟡 Bağlantı ✅, test gönderisi hesap ısınması sonrasına ertelendi |
| 5 | Otomasyon | ⏳ Sıradaki — dry-run modunda, plan onayı bekleniyor |
| 6 | Canlıya alma ve bakım | ⬜ |

## Faz 0 sonuçları
- Repo: https://github.com/hamamcioglutuncay-hub/ig-tech-bot (public, `main`)
- Python 3.12.16 (Homebrew) + proje içi `.venv`
- gh 2.104.0, hesap `hamamcioglutuncay-hub` (zaten girişliydi)
- Masaüstü iCloud senkronu kapalı → `.env` ve `.venv` proje içinde, `.gitignore`'da
- Pre-commit gizli bilgi taraması (`.githooks/pre-commit` → `scripts/secret_scan.sh`), sahte anahtarla test edildi: commit'i durduruyor
- Not: Intel Mac + macOS 26 için Homebrew hazır paket yok; paketler kaynak koddan derleniyor (yavaş)

## Faz 1 sonuçları
- İlk sürüm: 20 kaynak
- Türkçe oyun: Oyungezer, Merlin'in Kazanı, TurkMMO
- Kullanıcı isteği ama RSS'i yok: Multiplayer (akış boş/2024), Disket Kutusu (alan adı yanıt vermiyor), LEVEL (bmag.com.tr mağazasına yönleniyor)
- Oyungezer tarihleri saat dilimsiz → `tz: Europe/Istanbul` desteği eklendi
- Bağlantı kopmalarına 1 kez yeniden deneme
- Tekilleştirme: URL normalize + seen.json (30 gün) + benzer başlık birleştirme (aynı dil). Farklı dillerde aynı olay (ör. Wolfenstein 3 haberi 4 kaynakta) Faz 2'de Gemini ile birleştirilecek.
- Kaynak kategorisi kaynağa göre; teknoloji sitelerindeki oyun haberleri (ör. Webtekno'da GTA 6) Faz 2'de Gemini ile yeniden sınıflanacak.
- **Kaynak genişletme (kullanıcı isteği):** 55 kaynak — 17 EN teknoloji, 7 EN yapay zekâ (`topic: ai`), 8 TR teknoloji, 21 EN oyun, 5 TR oyun (+ ShiftDelete Oyun, Kayıp Rıhtım).
  Ayrı Türkçe YZ akışı bulunamadı. Denenip çalışmayanlar `feeds.yaml` sonunda listeli.
- Aynı link birden fazla akışta → `oyun` kategorisi ve `ai` etiketi korunur.
- Performans: başlık karşılaştırması 93 sn → <1 sn (kelime ön elemesi + önbellek). `collect` toplam ~13 sn.
- 15 test geçti. `python -m bot collect` ~835 tekil haber gösteriyor.

## Faz 2 sonuçları
- `.env` dolduruldu (kullanıcı). `python -m bot check`: Gemini ✅, Telegram ✅ (@singleplayer_tr_bot), Cloudflare ✅ (ilk token 20 karakterdi/geçersizdi; kullanıcı yeni Workers AI token'ı oluşturdu, FLUX-1-schnell erişilebilir).
- Gemini: `gemini-flash-latest` takma adı yok (404). Ücretsiz model zinciri: 3.8-flash → 3.7-flash → 3.5-flash → 3.5-flash-lite.
  3.8/3.7 sık sık 503 (yoğun) veriyor; zincir otomatik geçiyor. Tümü 429 ise tur atlanır + Telegram bildirimi.
- `pip install` Intel Mac'te bazı paketleri kaynaktan derlemeye çalışabiliyor → `pip install --only-binary=:all: -r requirements.txt`.
- İlk örnek: `output/2026-11-13/content.json` (model gemini-3.5-flash, 150 adaydan 5 haber, 2 oyun + 3 teknoloji, caption 690/1500).
  Nvidia/Kress iddiası kaynaklarla doğrulandı.
- Gemini çağrılarına zaman aşımı eklendi (üretim 120 sn, check 30 sn; SDK içi yeniden deneme kapalı) — yoğun model sonsuza kadar beklemiyor.
- İkinci örnek: caption maddeleri ayrı satırlarda (647/1500).
- 32 test geçti.

## Faz 3 sonuçları
- Marka: @singleplayer_tr, logo `assets/logo.png` (kullanıcı ekledi). Palet logodan: lacivert #081030, camgöbeği #00E8F8 (teknoloji), mor #B838F8 (oyun).
- Font: Archivo Black (başlık) + Archivo değişken (gövde), OFL, `assets/fonts/`.
- Tasarım turları: 1) A Neon / B Editoryal / C Cesur → kullanıcı B ile C arasında kaldı; 2) B+C karma (panel düzeni + iki tonlu görsel + kutulu BÜYÜK HARF başlık);
  3) kullanıcı "arka planlar çok boş/soyut" dedi → konuyla ilgili sahne görselleri, görsel panelin üstündeki alana sığdırılıyor. Kullanıcı 3. turu onayladı.
- Kullanıcı isteğiyle içerik değişti: haber sayısı 3–8 (önem puanı ≥6, denge kuralı), "5 haber" ifadesi hiçbir yerde yok;
  slaytta 2–3 cümle + "NEDEN ÖNEMLİ?" bloğu; caption'da her haber için başlık + paragraf + kaynak (≤2150 krk, paragraf sınırı haber sayısına göre);
  her slayt için otomatik alt_text (Faz 4'te Instagram'a gönderilecek).
- Instagram API carousel sınırı 10 → kapak + en fazla 8 haber + kapanış.
- `python -m bot render` → output/<gün>/slides/01..NN.jpg, Telegram albüm + caption önizleme, Finder'da açar. Arka planlar `output/<gün>/bg/` önbelleğinde (gitignore).
- `python -m bot write --images-only` → aynı haberler için yalnızca görsel tariflerini yeniler.
- FLUX: görsel başına ≈58 neuron (tahmin; API kullanım döndürmüyor), `state/usage.json` + `logs/neurons.log`. Geçici hata (8007/5xx) 3 kez denenir.
- Bilinen risk: FLUX bazen yazıya benzer şekil üretebiliyor; Gemini bazen kaynakta olmayan ayrıntı ekleyebiliyor → approve döneminde göz kontrolü.
- Kabul: Türkçe karakter ✅, metin taşmıyor ✅ (3 ve 8 haber, uzun metin testleri), 1080×1350 JPEG ✅ (80–240 KB), logo + kaynak etiketi ✅. 49 test geçti.

## Faz 4 durumu (2026-11-13)
- Meta panelinde ayrı "Instagram login" (IGAA) ekranı yok; "API setup with Unified login" EAA… token veriyor.
  Kod iki türü de destekliyor (EAA → graph.facebook.com, IGAA → graph.instagram.com). İzinler: instagram_basic, instagram_content_publish (+ reklam/mesaj, kullanılmıyor).
- `.env`: IG_USER_ID = sayısal kimlik (••••1600), IG_ACCESS_TOKEN = EAA…. IG_APP_ID/IG_APP_SECRET henüz boş (token yenileme için gerekli).
- `check`: Instagram ✅ @singleplayer_tr BUSINESS, paylaşım 0/100. `test-url`: Instagram GitHub raw URL'den görsel çekebiliyor ✅ (yayın yok).
- **Hesap uyarısı (19:58):** Meta, "singleplayer_tr" işletme portföyünü REKLAM için kısıtladı (gerekçe: "otomasyonla oluşturulmuş/kullanılmış görünüyor").
  Hesap Durumu: yalnızca Para Kazanma ⚠️; Özellikler, içerik, tavsiye ✅ → paylaşım etkilenmiyor.
  Muhtemel tetikleyici: yeni hesap + yeni işletme portföyü + reklam izinli uygulama aynı dakikalarda (+ benim birkaç başarısız işletme uç noktası okuma isteğim).
- Karar: test gönderisi 3–5 günlük elle "hesap ısınması" sonrasına ertelendi. Kullanıcı inceleme talep edecek.
  Isınmayı kullanıcı telefondan KENDİSİ yapar — cihaz/tarayıcı otomasyonu ile etkileşim YAPILMAZ (kural 3, sahte etkileşim).
- Bundan sonra yalnızca yayın için gereken API çağrıları; işletme/reklam uç noktalarına çağrı yok. Meta panelinde token/hesap değişikliği birkaç gün yapılmayacak.
- 62 test geçti.

## Sıradaki adım
Faz 5 planı (MODE=dry-run: Instagram'a hiç istek yok, yalnızca Telegram önizleme).
Isınma sonrası (≈2026-11-16/18): `python -m bot publish` ile test gönderisi (kullanıcı "yayınla" derse) → Faz 4 kapanışı.

## Açık sorunlar
- gh token'ında `workflow` izni yok → Faz 5'ten önce kullanıcı `gh auth refresh -h github.com -s workflow` çalıştırmalı (workflow dosyalarını push etmek için gerekli).
