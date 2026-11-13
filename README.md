# ig-tech-bot — @singleplayer_tr

Her gün en güncel **teknoloji ve oyun haberlerini** toplayıp Türkçe bir Instagram carousel'i hazırlayan,
yalnızca **ücretsiz katmanlar** ve **resmî API'ler** kullanan bot.

```
RSS (55 kaynak) → tekilleştirme → Gemini (seçim + Türkçe metin) → Cloudflare FLUX (arka planlar)
→ Pillow (slaytlar) → Telegram önizleme → Instagram (resmî Content Publishing API)
```

- Günde **3–8 haber** (önemine göre), kapak + haber slaytları + kapanış (en fazla 10 slayt).
- Her haber slaytında başlık, 2–3 cümle, "Neden önemli?" bloğu ve kaynak; caption'da her habere ayrı paragraf.
- Görseller haberin konusunu anlatan yapay zekâ sahneleridir; logo, gerçek kişi, oyun karakteri ve yazı içermez.

---

## Günlük kullanım

Her şey GitHub Actions'ta kendiliğinden çalışır; bilgisayarının açık olması gerekmez.

| Saat (İstanbul) | Ne olur |
|---|---|
| 08:30 | **İçerik üret** çalışır → slaytlar ve caption Telegram'a gelir |
| 12:30 | Yalnızca `auto` modunda **Instagram'da yayınla** kendiliğinden çalışır |
| Pazartesi 09:00 | Instagram token'ı yenilenir |
| Pazar 06:00 | 30 günden eski görseller silinir |

### Modlar

| Mod | Davranış |
|---|---|
| `dry-run` | Üretir, Telegram'a gönderir. **Asla yayınlamaz.** |
| `approve` | Üretir, Telegram'a gönderir. Yayın **senin telefondan tetiklemenle** olur. |
| `auto` | Üretir ve 12:30'da kendiliğinden yayınlar. |

**`approve` modunda yayınlamak (telefondan):**
1. GitHub mobil uygulaması → **ig-tech-bot** → **Actions**
2. **Instagram'da yayınla** → **Run workflow** → **Run workflow**
3. Birkaç dakika içinde gönderi linki Telegram'a gelir.

