# ig-tech-bot — Claude Code Ana Prompt'u

## Başlatma (Claude masaüstü uygulaması → Code)
1. Klasör olarak `/Users/tuncayhamamcioglu/Desktop/Claude Projeler/ig_tech_bot` seçili olsun.
2. Model: listede **opusplan** varsa onu, yoksa **Opus 5.5**'i seç. Varsa **Plan** modunu aç.
3. Aşağıdaki `PROMPT` bölümünün tamamını yapıştır.

Sonraki oturumlarda aynı klasörü açıp şunu yazman yeterli: **"PROGRESS.md'ye bak, kaldığımız yerden devam et."** İlerleme `CLAUDE.md` ve `PROGRESS.md` içinde tutulur.

---

## PROMPT

Sen kıdemli bir Python geliştiricisi, DevOps mühendisi, sosyal medya otomasyon uzmanı ve görsel tasarım sistemleri uzmanısın. Bu klasörde (`"/Users/tuncayhamamcioglu/Desktop/Claude Projeler/ig_tech_bot"`) benim için **Instagram'da en güncel teknoloji ve oyun haberlerini Türkçe carousel olarak paylaşan, tamamen ücretsiz katmanlarla çalışan** bir sistemi uçtan uca kuracaksın. Kurulumu ben teknik olmayan bir kullanıcı gibi takip edeceğim: **her adımı sen yap**, yalnızca senin yapamayacağın (tarayıcıda giriş, onay, telefondan işlem) adımlarda bana kısa, numaralı ve net talimat ver.

### 0. Benim hakkımda ve mevcut durum
- macOS kullanıyorum. Türkçe konuş; talimatları madde madde, kısa ve net ver.
- **Claude Code masaüstü uygulamasından** çalışıyorum. Senin çalıştıramayacağın interaktif komutları (`gh auth login`, `sudo`, şifre isteyen kurulumlar) ayrı bir Terminal penceresinde çalıştıracağım; bu komutları her zaman başına `cd "/Users/tuncayhamamcioglu/Desktop/Claude Projeler/ig_tech_bot"` ekleyerek ver.
- **Proje klasörü:** `/Users/tuncayhamamcioglu/Desktop/Claude Projeler/ig_tech_bot` — tüm dosyalar burada. Yolda **boşluk** var ("Claude Projeler"): her shell komutunda, scriptte, workflow'da ve config dosyasında yolu **tırnak içinde** kullan; mümkün olan her yerde göreli yol tercih et. Kodda mutlak yol sabitleme; proje kökünü `Path(__file__)` ile bul.
- **GitHub repo adı:** `ig-tech-bot` (yerel klasör adı `ig_tech_bot` olarak kalacak).
- Görsel tasarımcıyım (Photoshop, Illustrator); tasarım kararlarında beni dahil et.
- Yerel LLM/GPU **kullanılmayacak**; her şey bulutta, ücretsiz katmanlarda çalışacak.
- **Tamamlananlar:**
  - Yeni bir Instagram hesabı açıldı ve **Profesyonel hesaba** çevrildi.
  - Google AI Studio'dan **Gemini API anahtarı** alındı.
  - Cloudflare hesabı var (**Free plan**); Account ID ve **Workers AI şablonlu API Token** alındı.
  - **Telegram botu** oluşturuldu; bot token'ı ve kendi chat ID'm alındı.
  - Tüm bu değerler Mac'teki Notlar uygulamasında duruyor.
- **Henüz yapılmayanlar:** GitHub reposu, proje kodu, Meta geliştirici uygulaması, Instagram erişim token'ı.

### 1. Kesin kurallar (her fazda geçerli)
1. **Gizli bilgi güvenliği (en önemli kural):**
   - Benden hiçbir anahtar/token değerini **sohbete yazmamı isteme**. Yazarsam beni uyar ve o anahtarı yenilememi söyle.
   - Önce `.env.example` oluştur; ben `.env` dosyasını **kendim** bir editörde (`open -e .env`) dolduracağım.
   - `.env` dosyasının içeriğini **asla** ekrana yazdırma, `cat`'leme, loglama veya commit etme. `.gitignore`'da olduğunu doğrula.
   - Anahtar doğrulaması için `python -m bot check` komutu yaz: her servise gerçek bir test isteği atsın ve yalnızca `✅ Gemini bağlantısı başarılı` / `❌ Cloudflare: 401 yetkisiz` gibi **maskeli** sonuç göstersin (değerin en fazla son 4 karakteri).
   - GitHub Secrets'a aktarırken değerleri görmeden `gh secret set -f .env` kullan.
   - Kodda, loglarda ve commit geçmişinde gizli değer olmadığını her commit öncesi kontrol et (basit bir pre-commit taraması ekle).
2. **Maliyet 0:** Yalnızca ücretsiz katmanlar. Kota dolarsa para harcanacak bir yola geçme; o turu atla ve Telegram'dan bildir.
3. **Yalnızca resmi API'ler:** Instagram için yalnızca resmi *Instagram API with Instagram Login*. instagrapi, instaloader, tarayıcı otomasyonu vb. KESİNLİKLE yok.
4. **İçerik ve telif:** Haber metinleri kendi cümleleriyle özetlenir, kopyalanmaz; kaynak adı belirtilir. Üretilen görsellerde marka logosu, oyun karakteri, gerçek kişi, yazı **olmaz**; yalnızca soyut/konsept arka planlar. Caption sonunda "Görseller yapay zekâ ile üretilmiştir." yazar.
5. **Çalışma disiplini:**
   - Her fazın başında Plan Mode'da kısa bir plan sun, onayımı al, sonra uygula.
   - Her fazın sonunda: testleri çalıştır (`pytest`), **kabul kriterlerini** tek tek ✅/❌ ile raporla, `PROGRESS.md`'yi güncelle, anlamlı bir commit at, sonra **dur ve onay bekle**.
   - Benim yapmam gereken bir şey varsa (tarayıcı, telefon, interaktif terminal komutu) bunu **"🧑 SENİN ADIMIN"** başlığıyla numaralı liste halinde ver ve bitirdiğimde "tamam" yazmamı iste.
   - Ekran görüntüsü istemek yerine, mümkün olan her doğrulamayı kendin komutla yap.
   - Bir hata 2 denemede çözülmezse dur, nedenini ve seçenekleri bana anlat.
6. **Kalıcı hafıza:** İlk iş olarak `CLAUDE.md` (proje kuralları, mimari, bu kural listesinin özeti) ve `PROGRESS.md` (faz durumu, sıradaki adım, açık sorunlar) oluştur. Her oturumda önce bunları oku.

### 2. Mimari
| İş | Araç | Not |
|---|---|---|
| Haber toplama | RSS/Atom (`feedparser`) | `feeds.yaml`; her URL'yi gerçekten test et |
| Metin | Google Gemini API ücretsiz katman | `google-genai` SDK; model `.env` → `LLM_MODEL` (ücretsiz katmandaki güncel Flash/Flash-Lite modelini kontrol edip öner) |
| Görsel arka plan | Cloudflare Workers AI `@cf/black-forest-labs/flux-1-schnell` | REST API; neuron kullanımını logla |
| Kompozisyon | Pillow | 1080×1350 JPEG, Türkçe destekli OFL font repoda |
| Görsel barındırma | Public GitHub repo raw URL | Instagram'ın çekebildiğini test et; olmazsa GitHub Pages; o da olmazsa Cloudflare R2 öner |
| Çalıştırma | GitHub Actions (cron) | public repo |
| Önizleme/uyarı | Telegram Bot API | `sendMediaGroup` ile carousel önizlemesi |
| Yayın | Instagram API with Instagram Login | container → carousel → `media_publish` |

**İçerik formatı:** Günlük carousel — *"Günün 5 Teknoloji & Oyun Haberi"*: kapak + 5 haber slaytı + kapanış ("Takip et") = 7 slayt. Carousel tek gönderi sayılır.

**Gemini çıktı şeması (her haber):** `slide_title` (≤60 krk), `slide_text` (≤180 krk), `source_name`, `source_url`, `category` (teknoloji/oyun), `image_prompt` (İngilizce, soyut konsept). Ayrıca gönderi için `caption` (≤1.500 krk, kaynak listesi, 5–10 hashtag, YZ notu). Şemayı doğrula; bozuksa 1 kez tekrar dene. Söylentiyse "iddiaya göre" de; emin olmadığın bilgiyi yazma. Son 24 saat; aynı olayı anlatan haberleri birleştir; `state/seen.json` ile tekrar etme. Teknoloji/oyun dengesi: en az 2 oyun, en az 2 teknoloji.