**Mod değiştirmek** (Terminal'de):
```bash
cd "/Users/tuncayhamamcioglu/Desktop/Claude Projeler/ig_tech_bot" && gh variable set MODE --body approve
```
(`approve` yerine `dry-run` ya da `auto` yazabilirsin. Şu anki modu görmek: `gh variable list`)

**Bir günü elle yeniden üretmek:** Actions → **İçerik üret** → Run workflow → "Bugünün içeriği varsa bile yeniden üret" kutusunu işaretle.

---

## Düzenleme

| Ne | Dosya | Not |
|---|---|---|
| Haber kaynakları | `feeds.yaml` | Kaynak ekle/çıkar ya da `enabled: false` ile kapat |
| Yazım tonu ve kurallar | `prompts/writer_system.md` | Gemini'ye giden talimatlar |
| Görsel stili | `prompts/style_prompt.txt` | Her arka plana eklenen ortak stil |
| Tasarım | `design.yaml` | Renkler, fontlar, boyutlar, boşluklar, kapak/kapanış metinleri |
| Kendi şablonların | `assets/templates/cover.png`, `slide.png`, `outro.png` | 1080×1350 şeffaf PNG; varsa otomatik katman olarak eklenir |
| Logo | `assets/logo.png` | Şeffaf PNG |

Değişikliği kaydedip GitHub'a gönderdiğinde bir sonraki üretimde geçerli olur.

---

## Bilgisayarda çalıştırma

```bash
cd "/Users/tuncayhamamcioglu/Desktop/Claude Projeler/ig_tech_bot"
source .venv/bin/activate
python -m bot check            # tüm anahtarları maskeli olarak doğrula
python -m bot collect          # son 24 saatin haberleri (tablo)
python -m bot run --no-mark    # tam günlük akış (deneme; haberleri "kullanıldı" işaretlemez)
python -m bot render           # bugünkü içerikten slaytları yeniden üret
python -m bot write --images-only   # aynı haberler için yalnızca görselleri yenile
python -m bot test-url         # Instagram görselleri çekebiliyor mu (YAYIN YAPMAZ)
python -m bot publish          # bugünkü carousel'i yayınla (onay sorar; dry-run'da reddeder)
python -m pytest -q            # testler
```

---

## Anahtarlar ve yenileme

Anahtarlar yerelde `.env` dosyasında (asla GitHub'a gitmez), GitHub'da ise **Settings → Secrets and variables → Actions** altında durur.
`.env`'yi düzenledikten sonra GitHub'a aktarmak için:

```bash
cd "/Users/tuncayhamamcioglu/Desktop/Claude Projeler/ig_tech_bot" && gh secret set -f .env
```

| Anahtar | Nereden | Yenileme |
|---|---|---|
| `GEMINI_API_KEY` | aistudio.google.com → Get API key | Süresiz; sızarsa yenisini al |
| `CF_ACCOUNT_ID`, `CF_API_TOKEN` | dash.cloudflare.com → My Profile → API Tokens → Workers AI şablonu | Süresiz |
| `TELEGRAM_BOT_TOKEN`, `TELEGRAM_CHAT_ID` | Telegram @BotFather | Süresiz |
| `IG_USER_ID`, `IG_ACCESS_TOKEN` | developers.facebook.com → uygulama → Instagram → API setup → Generate token | 60 gün; bot haftalık yeniler |
| `IG_APP_ID`, `IG_APP_SECRET` | developers.facebook.com → Uygulama ayarları → Temel | Token yenileme için gerekli |
| `GH_PAT` (yalnız GitHub Secret) | github.com → Settings → Developer settings → Fine-grained tokens (bu repo, Secrets: Read and write) | Yenilenen token'ı Secret'a yazmak için |

**Bir anahtar sızdıysa:** ilgili servisten hemen yenisini oluştur, `.env`'yi güncelle, `gh secret set -f .env` çalıştır.

---

## Sorun giderme

| Belirti | Ne yapmalı |
|---|---|
| Telegram'a "kota doldu, tur atlandı" geldi | Normal; ücretsiz kota ertesi gün yenilenir. Para harcayan bir yola geçilmez. |
| "içerik üretimi başarısız" mesajı | GitHub → Actions → İçerik üret → son çalışmanın logu. `python -m bot check` ile anahtarları doğrula. |
| Instagram "token geçersiz" | Token süresi dolmuş olabilir: panelden yeni token al → `.env` → `gh secret set -f .env` |
| "Instagram token yenilenemedi" uyarısı | `IG_APP_ID`, `IG_APP_SECRET` ve `GH_PAT` Secret'larının dolu olduğunu kontrol et. |
| Görselde yazıya benzer şekil | `prompts/style_prompt.txt` ve `writer_system.md`'deki yasak listesine ekle; `write --images-only` ile yenile. |
| Bir haber bilgisi yanlış | `approve` modunda yayınlamadan önce Telegram önizlemesinden kontrol et; içerik `output/<gün>/content.json`'da düzeltilebilir, ardından `render`. |
| Instagram hesap uyarısı | Telefondaki Instagram → Profil → ☰ → **Hesap durumu**. Yalnızca "Para Kazanma" ise paylaşım etkilenmez. |

---

## Kurallar

- Yalnızca ücretsiz katmanlar; kota dolarsa o tur atlanır ve Telegram'dan bildirilir.
- Instagram için yalnızca Meta'nın resmî API'si; tarayıcı/cihaz otomasyonu ya da resmî olmayan kütüphane yok.
- Haberler kendi cümlelerimizle özetlenir, kaynak adı yazılır; caption sonunda "Görseller yapay zekâ ile üretilmiştir."
- Gizli değerler hiçbir zaman ekrana, loglara ya da commit'lere yazılmaz (commit öncesi otomatik tarama var).

Geliştirme notları: `CLAUDE.md` · İlerleme: `PROGRESS.md`