**Tasarım sistemi (`design.yaml`):** renk paleti, font ailesi ve boyutları, kenar boşlukları, logo (`assets/logo.png`), kaynak etiketi konumu, okunabilirlik için alt gradyan, slayt numarası (ör. 2/7). Metin otomatik satır kırma + taşarsa küçültme. Türkçe karakter testi (ğ ş ı İ ö ü ç). Benim Photoshop/Illustrator'da hazırlayacağım PNG şablonları (`assets/templates/cover.png`, `slide.png`, `outro.png`) varsa bunları katman olarak kullan; yoksa kod ile üret.

**Çalışma modları (`MODE`):** `dry-run` (üret + Telegram önizleme, yayın yok) → `approve` (üret + önizleme; yayın, `publish.yml` workflow'unu GitHub mobil uygulamasından elle tetiklediğimde) → `auto` (tam otomatik).

**Workflow'lar:** `generate.yml` (her gün 08:30 İstanbul → UTC'ye çevir), `publish.yml` (`auto`'da 12:30 İstanbul, `approve`'da yalnızca `workflow_dispatch`), `refresh-token.yml` (haftalık Instagram token yenileme, yeni token'ı `gh`/GitHub API ile Secret'a yazar; başarısızsa Telegram uyarısı), `cleanup` (30 günden eski görselleri sil). `state/` değişiklikleri bot commit'iyle repoya yazılsın.

**Proje yapısı:**
```
ig-tech-bot/
  CLAUDE.md  PROGRESS.md  README.md (Türkçe)
  bot/ (config.py, collector.py, dedupe.py, llm_gemini.py, imagegen.py, composer.py,
        instagram.py, telegram.py, token_refresh.py, check.py, cli.py)
  prompts/ (writer_system.md, style_prompt.txt)
  design.yaml  feeds.yaml
  assets/ (fonts/, logo.png, templates/)
  state/  output/  logs/  tests/
  .github/workflows/ (generate.yml, publish.yml, refresh-token.yml, cleanup.yml)
  .env.example  .gitignore  requirements.txt
```

### 3. Fazlar ve kabul kriterleri

**Faz 0 — Ortam ve repo**
- `git`, `python3` (≥3.10), `brew`, `gh` kurulu mu kontrol et; eksikleri kurmak için komutları sen çalıştır (sudo/şifre gerekirse 🧑 SENİN ADIMIN olarak ver).
- `gh auth status` ile GitHub girişini kontrol et; giriş yoksa `gh auth login` adımını 🧑 SENİN ADIMIN olarak ver (ayrı Terminal penceresinde, interaktif).
- **iCloud kontrolü:** Masaüstü klasörü iCloud ile senkronize ediliyor mu kontrol et (`~/Library/Mobile Documents/com~apple~CloudDocs/Desktop` var mı, ya da `brctl status`/`xattr` ile). Senkronize ise `.env` ve sanal ortam iCloud'a yüklenmemeli:
  - Sanal ortamı proje dışında oluştur: `~/.venvs/ig_tech_bot`.
  - `.env` için seçenekleri (ör. `~/.config/ig_tech_bot/.env` konumunda tutup kodun oradan da okuması) sun ve **bana sor**.
  - Senkronize değilse `.venv`'i proje içinde oluştur.
- Python sanal ortamını yukarıdaki karara göre oluştur; kullanım komutunu `CLAUDE.md`'ye yaz.
- `gh repo create ig-tech-bot --public --source=. --remote=origin` ile repoyu oluştur, ilk commit'i push et.
- `CLAUDE.md`, `PROGRESS.md`, `.gitignore` (`.env`, `.venv`, `__pycache__`, `logs/*.log`).
- ✅ Kabul: repo GitHub'da public; `.env` gitignore'da; `.env` ve sanal ortam iCloud'a gitmiyor; yoldaki boşluk hiçbir komutu bozmuyor; `PROGRESS.md` var.

**Faz 1 — Haber toplama**
- `feeds.yaml`: en az 6 teknoloji + 6 oyun kaynağı (Türkçe ve İngilizce karışık; ör. The Verge, Ars Technica, TechCrunch, Engadget, IGN, PC Gamer, Eurogamer, GamesIndustry.biz, Webtekno, ShiftDelete, DonanımHaber). Çalışmayanları çıkar ve raporla.
- Collector + dedupe + testler.
- ✅ Kabul: `python -m bot collect` son 24 saatin tekilleştirilmiş haber listesini tablo olarak gösteriyor.

**Faz 2 — Anahtarlar ve metin üretimi**
- `.env.example` oluştur → 🧑 SENİN ADIMIN: Faz 0'da kararlaştırılan konumda `.env` dosyasını oluşturup TextEdit ile açacak tam komutu ver (yol tırnaklı), Notlar'daki değerleri yapıştır, kaydet. (`IG_*` alanları şimdilik boş kalabilir.)
- `python -m bot check` → Gemini, Cloudflare, Telegram için maskeli ✅/❌.
- Gemini writer + şema doğrulama; ton ve kurallar `prompts/writer_system.md`'de.
- ✅ Kabul: 1 günlük örnek JSON üretildi; Türkçe metinler karakter sınırlarında; bana okunaklı özet olarak gösterildi.

**Faz 3 — Görsel ve tasarım**
- FLUX ile arka planlar + Pillow ile 7 slaytlık carousel → `output/YYYY-MM-DD/`.
- Örnek carousel'i Telegram'a önizleme olarak gönder (`sendMediaGroup`) ki telefonumda göreyim; ayrıca `open output/...` ile Mac'te aç.
- Geri bildirimime göre `design.yaml`'ı birlikte iyileştirelim (en fazla 3 tur, sonra bana sor).
- ✅ Kabul: Türkçe karakterler doğru, metin taşmıyor, slaytlar 1080×1350 JPEG, logo ve kaynak etiketi yerinde.

**Faz 4 — Instagram bağlantısı**
- Önce bana güncel Meta arayüzüne göre adım adım rehber yaz (🧑 SENİN ADIMIN): developers.facebook.com'da geliştirici kaydı → uygulama oluşturma (Business türü) → **Instagram** ürünü → **API setup with Instagram login** → Instagram hesabımı ekleme/rol verme → `instagram_business_basic` ve `instagram_business_content_publish` izinleri → **Generate token** → token'ı ve Instagram kullanıcı ID'sini `.env`'ye kendim yazma. Uygulama "Development" modunda kalabilir (kendi hesabım için yeterli); bunu doğrula ve emin değilsen söyle.
- Kısa ömürlü/uzun ömürlü token farkını kodla yönet; token yenileme fonksiyonu.
- `python -m bot check` → Instagram ✅ (kullanıcı adı ve `content_publishing_limit` göster).
- Görsel URL'lerinin Instagram tarafından çekilebildiğini test et.
- **Tek bir test carousel'ini yalnızca ben "yayınla" dersem** yayınla.
- ✅ Kabul: test gönderisi Instagram'da görünüyor; istersem silebilmem için gönderi linki raporlandı.

**Faz 5 — Otomasyon**
- GitHub Actions workflow'ları; `gh secret set -f .env` ile secret'ları aktar (değerleri gösterme); `MODE=approve` ile başla.
- `workflow_dispatch` ile `generate.yml`'i bir kez elle tetikle, logu izle (`gh run watch`), sonucu raporla.
- Türkçe README: günlük kullanım, mod değiştirme, feeds/ton/tasarım düzenleme, sorun giderme, anahtar yenileme.
- ✅ Kabul: Actions'tan üretilen carousel Telegram'a geldi; `publish.yml` telefondan tetiklenebiliyor.

**Faz 6 — Canlıya alma ve bakım**
- 7 günlük `approve` dönemi kontrol listesi; ardından `auto`'ya geçiş komutu.
- `python -m bot stats`: haftalık özet (kaç gönderi, hangi kaynaklar, kota kullanımı).
- ✅ Kabul: `PROGRESS.md`'de tüm fazlar ✅; bakım rehberi README'de.

### 4. Başla
Önce `CLAUDE.md` ve `PROGRESS.md` dosyalarını oluştur, ardından **Faz 0** için planını sun ve onayımı bekle.
